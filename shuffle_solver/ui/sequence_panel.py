"""The shuffle-sequence editor shared by the "Starting Order" and "Free Tracking" tabs.

Buttons to add each shuffle, the ordered step list (with the card you see at
each faro's, cut's or packet run's split), and X/Y editing of the selected step. It edits any model
with the ``StepList`` methods and shows the deck states its owner hands it;
it contains no shuffle math.
"""

import tkinter as tk

import ttkbootstrap as tb

from .. import shuffle_ops as ops
from .. import solver
from . import theme
from .model import DECK_SIZE, format_splits, split_cards

MONO = ("Courier", 10)

# Partial faro packet choices: label -> (cut from, woven into)
PARTIAL_DIRECTIONS = {
    "top into top": (ops.TOP, ops.TOP),
    "top into bottom": (ops.TOP, ops.BOTTOM),
    "bottom into top": (ops.BOTTOM, ops.TOP),
    "bottom into bottom": (ops.BOTTOM, ops.BOTTOM),
}

HELP_TEXT = ("Overhand run: X = 1–52 (52 reverses the deck). "
             "Packet run: pick up the top X cards (2–52), run Y of them one at a "
             "time onto the deck and drop the rest on top; Y blank runs them "
             "all, reversing the top X. "
             "Cut: X = 1–51. Partial faro: cut off X cards (up to 26) from "
             "the top or bottom and weave them into the top or bottom of "
             "the rest. Out keeps the packet's outer card on the outside "
             "(its top card on top, or its bottom card on the bottom); in "
             "tucks it one card inside.")


