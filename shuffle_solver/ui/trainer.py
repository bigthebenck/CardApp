"""The "Stack Trainer" tab: drill a memorised stack with random questions.

Left: the stack, entered as shorthand or a preset. Right: the range of
positions to train and the kinds of question to ask, then the question itself
with the answer box, how the last answer went, and the session's score. All
state lives in ``TrainerModel``; this module only draws it and forwards user
input.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QLabel, QLineEdit, QSplitter

from .. import deck
from .card_viewer import CardViewers
from .model import BEFORE, CARD_AT, POSITION_OF, QUESTION_KINDS, TrainerModel
from .open_in import OpenInTabButton
from .presets import PresetBar, PresetStore
from .sequence_panel import spin_box
from .widgets import Debounce, Panel, button, column, label, row, set_tone, text_box


class _AnswerBox(QLineEdit):
    """Enter checks the answer, Escape gives up."""

    def __init__(self, submit, give_up):
        super().__init__()
        self._submit, self._give_up = submit, give_up

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._submit()
        elif event.key() == Qt.Key_Escape:
            self._give_up()
        else:
            super().keyPressEvent(event)


class TrainerTab:
    def __init__(self, parent, model=None, presets=None, open_in=None):
        """``open_in(target, cards)``, if given, adds an "Open in new tab" button."""
        self.model = model or TrainerModel()
        self.presets = presets or PresetStore()
        self.open_in = open_in
        self._syncing = False
        self._text_is_source = False
        self._text_cards = None  # cards the shorthand box last described

        self.frame = QSplitter(Qt.Horizontal, parent)
        self.frame.setChildrenCollapsible(False)
        self._text_job = Debounce(self.frame, self.apply_text)
        self.viewers = CardViewers(self.frame)
        left, left_layout = column()
        self._build_deck_input(left_layout)
        left_layout.addStretch(1)
        self.frame.addWidget(left)
        right, right_layout = column(spacing=10)
        self._build_settings(right_layout)
        self._build_quiz(right_layout)
        self.frame.addWidget(right)
        self.frame.setStretchFactor(0, 1)
        self.frame.setStretchFactor(1, 2)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    # --- setup ----------------------------------------------------------------------

    def _build_deck_input(self, parent_layout):
        frame = Panel("Stack to train (top first)")
        parent_layout.addWidget(frame)
        body = frame.body

        self.preset_bar = PresetBar(frame, self.presets, self._preset_cards,
                                    self.model.set_cards)
        self.preset_bar.add_right(button("Clear", lambda: self.model.set_cards([])))
        body.addWidget(self.preset_bar.frame)

        body.addWidget(row(QLabel("Shorthand (e.g.  A-KH, A-KC, K-AD, K-AS):"), None,
                           button("View cards", self.view_cards)))
        self.deck_text = text_box(lines=4)
        self.deck_text.textChanged.connect(self._on_text_modified)
        body.addWidget(self.deck_text)
        if self.open_in is not None:
            self.open_button = OpenInTabButton(frame, self._preset_cards, self.open_in)
            body.addWidget(self.open_button.button, 0, Qt.AlignRight)
        self.text_error = label("", tone="danger", wrap=True)
        body.addWidget(self.text_error)
        self.deck_status = label("", wrap=True)
        body.addWidget(self.deck_status)

    def _build_settings(self, parent_layout):
        frame = Panel("What to train")
        parent_layout.addWidget(frame)
        body = frame.body

        self.first_box = spin_box(1, 52)
        self.last_box = spin_box(1, 52)
        for box in (self.first_box, self.last_box):
            box.valueChanged.connect(lambda _v: self.apply_range())
        self.range_total = label("", tone="muted")
        body.addWidget(row(QLabel("Positions"), self.first_box, QLabel("to"), self.last_box,
                           self.range_total, 8, button("Whole stack", self.whole_deck), None))
        self.range_error = label("", tone="danger")
        body.addWidget(self.range_error)

        self.kind_checks = {}
        checks = [QLabel("Ask:")]
        for kind, text in QUESTION_KINDS.items():
            check = QCheckBox(text)
            check.setChecked(kind in self.model.kinds)
            check.toggled.connect(lambda on, k=kind: self.model.set_kind(k, on))
            checks.append(check)
            self.kind_checks[kind] = check
        body.addWidget(row(*checks, None, spacing=12))

    def _build_quiz(self, parent_layout):
        frame = Panel("Question")
        parent_layout.addWidget(frame, 1)
        body = frame.body
        body.setSpacing(10)

        self.question_label = label("", role="question", wrap=True)
        body.addWidget(self.question_label)

        self.answer_entry = _AnswerBox(self.submit, self.give_up)
        font = QFont(self.answer_entry.font())
        font.setPointSize(14)
        self.answer_entry.setFont(font)
        self.answer_entry.setFixedWidth(160)
        self.check_button = button("Check", self.submit, kind="primary")
        self.give_up_button = button("Don't know", self.give_up)
        body.addWidget(row(self.answer_entry, self.check_button, self.give_up_button, None))
        body.addWidget(label("Enter checks the answer, Escape gives up. Type cards as "
                             "shorthand, e.g. 7H or 10S.", tone="muted"))

        self.feedback = label("", wrap=True)
        font = QFont(self.feedback.font())
        font.setPointSize(12)
        self.feedback.setFont(font)
        body.addWidget(self.feedback)
        body.addStretch(1)

        self.stats_label = QLabel("")
        font = QFont(self.stats_label.font())
        font.setPointSize(11)
        self.stats_label.setFont(font)
        body.addWidget(row(self.stats_label, None,
                           button("Reset score", self.model.reset_stats)))

    # --- deck events ----------------------------------------------------------------------

    def load_preset(self):
        self.preset_bar.load()

    def _preset_cards(self):
        """The deck as typed, to save as a preset."""
        self.apply_text()
        if self.model.error:
            raise ValueError(f"fix the shorthand first ({self.model.error})")
        return self.model.cards

    def _on_text_modified(self):
        if not self._syncing:
            self._text_job.start()

    def close(self):
        """Stop pending edits before the tab's widgets go away."""
        self._text_job.stop()
        self.preset_bar.dispose()

    def apply_text(self):
        """Parse the shorthand box into the model now (also called after the debounce)."""
        self._text_job.stop()
        self._text_is_source = True
        try:
            self.model.set_from_text(self.deck_text.toPlainText())
        finally:
            self._text_is_source = False

    def view_cards(self):
        if self._text_job.pending:  # show what was just typed
            self.apply_text()
        self.viewers.open("stack", "Stack (top first)", lambda: self.model.cards)

    # --- training events ------------------------------------------------------------------

    def apply_range(self):
        if not self.model.cards:
            return False
        try:
            self.model.set_range(self.first_box.value(), self.last_box.value())
        except ValueError as exc:
            self.range_error.setText(f"⚠ {exc}")
            return False
        self.range_error.setText("")
        return True

    def whole_deck(self):
        if self.model.cards:
            self.model.whole_deck()
        self.range_error.setText("")

    def submit(self):
        """Check the typed answer; returns the Outcome, or None if nothing was scored."""
        if self.model.question is None:
            return None
        try:
            outcome = self.model.answer(self.answer_entry.text())
        except ValueError as exc:
            self.feedback.setText(f"⚠ {exc}")
            set_tone(self.feedback, "warning")
            return None
        self._next()
        return outcome

    def give_up(self):
        if self.model.question is None:
            return None
        outcome = self.model.give_up()
        self._next()
        return outcome

    def _next(self):
        self.answer_entry.clear()
        self.answer_entry.setFocus()

    # --- refresh from model -------------------------------------------------------------

    def refresh(self):
        m = self.model
        if self._text_is_source:
            self._text_cards = list(m.cards)
        elif m.error is None and m.cards != self._text_cards:
            self._text_cards = list(m.cards)
            self._syncing = True
            self.deck_text.setPlainText(deck.format_cards(m.cards))
            self._syncing = False
        self.text_error.setText(f"⚠ {m.error}" if m.error else "")
        problems = m.deck_problems()
        if problems:
            self.deck_status.setText("\n".join(problems))
            set_tone(self.deck_status, "danger")
        else:
            n = len(m.cards)
            self.deck_status.setText(f"✓ {n} card{'s' if n != 1 else ''}, each once.")
            set_tone(self.deck_status, "success")

        n = len(m.cards)
        for box, value in ((self.first_box, m.first), (self.last_box, m.last)):
            box.blockSignals(True)
            box.setMaximum(max(n, 1))
            if n:
                box.setValue(value)
            box.blockSignals(False)
        self.range_total.setText(f"of {n}" if n else "")
        for kind, check in self.kind_checks.items():  # e.g. after loading a saved tab
            if check.isChecked() != (kind in m.kinds):
                check.blockSignals(True)
                check.setChecked(kind in m.kinds)
                check.blockSignals(False)

        q = m.question
        self.question_label.setText(q.prompt() if q else m.unavailable_reason())
        for widget in (self.answer_entry, self.check_button, self.give_up_button):
            widget.setEnabled(q is not None)

        o = m.last_outcome
        if o is None:
            self.feedback.setText("")
        elif o.correct:
            self.feedback.setText(f"✓ Right — {self._recap(o)}")
            set_tone(self.feedback, "success")
        else:
            given = f"You said {o.given}. " if o.given else ""
            self.feedback.setText(f"✗ {given}{self._recap(o)}")
            set_tone(self.feedback, "danger")

        if m.asked:
            self.stats_label.setText(
                f"Session: {m.correct} / {m.asked} right ({m.accuracy:.0%})   "
                f"Streak: {m.streak}   Best: {m.best_streak}")
        else:
            self.stats_label.setText("Session: no answers yet")
        self.viewers.refresh()

    @staticmethod
    def _recap(outcome):
        """The last question with its answer, e.g. "7♥ is at position 12."."""
        q = outcome.question
        if q.kind in (POSITION_OF, CARD_AT):
            return f"{q.card.pretty()} is at position {q.position}."
        where = "before" if q.kind == BEFORE else "after"
        return f"{q.answer.pretty()} comes {where} {q.card.pretty()}."
