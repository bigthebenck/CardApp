"""The "Starting Order" tab: the Final Deck, Shuffle Sequence and Result panels.

Enter the order the deck should end in and the shuffles you will do; the tab
shows the order to set it up in. All state lives in ``AppModel``; this module
only draws it and forwards user edits. It contains no shuffle math.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QGridLayout,
                               QHBoxLayout, QLabel, QPlainTextEdit, QSplitter, QVBoxLayout,
                               QWidget)

from .. import deck
from .. import shuffle_ops as ops
from . import dialogs
from .card_viewer import CardViewers
from .model import DECK_SIZE, AppModel, format_instructions, format_preview
from .open_in import OpenInTabButton
from .presets import PresetBar, PresetStore
from .sequence_panel import SequencePanel
from .widgets import (Debounce, Panel, button, copy, label, mono_font, row, set_text, set_tone,
                      text_box)

GRID_ROWS = 13

ALL_CARD_LABELS = [deck.Card(r, s).pretty() for s in deck.SUITS for r in deck.RANKS]
INDIFFERENT_LABELS = [deck.indifferent_card(rank=r).pretty()
                      for r in deck.INDIFFERENT_RANKS]

BADGES = {  # status -> (text, tone)
    "ok": ("PASS", "success"),
    "empty_sequence": ("PASS", "success"),
    "failed": ("FAIL", "danger"),
    "invalid_deck": ("WAITING", "warning"),
    "invalid_steps": ("WAITING", "warning"),
}


def write_file(parent, title, path, write):
    """Run ``write`` and tell the user where the file went, or why it failed."""
    try:
        write()
    except OSError as exc:
        dialogs.error(parent, title, f"Could not save {path}:\n{exc}")
    else:
        dialogs.info(parent, title, f"Saved to {path}")


class SlotBox(QComboBox):
    """One slot of the final deck: type a card, or pick one not placed elsewhere."""

    def __init__(self, fill_choices, commit):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setFont(mono_font())
        self.setMinimumContentsLength(4)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._fill = fill_choices
        self.activated.connect(lambda _i: commit())
        self.lineEdit().editingFinished.connect(commit)

    def showPopup(self):
        text = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems(self._fill())
        self.setCurrentIndex(-1)
        self.setEditText(text)
        self.blockSignals(False)
        super().showPopup()

    def text(self):
        return self.currentText()

    def set_text(self, text):
        if self.currentText() != text:
            self.blockSignals(True)
            self.setEditText(text)
            self.blockSignals(False)


class SolverTab:
    def __init__(self, parent, model=None, presets=None, open_in=None):
        """``open_in(target, cards)``, if given, adds "Open in new tab" buttons."""
        self.model = model or AppModel()
        self.presets = presets or PresetStore()
        self.open_in = open_in
        self._syncing_text = False
        self._text_is_source = False
        self._text_slots = None  # slots the shorthand box last described

        self.frame = QSplitter(Qt.Horizontal, parent)
        self.frame.setChildrenCollapsible(False)
        self._text_job = Debounce(self.frame, self.apply_text)
        self.viewers = CardViewers(self.frame)
        self.frame.addWidget(self._build_final_panel())
        self.sequence = SequencePanel(None, self.model, "2. Shuffle sequence (first → last)",
                                      self._states)
        self.frame.addWidget(self.sequence.frame)
        self.frame.addWidget(self._build_result_panel())
        for i, weight in enumerate((2, 1, 2)):
            self.frame.setStretchFactor(i, weight)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    def close(self):
        """Stop pending work before the tab's widgets go away."""
        self._text_job.stop()
        self.preset_bar.dispose()

    # --- setup ----------------------------------------------------------------------

    def _build_final_panel(self):
        frame = Panel("1. Final deck (desired order, top first)")
        body = frame.body

        self.preset_bar = PresetBar(frame, self.presets, self._preset_cards,
                                    self.model.set_final_cards)
        self.preset_bar.add_right(button("Clear", self.model.clear_final))
        body.addWidget(self.preset_bar.frame)

        body.addWidget(row(QLabel("Shorthand (e.g.  A-KH, (A-8, 9-K)`C, K-AD, ACHSD):"), None,
                           button("View cards", self.view_final_cards)))
        self.final_text = text_box(lines=4)
        self.final_text.textChanged.connect(self._on_text_modified)
        body.addWidget(self.final_text)
        if self.open_in is not None:
            self.open_final = OpenInTabButton(frame, self._preset_cards, self.open_in)
            body.addWidget(self.open_final.button, 0, Qt.AlignRight)
        self.text_error = label("", tone="danger", wrap=True)
        body.addWidget(self.text_error)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        self.slot_boxes = []
        for i in range(DECK_SIZE):
            r, col = i % GRID_ROWS, (i // GRID_ROWS) * 2
            number = label(f"{i + 1:>2}", tone="muted", mono=True)
            number.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(number, r, col)
            box = SlotBox(lambda i=i: self._slot_choices(i), lambda i=i: self._commit_slot(i))
            grid.addWidget(box, r, col + 1)
            self.slot_boxes.append(box)
        for c in range(1, 8, 2):
            grid.setColumnStretch(c, 1)
        body.addWidget(grid_widget)

        self.deck_status = label("", wrap=True)
        body.addWidget(self.deck_status)
        body.addStretch(1)
        return frame

    def _build_result_panel(self):
        frame = Panel("3. Starting order (set up like this)")
        body = frame.body

        self.badge = label("", role="badge")
        self.result_msg = label("", wrap=True)
        head = QWidget()
        h = QHBoxLayout(head)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.badge, 0, Qt.AlignTop)
        h.addWidget(self.result_msg, 1)
        body.addWidget(head)

        self.start_text = text_box(read_only=True)
        body.addWidget(self.start_text, 2)

        body.addWidget(row(button("Copy shorthand", lambda: copy(self._start_shorthand())),
                           button("Copy list", lambda: copy(self._start_numbered())),
                           button("Export…", self.export_start), None,
                           button("View cards", self.view_start_cards)))
        if self.open_in is not None:
            self.open_start = OpenInTabButton(frame, self._verified_start, self.open_in)
            body.addWidget(self.open_start.button, 0, Qt.AlignRight)

        self.preview_check = QCheckBox("Show step-by-step preview")
        self.preview_check.toggled.connect(lambda _on: self._toggle_preview())
        body.addWidget(self.preview_check)
        self.preview_text = text_box(read_only=True, wrap=False)
        self.preview_text.hide()
        body.addWidget(self.preview_text, 3)
        return frame

    # --- final deck events -------------------------------------------------------------

    def load_preset(self):
        self.preset_bar.load()

    def _preset_cards(self):
        """The final deck as typed, to save as a preset (empty slots are skipped)."""
        self.apply_text()
        if self.model.input_error:
            raise ValueError(f"fix the shorthand first ({self.model.input_error})")
        return self.model.filled_cards()

    def _on_text_modified(self):
        if not self._syncing_text:
            self._text_job.start()

    def apply_text(self):
        """Parse the shorthand box into the grid (also called after debounce)."""
        self._text_job.stop()
        self._text_is_source = True
        try:
            self.model.set_final_from_text(self.final_text.toPlainText())
        finally:
            self._text_is_source = False

    def _slot_choices(self, index):
        # Offer only cards not already placed in another slot; X, B, L can go anywhere.
        used = {c.key for i, c in enumerate(self.model.slots) if c is not None and i != index}
        return INDIFFERENT_LABELS + [
            lbl for lbl, key in zip(ALL_CARD_LABELS, deck.FULL_DECK_KEYS) if key not in used]

    def _commit_slot(self, index):
        text = self.slot_boxes[index].text().strip()
        if not text:
            self.model.set_slot(index, None)
            return
        try:
            cards = deck.parse_cards(text, allow_indifferent=True)
            if len(cards) != 1:
                raise ValueError("one card per slot")
        except ValueError:
            set_tone(self.slot_boxes[index], "bad")
            return
        self.model.set_slot(index, cards[0])
        self.refresh()  # normalise the slot's text even when nothing changed

    # --- refresh from model -----------------------------------------------------------------

    def refresh(self):
        m = self.model
        # Shorthand box: rewrite it only when the grid changed from somewhere
        # else, so the user's own formatting survives unrelated edits.
        if self._text_is_source:
            self._text_slots = list(m.slots)
        elif m.input_error is None and m.slots != self._text_slots:
            self._text_slots = list(m.slots)
            self._syncing_text = True
            self.final_text.setPlainText(m.final_text())
            self._syncing_text = False
        self.text_error.setText(f"⚠ {m.input_error}" if m.input_error else "")

        dups = m.duplicate_slots()
        focus = QApplication.focusWidget()
        for i, card in enumerate(m.slots):
            box = self.slot_boxes[i]
            if focus not in (box, box.lineEdit()) or card is not None:
                box.set_text(card.pretty() if card else "")
            set_tone(box, "dup" if i in dups else None)

        report = m.deck_report()
        if report.ok:
            x = report.indifferent
            text = ("✓ Full 52-card deck, no duplicates." if not x else
                    f"✓ 52 cards, no duplicates; {x} indifferent ({report.counts_text()}).")
            self.deck_status.setText(text)
            set_tone(self.deck_status, "success")
        else:
            self.deck_status.setText("\n".join(report.messages()))
            set_tone(self.deck_status, "danger")

        self.sequence.refresh()

        res = m.result
        text, tone = BADGES[res.status]
        self.badge.setText(text)
        set_tone(self.badge, tone)
        self.result_msg.setText(" ".join(res.messages))
        set_text(self.start_text, self._start_numbered() if res.has_answer else "")
        self._render_preview()
        self.viewers.refresh()

    def _states(self):
        res = self.model.result
        return res.states if res.has_answer else None

    def _toggle_preview(self):
        self.preview_text.setVisible(self.preview_check.isChecked())
        self._render_preview()

    def _render_preview(self):
        res = self.model.result
        if self.preview_check.isChecked() and res.has_answer:
            set_text(self.preview_text, format_preview(res.states, self.model.steps))
        else:
            set_text(self.preview_text, "")

    # --- card image popups ------------------------------------------------------------------

    def view_final_cards(self):
        if self._text_job.pending:  # show what was just typed, not the pre-debounce slots
            self.apply_text()
        self.viewers.open("final", "Final deck (top first)", lambda: self.model.slots)

    def view_start_cards(self):
        self.viewers.open("start", "Starting order (top first)", self._start_cards)

    def _start_cards(self):
        res = self.model.result
        return res.start if res.has_answer else []

    # --- output -------------------------------------------------------------------------------

    def _verified_start(self):
        """The starting order, to open in another tab."""
        res = self.model.result
        if not (res.has_answer and res.verified):
            raise ValueError("there is no verified starting order yet")
        return res.start

    def _start_shorthand(self):
        res = self.model.result
        return deck.format_cards(res.start) if res.has_answer and res.verified else ""

    def _start_numbered(self):
        res = self.model.result
        return deck.format_numbered(res.start) if res.has_answer else ""

    def export_start(self):
        window = self.frame.window()
        res = self.model.result
        if not (res.has_answer and res.verified):
            dialogs.info(window, "Export", "There is no verified starting order to export yet.")
            return
        notes = self._ask_export_notes()
        if notes is None:
            return
        path = dialogs.save_path(window, "Export", "Text (*.txt);;All files (*)", ".txt")
        if not path:
            return
        steps = format_instructions(self.model.steps, res.states) or "(none)"
        if any(ops.split_point(s.kind, s.x) is not None for s in self.model.steps):
            steps += ("\n\n(split A|B): split the deck so A is the card you see on the bottom "
                      "of the upper packet and B is the top card of the rest.")
        text = (f"Shuffle sequence:\n{steps}\n\nStarting order (top first):\n"
                + self._start_numbered() + "\n\nShorthand:\n" + self._start_shorthand() + "\n")
        if notes:
            text += f"\nNotes:\n{notes}\n"

        def write():
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        write_file(window, "Export", path, write)

    def _ask_export_notes(self):
        """Ask for optional notes to end the export with; None if the user cancels."""
        dialog = QDialog(self.frame.window())
        dialog.setWindowTitle("Export notes")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Notes (optional) — added to the end of the file:"))
        box = QPlainTextEdit()
        box.setMinimumSize(420, 120)
        layout.addWidget(box)
        ok = button("Choose file…", dialog.accept, kind="primary")
        ok.setDefault(True)
        layout.addWidget(row(None, ok, button("Cancel", dialog.reject)))
        box.setFocus()
        accepted = dialog.exec() == QDialog.Accepted
        notes = box.toPlainText().strip()
        dialog.deleteLater()
        return notes if accepted else None

    def save(self):
        window = self.frame.window()
        path = dialogs.save_path(window, "Save setup", "Shuffle setup (*.json)", ".json")
        if path:
            write_file(window, "Save setup", path, lambda: self.model.save(path))
        return path or None
