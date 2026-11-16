"""The shuffle-sequence editor shared by the "Starting Order" and "Free Tracking" tabs.

Buttons to add each shuffle, the ordered step list (with the card you see at
each faro's, cut's or packet run's split), and X/Y editing of the selected step. It edits any model
with the ``StepList`` methods and shows the deck states its owner hands it;
it contains no shuffle math.
"""

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QSpinBox, QStyle, QStyledItemDelegate,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import shuffle_ops as ops
from .. import solver
from . import theme
from .model import DECK_SIZE, format_splits, split_cards
from .widgets import Panel, button, label, row

ROW_ID = Qt.UserRole

# Partial faro packet choices: label -> (cut from, woven into)
PARTIAL_DIRECTIONS = {
    "top into top": (ops.TOP, ops.TOP),
    "top into bottom": (ops.TOP, ops.BOTTOM),
    "bottom into top": (ops.BOTTOM, ops.TOP),
    "bottom into bottom": (ops.BOTTOM, ops.BOTTOM),
}

HELP_TEXT = ("Overhand run: X = 1–52 (52 reverses the deck). "
             "Packet run: pick up the top X cards (2–52), run Y of them one at a "
             "time onto the deck and drop the rest on top; Y \"all\" runs them "
             "all, reversing the top X. "
             "Cut: X = 1–51. Partial faro: cut off X cards (up to 26) from "
             "the top or bottom and weave them into the top or bottom of "
             "the rest. Out keeps the packet's outer card on the outside "
             "(its top card on top, or its bottom card on the bottom); in "
             "tucks it one card inside.")


def spin_box(lo, hi, value=None, blank=None):
    """A number box; with ``blank``, its lowest value shows as that text (meaning none)."""
    box = QSpinBox()
    box.setRange(lo, hi)
    box.setKeyboardTracking(False)  # report a value once typing is done, not per keystroke
    if blank is not None:
        box.setSpecialValueText(blank)
    if value is not None:
        box.setValue(value)
    box.setMinimumWidth(64)
    return box


class _TintDelegate(QStyledItemDelegate):
    """Paints a row's own background (a group's colour) under the stylesheet's drawing,
    which would otherwise leave it out."""

    def paint(self, painter, option, index):
        brush = index.data(Qt.BackgroundRole)
        if brush is not None and not option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, brush)
        super().paint(painter, option, index)


class StepTree(QTreeWidget):
    """The step list: Delete removes the selected step, Escape runs ``on_escape``."""

    def __init__(self):
        super().__init__()
        self.on_delete = None
        self.on_escape = None
        self.setItemDelegate(_TintDelegate(self))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete and self.on_delete is not None:
            self.on_delete()
        elif event.key() == Qt.Key_Escape and self.on_escape is not None:
            self.on_escape()
        else:
            super().keyPressEvent(event)

    def item_of(self, row_id):
        for item in self.all_items():
            if item.data(0, ROW_ID) == row_id:
                return item
        return None

    def all_items(self):
        out = []
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            out.append(top)
            out += [top.child(j) for j in range(top.childCount())]
        return out

    def children_of(self, row_id=None):
        """The row ids at the top level, or under group ``row_id``."""
        if row_id is None:
            return tuple(self.topLevelItem(i).data(0, ROW_ID)
                         for i in range(self.topLevelItemCount()))
        item = self.item_of(row_id)
        return tuple(item.child(j).data(0, ROW_ID) for j in range(item.childCount()))

    def selected_ids(self):
        return [item.data(0, ROW_ID) for item in self.selectedItems()]