class SequencePanel:
    """The step list and the buttons that add to it.

    ``get_states()`` gives, for each step k (from 1), the deck it is done on at
    index k - 1 (None where there is no single deck), or None for no decks at all.
    ``on_select(index or None)`` runs whenever the selected step changes.
    ``deck_size(index)`` is the size of the deck a new step at ``index`` would be
    done on (None if unknown; default: always a full deck). ``row_problem(index)``
    gives the message for a step that can't be done, else None.
    ``extra_tabs`` are (title, build(frame)) pairs shown next to the shuffle buttons.
    ``groups()`` gives the model's step groups (see ``StepGroup``); with it, several
    steps can be selected at once and each group is a coloured, foldable row.
    ``controls``, if given, is a frame elsewhere to hold the add buttons and help,
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
        self.frame = tb.LabelFrame(parent, text=title, padding=6)
        self._build(extra_buttons, extra_tabs, controls)

    def _build(self, extra_buttons, extra_tabs, controls):
        frame = self.frame
        host = frame if controls is None else controls  # where the add buttons go
        if extra_tabs:
            self.add_tabs = tb.Notebook(host)
            self.add_tabs.pack(fill=tk.X)
            add = tb.Frame(self.add_tabs, padding=4)
            self.add_tabs.add(add, text="Shuffles")
            for tab_title, build in extra_tabs:
                tab = tb.Frame(self.add_tabs, padding=4)
                build(tab)
                self.add_tabs.add(tab, text=tab_title)
        else:
            add = tb.Frame(host)
            add.pack(fill=tk.X)
        self.faro_buttons = [
            tb.Button(add, text="+ Out-Faro", command=lambda: self.add_step(ops.OUT_FARO)),
            tb.Button(add, text="+ In-Faro", command=lambda: self.add_step(ops.IN_FARO))]
        for col, button in enumerate(self.faro_buttons):
            button.grid(row=0, column=col, sticky=tk.EW)
        tb.Button(add, text="+ Overhand Run",
                  command=lambda: self.add_step(ops.OVERHAND_RUN)).grid(row=1, column=0,
                                                                        sticky=tk.EW)
        tb.Button(add, text="+ Cut",
                  command=lambda: self.add_step(ops.CUT)).grid(row=1, column=1, sticky=tk.EW)
        tb.Button(add, text="+ Partial Out-Faro",
                  command=lambda: self.add_step(self.partial_kind(True))).grid(
            row=2, column=0, sticky=tk.EW)
        tb.Button(add, text="+ Partial In-Faro",
                  command=lambda: self.add_step(self.partial_kind(False))).grid(
            row=2, column=1, sticky=tk.EW)
        packet = tb.Frame(add)
        packet.grid(row=3, column=0, columnspan=2, sticky=tk.EW, pady=(2, 0))
        tb.Label(packet, text="Partial faro packet:").pack(side=tk.LEFT)
        self.partial_dir_var = tk.StringVar(value=next(iter(PARTIAL_DIRECTIONS)))
        tb.Combobox(packet, textvariable=self.partial_dir_var, values=list(PARTIAL_DIRECTIONS),
                    state="readonly", width=18).pack(side=tk.LEFT, padx=4)
        tb.Button(add, text="+ Packet Run",
                  command=lambda: self.add_step(ops.PACKET_RUN)).grid(row=4, column=0,
                                                                      sticky=tk.EW, pady=(2, 0))
        run = tb.Frame(add)
        run.grid(row=4, column=1, columnspan=3, sticky=tk.W, padx=(6, 0), pady=(2, 0))
        tb.Label(run, text="Run Y:").pack(side=tk.LEFT)
        self.new_y_var = tk.StringVar(value="")
        tb.Spinbox(run, from_=1, to=DECK_SIZE, width=4,
                   textvariable=self.new_y_var).pack(side=tk.LEFT, padx=4)
        tb.Label(run, text="(blank = all)", style="Muted.TLabel").pack(side=tk.LEFT)
        self.odd_note = tb.Label(add, text="", style="Muted.TLabel")
        self.odd_note.grid(row=5, column=0, columnspan=4, sticky=tk.W)
        tb.Label(add, text="X:").grid(row=1, column=2, rowspan=2, padx=(8, 2))
        self.new_x_var = tk.StringVar(value="5")
        self.new_x = tb.Spinbox(add, from_=1, to=DECK_SIZE, width=4,
                                textvariable=self.new_x_var)
        self.new_x.grid(row=1, column=3, rowspan=2)
        add.columnconfigure(0, weight=1)
        add.columnconfigure(1, weight=1)

        body = tb.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True, pady=6)
        # Buttons and scrollbar are packed first so a narrow pane squeezes the list, not them.
        buttons = tb.Frame(body)
        buttons.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        for text, cmd in (("↑ Up", lambda: self._move_step(-1)),
                          ("↓ Down", lambda: self._move_step(1)),
                          ("Duplicate", self._duplicate_step),
                          ("Delete", self._delete_step),
                          ("Clear all", self.model.clear_steps),
                          *extra_buttons):
            tb.Button(buttons, text=text, command=cmd).pack(fill=tk.X, pady=1)

        # Two columns so the card seen at a split stays visible in a narrow pane.
        self.step_list = tb.Treeview(body, columns=("step", "see"),
                                     show="tree headings" if self.groups else "headings",
                                     selectmode="extended" if self.groups else "browse", height=10)
        self.step_list.column("#0", width=26, stretch=False)  # fold arrows of groups
        self.step_list.heading("step", text="Shuffle", anchor=tk.W)
        self.step_list.heading("see", text="Split" if self.splits_in_list else "You see",
                               anchor=tk.CENTER)
        self.step_list.column("step", width=250, stretch=True, anchor=tk.W)
        self.step_list.column("see", width=96 if self.splits_in_list else 64, stretch=False,
                              anchor=tk.CENTER)
        sb = tb.Scrollbar(body, orient=tk.VERTICAL, command=self.step_list.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.step_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.step_list.bind("<<TreeviewSelect>>", lambda e: self._on_step_select())
        self.step_list.bind("<Delete>", lambda e: self._delete_step())
        self.step_list.config(yscrollcommand=sb.set)

        # Where each faro, cut or packet run splits the deck, once there is a deck to split.
        self.split_label = tb.Label(frame, text="", font=MONO, justify=tk.LEFT, wraplength=320)
        if not self.splits_in_list:
            self.split_label.pack(anchor=tk.W, pady=(0, 6))

        edit = tb.Frame(frame)
        edit.pack(fill=tk.X)
        tb.Label(edit, text="Selected step X:").pack(side=tk.LEFT)
        self.edit_x_var = tk.StringVar()
        self.edit_x = tb.Spinbox(edit, from_=1, to=DECK_SIZE, width=4,
                                 textvariable=self.edit_x_var, command=self.commit_edit_x)
        self.edit_x.pack(side=tk.LEFT, padx=4)
        self.edit_x.bind("<Return>", lambda e: self.commit_edit_x())
        self.edit_x.bind("<FocusOut>", lambda e: self.commit_edit_x())
        tb.Label(edit, text="Y:").pack(side=tk.LEFT, padx=(8, 0))
        self.edit_y_var = tk.StringVar()
        self.edit_y = tb.Spinbox(edit, from_=1, to=DECK_SIZE, width=4,
                                 textvariable=self.edit_y_var, command=self.commit_edit_y)
        self.edit_y.pack(side=tk.LEFT, padx=4)
        self.edit_y.bind("<Return>", lambda e: self.commit_edit_y())
        self.edit_y.bind("<FocusOut>", lambda e: self.commit_edit_y())
        self.seq_error = tb.Label(frame, text="", bootstyle="danger", wraplength=320)
        self.seq_error.pack(anchor=tk.W, pady=(4, 0))
        help_text = tb.Label(frame if controls is None else add, text=HELP_TEXT,
                             style="Muted.TLabel", wraplength=260 if controls is None else 360)
        if controls is None:
            help_text.pack(anchor=tk.W)
        else:  # the Shuffles tab has room to spare beside the taller tabs
            help_text.grid(row=6, column=0, columnspan=4, sticky=tk.W, pady=(8, 0))

    # --- events -----------------------------------------------------------------------------

    def partial_kind(self, out):
        source, dest = PARTIAL_DIRECTIONS[self.partial_dir_var.get()]
        return ops.partial_faro_kind(source, dest, out)

    # Rows are named "s<index>" for a step and "g<id>" for a group.

    def selected_step(self):
        """The selected step, when exactly one step (and no group) is selected."""
        sel = self.step_list.selection()
        return int(sel[0][1:]) if len(sel) == 1 and sel[0].startswith("s") else None

    def selected_range(self):
        """(first, last) step covered by the selection (a group covers its steps), or None."""
        spans = [self._group_rows.get(row) or (int(row[1:]),) * 2
                 for row in self.step_list.selection()]
        if not spans:
            return None
        return min(a for a, _b in spans), max(b for _a, b in spans)

    def selected_group(self):
        """The id of the group row selected on its own, else None."""
        sel = self.step_list.selection()
        return int(sel[0][1:]) if len(sel) == 1 and sel[0].startswith("g") else None

    def select_step(self, index):
        """Select step ``index`` (None clears the selection)."""
        row = f"s{index}"
        if index is not None and self.step_list.exists(row):
            self._select_rows([row])
        else:
            self._select_rows([])

    def select_range(self, first, last):
        """Select steps ``first``..``last``."""
        self._select_rows([f"s{i}" for i in range(first, last + 1)
                           if self.step_list.exists(f"s{i}")])

    def _select_rows(self, rows):
        self.step_list.selection_set(rows)
        if rows:
            self.step_list.focus(rows[0])
            self.step_list.see(rows[0])
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
            self.seq_error.config(text=f"Can't add step: {n} cards; a full faro needs an even "
                                       "number, so use a partial faro")
            return
        try:
            if kind in ops.KINDS_WITH_X:
                x = int(self.new_x_var.get())
                if kind in ops.KINDS_WITH_Y:
                    y = _optional_int(self.new_y_var.get())
                    y = None if y == x else y
            step = solver.Step(kind, x, y)
            step.validate(n)
        except (ValueError, TypeError) as exc:
            self.seq_error.config(text=f"Can't add step: {exc}")
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
            self.seq_error.config(text=f"Can't add step: {exc}")
            return False
        self.seq_error.config(text="")
        self.select_step(index)
        return True

    def _move_step(self, delta):
        sel = self.selected_step()
        if sel is not None:
            self.select_step(self.model.move_step(sel, delta))

    def _duplicate_step(self):
        sel = self.selected_step()
        if sel is not None:
            self.model.duplicate_step(sel)
            self.select_step(sel + 1)

    def _delete_step(self):
        sel = self.selected_step()
        if sel is not None:
            self.model.remove_step(sel)
            self.select_step(min(sel, len(self.model.steps) - 1))

    def _on_step_select(self):
        sel = self.selected_step()
        step = self.model.steps[sel] if sel is not None else None
        if step is not None and step.kind in ops.KINDS_WITH_X:
            states = self.get_states()
            deck = states[sel] if states and sel < len(states) else None
            lo, hi = ops.x_bounds(step.kind, DECK_SIZE if deck is None else len(deck))
            self.edit_x.configure(state=tk.NORMAL, from_=lo, to=hi)
            self.edit_x_var.set(str(step.x))
        else:
            self.edit_x_var.set("")
            self.edit_x.configure(state=tk.DISABLED)
        if step is not None and step.kind in ops.KINDS_WITH_Y:
            self.edit_y.configure(state=tk.NORMAL, from_=1, to=step.x)
            self.edit_y_var.set("" if step.y is None else str(step.y))
        else:
            self.edit_y_var.set("")
            self.edit_y.configure(state=tk.DISABLED)
        self.update_add_buttons()
        if self.on_select is not None:
            self.on_select(sel)

    def update_add_buttons(self):
        """Allow full faros only on an even deck, and X only up to the deck's size."""
        n = self._new_deck_size()
        self.new_x.configure(to=max(n, 1))
        for button in self.faro_buttons:
            button.configure(state=tk.DISABLED if n % 2 else tk.NORMAL)
        self.odd_note.config(text=f"Odd number of cards ({n}): partial faros only."
                             if n % 2 else "")

    def commit_edit_x(self):
        sel = self.selected_step()
        if sel is None or self.model.steps[sel].kind not in ops.KINDS_WITH_X:
            return
        try:
            self.model.set_step_x(sel, int(self.edit_x_var.get()))
            self.seq_error.config(text="")
        except (ValueError, TypeError) as exc:
            self.seq_error.config(text=f"Invalid X: {exc}")
            return
        self.select_step(sel)

    def commit_edit_y(self):
        sel = self.selected_step()
        if sel is None or self.model.steps[sel].kind not in ops.KINDS_WITH_Y:
            return
        try:
            self.model.set_step_y(sel, _optional_int(self.edit_y_var.get()))
            self.seq_error.config(text="")
        except (ValueError, TypeError) as exc:
            self.seq_error.config(text=f"Invalid Y: {exc}")
            return
        self.select_step(sel)

    # --- refresh from model -----------------------------------------------------------------

    def refresh(self):
        """Redraw the step list from the model, keeping the selected rows."""
        steps, states = self.model.steps, self.get_states()
        t = self.step_list
        keep = t.selection()
        closed = {row for row in self._group_rows
                  if t.exists(row) and not t.item(row, "open")}
        t.delete(*t.get_children())
        starts = {g.first: g for g in self.groups()} if self.groups else {}
        self._group_rows = {}
        group = None  # the group the steps are being added under
        problem = None
        for k, step in enumerate(steps, 1):
            if k - 1 in starts:
                group = starts[k - 1]
                row = f"g{group.id}"
                self._group_rows[row] = (group.first, group.last)
                span = f"#{group.first + 1}" + (f"\u2013#{group.last + 1}"
                                                if group.last > group.first else "")
                t.insert("", tk.END, iid=row, open=row not in closed, tags=(row,),
                         values=(f"{group.title}   ({span})", ""))
                t.tag_configure(row, background=theme.tint(group.color, 0.55),
                                font=("TkDefaultFont", 9, "bold"))
                t.tag_configure(f"in{group.id}", background=theme.tint(group.color, 0.2))
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
            t.insert(f"g{group.id}" if inside else "", tk.END, iid=f"s{k - 1}",
                     tags=(f"in{group.id}",) if inside else (), values=(
                         f"{'⚠ ' if note else ''}{k}. {step.label()}", see))
            if inside and k - 1 == group.last:
                group = None
        self.split_label.config(text=format_splits(steps, states) if states else "")
        if problem is not None:
            self.seq_error.config(text=problem)
        elif self._problem_shown:
            self.seq_error.config(text="")
        self._problem_shown = problem is not None
        keep = [row for row in keep if t.exists(row)]
        t.selection_set(keep)
        if keep:
            t.focus(keep[0])
        self._on_step_select()


def _optional_int(text):
    """A spinbox's number, or None when it is left blank."""
    text = text.strip()
    return int(text) if text else None
