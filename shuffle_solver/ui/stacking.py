"""The "Stacking" tab: pick the cards each poker hand should get, get the stack.

Left: the game, the number of players and (for hold'em) burn cards, then one
shorthand box per hand, and the flop, turn and river for hold'em. Right: the
starting order that deals those hands, each card marked with where it goes.
All state lives in ``StackingModel``; this module only draws it and forwards
user input.
"""

import tkinter as tk

import ttkbootstrap as tb

from .. import stacking
from .card_viewer import CardViewers
from .model import StackingModel

MONO = ("Courier", 10)


class StackingTab:
    def __init__(self, parent, model=None, use_as_final=None):
        """``use_as_final(cards)``, if given, adds a button that hands the stack on."""
        self.model = model or StackingModel()
        self.use_as_final = use_as_final
        self._shown_hands = None  # the hands the rows were last built for
        self.hand_vars = {}
        self.hand_errors = {}

        self.frame = tb.Panedwindow(parent, orient=tk.HORIZONTAL)
        self.viewers = CardViewers(self.frame)
        left = tb.Frame(self.frame)
        self._build_deal(left)
        self._build_hands(left)
        self.frame.add(left, weight=1)
        self.frame.add(self._build_result(self.frame), weight=1)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    # --- setup ----------------------------------------------------------------------

    def _build_deal(self, parent):
        frame = tb.LabelFrame(parent, text="1. The deal", padding=6)
        frame.pack(fill=tk.X)

        row = tb.Frame(frame)
        row.pack(fill=tk.X)
        tb.Label(row, text="Game:").pack(side=tk.LEFT)
        self.game_var = tk.StringVar(value=self.model.game)
        for game, label in stacking.GAMES.items():
            tb.Radiobutton(row, text=label, value=game, variable=self.game_var,
                           command=lambda: self.model.set_game(self.game_var.get())).pack(
                side=tk.LEFT, padx=(8, 0))

        row = tb.Frame(frame)
        row.pack(fill=tk.X, pady=(6, 0))
        tb.Label(row, text="Players:").pack(side=tk.LEFT)
        self.players_var = tk.StringVar(value=str(self.model.players))
        self.players_box = tb.Spinbox(row, from_=stacking.MIN_PLAYERS, to=stacking.MAX_PLAYERS,
                                      width=4, textvariable=self.players_var,
                                      command=self.apply_players)
        self.players_box.pack(side=tk.LEFT, padx=4)
        for seq in ("<Return>", "<FocusOut>"):
            self.players_box.bind(seq, lambda e: self.apply_players())
        self.burns_var = tk.BooleanVar(value=self.model.burns)
        self.burns_check = tb.Checkbutton(
            row, text="Burn a card before the flop, turn and river", variable=self.burns_var,
            command=lambda: self.model.set_burns(self.burns_var.get()))
        self.burns_check.pack(side=tk.LEFT, padx=(16, 0))
        self.players_error = tb.Label(frame, text="", bootstyle="danger")
        self.players_error.pack(anchor=tk.W)
        tb.Label(frame, text="Player 1 sits on the dealer's left and gets the first card; "
                             "the last player is the dealer.",
                 style="Muted.TLabel").pack(anchor=tk.W)

    def _build_hands(self, parent):
        frame = tb.LabelFrame(parent, text="2. Cards wanted", padding=6)
        frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        head = tb.Frame(frame)
        head.pack(fill=tk.X)
        tb.Label(head, text="Shorthand, e.g.  AS, KH.  X or a short hand = any card there.",
                 style="Muted.TLabel").pack(side=tk.LEFT)
        tb.Button(head, text="Clear all", bootstyle="secondary",
                  command=self.model.clear).pack(side=tk.RIGHT)
        self.hands_frame = tb.Frame(frame)
        self.hands_frame.pack(fill=tk.X, pady=(6, 0))
        self.hands_frame.columnconfigure(1, weight=1)

    def _build_result(self, parent):
        frame = tb.LabelFrame(parent, text="3. Starting order (top first)", padding=6)
        self.summary = tb.Label(frame, text="", wraplength=440, justify=tk.LEFT)
        self.summary.pack(anchor=tk.W, fill=tk.X)
        self.stack_text = tb.Text(frame, height=20, width=36, font=MONO, state=tk.DISABLED)
        self.stack_text.pack(fill=tk.BOTH, expand=True, pady=6)
        self.fill_var = tk.BooleanVar(value=self.model.fill)
        tb.Checkbutton(frame, text="Fill the other positions with the unused cards "
                                   "(new deck order) instead of X",
                       variable=self.fill_var,
                       command=lambda: self.model.set_fill(self.fill_var.get())).pack(
            anchor=tk.W)

        btns = tb.Frame(frame)
        btns.pack(fill=tk.X, pady=(6, 0))
        tb.Button(btns, text="Copy shorthand",
                  command=lambda: self._copy(self.model.shorthand())).pack(side=tk.LEFT)
        tb.Button(btns, text="Copy list",
                  command=lambda: self._copy(self.model.numbered())).pack(side=tk.LEFT, padx=4)
        tb.Button(btns, text="View cards", command=self.view_cards).pack(side=tk.LEFT)
        if self.use_as_final is not None:
            self.final_button = tb.Button(btns, text="Use as final deck →",
                                          command=self.send_to_final)
            self.final_button.pack(side=tk.RIGHT)
        return frame

    def _build_hand_rows(self):
        for child in self.hands_frame.winfo_children():
            child.destroy()
        self.hand_vars, self.hand_errors = {}, {}
        row = 0
        for name, size in self.model.hands():
            text = f"{self.model.hand_label(name)} ({size} card{'s' if size != 1 else ''})"
            tb.Label(self.hands_frame, text=text).grid(row=row, column=0, sticky=tk.W,
                                                       padx=(0, 8), pady=(2, 0))
            var = tk.StringVar(value=self.model.texts.get(name, ""))
            tb.Entry(self.hands_frame, textvariable=var, font=MONO).grid(
                row=row, column=1, sticky=tk.EW, pady=(2, 0))
            var.trace_add("write", lambda *_a, n=name, v=var: self.model.set_hand_text(
                n, v.get()))
            error = tb.Label(self.hands_frame, text="", bootstyle="danger")
            error.grid(row=row + 1, column=1, sticky=tk.W)
            self.hand_vars[name], self.hand_errors[name] = var, error
            row += 2

    # --- events --------------------------------------------------------------------------

    def apply_players(self):
        try:
            self.model.set_players(int(self.players_var.get()))
        except ValueError:
            self.players_error.config(text=f"⚠ pick {stacking.MIN_PLAYERS} to "
                                           f"{stacking.MAX_PLAYERS} players")
            return False
        self.players_error.config(text="")
        return True

    def view_cards(self):
        self.viewers.open("stack", "Poker stack (top first)", lambda: self.model.stack or [])

    def send_to_final(self):
        if self.model.stack is not None:
            self.use_as_final(list(self.model.stack))

    def _copy(self, text):
        if not text:
            return
        self.frame.clipboard_clear()
        self.frame.clipboard_append(text)

    # --- refresh from model -------------------------------------------------------------

    def refresh(self):
        m = self.model
        hands = (m.game, m.players)
        if hands != self._shown_hands:
            self._shown_hands = hands
            self._build_hand_rows()
        for name, var in self.hand_vars.items():
            if var.get() != m.texts.get(name, ""):  # e.g. after Clear all
                var.set(m.texts.get(name, ""))
            error = m.errors.get(name)
            label = self.hand_errors[name]
            if error:
                label.config(text=f"⚠ {error}")
                label.grid()
            else:
                label.grid_remove()

        self.game_var.set(m.game)
        self.players_var.set(str(m.players))
        self.burns_var.set(m.burns)
        self.burns_check.config(state=tk.NORMAL if m.game == stacking.HOLDEM else tk.DISABLED)
        self.fill_var.set(m.fill)

        if m.stack is not None:
            self.summary.config(text=m.summary(), style="TLabel")
        else:
            self.summary.config(text=f"⚠ {m.problem}", bootstyle="danger")
        self.stack_text.config(state=tk.NORMAL)
        self.stack_text.delete("1.0", tk.END)
        self.stack_text.insert("1.0", m.numbered())
        self.stack_text.config(state=tk.DISABLED)
        if self.use_as_final is not None:
            self.final_button.config(state=tk.NORMAL if m.stack is not None else tk.DISABLED)
        self.viewers.refresh()
