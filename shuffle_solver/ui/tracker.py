"""The "Free Tracking" tab: enter a deck, work on it, and watch every pile.

Left: the deck you start with, entered as shorthand, and below it the buttons
that add steps. Middle: the steps, in order -- shuffles, card and packet moves
(take out, add, split, put one pile on another, gather), and rearrangements
typed in whole. Right: the table before the picked step, and under it the
table after. The whole tab saves as a project (``TrackerModel.save``). With no
step picked, the two sides show the very first and the very last table; with
several picked (or a group), before the first and after the last. Steps can be
grouped under a coloured title, e.g. one trick of a routine. All state lives in
``TrackerModel``; this module only draws it and forwards user edits. It
contains no shuffle math.
"""

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QLabel, QLineEdit, QSpinBox, QSplitter,
                               QVBoxLayout)

from .. import deck, tracking
from . import theme
from .card_viewer import CardViewers
from .model import TrackerModel, format_table
from .open_in import OpenInTabButton
from .presets import PresetBar, PresetStore
from .sequence_panel import SequencePanel
from .widgets import (Debounce, Panel, button, column, copy, label, mono_font, row, set_text,
                      set_tone, text_box)

PLACE_WHERE = {"on top of": True, "under": False}


def _line(width=None):
    edit = QLineEdit()
    edit.setFont(mono_font())
    if width:
        edit.setMinimumWidth(width)
    return edit


def _combo(values=(), width=None):
    box = QComboBox()
    box.addItems(list(values))
    if width:
        box.setMinimumContentsLength(width)
    return box


def _set_choices(box, values):
    """Offer ``values`` in ``box``, keeping its pick if it's still there."""
    picked = box.currentText()
    box.blockSignals(True)
    box.clear()
    box.addItems(list(values))
    if picked in values:
        box.setCurrentText(picked)
    box.blockSignals(False)


def _position_box():
    box = QSpinBox()
    box.setRange(1, 200)
    box.setMinimumWidth(64)
    return box


