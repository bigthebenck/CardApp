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
import tkinter as tk

import ttkbootstrap as tb

from .. import deck, tracking
from . import theme
from .card_viewer import CardViewers
from .model import TrackerModel, format_table
from .sequence_panel import SequencePanel

TEXT_DEBOUNCE_MS = 400
MONO = ("Courier", 10)
PLACE_WHERE = {"on top of": True, "under": False}


class TrackerTab:
    def __init__(self, parent, model=None):
        self.model = model or TrackerModel()
        self._text_job = None
        self._syncing = False
        self._text_is_source = False
        self._text_cards = None  # cards the shorthand box last described
        self._shown = {"before": None, "after": None}  # Table each side shows, if any
        self._titles = {"before": "", "after": ""}

        self.frame = tb.Panedwindow(parent, orient=tk.HORIZONTAL)
        self.viewers = CardViewers(self.frame)
        self.boxes, self.views = {}, {}

        # Left: what to track and how to add to it. Middle: the steps, as tall as the
        # window allows. Right: the table before and after the picked steps.
        left = tb.Frame(self.frame)
        self._build_deck_input(left)
        controls = tb.LabelFrame(left, text="Add a step (after the picked one, or at the end)",
                                 padding=6)
        controls.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        pile_row = tb.Frame(controls)
        pile_row.pack(fill=tk.X, pady=(0, 4))
        tb.Label(pile_row, text="Shuffle pile:").pack(side=tk.LEFT)
        self.pile_var = tk.StringVar(value=self.model.target_pile)
        self.pile_box = tb.Combobox(pile_row, textvariable=self.pile_var, state="readonly",
                                    width=5, values=[self.model.target_pile])
        self.pile_box.pack(side=tk.LEFT, padx=4)
        self.pile_box.bind("<<ComboboxSelected>>", lambda e: self._on_pile_chosen())
        tb.Label(pile_row, text="(new shuffles, splits and added cards go to this pile)",
                 style="Muted.TLabel").pack(side=tk.LEFT)
        self.frame.add(left, weight=1)

        middle = tb.Frame(self.frame)
        tb.Label(middle, text="Shift- or Ctrl-click to pick several steps, then Group… to "
                              "title and colour them. Double-click a rearrangement or a "
                              "group to edit it. Split A | B: A is the card you see on the "
                              "bottom of the upper packet, B the top card of the rest.",
                 style="Muted.TLabel", wraplength=420).pack(anchor=tk.W, pady=(0, 4))
        self.sequence = SequencePanel(
            middle, self.model, "Steps (click one to see before and after it)",
            self._step_decks, on_select=self._show_states,
            extra_buttons=(("Start → End", self.show_whole_run),
                           ("Group…", self.open_group_dialog)),
            deck_size=lambda index: self.model.size_at(index),
            row_problem=self.model.step_problem,
            extra_tabs=(("Cards & packets", self._build_card_ops),),
            groups=lambda: self.model.groups, controls=controls, splits_in_list=True)
        self.sequence.frame.pack(fill=tk.BOTH, expand=True)
        self.sequence.step_list.bind("<Escape>", lambda e: self.show_whole_run())
        self.sequence.step_list.bind("<Double-1>", self._on_double_click)
        self.dialog = None  # the open Rearrange or Group window, if any
        self.frame.add(middle, weight=1)

        right = tb.Frame(self.frame)
        self._build_state_view(right, "before")
        self._build_state_view(right, "after")
        self.frame.add(right, weight=1)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    # --- setup ----------------------------------------------------------------------

    def _build_deck_input(self, parent):
        frame = tb.LabelFrame(parent, text="Deck to track (top first)", padding=6)
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

        tb.Label(frame, text="Shorthand, any number of cards (e.g.  A-KH, A-KC, K-AD, K-AS):"
                 ).pack(anchor=tk.W, pady=(6, 0))
        self.deck_text = tb.Text(frame, height=3, width=44, wrap=tk.WORD, font=MONO, undo=True)
        self.deck_text.pack(fill=tk.X)
        self.deck_text.bind("<<Modified>>", self._on_text_modified)
        self.text_error = tb.Label(frame, text="", bootstyle="danger", wraplength=380)
        self.text_error.pack(anchor=tk.W)
        self.deck_status = tb.Label(frame, text="", wraplength=380, justify=tk.LEFT)
        self.deck_status.pack(anchor=tk.W)

    def _build_state_view(self, parent, side):
        """A read-only table of piles, each in columns of 13, with copy and view buttons."""
        frame = tb.LabelFrame(parent, text="", padding=6)
        frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0) if side == "after" else 0)
        # The buttons are packed first so a short window squeezes the list, not them.
        btns = tb.Frame(frame)
        btns.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        tb.Button(btns, text="Copy shorthand",
                  command=lambda: self._copy(self.shorthand(side))).pack(side=tk.LEFT)
        tb.Button(btns, text="View cards",
                  command=lambda: self.view_cards(side)).pack(side=tk.RIGHT)
        text = tb.Text(frame, height=8, width=40, font=MONO, wrap=tk.NONE, state=tk.DISABLED)
        sb = tb.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.config(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.boxes[side] = frame
        self.views[side] = text

    def _build_card_ops(self, tab):
        """The "Cards & packets" tab: steps that move cards rather than shuffle them."""
        row = tb.Frame(tab)
        row.pack(fill=tk.X, pady=(0, 8))
        tb.Button(row, text="Rearrange…", command=self.open_rearrange).pack(side=tk.LEFT)
        tb.Label(row, text="type the whole new order, e.g. after revealing cards",
                 style="Muted.TLabel").pack(side=tk.LEFT, padx=6)

        row = tb.Frame(tab)
        row.pack(fill=tk.X)
        tb.Label(row, text="Cards:").pack(side=tk.LEFT)
        self.cards_var = tk.StringVar()
        tb.Entry(row, textvariable=self.cards_var, font=MONO, width=22).pack(
            side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        tb.Label(row, text="e.g. AC AH AS AD", style="Muted.TLabel").pack(side=tk.LEFT)

        row = tb.Frame(tab)
        row.pack(fill=tk.X, pady=(2, 0))
        for text, mode in (("Take out → new pile", "pile"),
                           ("Take out → one pile each", "each"), ("Discard", "discard")):
            tb.Button(row, text=text, command=lambda m=mode: self.take_out(m)).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))

        row = tb.Frame(tab)
        row.pack(fill=tk.X, pady=(2, 0))
        tb.Button(row, text="Add cards", command=self.add_cards).pack(side=tk.LEFT)
        tb.Label(row, text="to the shuffle pile at position").pack(side=tk.LEFT, padx=(6, 2))
        self.add_pos_var = tk.StringVar(value="1")
        tb.Spinbox(row, from_=1, to=200, width=4, textvariable=self.add_pos_var).pack(
            side=tk.LEFT)
        tb.Label(row, text="(1 = top)", style="Muted.TLabel").pack(side=tk.LEFT, padx=4)

        row = tb.Frame(tab)
        row.pack(fill=tk.X, pady=(8, 0))
        tb.Button(row, text="Split", command=self.split).pack(side=tk.LEFT)
        tb.Label(row, text="shuffle pile into packets of").pack(side=tk.LEFT, padx=(6, 2))
        self.sizes_var = tk.StringVar()
        tb.Entry(row, textvariable=self.sizes_var, font=MONO, width=14).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        tb.Label(tab, text="Sizes from the top, e.g. 1,1,1,1,12,12,12,12; cards left over "
                           "make one more packet.", style="Muted.TLabel",
                 wraplength=330).pack(anchor=tk.W)

        row = tb.Frame(tab)
        row.pack(fill=tk.X, pady=(8, 0))
        tb.Button(row, text="Put", command=self.place).pack(side=tk.LEFT)
        tb.Label(row, text="pile").pack(side=tk.LEFT, padx=(6, 2))
        self.place_pile_var = tk.StringVar()
        self.place_pile_box = tb.Combobox(row, textvariable=self.place_pile_var,
                                          state="readonly", width=4)
        self.place_pile_box.pack(side=tk.LEFT)
        self.place_where_var = tk.StringVar(value=next(iter(PLACE_WHERE)))
        tb.Combobox(row, textvariable=self.place_where_var, values=list(PLACE_WHERE),
                    state="readonly", width=9).pack(side=tk.LEFT, padx=4)
        tb.Label(row, text="pile").pack(side=tk.LEFT, padx=(0, 2))
        self.place_onto_var = tk.StringVar()
        self.place_onto_box = tb.Combobox(row, textvariable=self.place_onto_var,
                                          state="readonly", width=4)
        self.place_onto_box.pack(side=tk.LEFT)

        row = tb.Frame(tab)
        row.pack(fill=tk.X, pady=(8, 0))
        tb.Button(row, text="Gather", command=self.gather).pack(side=tk.LEFT)
        tb.Label(row, text="piles").pack(side=tk.LEFT, padx=(6, 2))
        self.gather_var = tk.StringVar()
        tb.Entry(row, textvariable=self.gather_var, font=MONO, width=12).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        tb.Label(tab, text="e.g. A B C D, first on top; blank gathers every pile in "
                           "table order.", style="Muted.TLabel", wraplength=330).pack(
            anchor=tk.W)

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

    # --- step events ------------------------------------------------------------------------

    def _on_pile_chosen(self):
        self.model.target_pile = self.pile_var.get()
        self.sequence.update_add_buttons()

    def _refuse(self, message):
        self.sequence.seq_error.config(text=f"Can't add step: {message}")
        return False

    def _named_cards(self):
        text = self.cards_var.get().strip()
        if not text:
            raise ValueError("type the cards in the Cards box")
        # Spaces separate cards here as well as commas: "AC AH" means "AC, AH".
        return tuple(deck.parse_cards(", ".join(re.split(r"[\s,]+", text))))

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
            position = int(self.add_pos_var.get())
        except ValueError as exc:
            return self._refuse(exc)
        return self.sequence.add(tracking.AddCards(cards, self.model.target_pile, position))

    def split(self):
        try:
            sizes = tuple(int(s) for s in re.split(r"[\s,;]+", self.sizes_var.get().strip()))
        except ValueError:
            return self._refuse("packet sizes are whole numbers, e.g. 1,1,1,1,12,12,12,12")
        return self.sequence.add(tracking.Split(self.model.target_pile, sizes))

    def place(self):
        return self.sequence.add(tracking.Place(self.place_pile_var.get(),
                                                self.place_onto_var.get(),
                                                PLACE_WHERE[self.place_where_var.get()]))

    def gather(self):
        names = tuple(n.upper() for n in re.split(r"[\s,;]+", self.gather_var.get()) if n)
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
        self.sequence.seq_error.config(text=f"Can't group: {message}")
        return None

    def _close_dialog(self):
        if self.dialog is not None:
            self.dialog.close()

    def _on_double_click(self, event):
        row = self.sequence.step_list.identify_row(event.y)
        if row.startswith("g"):
            self.sequence.step_list.selection_set([row])
            self.open_group_dialog()
            return "break"  # don't also fold the group
        if row.startswith("s") and isinstance(self.model.steps[int(row[1:])],
                                              tracking.Rearrange):
            self.open_rearrange(int(row[1:]))
            return "break"
        return None

    def show_whole_run(self):
        """Go back to the very first and very last table."""
        self.sequence.select_step(None)

    # --- output ---------------------------------------------------------------------------

    def view_cards(self, side):
        if self._text_job is not None:  # show what was just typed
            self.apply_text()
        self.viewers.open(side, self._titles[side], lambda: self._groups(side))

    def _groups(self, side):
        """The side's piles as card-viewer groups: (heading, cards)."""
        table = self._shown[side]
        if table is None:
            return []
        return [(f"Pile {p.name} — {len(p)} card{'s' if len(p) != 1 else ''}",
                 list(p.cards)) for p in table.piles]

    def shorthand(self, side):
        """The side's cards as shorthand; several piles as ``A: ... | B: ...``."""
        table = self._shown[side]
        if table is None or not table.piles:
            return ""
        return tracking.format_piles(table.piles)

    def _copy(self, text):
        if text:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)

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
            full = " (a full deck)" if deck.validate_deck(m.cards).ok else ""
            self.deck_status.config(text=f"✓ {n} card{'s' if n != 1 else ''}{full}, each once.",
                                    bootstyle="success")
        self.sequence.refresh()  # also redraws both sides through _show_states

    def _update_pile_choices(self):
        """Offer the piles a new step (after the selected one) would find."""
        names = self.model.piles_at(self.sequence.insert_index())
        self.pile_box["values"] = names
        if self.model.target_pile not in names:
            self.model.target_pile = names[0]
        self.pile_var.set(self.model.target_pile)
        for box, var, default in ((self.place_pile_box, self.place_pile_var, names[-1]),
                                  (self.place_onto_box, self.place_onto_var, names[0])):
            box["values"] = names
            if var.get() not in names:
                var.set(default)
        self.sequence.update_add_buttons()

    def _show_states(self, _index):
        self._update_pile_choices()
        span = self.sequence.selected_range()
        before_title, before, after_title, after = self.model.around(*(span or (None,)))
        for side, title, table in (("before", before_title, before),
                                   ("after", after_title, after)):
            self._titles[side] = title
            self._shown[side] = table
            self.boxes[side].config(text=title)
            viewer = self.viewers.get(side)
            if viewer is not None:
                viewer.win.title(title)
            text = self.views[side]
            text.config(state=tk.NORMAL)
            text.delete("1.0", tk.END)
            text.insert("1.0", format_table(table) if table is not None else
                        self.model.missing_reason())
            text.config(state=tk.DISABLED)
        self.viewers.refresh()