class SequencePanel:
    """The step list and the buttons that add to it.

    ``get_states()`` gives, for each step k (from 1), the deck it is done on at
    index k - 1 (None where there is no single deck), or None for no decks at all.
    ``on_select(index or None)`` runs whenever the selected step changes.
    ``deck_size(index)`` is the size of the deck a new step at ``index`` would be
    done on (None if unknown; default: always a full deck). ``row_problem(index)``
    gives the message for a step that can't be done, else None.
    ``extra_tabs`` are (title, build(widget)) pairs shown next to the shuffle buttons.
    ``groups()`` gives the model's step groups (see ``StepGroup``); with it, several
    steps can be selected at once and each group is a coloured, foldable row.
    ``controls``, if given, is a layout elsewhere to hold the add buttons and help,
    leaving the panel to the step list. ``splits_in_list`` shows both cards at
    each split in the list's own column instead of in a list under it.
    """

    def __init__(self, parent, model, title, get_states, on_select=None, extra_buttons=(),
                 deck_size=None, row_problem=None, extra_tabs=(), groups=None,
                 controls=None, splits_in_list=False):
        self.model = model
        self.groups = groups
        self._group_rows = {}  # group row id -> (first, last) step
        self.get_states = get_states
        self.on_select = on_select
        self.deck_size = deck_size or (lambda _index: DECK_SIZE)
        self.row_problem = row_problem or (lambda _index: None)
        self._problem_shown = False
        self.splits_in_list = splits_in_list
        self.frame = Panel(title, parent)
        self._build(extra_buttons, extra_tabs, controls)

    def _build(self, extra_buttons, extra_tabs, controls):
        body = self.frame.body
        host = body if controls is None else controls  # where the add buttons go
        if extra_tabs:
            self.add_tabs = QTabWidget()
            host.addWidget(self.add_tabs)
            add = QWidget()
            self.add_tabs.addTab(add, "Shuffles")
            for tab_title, build in extra_tabs:
                tab = QWidget()
                build(tab)
                self.add_tabs.addTab(tab, tab_title)
        else:
            add = QWidget()
            host.addWidget(add)
        grid = QGridLayout(add)
        grid.setContentsMargins(0, 6 if extra_tabs else 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self.faro_buttons = [button("+ Out-Faro", lambda: self.add_step(ops.OUT_FARO)),
                             button("+ In-Faro", lambda: self.add_step(ops.IN_FARO))]
        for col, b in enumerate(self.faro_buttons):
            grid.addWidget(b, 0, col)
        grid.addWidget(button("+ Overhand Run", lambda: self.add_step(ops.OVERHAND_RUN)), 1, 0)
        grid.addWidget(button("+ Cut", lambda: self.add_step(ops.CUT)), 1, 1)
        grid.addWidget(button("+ Partial Out-Faro",
                              lambda: self.add_step(self.partial_kind(True))), 2, 0)
        grid.addWidget(button("+ Partial In-Faro",
                              lambda: self.add_step(self.partial_kind(False))), 2, 1)
        self.partial_dir = QComboBox()
        self.partial_dir.addItems(list(PARTIAL_DIRECTIONS))
        grid.addWidget(row(QLabel("Partial faro packet:"), self.partial_dir, None), 3, 0, 1, 4)
        grid.addWidget(button("+ Packet Run", lambda: self.add_step(ops.PACKET_RUN)), 4, 0)
        self.new_y = spin_box(0, DECK_SIZE, 0, blank="all")
        grid.addWidget(row(QLabel("Run Y:"), self.new_y, None), 4, 1, 1, 3)
        self.odd_note = label("", tone="muted")
        grid.addWidget(self.odd_note, 5, 0, 1, 4)
        x_label = QLabel("X:")
        x_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(x_label, 1, 2, 2, 1)
        self.new_x = spin_box(1, DECK_SIZE, 5)
        grid.addWidget(self.new_x, 1, 3, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        middle = QWidget()
        mid = QHBoxLayout(middle)
        mid.setContentsMargins(0, 4, 0, 4)
        # Two columns so the card seen at a split stays visible in a narrow pane.
        t = self.step_list = StepTree()
        t.setColumnCount(2)
        t.setHeaderLabels(["Shuffle", "Split" if self.splits_in_list else "You see"])
        t.setRootIsDecorated(bool(self.groups))
        if not self.groups:
            t.setIndentation(0)
        t.setSelectionMode(QAbstractItemView.ExtendedSelection if self.groups
                           else QAbstractItemView.SingleSelection)
        t.setExpandsOnDoubleClick(False)
        t.setUniformRowHeights(True)
        header = t.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.resizeSection(1, 100 if self.splits_in_list else 72)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        t.itemSelectionChanged.connect(self._on_step_select)
        t.on_delete = self._delete_step
        mid.addWidget(t, 1)
        buttons = QVBoxLayout()
        buttons.setSpacing(4)
        for text, cmd in (("↑ Up", lambda: self._move_step(-1)),
                          ("↓ Down", lambda: self._move_step(1)),
                          ("Duplicate", self._duplicate_step),
                          ("Delete", self._delete_step),
                          ("Clear all", self.model.clear_steps),
                          *extra_buttons):
            buttons.addWidget(button(text, cmd))
        buttons.addStretch(1)
        mid.addLayout(buttons)
        body.addWidget(middle, 1)

        # Where each faro, cut or packet run splits the deck, once there is a deck to split.
        self.split_label = label("", mono=True, wrap=True)
        if not self.splits_in_list:
            body.addWidget(self.split_label)

        self.edit_x = spin_box(0, 0, blank="–")
        self.edit_x.valueChanged.connect(lambda _v: self.commit_edit_x())
        self.edit_y = spin_box(0, 0, blank="–")
        self.edit_y.valueChanged.connect(lambda _v: self.commit_edit_y())
        body.addWidget(row(QLabel("Selected step X:"), self.edit_x, 8, QLabel("Y:"),
                           self.edit_y, None))
        self.seq_error = label("", tone="danger", wrap=True)
        body.addWidget(self.seq_error)
        help_text = label(HELP_TEXT, tone="muted", wrap=True)
        if controls is None:
            body.addWidget(help_text)
        else:  # the Shuffles tab has room to spare beside the taller tabs
            grid.addWidget(help_text, 6, 0, 1, 4)
            grid.setRowStretch(7, 1)

    # --- events -----------------------------------------------------------------------------

    def partial_kind(self, out):
        source, dest = PARTIAL_DIRECTIONS[self.partial_dir.currentText()]
        return ops.partial_faro_kind(source, dest, out)

    # Rows are named "s<index>" for a step and "g<id>" for a group.

    def selected_step(self):
        """The selected step, when exactly one step (and no group) is selected."""
        sel = self.step_list.selected_ids()
        return int(sel[0][1:]) if len(sel) == 1 and sel[0].startswith("s") else None

    def selected_range(self):
        """(first, last) step covered by the selection (a group covers its steps), or None."""
        spans = [self._group_rows.get(r) or (int(r[1:]),) * 2
                 for r in self.step_list.selected_ids()]
        if not spans:
            return None
        return min(a for a, _b in spans), max(b for _a, b in spans)

    def selected_group(self):
        """The id of the group row selected on its own, else None."""
        sel = self.step_list.selected_ids()
        return int(sel[0][1:]) if len(sel) == 1 and sel[0].startswith("g") else None

    def select_step(self, index):
        """Select step ``index`` (None clears the selection)."""
        self.select_rows([] if index is None else [f"s{index}"])

    def select_range(self, first, last):
        """Select steps ``first``..``last``."""
        self.select_rows([f"s{i}" for i in range(first, last + 1)])

    def select_rows(self, rows):
        t = self.step_list
        items = [item for item in (t.item_of(r) for r in rows) if item is not None]
        t.blockSignals(True)
        t.clearSelection()
        for item in items:
            item.setSelected(True)
        if items:
            t.setCurrentItem(items[0], 0, QItemSelectionModel.NoUpdate)
            t.scrollToItem(items[0])
        t.blockSignals(False)
        t.viewport().update()
        self._on_step_select()

    def insert_index(self):
        """Where a new step goes: after the selected ones, or at the end."""
        span = self.selected_range()
        return len(self.model.steps) if span is None else span[1] + 1

    def _new_deck_size(self):
        size = self.deck_size(self.insert_index())
        return DECK_SIZE if size is None else size

    def add_step(self, kind):
        """Add a shuffle after the selected step (or at the end) and select it."""
        x = y = None
        n = self._new_deck_size()
        if kind in (ops.OUT_FARO, ops.IN_FARO) and n % 2:
            self.seq_error.setText(f"Can't add step: {n} cards; a full faro needs an even "
                                   "number, so use a partial faro")
            return
        try:
            if kind in ops.KINDS_WITH_X:
                x = self.new_x.value()
                if kind in ops.KINDS_WITH_Y:
                    y = self.new_y.value() or None
                    y = None if y == x else y
            step = solver.Step(kind, x, y)
            step.validate(n)
        except (ValueError, TypeError) as exc:
            self.seq_error.setText(f"Can't add step: {exc}")
            return
        self.add(step)

    def add(self, step, index=None):
        """Add any step the model takes after the selected one (or at ``index``) and
        select it. Returns False (and shows why) if the model refuses it.
        """
        index = self.insert_index() if index is None else index
        try:
            self.model.add_step(step, index)
        except (ValueError, TypeError) as exc:
            self.seq_error.setText(f"Can't add step: {exc}")
            return False
        self.seq_error.setText("")
        self.select_step(index)
        return True

    def _move_step(self, delta):
        sel = self.selected_step()
        if sel is not None:
            self.select_step(self.model.move_step(sel, delta))

    def _duplicate_step(self):
        """Copy the selected step, steps or group to just after the selection."""
        span = self.selected_range()
        if span is None:
            return
        first, last = span
        at = self.model.duplicate_steps(first, last)
        end = at + last - first
        copy = next((g for g in (self.groups() if self.groups else ())
                     if (g.first, g.last) == (at, end)), None)
        if copy is not None:
            self.select_rows([f"g{copy.id}"])
        elif at == end:
            self.select_step(at)
        else:
            self.select_range(at, end)

    def _delete_step(self):
        sel = self.selected_step()
        if sel is not None:
            self.model.remove_step(sel)
            self.select_step(min(sel, len(self.model.steps) - 1))

    @staticmethod
    def _set_box(box, lo=None, hi=None, value=None, blank="–"):
        """Show ``value`` in ``box`` with the range lo..hi; None for all three: blank and off."""
        box.blockSignals(True)
        if lo is None:
            box.setSpecialValueText(blank)
            box.setRange(0, 0)
            box.setEnabled(False)
        else:
            box.setSpecialValueText("all" if lo == 0 else "")
            box.setRange(lo, hi)
            box.setValue(value)
            box.setEnabled(True)
        box.blockSignals(False)

    def _on_step_select(self):
        sel = self.selected_step()
        step = self.model.steps[sel] if sel is not None else None
        if step is not None and step.kind in ops.KINDS_WITH_X:
            states = self.get_states()
            deck = states[sel] if states and sel < len(states) else None
            lo, hi = ops.x_bounds(step.kind, DECK_SIZE if deck is None else len(deck))
            self._set_box(self.edit_x, lo, max(hi, lo), step.x)
        else:
            self._set_box(self.edit_x)
        if step is not None and step.kind in ops.KINDS_WITH_Y:
            self._set_box(self.edit_y, 0, step.x, step.y or 0)  # 0 shows as "all"
        else:
            self._set_box(self.edit_y)
        self.update_add_buttons()
        if self.on_select is not None:
            self.on_select(sel)

    def update_add_buttons(self):
        """Allow full faros only on an even deck, and X only up to the deck's size."""
        n = self._new_deck_size()
        self.new_x.setMaximum(max(n, 1))
        for b in self.faro_buttons:
            b.setEnabled(not n % 2)
        self.odd_note.setText(f"Odd number of cards ({n}): partial faros only."
                              if n % 2 else "")

    def commit_edit_x(self, value=None):
        """Give the selected step the X in the box (or ``value``)."""
        sel = self.selected_step()
        if sel is None or self.model.steps[sel].kind not in ops.KINDS_WITH_X:
            return
        try:
            self.model.set_step_x(sel, self.edit_x.value() if value is None else value)
            self.seq_error.setText("")
        except (ValueError, TypeError) as exc:
            self.seq_error.setText(f"Invalid X: {exc}")
            return
        self.select_step(sel)

    def commit_edit_y(self, value=None):
        """Give the selected step the Y in the box (or ``value``; 0 or None: all)."""
        sel = self.selected_step()
        if sel is None or self.model.steps[sel].kind not in ops.KINDS_WITH_Y:
            return
        y = self.edit_y.value() if value is None else value
        try:
            self.model.set_step_y(sel, y or None)
            self.seq_error.setText("")
        except (ValueError, TypeError) as exc:
            self.seq_error.setText(f"Invalid Y: {exc}")
            return
        self.select_step(sel)

    # --- refresh from model -----------------------------------------------------------------

    def refresh(self):
        """Redraw the step list from the model, keeping the selected rows."""
        steps, states = self.model.steps, self.get_states()
        t = self.step_list
        keep = t.selected_ids()
        closed = {r for r in self._group_rows
                  if (item := t.item_of(r)) is not None and not item.isExpanded()}
        t.blockSignals(True)
        t.clear()
        starts = {g.first: g for g in self.groups()} if self.groups else {}
        self._group_rows = {}
        group = parent = None  # the group the steps are being added under, and its row
        problem = None
        bold = QFont(t.font())
        bold.setBold(True)
        folds = []
        for k, step in enumerate(steps, 1):
            if k - 1 in starts:
                group = starts[k - 1]
                gid = f"g{group.id}"
                self._group_rows[gid] = (group.first, group.last)
                span = f"#{group.first + 1}" + (f"–#{group.last + 1}"
                                                if group.last > group.first else "")
                parent = QTreeWidgetItem([f"{group.title}   ({span})", ""])
                parent.setData(0, ROW_ID, gid)
                for col in (0, 1):
                    parent.setBackground(col, QBrush(theme.tint(group.color, 0.55)))
                    parent.setFont(col, bold)
                t.addTopLevelItem(parent)
                folds.append((parent, gid not in closed))
            before = states[k - 1] if states and k - 1 < len(states) else None
            cards = split_cards(step, before) if before is not None else None
            note = self.row_problem(k - 1)
            if note and problem is None:
                problem = f"Step {k} can't be done: {note}"
            inside = group is not None and k - 1 <= group.last
            see = ""
            if cards:
                see = (f"{cards[0].pretty()} | {cards[1].pretty()}" if self.splits_in_list
                       else cards[0].pretty())
            item = QTreeWidgetItem([f"{'⚠ ' if note else ''}{k}. {step.label()}", see])
            item.setData(0, ROW_ID, f"s{k - 1}")
            item.setTextAlignment(1, Qt.AlignCenter)
            if inside:
                for col in (0, 1):
                    item.setBackground(col, QBrush(theme.tint(group.color, 0.2)))
                parent.addChild(item)
            else:
                t.addTopLevelItem(item)
            if inside and k - 1 == group.last:
                group = None
        for item, is_open in folds:
            item.setExpanded(is_open)
        self.split_label.setText(format_splits(steps, states) if states else "")
        if problem is not None:
            self.seq_error.setText(problem)
        elif self._problem_shown:
            self.seq_error.setText("")
        self._problem_shown = problem is not None
        items = [item for item in (t.item_of(r) for r in keep) if item is not None]
        for item in items:
            item.setSelected(True)
        if items:
            t.setCurrentItem(items[0], 0, QItemSelectionModel.NoUpdate)
        t.blockSignals(False)
        self._on_step_select()
