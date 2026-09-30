"""The "Stack Trainer" tab: drill a memorised stack with random questions.

Left: the stack, entered as shorthand or a preset. Right: the range of
positions to train and the kinds of question to ask, then the question itself
with the answer box, how the last answer went, and the session's score. All
state lives in ``TrainerModel``; this module only draws it and forwards user
input.
"""

import tkinter as tk

import ttkbootstrap as tb

from .. import deck
from .card_viewer import CardViewers
from .model import BEFORE, CARD_AT, POSITION_OF, QUESTION_KINDS, TrainerModel

TEXT_DEBOUNCE_MS = 400
MONO = ("Courier", 10)
QUESTION_FONT = ("TkDefaultFont", 18, "bold")


class TrainerTab:
    def __init__(self, parent, model=None):
        self.model = model or TrainerModel()
        self._text_job = None
        self._syncing = False
        self._text_is_source = False
        self._text_cards = None  # cards the shorthand box last described

        self.frame = tb.Panedwindow(parent, orient=tk.HORIZONTAL)
        self.viewers = CardViewers(self.frame)
        left = tb.Frame(self.frame)
        self._build_deck_input(left)
        self.frame.add(left, weight=1)
        right = tb.Frame(self.frame)
        self._build_settings(right)
        self._build_quiz(right)
        self.frame.add(right, weight=2)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    # --- setup ----------------------------------------------------------------------

    def _build_deck_input(self, parent):
        frame = tb.LabelFrame(parent, text="Stack to train (top first)", padding=6)
        frame.pack(fill=tk.X)

        top = tb.Frame(frame)
        top.pack(fill=tk.X)
        tb.Label(top, text="Preset:").pack(side=tk.LEFT)
        self.preset_var = tk.StringVar(value=next(iter(deck.PRESETS)))
        tb.Combobox(top, textvariable=self.preset_var, values=list(deck.PRESETS),
                    state="readonly", width=20).pack(side=tk.LEFT, padx=4)
        tb.Button(top, text="Load", command=self.load_preset).pack(side=tk.LEFT)
        tb.Button(top, text="Clear", command=lambda: self.model.set_cards([])).pack(
            side=tk.RIGHT)

        label_row = tb.Frame(frame)
        label_row.pack(fill=tk.X, pady=(6, 0))
        tb.Label(label_row, text="Shorthand (e.g.  A-KH, A-KC, K-AD, K-AS):").pack(side=tk.LEFT)
        tb.Button(label_row, text="View cards", command=self.view_cards).pack(side=tk.RIGHT)
        self.deck_text = tb.Text(frame, height=4, width=44, wrap=tk.WORD, font=MONO, undo=True)
        self.deck_text.pack(fill=tk.X)
        self.deck_text.bind("<<Modified>>", self._on_text_modified)
        self.text_error = tb.Label(frame, text="", bootstyle="danger", wraplength=380)
        self.text_error.pack(anchor=tk.W)
        self.deck_status = tb.Label(frame, text="", wraplength=380, justify=tk.LEFT)
        self.deck_status.pack(anchor=tk.W)

    def _build_settings(self, parent):
        frame = tb.LabelFrame(parent, text="What to train", padding=6)
        frame.pack(fill=tk.X)

        row = tb.Frame(frame)
        row.pack(fill=tk.X)
        tb.Label(row, text="Positions").pack(side=tk.LEFT)
        self.first_var, self.last_var = tk.StringVar(), tk.StringVar()
        self.range_boxes = []
        for var, after in ((self.first_var, "to"), (self.last_var, None)):
            box = tb.Spinbox(row, from_=1, to=52, width=4, textvariable=var,
                             command=self.apply_range)
            box.pack(side=tk.LEFT, padx=4)
            for seq in ("<Return>", "<FocusOut>"):
                box.bind(seq, lambda e: self.apply_range())
            self.range_boxes.append(box)
            if after:
                tb.Label(row, text=after).pack(side=tk.LEFT)
        self.range_total = tb.Label(row, text="", style="Muted.TLabel")
        self.range_total.pack(side=tk.LEFT, padx=(2, 8))
        tb.Button(row, text="Whole stack", bootstyle="secondary",
                  command=self.whole_deck).pack(side=tk.LEFT)
        self.range_error = tb.Label(frame, text="", bootstyle="danger")
        self.range_error.pack(anchor=tk.W)

        row = tb.Frame(frame)
        row.pack(fill=tk.X, pady=(4, 0))
        tb.Label(row, text="Ask:").pack(side=tk.LEFT)
        self.kind_vars = {}
        for kind, label in QUESTION_KINDS.items():
            var = tk.BooleanVar(value=kind in self.model.kinds)
            tb.Checkbutton(row, text=label, variable=var,
                           command=lambda k=kind: self.model.set_kind(
                               k, self.kind_vars[k].get())).pack(side=tk.LEFT, padx=(6, 0))
            self.kind_vars[kind] = var

    def _build_quiz(self, parent):
        frame = tb.LabelFrame(parent, text="Question", padding=12)
        frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        self.question_label = tb.Label(frame, text="", font=QUESTION_FONT, wraplength=520)
        self.question_label.pack(anchor=tk.W, pady=(0, 10))

        row = tb.Frame(frame)
        row.pack(fill=tk.X)
        self.answer_var = tk.StringVar()
        self.answer_entry = tb.Entry(row, textvariable=self.answer_var, width=12,
                                     font=("TkDefaultFont", 14))
        self.answer_entry.pack(side=tk.LEFT)
        self.answer_entry.bind("<Return>", lambda e: self.submit())
        self.answer_entry.bind("<Escape>", lambda e: self.give_up())
        self.check_button = tb.Button(row, text="Check", command=self.submit)
        self.check_button.pack(side=tk.LEFT, padx=6)
        self.give_up_button = tb.Button(row, text="Don't know", bootstyle="secondary",
                                        command=self.give_up)
        self.give_up_button.pack(side=tk.LEFT)
        tb.Label(frame, text="Enter checks the answer, Escape gives up. Type cards as "
                             "shorthand, e.g. 7H or 10S.",
                 style="Muted.TLabel").pack(anchor=tk.W, pady=(4, 0))

        self.feedback = tb.Label(frame, text="", font=("TkDefaultFont", 12), wraplength=520,
                                 justify=tk.LEFT)
        self.feedback.pack(anchor=tk.W, pady=(12, 0))

        stats = tb.Frame(frame)
        stats.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        self.stats_label = tb.Label(stats, text="", font=("TkDefaultFont", 11))
        self.stats_label.pack(side=tk.LEFT)
        tb.Button(stats, text="Reset score", bootstyle="secondary-outline",
                  command=self.model.reset_stats).pack(side=tk.RIGHT)

    # --- deck events ----------------------------------------------------------------------

    def load_preset(self):
        self.model.load_preset(self.preset_var.get())

    def _on_text_modified(self, _event):
        if not self.deck_text.edit_modified():
            return
        self.deck_text.edit_modified(False)
        if self._syncing:
            return
        if self._text_job is not None:
            self.frame.after_cancel(self._text_job)
        self._text_job = self.frame.after(TEXT_DEBOUNCE_MS, self.apply_text)

    def close(self):
        """Stop pending edits before the tab's widgets go away."""
        if self._text_job is not None:
            self.frame.after_cancel(self._text_job)
            self._text_job = None

    def apply_text(self):
        """Parse the shorthand box into the model now (also called after the debounce)."""
        if self._text_job is not None:
            self.frame.after_cancel(self._text_job)
        self._text_job = None
        self._text_is_source = True
        try:
            self.model.set_from_text(self.deck_text.get("1.0", tk.END))
        finally:
            self._text_is_source = False

    def view_cards(self):
        if self._text_job is not None:  # show what was just typed
            self.apply_text()
        self.viewers.open("stack", "Stack (top first)", lambda: self.model.cards)

    # --- training events ------------------------------------------------------------------

    def apply_range(self):
        if not self.model.cards:
            return False
        try:
            self.model.set_range(int(self.first_var.get()), int(self.last_var.get()))
        except ValueError as exc:
            if "invalid literal" in str(exc):
                exc = "positions are whole numbers"
            self.range_error.config(text=f"⚠ {exc}")
            return False
        self.range_error.config(text="")
        return True

    def whole_deck(self):
        if self.model.cards:
            self.model.whole_deck()
        self.range_error.config(text="")

    def submit(self):
        """Check the typed answer; returns the Outcome, or None if nothing was scored."""
        if self.model.question is None:
            return None
        try:
            outcome = self.model.answer(self.answer_var.get())
        except ValueError as exc:
            self.feedback.config(text=f"⚠ {exc}", bootstyle="warning")
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
        self.answer_var.set("")
        self.answer_entry.focus_set()

    # --- refresh from model -------------------------------------------------------------

    def refresh(self):
        m = self.model
        if self._text_is_source:
            self._text_cards = list(m.cards)
        elif m.error is None and m.cards != self._text_cards:
            self._text_cards = list(m.cards)
            self._syncing = True
            self.deck_text.delete("1.0", tk.END)
            self.deck_text.insert("1.0", deck.format_cards(m.cards))
            self.deck_text.edit_modified(False)
            self._syncing = False
        self.text_error.config(text=f"⚠ {m.error}" if m.error else "")
        problems = m.deck_problems()
        if problems:
            self.deck_status.config(text="\n".join(problems), bootstyle="danger")
        else:
            n = len(m.cards)
            self.deck_status.config(text=f"✓ {n} card{'s' if n != 1 else ''}, each once.",
                                    bootstyle="success")

        n = len(m.cards)
        for box in self.range_boxes:
            box.config(to=max(n, 1))
        if n:
            self.first_var.set(str(m.first))
            self.last_var.set(str(m.last))
        self.range_total.config(text=f"of {n}" if n else "")
        for kind, var in self.kind_vars.items():  # e.g. after loading a saved tab
            if var.get() != (kind in m.kinds):
                var.set(kind in m.kinds)

        q = m.question
        self.question_label.config(text=q.prompt() if q else m.unavailable_reason())
        state = tk.NORMAL if q else tk.DISABLED
        for widget in (self.answer_entry, self.check_button, self.give_up_button):
            widget.config(state=state)

        o = m.last_outcome
        if o is None:
            self.feedback.config(text="")
        elif o.correct:
            self.feedback.config(text=f"✓ Right — {self._recap(o)}", bootstyle="success")
        else:
            given = f"You said {o.given}. " if o.given else ""
            self.feedback.config(text=f"✗ {given}{self._recap(o)}", bootstyle="danger")

        if m.asked:
            self.stats_label.config(
                text=f"Session: {m.correct} / {m.asked} right ({m.accuracy:.0%})   "
                     f"Streak: {m.streak}   Best: {m.best_streak}")
        else:
            self.stats_label.config(text="Session: no answers yet")
        self.viewers.refresh()

    @staticmethod
    def _recap(outcome):
        """The last question with its answer, e.g. "7♥ is at position 12."."""
        q = outcome.question
        if q.kind in (POSITION_OF, CARD_AT):
            return f"{q.card.pretty()} is at position {q.position}."
        where = "before" if q.kind == BEFORE else "after"
        return f"{q.answer.pretty()} comes {where} {q.card.pretty()}."