class _Dialog:
    """A small window over the tab, closed by Cancel, Escape or its own OK."""

    def __init__(self, tab, title):
        self.tab = tab
        self.win = tb.Toplevel(tab.frame)
        self.win.title(title)
        self.win.transient(tab.frame.winfo_toplevel())
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda e: self.close())
        self.body = tb.Frame(self.win, padding=10)
        self.body.pack(fill=tk.BOTH, expand=True)

    def buttons(self, ok_text, extra=()):
        row = tb.Frame(self.body)
        row.pack(fill=tk.X, pady=(10, 0))
        tb.Button(row, text="Cancel", bootstyle="secondary",
                  command=self.close).pack(side=tk.RIGHT)
        tb.Button(row, text=ok_text, command=self.ok).pack(side=tk.RIGHT, padx=(0, 6))
        for text, command, style in extra:
            tb.Button(row, text=text, command=command, bootstyle=style).pack(side=tk.LEFT)

    def is_open(self):
        return self.win is not None and bool(self.win.winfo_exists())

    def close(self):
        if self.win is not None:
            self.win.destroy()
            self.win = None
        if self.tab.dialog is self:
            self.tab.dialog = None


class RearrangeDialog(_Dialog):
    """Type a new order for the whole table, with a short title (a Rearrange step)."""

    HELP = ("The table after this step, top card first. Separate piles with | "
            "and name them with their letter, e.g.\n"
            "    A: 2-KC, AC |\n    B: 2-KH, AH\n"
            "Without names, piles keep the names of the piles already on the table, in "
            "order. It must hold exactly the cards on the table; a ` marks a face-up card.")

    def __init__(self, tab, edit=None):
        super().__init__(tab, "Edit rearrangement" if edit is not None else "Rearrange")
        model = tab.model
        self.edit = edit
        self.index = edit if edit is not None else tab.sequence.insert_index()
        step = model.steps[edit] if edit is not None else None
        table = model.table_before(self.index)

        row = tb.Frame(self.body)
        row.pack(fill=tk.X)
        tb.Label(row, text="Title:").pack(side=tk.LEFT)
        self.title_var = tk.StringVar(value=step.title if step else "")
        title = tb.Entry(row, textvariable=self.title_var, width=40)
        title.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        tb.Label(row, text="e.g. Card revelations", style="Muted.TLabel").pack(side=tk.LEFT)
        tb.Label(self.body, text=self.HELP, style="Muted.TLabel", justify=tk.LEFT,
                 wraplength=520).pack(anchor=tk.W, pady=(8, 4))
        self.text = tb.Text(self.body, height=10, width=64, wrap=tk.WORD, font=MONO, undo=True)
        self.text.pack(fill=tk.BOTH, expand=True)
        start = step.text() if step else (tracking.format_piles(table.piles)
                                          if table is not None and table.piles else "")
        self.text.insert("1.0", start)
        self.text.bind("<KeyRelease>", lambda e: self.check())
        self.status = tb.Label(self.body, text="", wraplength=520, justify=tk.LEFT)
        self.status.pack(anchor=tk.W, pady=(4, 0))
        self.buttons("Save" if edit is not None else "Add step")
        self.check()
        title.focus_set()

    def set_text(self, text):
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", text)
        self.check()

    def step(self):
        """The Rearrange step as typed, or raise ValueError saying what's wrong."""
        piles = tracking.parse_piles(self.text.get("1.0", "end-1c"))
        step = tracking.Rearrange(self.title_var.get().strip(), piles)
        table = self.tab.model.table_before(self.index)
        if table is not None:
            step.apply(table)
        return step

    def check(self):
        """Show whether the text is a usable new order; returns the error or None."""
        try:
            step = self.step()
        except ValueError as exc:
            self.status.config(text=f"⚠ {exc}", bootstyle="danger")
            return str(exc)
        n = sum(len(cards) for _name, cards in step.piles)
        piles = len(step.piles)
        self.status.config(text=f"✓ {n} card{'s' if n != 1 else ''}"
                                + (f" in {piles} piles" if piles != 1 else ""),
                           bootstyle="success")
        return None

    def ok(self):
        if self.check() is not None:
            return False
        step = self.step()
        if self.edit is not None:
            try:
                self.tab.model.replace_step(self.edit, step)
            except ValueError as exc:
                self.status.config(text=f"⚠ {exc}", bootstyle="danger")
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
        tb.Label(self.body, text=f"Steps {first + 1}\u2013{last + 1}" if last > first
                 else f"Step {first + 1}").pack(anchor=tk.W)
        row = tb.Frame(self.body)
        row.pack(fill=tk.X, pady=(6, 0))
        tb.Label(row, text="Title:").pack(side=tk.LEFT)
        self.title_var = tk.StringVar(value=group.title if group else "")
        title = tb.Entry(row, textvariable=self.title_var, width=28)
        title.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        row = tb.Frame(self.body)
        row.pack(fill=tk.X, pady=(6, 0))
        tb.Label(row, text="Colour:").pack(side=tk.LEFT)
        self.color_var = tk.StringVar(value=group.color if group else
                                      next(iter(theme.GROUP_COLORS)))
        tb.Combobox(row, textvariable=self.color_var, values=list(theme.GROUP_COLORS),
                    state="readonly", width=10).pack(side=tk.LEFT, padx=4)
        self.status = tb.Label(self.body, text="", bootstyle="danger", wraplength=320)
        self.status.pack(anchor=tk.W, pady=(4, 0))
        extra = (("Ungroup", self.ungroup, "danger-outline"),) if group else ()
        self.buttons("Save" if group else "Group", extra)
        self.win.bind("<Return>", lambda e: self.ok())
        title.focus_set()

    def ok(self):
        model = self.tab.model
        try:
            if self.group_id is not None:
                model.edit_group(self.group_id, self.title_var.get(), self.color_var.get())
            else:
                model.add_group(*self.span, self.title_var.get(), self.color_var.get())
        except ValueError as exc:
            self.status.config(text=f"⚠ {exc}")
            return False
        self.close()
        return True

    def ungroup(self):
        self.tab.model.remove_group(self.group_id)
        self.close()