class TrackerTab:
    def __init__(self, parent, model=None, presets=None, open_in=None):
        """``open_in(target, cards)``, if given, adds "Open in new tab" buttons."""
        self.model = model or TrackerModel()
        self.presets = presets or PresetStore()
        self.open_in = open_in
        self.open_buttons = {}  # "deck", "before", "after" -> OpenInTabButton
        self._syncing = False
        self._text_is_source = False
        self._text_cards = None  # cards the shorthand box last described
        self._shown = {"before": None, "after": None}  # Table each side shows, if any
        self._titles = {"before": "", "after": ""}

        self.frame = QSplitter(Qt.Horizontal, parent)
        self.frame.setChildrenCollapsible(False)
        self._text_job = Debounce(self.frame, self.apply_text)
        self.viewers = CardViewers(self.frame)
        self.boxes, self.views = {}, {}

        # Left: what to track and how to add to it. Middle: the steps, as tall as the
        # window allows. Right: the table before and after the picked steps.
        left, left_layout = column(spacing=10)
        self._build_deck_input(left_layout)
        controls = Panel("Add a step (after the picked one, or at the end)")
        left_layout.addWidget(controls, 1)
        self.pile_box = _combo([self.model.target_pile], width=3)
        self.pile_box.currentTextChanged.connect(lambda _t: self._on_pile_chosen())
        controls.body.addWidget(row(QLabel("Shuffle pile:"), self.pile_box,
                                    label("(new shuffles, splits and added cards go to this "
                                          "pile)", tone="muted", wrap=True), None))
        self.frame.addWidget(left)

        middle, middle_layout = column()
        middle_layout.addWidget(label(
            "Shift- or Ctrl-click to pick several steps, then Group… to title and colour "
            "them. Double-click a rearrangement or a group to edit it. Split A | B: A is the "
            "card you see on the bottom of the upper packet, B the top card of the rest.",
            tone="muted", wrap=True))
        self.sequence = SequencePanel(
            None, self.model, "Steps (click one to see before and after it)",
            self._step_decks, on_select=self._show_states,
            extra_buttons=(("Start → End", self.show_whole_run),
                           ("Group…", self.open_group_dialog)),
            deck_size=lambda index: self.model.size_at(index),
            row_problem=self.model.step_problem,
            extra_tabs=(("Cards && packets", self._build_card_ops),),
            groups=lambda: self.model.groups, controls=controls.body, splits_in_list=True)
        middle_layout.addWidget(self.sequence.frame, 1)
        self.sequence.step_list.on_escape = self.show_whole_run
        self.sequence.step_list.itemDoubleClicked.connect(self._on_double_click)
        self.dialog = None  # the open Rearrange or Group window, if any
        self.frame.addWidget(middle)

        right, right_layout = column(spacing=10)
        self._build_state_view(right_layout, "before")
        self._build_state_view(right_layout, "after")
        self.frame.addWidget(right)
        for i in range(3):
            self.frame.setStretchFactor(i, 1)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    # --- setup ----------------------------------------------------------------------

    def _build_deck_input(self, parent_layout):
        frame = Panel("Deck to track (top first)")
        parent_layout.addWidget(frame)
        body = frame.body

        self.preset_bar = PresetBar(frame, self.presets, self._preset_cards,
                                    self.model.set_cards)
        self.preset_bar.add_right(button("Clear", lambda: self.model.set_cards([])))
        body.addWidget(self.preset_bar.frame)

        body.addWidget(label("Shorthand, any number of cards (e.g.  A-KH, A-KC, K-AD, K-AS;\n"
                             "X = any card, X12 = twelve of them, B = any high, L = any low):"))
        self.deck_text = text_box(lines=3)
        self.deck_text.textChanged.connect(self._on_text_modified)
        body.addWidget(self.deck_text)
        if self.open_in is not None:
            self.open_buttons["deck"] = OpenInTabButton(frame, self._preset_cards, self.open_in)
            body.addWidget(self.open_buttons["deck"].button, 0, Qt.AlignRight)
        self.text_error = label("", tone="danger", wrap=True)
        body.addWidget(self.text_error)
        self.deck_status = label("", wrap=True)
        body.addWidget(self.deck_status)

    def _build_state_view(self, parent_layout, side):
        """A read-only table of piles, each in columns of 13, with copy and view buttons."""
        frame = Panel("")
        parent_layout.addWidget(frame, 1)
        text = text_box(read_only=True, wrap=False)
        text.setMinimumHeight(80)
        frame.body.addWidget(text, 1)
        buttons = [button("Copy shorthand", lambda: copy(self.shorthand(side))), None]
        if self.open_in is not None:
            self.open_buttons[side] = OpenInTabButton(
                frame, lambda: self._shown_cards(side), self.open_in, text="Open in…")
            buttons.append(self.open_buttons[side].button)
        buttons.append(button("View cards", lambda: self.view_cards(side)))
        frame.body.addWidget(row(*buttons))
        self.boxes[side] = frame
        self.views[side] = text

    def _build_card_ops(self, tab):
        """The "Cards & packets" tab: steps that move cards rather than shuffle them."""
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(row(button("Rearrange…", self.open_rearrange),
                             label("type the whole new order, e.g. after revealing cards",
                                   tone="muted", wrap=True), None))
        layout.addSpacing(6)

        self.cards_edit = _line(140)
        layout.addWidget(row(QLabel("Cards:"), self.cards_edit,
                             label("e.g. AC AH AS AD, or X5 to add", tone="muted")))
        take = row(*(button(text, lambda m=mode: self.take_out(m))
                     for text, mode in (("Take out → new pile", "pile"),
                                        ("Take out → one pile each", "each"),
                                        ("Discard", "discard"))), spacing=4)
        layout.addWidget(take)

        self.add_pos = _position_box()
        layout.addWidget(row(button("Add cards", self.add_cards),
                             QLabel("to the shuffle pile at position"), self.add_pos,
                             label("(1 = top)", tone="muted"), None))
        self.name_pos = _position_box()
        layout.addWidget(row(button("Name X cards", self.name_cards),
                             QLabel("in the shuffle pile from position"), self.name_pos, None))
        layout.addWidget(label("Turns the X cards there into the Cards box's cards, in earlier "
                               "steps too, e.g. to know the card at a faro's split.",
                               tone="muted", wrap=True))
        layout.addSpacing(6)

        self.sizes_edit = _line(110)
        layout.addWidget(row(button("Split", self.split), QLabel("shuffle pile into packets of"),
                             self.sizes_edit))
        layout.addWidget(label("Sizes from the top, e.g. 1,1,1,1,12,12,12,12; cards left over "
                               "make one more packet.", tone="muted", wrap=True))
        layout.addSpacing(6)

        self.place_pile_box = _combo(width=3)
        self.place_where_box = _combo(PLACE_WHERE)
        self.place_onto_box = _combo(width=3)
        layout.addWidget(row(button("Put", self.place), QLabel("pile"), self.place_pile_box,
                             self.place_where_box, QLabel("pile"), self.place_onto_box, None))
        layout.addSpacing(6)

        self.gather_edit = _line(90)
        layout.addWidget(row(button("Gather", self.gather), QLabel("piles"), self.gather_edit))
        layout.addWidget(label("e.g. A B C D, first on top; blank gathers every pile in "
                               "table order.", tone="muted", wrap=True))
        layout.addStretch(1)

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
        self._close_dialog()

    def apply_text(self):
        """Parse the shorthand box into the model now (also called after the debounce)."""
        self._text_job.stop()
        self._text_is_source = True
        try:
            self.model.set_from_text(self.deck_text.toPlainText())
        finally:
            self._text_is_source = False

    # --- step events ------------------------------------------------------------------------

    def _on_pile_chosen(self):
        if self.pile_box.currentText():
            self.model.target_pile = self.pile_box.currentText()
            self.sequence.update_add_buttons()

    def _refuse(self, message):
        self.sequence.seq_error.setText(f"Can't add step: {message}")
        return False

    def _named_cards(self):
        text = self.cards_edit.text().strip()
        if not text:
            raise ValueError("type the cards in the Cards box")
        # Spaces separate cards here as well as commas: "AC AH" means "AC, AH".
        return tuple(deck.parse_cards(", ".join(re.split(r"[\s,]+", text)),
                                      allow_indifferent=True))

    def take_out(self, mode):
        """Take the Cards box's cards out: as one pile, a pile each, or for good."""
        try:
            cards = self._named_cards()
        except ValueError as exc:
            return self._refuse(exc)
        return self.sequence.add(tracking.TakeOut(cards, mode))

    def add_cards(self):
        try:
            cards = self._named_cards()
        except ValueError as exc:
            return self._refuse(exc)
        return self.sequence.add(tracking.AddCards(cards, self.model.target_pile,
                                                   self.add_pos.value()))

    def name_cards(self):
        """Turn the X cards at the chosen position into the Cards box's cards."""
        try:
            cards = self._named_cards()
        except ValueError as exc:
            return self._refuse(exc)
        return self.sequence.add(tracking.NameCards(cards, self.model.target_pile,
                                                    self.name_pos.value()))

    def split(self):
        try:
            sizes = tuple(int(s) for s in re.split(r"[\s,;]+", self.sizes_edit.text().strip()))
        except ValueError:
            return self._refuse("packet sizes are whole numbers, e.g. 1,1,1,1,12,12,12,12")
        return self.sequence.add(tracking.Split(self.model.target_pile, sizes))

    def place(self):
        return self.sequence.add(tracking.Place(self.place_pile_box.currentText(),
                                                self.place_onto_box.currentText(),
                                                PLACE_WHERE[self.place_where_box.currentText()]))

    def gather(self):
        names = tuple(n.upper() for n in re.split(r"[\s,;]+", self.gather_edit.text()) if n)
        return self.sequence.add(tracking.Gather(names))

    def open_rearrange(self, edit=None):
        """Open the Rearrange window: for a new step, or to edit step ``edit``."""
        self._close_dialog()
        self.dialog = RearrangeDialog(self, edit)
        return self.dialog

    def open_group_dialog(self):
        """Group the selected steps, or edit the selected group."""
        self._close_dialog()
        group_id = self.sequence.selected_group()
        span = self.sequence.selected_range()
        if group_id is None and span is not None:
            group = self.model.group_of(span[0])
            if group is not None and (group.first, group.last) == span:
                group_id = group.id
        if group_id is None and span is None:
            return self._refuse_group("select the steps to group first (click the first, "
                                      "shift-click the last)")
        self.dialog = GroupDialog(self, span, group_id)
        return self.dialog

    def _refuse_group(self, message):
        self.sequence.seq_error.setText(f"Can't group: {message}")
        return None

    def _close_dialog(self):
        if self.dialog is not None:
            self.dialog.close()

    def _on_double_click(self, item, _column):
        row_id = item.data(0, Qt.UserRole)
        if row_id.startswith("g"):
            self.sequence.select_rows([row_id])
            self.open_group_dialog()
        elif isinstance(self.model.steps[int(row_id[1:])], tracking.Rearrange):
            self.open_rearrange(int(row_id[1:]))

    def show_whole_run(self):
        """Go back to the very first and very last table."""
        self.sequence.select_step(None)

    # --- output ---------------------------------------------------------------------------

    def view_cards(self, side):
        if self._text_job.pending:  # show what was just typed
            self.apply_text()
        self.viewers.open(side, self._titles[side], lambda: self._groups(side))

    def _groups(self, side):
        """The side's piles as card-viewer groups: (heading, cards)."""
        table = self._shown[side]
        if table is None:
            return []
        return [(f"Pile {p.name} — {len(p)} card{'s' if len(p) != 1 else ''}",
                 list(p.cards)) for p in table.piles]

    def _shown_cards(self, side):
        """The side's cards, to open in another tab (which takes one pile only)."""
        if self._text_job.pending:  # use what was just typed
            self.apply_text()
        table = self._shown[side]
        if table is None or not table.piles:
            raise ValueError("there are no cards to open")
        if len(table.piles) > 1:
            raise ValueError("the cards are in several piles; gather them into one first")
        return list(table.piles[0].cards)

    def shorthand(self, side):
        """The side's cards as shorthand; several piles as ``A: ... | B: ...``."""
        table = self._shown[side]
        if table is None or not table.piles:
            return ""
        return tracking.format_piles(table.piles)

    # --- refresh from model -------------------------------------------------------------

    def _step_decks(self):
        return self.model.step_decks() if self.model.states is not None else None

    def refresh(self):
        m = self.model
        # Rewrite the box only when the deck changed from somewhere else (preset,
        # clear), so the user's own formatting survives.
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
            full = " (a full deck)" if deck.validate_deck(m.cards).ok else ""
            self.deck_status.setText(f"✓ {n} card{'s' if n != 1 else ''}{full}, each once.")
            set_tone(self.deck_status, "success")
        self.sequence.refresh()  # also redraws both sides through _show_states

    def _update_pile_choices(self):
        """Offer the piles a new step (after the selected one) would find."""
        names = self.model.piles_at(self.sequence.insert_index())
        if self.model.target_pile not in names:
            self.model.target_pile = names[0]
        _set_choices(self.pile_box, names)
        self.pile_box.blockSignals(True)
        self.pile_box.setCurrentText(self.model.target_pile)
        self.pile_box.blockSignals(False)
        for box, default in ((self.place_pile_box, names[-1]), (self.place_onto_box, names[0])):
            had = box.currentText()
            _set_choices(box, names)
            if had not in names:
                box.setCurrentText(default)
        self.sequence.update_add_buttons()

    def _show_states(self, _index):
        self._update_pile_choices()
        span = self.sequence.selected_range()
        before_title, before, after_title, after = self.model.around(*(span or (None,)))
        for side, title, table in (("before", before_title, before),
                                   ("after", after_title, after)):
            self._titles[side] = title
            self._shown[side] = table
            self.boxes[side].setTitle(title)
            viewer = self.viewers.get(side)
            if viewer is not None:
                viewer.set_title(title)
            set_text(self.views[side], format_table(table) if table is not None else
                     self.model.missing_reason())
        self.viewers.refresh()


