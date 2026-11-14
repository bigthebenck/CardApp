"""The "Stacking" tab: pick the cards each poker hand should get, get the stack.

Left: the game, the number of players and (for hold'em) burn cards, then one
shorthand box per hand, and the flop, turn and river for hold'em. Right: the
starting order that deals those hands, each card marked with where it goes.
All state lives in ``StackingModel``; this module only draws it and forwards
user input.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QGridLayout, QLabel, QLineEdit,
                               QRadioButton, QSplitter, QWidget)

from .. import stacking
from .card_viewer import CardViewers
from .model import StackingModel
from .open_in import OpenInTabButton
from .sequence_panel import spin_box
from .widgets import Panel, button, column, copy, label, mono_font, row, set_text, set_tone, \
    text_box


class StackingTab:
    def __init__(self, parent, model=None, use_as_final=None, open_in=None):
        """``use_as_final(cards)``, if given, adds a button that hands the stack on;
        ``open_in(target, cards)`` adds an "Open in new tab" button."""
        self.model = model or StackingModel()
        self.use_as_final = use_as_final
        self.open_in = open_in
        self._shown_hands = None  # the hands the rows were last built for
        self.hand_edits = {}
        self.hand_errors = {}

        self.frame = QSplitter(Qt.Horizontal, parent)
        self.frame.setChildrenCollapsible(False)
        self.viewers = CardViewers(self.frame)
        left, left_layout = column(spacing=10)
        self._build_deal(left_layout)
        self._build_hands(left_layout)
        self.frame.addWidget(left)
        self.frame.addWidget(self._build_result())
        self.frame.setStretchFactor(0, 1)
        self.frame.setStretchFactor(1, 1)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    # --- setup ----------------------------------------------------------------------

    def _build_deal(self, parent_layout):
        frame = Panel("1. The deal")
        parent_layout.addWidget(frame)
        body = frame.body

        self.game_buttons = {}
        self.game_group = QButtonGroup(frame)
        radios = [QLabel("Game:")]
        for game, text in stacking.GAMES.items():
            radio = QRadioButton(text)
            radio.toggled.connect(lambda on, g=game: on and self.model.set_game(g))
            self.game_group.addButton(radio)
            self.game_buttons[game] = radio
            radios.append(radio)
        body.addWidget(row(*radios, None, spacing=12))

        self.players_box = spin_box(stacking.MIN_PLAYERS, stacking.MAX_PLAYERS,
                                    self.model.players)
        self.players_box.valueChanged.connect(lambda _v: self.apply_players())
        self.burns_check = QCheckBox("Burn a card before the flop, turn and river")
        self.burns_check.toggled.connect(self.model.set_burns)
        body.addWidget(row(QLabel("Players:"), self.players_box, 16, self.burns_check, None))
        self.players_error = label("", tone="danger")
        body.addWidget(self.players_error)
        body.addWidget(label("Player 1 sits on the dealer's left and gets the first card; "
                             "the last player is the dealer.", tone="muted", wrap=True))

    def _build_hands(self, parent_layout):
        frame = Panel("2. Cards wanted")
        parent_layout.addWidget(frame, 1)
        body = frame.body
        body.addWidget(row(label("Shorthand, e.g.  AS, KH.  X or a short hand = any card there.",
                                 tone="muted", wrap=True), None,
                           button("Clear all", self.model.clear)))
        self._hands_host = body
        self.hands_frame = QWidget()
        body.addWidget(self.hands_frame)
        body.addStretch(1)

    def _build_result(self):
        frame = Panel("3. Starting order (top first)")
        body = frame.body
        self.summary = label("", wrap=True)
        body.addWidget(self.summary)
        self.stack_text = text_box(read_only=True)
        body.addWidget(self.stack_text, 1)
        self.fill_check = QCheckBox("Fill the other positions with the unused cards "
                                    "(new deck order) instead of X")
        self.fill_check.toggled.connect(self.model.set_fill)
        body.addWidget(self.fill_check)

        buttons = [button("Copy shorthand", lambda: copy(self.model.shorthand())),
                   button("Copy list", lambda: copy(self.model.numbered())),
                   button("View cards", self.view_cards), None]
        if self.use_as_final is not None:
            self.final_button = button("Use as final deck →", self.send_to_final, kind="primary")
            buttons.append(self.final_button)
        body.addWidget(row(*buttons))
        if self.open_in is not None:
            self.open_button = OpenInTabButton(frame, self._stack_cards, self.open_in)
            body.addWidget(self.open_button.button, 0, Qt.AlignRight)
        return frame

    def _build_hand_rows(self):
        old = self.hands_frame
        self.hands_frame = QWidget()
        self._hands_host.replaceWidget(old, self.hands_frame)
        old.deleteLater()
        grid = QGridLayout(self.hands_frame)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        self.hand_edits, self.hand_errors = {}, {}
        r = 0
        for name, size in self.model.hands():
            text = f"{self.model.hand_label(name)} ({size} card{'s' if size != 1 else ''})"
            grid.addWidget(QLabel(text), r, 0)
            edit = QLineEdit(self.model.texts.get(name, ""))
            edit.setFont(mono_font())
            edit.textChanged.connect(lambda t, n=name: self.model.set_hand_text(n, t))
            grid.addWidget(edit, r, 1)
            error = label("", tone="danger")
            error.hide()
            grid.addWidget(error, r + 1, 1)
            self.hand_edits[name], self.hand_errors[name] = edit, error
            r += 2

    # --- events --------------------------------------------------------------------------

    def apply_players(self, players=None):
        """Deal to the players in the box (or ``players``); False if that's not allowed."""
        try:
            self.model.set_players(self.players_box.value() if players is None else players)
        except ValueError:
            self.players_error.setText(f"⚠ pick {stacking.MIN_PLAYERS} to "
                                       f"{stacking.MAX_PLAYERS} players")
            return False
        self.players_error.setText("")
        return True

    def view_cards(self):
        self.viewers.open("stack", "Poker stack (top first)", lambda: self.model.stack or [])

    def send_to_final(self):
        if self.model.stack is not None:
            self.use_as_final(list(self.model.stack))

    def _stack_cards(self):
        """The stack, to open in another tab."""
        if self.model.stack is None:
            raise ValueError(self.model.problem)
        return list(self.model.stack)

    # --- refresh from model -------------------------------------------------------------

    def refresh(self):
        m = self.model
        hands = (m.game, m.players)
        if hands != self._shown_hands:
            self._shown_hands = hands
            self._build_hand_rows()
        for name, edit in self.hand_edits.items():
            if edit.text() != m.texts.get(name, ""):  # e.g. after Clear all
                edit.blockSignals(True)
                edit.setText(m.texts.get(name, ""))
                edit.blockSignals(False)
            error = m.errors.get(name)
            shown = self.hand_errors[name]
            shown.setText(f"⚠ {error}" if error else "")
            shown.setVisible(bool(error))

        for game, radio in self.game_buttons.items():
            if radio.isChecked() != (game == m.game):
                radio.blockSignals(True)
                radio.setChecked(game == m.game)
                radio.blockSignals(False)
        self.players_box.blockSignals(True)
        self.players_box.setValue(m.players)
        self.players_box.blockSignals(False)
        for check, on in ((self.burns_check, m.burns), (self.fill_check, m.fill)):
            check.blockSignals(True)
            check.setChecked(on)
            check.blockSignals(False)
        self.burns_check.setEnabled(m.game == stacking.HOLDEM)

        if m.stack is not None:
            self.summary.setText(m.summary())
            set_tone(self.summary, None)
        else:
            self.summary.setText(f"⚠ {m.problem}")
            set_tone(self.summary, "danger")
        set_text(self.stack_text, m.numbered())
        if self.use_as_final is not None:
            self.final_button.setEnabled(m.stack is not None)
        self.viewers.refresh()
