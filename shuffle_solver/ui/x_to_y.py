"""The "X to Y" tab: enter a starting and an ending order, get the shuffles between them.

All state lives in ``XToYModel``; this module only draws it and forwards user
edits. It contains no shuffle math. The search runs on a worker thread so the
window stays usable (and the search can be cancelled); the worker only sees
copies of the cards and never touches Tk.
"""

import gc
import threading
import time
import tkinter as tk

import ttkbootstrap as tb

from .. import deck, path_finder
from .card_viewer import CardViewers
from .model import (PathOutcome, XToYModel, cancelled_outcome, format_instructions,
                    format_preview, search_outcome)

TEXT_DEBOUNCE_MS = 400
POLL_MS = 100
MONO = ("Courier", 10)

BADGES = {  # status -> (text, bootstyle)
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
    """One search on a worker thread; the Tk side polls ``done`` and ``progress``."""

    def __init__(self, cards, depth):
        self.cards = cards  # copies, so later edits can't reach the worker
        self.depth = depth
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.progress = (None, "Starting…")
        self.best = None  # "searching" outcome for the best route so far, if any
        self.outcome = None  # stays None when cancelled
        self.error = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.outcome = search_outcome(self.cards["start"], self.cards["end"], self.depth,
                                          self.cancel.is_set, self._report, self._improved)
        except path_finder.SearchCancelled:
            pass
        except Exception as exc:  # shown in the window instead of dying silently
            self.error = exc
        finally:
            self.done.set()

    def _report(self, fraction, text):
        self.progress = (fraction, text)  # a single assignment, read by the Tk thread

    def _improved(self, outcome):
        self.best = outcome  # likewise


class XToYTab:
    TITLES = {"start": "X. Starting order (top first)", "end": "Y. Ending order (top first)"}

    def __init__(self, parent, model=None):
        self.model = model or XToYModel()
        self.frame = tb.Frame(parent, padding=6)
        self._jobs = {}
        self._syncing = False
        self._text_source = None  # side whose box is being parsed right now
        self._text_cards = {"start": None, "end": None}  # cards each box last described
        self.viewers = CardViewers(self.frame)
        self._job = None  # the running _SearchJob, if any
        self._poll_job = None  # the pending after() call to _poll
        self._phase = None  # (progress text, start time, start fraction) for the time estimate

        self.texts, self.errors, self.statuses, self.preset_vars = {}, {}, {}, {}
        left = tb.Frame(self.frame)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._build_order_panel(left, "start", self.TITLES["start"])
        self._build_search_bar(left)
        self._build_order_panel(left, "end", self.TITLES["end"])
        self._build_result_panel(self.frame).pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                                  padx=(6, 0))

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    # --- setup ----------------------------------------------------------------------

    def _build_order_panel(self, parent, side, title):
        frame = tb.LabelFrame(parent, text=title, padding=6)
        frame.pack(fill=tk.BOTH, expand=True)

        top = tb.Frame(frame)
        top.pack(fill=tk.X)
        tb.Label(top, text="Preset:").pack(side=tk.LEFT)
        var = tk.StringVar(value=next(iter(deck.PRESETS)))
        self.preset_vars[side] = var
        tb.Combobox(top, textvariable=var, values=list(deck.PRESETS), state="readonly",
                    width=24).pack(side=tk.LEFT, padx=4)
        tb.Button(top, text="Load", command=lambda: self.load_preset(side)).pack(side=tk.LEFT)
        tb.Button(top, text="Clear",
                  command=lambda: self.model.set_cards(side, [])).pack(side=tk.RIGHT)

        label_row = tb.Frame(frame)
        label_row.pack(fill=tk.X, pady=(6, 0))
        tb.Label(label_row, text="Shorthand (e.g.  A-KH, A-KC, K-AD, K-AS;  X = any card):").pack(
            side=tk.LEFT)
        tb.Button(label_row, text="View cards",
                  command=lambda: self.view_cards(side)).pack(side=tk.RIGHT)
        text = tb.Text(frame, height=5, width=52, wrap=tk.WORD, font=MONO, undo=True)
        text.pack(fill=tk.BOTH, expand=True)
        text.bind("<<Modified>>", lambda e: self._on_text_modified(side))
        self.texts[side] = text
        self.errors[side] = tb.Label(frame, text="", bootstyle="danger", wraplength=440)
        self.errors[side].pack(anchor=tk.W)
        self.statuses[side] = tb.Label(frame, text="", wraplength=440, justify=tk.LEFT)
        self.statuses[side].pack(anchor=tk.W)

    def _build_search_bar(self, parent):
        mid = tb.Frame(parent)
        mid.pack(fill=tk.X, pady=4)
        row = tb.Frame(mid)
        row.pack(fill=tk.X)
        tb.Button(row, text="⇅ Swap", command=self.swap).pack(side=tk.LEFT)
        self.find_button = tb.Button(row, text="Find shuffles ▶", command=self.solve)
        self.find_button.pack(side=tk.RIGHT)
        tb.Label(row, text="shuffles").pack(side=tk.RIGHT, padx=(2, 12))
        self.depth_var = tk.IntVar(value=self.model.depth)
        tb.Label(row, textvariable=self.depth_var, width=2, anchor=tk.E).pack(side=tk.RIGHT)
        self.depth_scale = tb.Scale(row, from_=1, to=path_finder.MAX_DEPTH, orient=tk.HORIZONTAL,
                                    length=150, variable=self.depth_var, command=self._on_depth)
        self.depth_scale.pack(side=tk.RIGHT)
        tb.Label(row, text="Shortest-route search up to").pack(side=tk.RIGHT, padx=(12, 4))
        self.depth_note = tb.Label(mid, text="", wraplength=440, justify=tk.LEFT)
        self.depth_note.pack(anchor=tk.W)

        self.progress_row = tb.Frame(mid)  # shown only while a search runs
        self.progress_bar = tb.Progressbar(self.progress_row, maximum=1000, length=200)
        self.progress_bar.pack(side=tk.LEFT)
        tb.Button(self.progress_row, text="Cancel", command=self.cancel_search).pack(
            side=tk.RIGHT)
        self.progress_label = tb.Label(self.progress_row, text="")
        self.progress_label.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)
        self._show_depth_note()

    def _build_result_panel(self, parent):
        frame = tb.LabelFrame(parent, text="Instructions (do these in order)", padding=6)

        head = tb.Frame(frame)
        head.pack(fill=tk.X)
        self.badge = tb.Label(head, text="", font=("TkDefaultFont", 11, "bold"),
                              padding=(10, 2))
        self.badge.pack(side=tk.LEFT)
        self.result_msg = tb.Label(head, text="", wraplength=380, justify=tk.LEFT)
        self.result_msg.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

        body = tb.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True, pady=6)
        self.steps_text = tb.Text(body, height=18, width=30, font=MONO, state=tk.DISABLED)
        self.steps_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = tb.Scrollbar(body, orient=tk.VERTICAL, command=self.steps_text.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.steps_text.config(yscrollcommand=sb.set)

        tb.Button(frame, text="Copy instructions",
                  command=lambda: self._copy(self._instructions())).pack(anchor=tk.W)

        self.preview_var = tk.BooleanVar(value=False)
        tb.Checkbutton(frame, text="Show step-by-step preview", variable=self.preview_var,
                       command=self._toggle_preview).pack(anchor=tk.W, pady=(6, 0))
        self.preview_frame = tb.Frame(frame)
        self.preview_text = tb.Text(self.preview_frame, height=14, font=MONO, wrap=tk.NONE,
                                    state=tk.DISABLED)
        xs = tb.Scrollbar(self.preview_frame, orient=tk.HORIZONTAL,
                          command=self.preview_text.xview)
        ys = tb.Scrollbar(self.preview_frame, orient=tk.VERTICAL,
                          command=self.preview_text.yview)
        self.preview_text.config(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.preview_text.grid(row=0, column=0, sticky=tk.NSEW)
        ys.grid(row=0, column=1, sticky=tk.NS)
        xs.grid(row=1, column=0, sticky=tk.EW)
        self.preview_frame.rowconfigure(0, weight=1)
        self.preview_frame.columnconfigure(0, weight=1)
        return frame

    # --- events -------------------------------------------------------------------------

    def load_preset(self, side):
        self.model.load_preset(side, self.preset_vars[side].get())

    def swap(self):
        """Swap the two orders, keeping each box's text exactly as typed."""
        self.apply_text()
        raw = {side: self.texts[side].get("1.0", "end-1c") for side in self.model.SIDES}
        self._text_cards = {"start": list(self.model.cards["end"]),
                            "end": list(self.model.cards["start"])}
        self.model.swap()
        self._syncing = True
        for side, other in (("start", "end"), ("end", "start")):
            self.texts[side].delete("1.0", tk.END)
            self.texts[side].insert("1.0", raw[other])
            self.texts[side].edit_modified(False)
        self._syncing = False

    @property
    def searching(self):
        return self._job is not None

    def solve(self):
        """Start a search on a worker thread (the result arrives via ``_poll``)."""
        if self._job is not None:
            return
        self.apply_text()  # don't wait for the debounce if the user typed and clicked
        problems = self.model.problems()
        if problems:
            self.model.set_outcome(PathOutcome("waiting", problems))
            return
        cards = {side: list(self.model.cards[side]) for side in self.model.SIDES}
        # Free unreachable Tk objects (closed popups' images, ...) here on the Tk thread;
        # otherwise the worker's garbage collections could run their Tk cleanup.
        gc.collect()
        self._job = _SearchJob(cards, self.model.depth)
        self._phase = None
        self.find_button.config(state=tk.DISABLED)
        self.depth_scale.config(state=tk.DISABLED)
        self.progress_row.pack(fill=tk.X, pady=(4, 0))
        self._poll()

    def cancel_search(self):
        if self._job is not None:
            self._job.cancel.set()
            self.progress_label.config(text="Cancelling…")

    def close(self):
        """Stop the search and pending edits before the tab's widgets go away."""
        if self._job is not None:
            self._job.cancel.set()
        for job in [self._poll_job, *self._jobs.values()]:
            if job is not None:
                self.frame.after_cancel(job)

    def _poll(self):
        self._poll_job = None
        job = self._job
        if job is None:
            return
        if not job.done.is_set():
            self._show_progress(*job.progress)
            best = job.best
            if (best is not None and best is not self.model.outcome
                    and job.cards == self.model.cards and not job.cancel.is_set()):
                self.model.set_outcome(best)  # show the best route so far
            self._poll_job = self.frame.after(POLL_MS, self._poll)
            return
        self._job = None
        self.progress_bar.stop()
        self.progress_row.pack_forget()
        self.find_button.config(state=tk.NORMAL)
        self.depth_scale.config(state=tk.NORMAL)
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
            if str(bar.cget("mode")) != "indeterminate":
                bar.config(mode="indeterminate")
                bar.start(15)
            self.progress_label.config(text=text)
            return
        if str(bar.cget("mode")) != "determinate":
            bar.stop()
            bar.config(mode="determinate")
        bar["value"] = fraction * 1000
        now = time.monotonic()
        if self._phase is None or self._phase[0] != text:
            self._phase = (text, now, fraction)
        _t, t0, f0 = self._phase
        label = f"{text} {fraction:.0%}"
        if fraction - f0 > 0.005 and now - t0 > 3:
            left = (now - t0) / (fraction - f0) * (1 - fraction)
            label += f", about {_duration(left)} left"
        self.progress_label.config(text=label)

    def _on_depth(self, value):
        depth = round(float(value))
        self.depth_var.set(depth)  # snap the slider to whole shuffles
        if depth != self.model.depth:
            self.model.set_depth(depth)
            self._show_depth_note()

    def _show_depth_note(self):
        depth = self.model.depth
        if depth > 5:
            self.depth_note.config(text=DEPTH_NOTES[depth], bootstyle="danger")
        else:
            self.depth_note.config(text=DEPTH_NOTES[depth], style="Muted.TLabel")

    def view_cards(self, side):
        if self._jobs.get(side) is not None:  # show what was just typed
            self.apply_text(side)
        self.viewers.open(side, self.TITLES[side], lambda: self.model.cards[side])

    def _on_text_modified(self, side):
        text = self.texts[side]
        if not text.edit_modified():
            return
        text.edit_modified(False)
        if self._syncing:
            return
        if self._jobs.get(side) is not None:
            self.frame.after_cancel(self._jobs[side])
        self._jobs[side] = self.frame.after(TEXT_DEBOUNCE_MS, lambda: self.apply_text(side))

    def apply_text(self, side=None):
        """Parse a box's shorthand into the model now (one side, or both)."""
        for s in (side,) if side else self.model.SIDES:
            if self._jobs.get(s) is not None:
                self.frame.after_cancel(self._jobs[s])
            self._jobs[s] = None
            self._text_source = s
            try:
                self.model.set_from_text(s, self.texts[s].get("1.0", tk.END))
            finally:
                self._text_source = None

    # --- refresh from model -------------------------------------------------------------

    def refresh(self):
        m = self.model
        if self._job is not None and self._job.cards != m.cards:
            self.cancel_search()  # its answer would be for orders that are gone
        if self.depth_var.get() != m.depth:  # e.g. after loading a saved tab
            self.depth_var.set(m.depth)
            self._show_depth_note()
        for side in m.SIDES:
            # Rewrite a box only when its cards changed from somewhere else (preset,
            # swap, clear), so the user's own formatting survives.
            if side == self._text_source:
                self._text_cards[side] = list(m.cards[side])
            elif m.errors[side] is None and m.cards[side] != self._text_cards[side]:
                self._text_cards[side] = list(m.cards[side])
                self._syncing = True
                self.texts[side].delete("1.0", tk.END)
                self.texts[side].insert("1.0", deck.format_cards(m.cards[side]))
                self.texts[side].edit_modified(False)
                self._syncing = False
            self.errors[side].config(text=f"⚠ {m.errors[side]}" if m.errors[side] else "")
            report = m.report(side)
            if report.ok:
                x = report.indifferent
                text = ("✓ Full 52-card deck, no duplicates." if not x else
                        f"✓ 52 cards, no duplicates; {x} indifferent (X).")
                self.statuses[side].config(text=text, bootstyle="success")
            else:
                self.statuses[side].config(text="\n".join(report.messages()),
                                           bootstyle="danger")

        out = m.outcome
        text, style = BADGES[out.status]
        self.badge.config(text=text, bootstyle=f"@{style}")
        self.result_msg.config(text=" ".join(out.messages))
        self._set_text(self.steps_text, self._instructions() or "")
        self._render_preview()
        self.viewers.refresh()

    def _toggle_preview(self):
        if self.preview_var.get():
            self.preview_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.preview_frame.pack_forget()
        self._render_preview()

    def _render_preview(self):
        out = self.model.outcome
        if self.preview_var.get() and out.has_answer:
            self._set_text(self.preview_text, format_preview(out.states, out.steps))
        else:
            self._set_text(self.preview_text, "")

    def _instructions(self):
        out = self.model.outcome
        if not (out.has_answer and out.verified):
            return ""
        if not out.steps:
            return "(no shuffles needed)"
        return format_instructions(out.steps, out.states)

    @staticmethod
    def _set_text(widget, text):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.config(state=tk.DISABLED)

    def _copy(self, text):
        if text:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)


def _duration(seconds):
    if seconds < 90:
        return f"{max(round(seconds), 1)} s"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} min"
    if seconds < 36 * 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} days"