class _Dialog:
    """A small window over the tab, closed by Cancel, Escape or its own OK."""

    def __init__(self, tab, title):
        self.tab = tab
        self.win = QDialog(tab.frame.window())
        self.win.setWindowTitle(title)
        self.win.rejected.connect(self.close)
        self.layout = QVBoxLayout(self.win)
        self.layout.setContentsMargins(14, 14, 14, 14)

    def buttons(self, ok_text, extra=()):
        ok = button(ok_text, self.ok, kind="primary")
        ok.setDefault(True)
        items = [button(text, command, kind=kind) for text, command, kind in extra]
        self.layout.addSpacing(6)
        self.layout.addWidget(row(*items, None, ok, button("Cancel", self.close)))
        self.win.show()

    def is_open(self):
        return self.win is not None

    def close(self):
        if self.win is not None:
            win, self.win = self.win, None
            win.hide()
            win.deleteLater()
        if self.tab.dialog is self:
            self.tab.dialog = None


class RearrangeDialog(_Dialog):
    """Type a new order for the whole table, with a short title (a Rearrange step)."""

    HELP = ("The table after this step, top card first. Separate piles with | "
            "and name them with their letter, e.g.\n"
            "    A: 2-KC, AC |\n    B: 2-KH, AH\n"
            "Without names, piles keep the names of the piles already on the table, in "
            "order. It must hold exactly the cards on the table, with as many X cards as "
            "before; a ` marks a face-up card.")

    def __init__(self, tab, edit=None):
        super().__init__(tab, "Edit rearrangement" if edit is not None else "Rearrange")
        model = tab.model
        self.edit = edit
        self.index = edit if edit is not None else tab.sequence.insert_index()
        step = model.steps[edit] if edit is not None else None
        table = model.table_before(self.index)

        self.title_edit = QLineEdit(step.title if step else "")
        self.title_edit.setMinimumWidth(280)
        self.layout.addWidget(row(QLabel("Title:"), self.title_edit,
                                  label("e.g. Card revelations", tone="muted")))
        self.layout.addWidget(label(self.HELP, tone="muted", wrap=True))
        self.text = text_box()
        self.text.setMinimumSize(560, 200)
        start = step.text() if step else (tracking.format_piles(table.piles)
                                          if table is not None and table.piles else "")
        self.text.setPlainText(start)
        self.text.textChanged.connect(self.check)
        self.layout.addWidget(self.text, 1)
        self.status = label("", wrap=True)
        self.layout.addWidget(self.status)
        self.buttons("Save" if edit is not None else "Add step")
        self.check()
        self.title_edit.setFocus()

    def set_text(self, text):
        self.text.setPlainText(text)
        self.check()

    def step(self):
        """The Rearrange step as typed, or raise ValueError saying what's wrong."""
        piles = tracking.parse_piles(self.text.toPlainText())
        step = tracking.Rearrange(self.title_edit.text().strip(), piles)
        table = self.tab.model.table_before(self.index)
        if table is not None:
            step.apply(table)
        return step

    def _status(self, text, tone):
        self.status.setText(text)
        set_tone(self.status, tone)

    def check(self):
        """Show whether the text is a usable new order; returns the error or None."""
        try:
            step = self.step()
        except ValueError as exc:
            self._status(f"⚠ {exc}", "danger")
            return str(exc)
        n = sum(len(cards) for _name, cards in step.piles)
        piles = len(step.piles)
        self._status(f"✓ {n} card{'s' if n != 1 else ''}"
                     + (f" in {piles} piles" if piles != 1 else ""), "success")
        return None

    def ok(self):
        if self.check() is not None:
            return False
        step = self.step()
        if self.edit is not None:
            try:
                self.tab.model.replace_step(self.edit, step)
            except ValueError as exc:
                self._status(f"⚠ {exc}", "danger")
                return False
            self.tab.sequence.select_step(self.edit)
        elif not self.tab.sequence.add(step, self.index):
            return False
        self.close()
        return True


