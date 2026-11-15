"""The "X to Y" tab: enter a starting and an ending order, get the shuffles between them.

All state lives in ``XToYModel``; this module only draws it and forwards user
edits. It contains no shuffle math. The search runs in a worker process
(``search_process``) so the window stays smooth (and the search can be
cancelled); the worker only sees copies of the cards and never touches Qt.
"""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QProgressBar, QSlider, QWidget

from .. import deck, path_finder
from .card_viewer import CardViewers
from . import search_process
from .model import (PathOutcome, XToYModel, cancelled_outcome, format_instructions,
                    format_preview)
from .open_in import OpenInTabButton
from .presets import PresetBar, PresetStore
from .widgets import (Debounce, Panel, button, column, copy, label, row, set_text, set_tone,
                      text_box)

POLL_MS = 100

BADGES = {  # status -> (text, tone)
    "ok": ("PASS", "success"),
    "failed": ("FAIL", "danger"),
    "waiting": ("WAITING", "warning"),
    "searching": ("SEARCHING", "info"),  # best route so far, search still running
}
# Rough times on a typical desktop; depth 7 is ~100 times slower than 6.
DEPTH_NOTES = {
    1: "Checks every route of 1 shuffle. Under a second.",
    2: "Checks every route of up to 2 shuffles. Under a second.",
    3: "Checks every route of up to 3 shuffles. Under a second.",
    4: "Checks every route of up to 4 shuffles. Under a second.",
    5: "Checks every route of up to 5 shuffles. About a second.",
    6: "Checks every route of up to 6 shuffles. A few seconds, and about half a GB "
       "of memory.",
    7: "⚠ Checks every route of up to 7 shuffles. This takes around 5–10 minutes "
       "(about 100× slower than 6). You can cancel it.",
}


class _SearchJob:
    """One search in a worker process; the Qt side calls ``update`` and reads the rest."""

    def __init__(self, cards, depth):
        self.cards = cards  # copies, so later edits can't reach the worker
        self.depth = depth
        self.progress = (None, "Starting…")
        self.best = None  # "searching" outcome for the best route so far, if any
        self.outcome = None  # stays None when cancelled
        self.error = None
        self.done = False
        self.worker = search_process.take()
        self.cancel = self.worker.cancel  # set once the search is stopped
        self.worker.run(cards["start"], cards["end"], depth)

    def update(self):
        """Take in what the worker sent; sets ``done`` once it has finished."""
        if self.done:
            return
        alive = self.worker.alive()  # before reading, so nothing sent at the end is missed
        for kind, value in self.worker.messages():
            if kind == "progress":
                self.progress = value
            elif kind == "best":
                self.best = value
            else:
                self.outcome = value if kind == "done" else None
                self.error = value if kind == "error" else None
                self._finish()
                return
        if not alive:
            self.error = "the search process stopped unexpectedly"
            self._finish()

    def stop(self):
        """Stop the search now, keeping the best route it had sent."""
        if not self.done:
            self.update()
        if not self.done:
            self._finish()

    def _finish(self):
        self.done = True
        self.worker.stop()
        search_process.warm_up()  # ready for the next search