class GroupDialog(_Dialog):
    """Title and colour a run of steps (a new group), or change or remove a group."""

    def __init__(self, tab, span, group_id=None):
        super().__init__(tab, "Edit group" if group_id is not None else "Group steps")
        model = tab.model
        self.group_id = group_id
        group = model.group(group_id) if group_id is not None else None
        self.span = (group.first, group.last) if group else span
        first, last = self.span
        self.layout.addWidget(QLabel(f"Steps {first + 1}–{last + 1}" if last > first
                                     else f"Step {first + 1}"))
        self.title_edit = QLineEdit(group.title if group else "")
        self.title_edit.setMinimumWidth(220)
        self.layout.addWidget(row(QLabel("Title:"), self.title_edit))
        self.color_box = _combo(theme.GROUP_COLORS)
        self.color_box.setCurrentText(group.color if group else next(iter(theme.GROUP_COLORS)))
        self.layout.addWidget(row(QLabel("Colour:"), self.color_box, None))
        self.status = label("", tone="danger", wrap=True)
        self.layout.addWidget(self.status)
        extra = (("Ungroup", self.ungroup, "danger"),) if group else ()
        self.buttons("Save" if group else "Group", extra)
        self.title_edit.setFocus()

    def ok(self):
        model = self.tab.model
        try:
            if self.group_id is not None:
                model.edit_group(self.group_id, self.title_edit.text(),
                                 self.color_box.currentText())
            else:
                model.add_group(*self.span, self.title_edit.text(), self.color_box.currentText())
        except ValueError as exc:
            self.status.setText(f"⚠ {exc}")
            return False
        self.close()
        return True

    def ungroup(self):
        self.tab.model.remove_group(self.group_id)
        self.close()