class XToYTab:
    TITLES = {"start": "X. Starting order (top first)", "end": "Y. Ending order (top first)"}

    def __init__(self, parent, model=None, presets=None, open_in=None):
        """``open_in(target, cards)``, if given, adds "Open in new tab" buttons."""
        self.model = model or XToYModel()
        self.presets = presets or PresetStore()
        self.open_in = open_in
        self.open_buttons = {}
        self.frame = QWidget(parent)
        self._jobs = {side: Debounce(self.frame, lambda s=side: self.apply_text(s))
                      for side in self.model.SIDES}
        self._syncing = False
        self._text_source = None  # side whose box is being parsed right now
        self._text_cards = {"start": None, "end": None}  # cards each box last described
        self.viewers = CardViewers(self.frame)
        self._job = None  # the running _SearchJob, if any
        self._poll_timer = QTimer(self.frame)
        self._poll_timer.setSingleShot(True)
        self._poll_timer.timeout.connect(self._poll)
        self._phase = None  # (progress text, start time, start fraction) for the time estimate

        self.texts, self.errors, self.statuses = {}, {}, {}
        self.preset_bars = {}
        layout = QHBoxLayout(self.frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        left, left_layout = column(spacing=8)
        self._build_order_panel(left_layout, "start", self.TITLES["start"])
        self._build_search_bar(left_layout)
        self._build_order_panel(left_layout, "end", self.TITLES["end"])
        layout.addWidget(left, 1)
        layout.addWidget(self._build_result_panel(), 1)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()
        search_process.warm_up()  # so the first search starts at once

    # --- setup ----------------------------------------------------------------------

    def _build_order_panel(self, parent_layout, side, title):
        frame = Panel(title)
        parent_layout.addWidget(frame, 1)
        body = frame.body

        bar = PresetBar(frame, self.presets, lambda: self._preset_cards(side),
                        lambda cards: self.model.set_cards(side, cards), width=24)
        bar.add_right(button("Clear", lambda: self.model.set_cards(side, [])))
        body.addWidget(bar.frame)
        self.preset_bars[side] = bar

        body.addWidget(row(QLabel("Shorthand (e.g.  A-KH, A-KC, K-AD, K-AS;  X = any card):"),
                           None, button("View cards", lambda: self.view_cards(side))))
        text = text_box()
        text.setMinimumHeight(90)
        text.textChanged.connect(lambda: self._on_text_modified(side))
        body.addWidget(text, 1)
        self.texts[side] = text
        if self.open_in is not None:
            self.open_buttons[side] = OpenInTabButton(
                frame, lambda: self._preset_cards(side), self.open_in)
            body.addWidget(self.open_buttons[side].button, 0, Qt.AlignRight)
        self.errors[side] = label("", tone="danger", wrap=True)
        body.addWidget(self.errors[side])
        self.statuses[side] = label("", wrap=True)
        body.addWidget(self.statuses[side])

    def _build_search_bar(self, parent_layout):
        mid = Panel("")
        body = mid.body
        self.find_button = button("Find shuffles ▶", self.solve, kind="primary")
        self.depth_label = QLabel(str(self.model.depth))
        self.depth_label.setMinimumWidth(14)
        self.depth_scale = QSlider(Qt.Horizontal)
        self.depth_scale.setRange(1, path_finder.MAX_DEPTH)
        self.depth_scale.setValue(self.model.depth)
        self.depth_scale.setPageStep(1)
        self.depth_scale.setMinimumWidth(150)
        self.depth_scale.valueChanged.connect(self._on_depth)
        body.addWidget(row(button("⇅ Swap", self.swap), None,
                           QLabel("Shortest-route search up to"), self.depth_scale,
                           self.depth_label, QLabel("shuffles"), 8, self.find_button))
        self.depth_note = label("", wrap=True)
        body.addWidget(self.depth_note)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setMaximumWidth(220)
        self.progress_label = QLabel("")
        self.progress_row = row(self.progress_bar, self.progress_label, None,
                                button("Cancel", self.cancel_search))
        self.progress_row.hide()  # shown only while a search runs
        body.addWidget(self.progress_row)
        mid.setStyleSheet("QGroupBox { padding-top: 12px; }")
        parent_layout.addWidget(mid)
        self._show_depth_note()

    def _build_result_panel(self):
        frame = Panel("Instructions (do these in order)")
        body = frame.body

        self.badge = label("", role="badge")
        self.result_msg = label("", wrap=True)
        head = QWidget()
        h = QHBoxLayout(head)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.badge, 0, Qt.AlignTop)
        h.addWidget(self.result_msg, 1)
        body.addWidget(head)

        self.steps_text = text_box(read_only=True)
        body.addWidget(self.steps_text, 2)
        body.addWidget(row(button("Copy instructions", lambda: copy(self._instructions())),
                           None))

        self.preview_check = QCheckBox("Show step-by-step preview")
        self.preview_check.toggled.connect(lambda _on: self._toggle_preview())
        body.addWidget(self.preview_check)
        self.preview_text = text_box(read_only=True, wrap=False)
        self.preview_text.hide()
        body.addWidget(self.preview_text, 3)
        return frame

    # --- events -------------------------------------------------------------------------

    def load_preset(self, side):
        self.preset_bars[side].load()

    def _preset_cards(self, side):
        """One order as typed, to save as a preset."""
        self.apply_text(side)
        if self.model.errors[side]:
            raise ValueError(f"fix the shorthand first ({self.model.errors[side]})")
        return self.model.cards[side]

    def swap(self):
        """Swap the two orders, keeping each box's text exactly as typed."""
        self.apply_text()
        raw = {side: self.texts[side].toPlainText() for side in self.model.SIDES}
        self._text_cards = {"start": list(self.model.cards["end"]),
                            "end": list(self.model.cards["start"])}
        self.model.swap()
        self._syncing = True
        for side, other in (("start", "end"), ("end", "start")):
            self.texts[side].setPlainText(raw[other])
        self._syncing = False

    @property
    def searching(self):
        return self._job is not None

    def solve(self):
        """Start a search in a worker process (the result arrives via ``_poll``)."""
        if self._job is not None:
            return
        self.apply_text()  # don't wait for the debounce if the user typed and clicked
        problems = self.model.problems()
        if problems:
            self.model.set_outcome(PathOutcome("waiting", problems))
            return
        cards = {side: list(self.model.cards[side]) for side in self.model.SIDES}
        self._job = _SearchJob(cards, self.model.depth)
        self._phase = None
        self.find_button.setEnabled(False)
        self.depth_scale.setEnabled(False)
        self.progress_row.show()
        self._poll()

    def cancel_search(self):
        if self._job is not None:
            self._job.stop()
            self._poll()

    def close(self):
        """Stop the search and pending edits before the tab's widgets go away."""
        if self._job is not None:
            self._job.stop()
            self._job = None
        self._poll_timer.stop()
        for job in self._jobs.values():
            job.stop()
        for bar in self.preset_bars.values():
            bar.dispose()

    def _poll(self):
        job = self._job
        if job is None:
            return
        job.update()
        if not job.done:
            self._show_progress(*job.progress)
            best = job.best
            if (best is not None and best is not self.model.outcome
                    and job.cards == self.model.cards):
                self.model.set_outcome(best)  # show the best route so far
            self._poll_timer.start(POLL_MS)
            return
        self._job = None
        self.progress_row.hide()
        self.find_button.setEnabled(True)
        self.depth_scale.setEnabled(True)
        if job.cards != self.model.cards:
            return  # an order was edited meanwhile; the model already dropped the answer
        if job.error is not None:
            self.model.set_outcome(PathOutcome("failed", [f"Search failed: {job.error}"]))
        elif job.outcome is None:
            self.model.set_outcome(cancelled_outcome(job.best))
        else:
            self.model.set_outcome(job.outcome)

    def _show_progress(self, fraction, text):
        bar = self.progress_bar
        if fraction is None:
            bar.setRange(0, 0)  # busy, with no idea how far along
            self.progress_label.setText(text)
            return
        bar.setRange(0, 1000)
        bar.setValue(round(fraction * 1000))
        now = time.monotonic()
        if self._phase is None or self._phase[0] != text:
            self._phase = (text, now, fraction)
        _t, t0, f0 = self._phase
        text_shown = f"{text} {fraction:.0%}"
        if fraction - f0 > 0.005 and now - t0 > 3:
            left = (now - t0) / (fraction - f0) * (1 - fraction)
            text_shown += f", about {_duration(left)} left"
        self.progress_label.setText(text_shown)

    def set_depth(self, depth):
        """Search up to ``depth`` shuffles (as if the slider were moved there)."""
        self.depth_scale.setValue(depth)
        self._on_depth(depth)

    def _on_depth(self, value):
        depth = int(value)
        self.depth_label.setText(str(depth))
        if depth != self.model.depth:
            self.model.set_depth(depth)
            self._show_depth_note()

    def _show_depth_note(self):
        depth = self.model.depth
        self.depth_note.setText(DEPTH_NOTES[depth])
        set_tone(self.depth_note, "danger" if depth > 5 else "muted")

    def view_cards(self, side):
        if self._jobs[side].pending:  # show what was just typed
            self.apply_text(side)
        self.viewers.open(side, self.TITLES[side], lambda: self.model.cards[side])

    def _on_text_modified(self, side):
        if not self._syncing:
            self._jobs[side].start()

    def apply_text(self, side=None):
        """Parse a box's shorthand into the model now (one side, or both)."""
        for s in (side,) if side else self.model.SIDES:
            self._jobs[s].stop()
            self._text_source = s
            try:
                self.model.set_from_text(s, self.texts[s].toPlainText())
            finally:
                self._text_source = None

    # --- refresh from model -------------------------------------------------------------

    def refresh(self):
        m = self.model
        if self._job is not None and self._job.cards != m.cards:
            self.cancel_search()  # its answer would be for orders that are gone
        if self.depth_scale.value() != m.depth:  # e.g. after loading a saved tab
            self.depth_scale.blockSignals(True)
            self.depth_scale.setValue(m.depth)
            self.depth_scale.blockSignals(False)
            self.depth_label.setText(str(m.depth))
            self._show_depth_note()
        for side in m.SIDES:
            # Rewrite a box only when its cards changed from somewhere else (preset,
            # swap, clear), so the user's own formatting survives.
            if side == self._text_source:
                self._text_cards[side] = list(m.cards[side])
            elif m.errors[side] is None and m.cards[side] != self._text_cards[side]:
                self._text_cards[side] = list(m.cards[side])
                self._syncing = True
                self.texts[side].setPlainText(deck.format_cards(m.cards[side]))
                self._syncing = False
            self.errors[side].setText(f"⚠ {m.errors[side]}" if m.errors[side] else "")
            report = m.report(side)
            if report.ok:
                x = report.indifferent
                text = ("✓ Full 52-card deck, no duplicates." if not x else
                        f"✓ 52 cards, no duplicates; {x} indifferent "
                        f"({report.counts_text()}).")
                self.statuses[side].setText(text)
                set_tone(self.statuses[side], "success")
            else:
                self.statuses[side].setText("\n".join(report.messages()))
                set_tone(self.statuses[side], "danger")

        out = m.outcome
        text, tone = BADGES[out.status]
        self.badge.setText(text)
        set_tone(self.badge, tone)
        self.result_msg.setText(" ".join(out.messages))
        set_text(self.steps_text, self._instructions() or "")
        self._render_preview()
        self.viewers.refresh()

    def _toggle_preview(self):
        self.preview_text.setVisible(self.preview_check.isChecked())
        self._render_preview()

    def _render_preview(self):
        out = self.model.outcome
        if self.preview_check.isChecked() and out.has_answer:
            set_text(self.preview_text, format_preview(out.states, out.steps))
        else:
            set_text(self.preview_text, "")

    def _instructions(self):
        out = self.model.outcome
        if not (out.has_answer and out.verified):
            return ""
        if not out.steps:
            return "(no shuffles needed)"
        return format_instructions(out.steps, out.states)


def _duration(seconds):
    if seconds < 90:
        return f"{max(round(seconds), 1)} s"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} min"
    if seconds < 36 * 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"
