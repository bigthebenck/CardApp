"""Tkinter window with two tabs.

The first tab holds the Final Deck, Shuffle Sequence and Result panels; the
second ("X to Y") finds shuffles from one order to another. All state lives in
``AppModel`` and ``XToYModel``; this module only draws it and forwards user
edits. It contains no shuffle math.
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import deck, solver
from .. import shuffle_ops as ops
from .model import DECK_SIZE, AppModel, format_preview
from .x_to_y import XToYTab

TEXT_DEBOUNCE_MS = 400
GRID_ROWS = 13
MONO = ("Courier", 10)

ALL_CARD_LABELS = [deck.Card(r, s).pretty() for s in deck.SUITS for r in deck.RANKS]

SOLVER_TAB_TITLE = "Starting Order"
X_TO_Y_TAB_TITLE = "X to Y"

BADGES = {
    "ok": ("PASS", "#1e7b34"),
    "empty_sequence": ("PASS", "#1e7b34"),
    "failed": ("FAIL", "#b00020"),
    "invalid_deck": ("WAITING", "#8a6d00"),
    "invalid_steps": ("WAITING", "#8a6d00"),
}


class ShuffleSolverApp:
    def __init__(self, root, model=None, x_to_y_model=None):
        self.root = root
        self.model = model or AppModel()
        self._text_job = None
        self._syncing_text = False
        self._text_is_source = False
        self._text_slots = None  # slots the shorthand box last described

        root.title("Faro/Overhand Shuffle Solver")
        root.minsize(1200, 700)
        self._init_styles()
        self._build_menu()

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        panes = ttk.PanedWindow(self.notebook, orient=tk.HORIZONTAL)
        self.notebook.add(panes, text=SOLVER_TAB_TITLE)
        panes.add(self._build_final_panel(panes), weight=2)
        panes.add(self._build_sequence_panel(panes), weight=1)
        panes.add(self._build_result_panel(panes), weight=2)
        self.x_to_y = XToYTab(self.notebook, x_to_y_model)
        self.notebook.add(self.x_to_y.frame, text=X_TO_Y_TAB_TITLE)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    # --- setup ----------------------------------------------------------------------

    def _init_styles(self):
        style = ttk.Style(self.root)
        style.configure("Dup.TCombobox", fieldbackground="#ffc9c9", foreground="#8b0000")
        style.configure("Bad.TCombobox", fieldbackground="#ffe8a3")
        style.configure("Error.TLabel", foreground="#b00020")

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        filemenu = tk.Menu(menubar, tearoff=False)
        filemenu.add_command(label="Open setup…", command=self.open_setup, accelerator="Ctrl+O")
        filemenu.add_command(label="Save setup…", command=self.save_setup, accelerator="Ctrl+S")
        filemenu.add_separator()
        filemenu.add_command(label="Export starting order…", command=self.export_start)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        helpmenu = tk.Menu(menubar, tearoff=False)
        helpmenu.add_command(label="Shorthand syntax", command=self.show_syntax_help)
        menubar.add_cascade(label="Help", menu=helpmenu)
        self.root.config(menu=menubar)
        self.root.bind("<Control-o>", lambda e: self.open_setup())
        self.root.bind("<Control-s>", lambda e: self.save_setup())

    def _build_final_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="1. Final deck (desired order, top first)", padding=6)

        top = ttk.Frame(frame)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Preset:").pack(side=tk.LEFT)
        self.preset_var = tk.StringVar(value=next(iter(deck.PRESETS)))
        ttk.Combobox(top, textvariable=self.preset_var, values=list(deck.PRESETS),
                     state="readonly", width=20).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Load", command=self.load_preset).pack(side=tk.LEFT)
        ttk.Button(top, text="Clear", command=self.model.clear_final).pack(side=tk.RIGHT)

        ttk.Label(frame, text="Shorthand (e.g.  A-KH, (A-8, 9-K)`C, K-AD, ACHSD):").pack(
            anchor=tk.W, pady=(6, 0))
        self.final_text = tk.Text(frame, height=4, width=44, wrap=tk.WORD, font=MONO, undo=True)
        self.final_text.pack(fill=tk.X)
        self.final_text.bind("<<Modified>>", self._on_text_modified)
        self.text_error = ttk.Label(frame, text="", style="Error.TLabel", wraplength=420)
        self.text_error.pack(anchor=tk.W)

        grid = ttk.Frame(frame)
        grid.pack(anchor=tk.W, pady=(4, 0))
        self.slot_boxes = []
        self.slot_vars = []
        for i in range(DECK_SIZE):
            row, col = i % GRID_ROWS, (i // GRID_ROWS) * 2
            ttk.Label(grid, text=f"{i + 1:>2}", font=MONO).grid(row=row, column=col, sticky=tk.E,
                                                                 padx=(6, 2))
            var = tk.StringVar()
            box = ttk.Combobox(grid, textvariable=var, width=6, font=MONO,
                               postcommand=lambda i=i: self._fill_slot_choices(i))
            box.grid(row=row, column=col + 1, pady=1, sticky=tk.W)
            for seq in ("<<ComboboxSelected>>", "<Return>", "<FocusOut>"):
                box.bind(seq, lambda e, i=i: self._commit_slot(i))
            self.slot_boxes.append(box)
            self.slot_vars.append(var)

        self.deck_status = ttk.Label(frame, text="", wraplength=420, justify=tk.LEFT)
        self.deck_status.pack(anchor=tk.W, pady=(6, 0))
        return frame

    def _build_sequence_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="2. Shuffle sequence (first \u2192 last)",
                               padding=6)

        add = ttk.Frame(frame)
        add.pack(fill=tk.X)
        ttk.Button(add, text="+ Out-Faro",
                   command=lambda: self._add_step(ops.OUT_FARO)).grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(add, text="+ In-Faro",
                   command=lambda: self._add_step(ops.IN_FARO)).grid(row=0, column=1, sticky=tk.EW)
        ttk.Button(add, text="+ Overhand Run",
                   command=lambda: self._add_step(ops.OVERHAND_RUN)).grid(row=1, column=0,
                                                                          sticky=tk.EW)
        ttk.Button(add, text="+ Cut",
                   command=lambda: self._add_step(ops.CUT)).grid(row=1, column=1, sticky=tk.EW)
        ttk.Button(add, text="+ Partial Out-Faro",
                   command=lambda: self._add_step(ops.PARTIAL_OUT_FARO)).grid(row=2, column=0,
                                                                              sticky=tk.EW)
        ttk.Button(add, text="+ Partial In-Faro",
                   command=lambda: self._add_step(ops.PARTIAL_IN_FARO)).grid(row=2, column=1,
                                                                             sticky=tk.EW)
        ttk.Label(add, text="X:").grid(row=1, column=2, rowspan=2, padx=(8, 2))
        self.new_x_var = tk.StringVar(value="5")
        ttk.Spinbox(add, from_=1, to=DECK_SIZE, width=4,
                    textvariable=self.new_x_var).grid(row=1, column=3, rowspan=2)
        add.columnconfigure(0, weight=1)
        add.columnconfigure(1, weight=1)

        body = ttk.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True, pady=6)
        self.step_list = tk.Listbox(body, font=MONO, width=27, activestyle="dotbox",
                                    exportselection=False)
        self.step_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.step_list.bind("<<ListboxSelect>>", lambda e: self._on_step_select())
        self.step_list.bind("<Delete>", lambda e: self._delete_step())
        sb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.step_list.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.step_list.config(yscrollcommand=sb.set)

        buttons = ttk.Frame(body)
        buttons.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 0))
        for text, cmd in (("↑ Up", lambda: self._move_step(-1)),
                          ("↓ Down", lambda: self._move_step(1)),
                          ("Duplicate", self._duplicate_step),
                          ("Delete", self._delete_step),
                          ("Clear all", self.model.clear_steps)):
            ttk.Button(buttons, text=text, command=cmd).pack(fill=tk.X, pady=1)

        edit = ttk.Frame(frame)
        edit.pack(fill=tk.X)
        ttk.Label(edit, text="Selected step X:").pack(side=tk.LEFT)
        self.edit_x_var = tk.StringVar()
        self.edit_x = ttk.Spinbox(edit, from_=1, to=DECK_SIZE, width=4,
                                  textvariable=self.edit_x_var, command=self._commit_edit_x)
        self.edit_x.pack(side=tk.LEFT, padx=4)
        self.edit_x.bind("<Return>", lambda e: self._commit_edit_x())
        self.edit_x.bind("<FocusOut>", lambda e: self._commit_edit_x())
        self.seq_error = ttk.Label(frame, text="", style="Error.TLabel", wraplength=320)
        self.seq_error.pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(frame, text="Overhand run: X = 1–52 (52 reverses the deck). "
                              "Cut: X = 1–51. Partial faro: cut off the top X (up to 26) "
                              "and weave them into the top of the rest; out keeps the "
                              "top card on top, in makes it second.", foreground="#555",
                  wraplength=260).pack(anchor=tk.W)
        return frame

    def _build_result_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="3. Starting order (set up like this)",
                               padding=6)

        head = ttk.Frame(frame)
        head.pack(fill=tk.X)
        self.badge = tk.Label(head, text="", fg="white", font=("TkDefaultFont", 11, "bold"),
                              padx=10, pady=2)
        self.badge.pack(side=tk.LEFT)
        self.result_msg = ttk.Label(head, text="", wraplength=360, justify=tk.LEFT)
        self.result_msg.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

        self.start_text = tk.Text(frame, height=18, width=34, font=MONO, state=tk.DISABLED)
        self.start_text.pack(fill=tk.BOTH, expand=True, pady=6)

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Copy shorthand",
                   command=lambda: self._copy(self._start_shorthand())).pack(side=tk.LEFT)
        ttk.Button(btns, text="Copy list",
                   command=lambda: self._copy(self._start_numbered())).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Export…", command=self.export_start).pack(side=tk.LEFT)

        self.preview_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Show step-by-step preview", variable=self.preview_var,
                        command=self._toggle_preview).pack(anchor=tk.W, pady=(6, 0))
        self.preview_frame = ttk.Frame(frame)
        self.preview_text = tk.Text(self.preview_frame, height=14, font=MONO, wrap=tk.NONE,
                                    state=tk.DISABLED)
        xs = ttk.Scrollbar(self.preview_frame, orient=tk.HORIZONTAL,
                           command=self.preview_text.xview)
        ys = ttk.Scrollbar(self.preview_frame, orient=tk.VERTICAL,
                           command=self.preview_text.yview)
        self.preview_text.config(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.preview_text.grid(row=0, column=0, sticky=tk.NSEW)
        ys.grid(row=0, column=1, sticky=tk.NS)
        xs.grid(row=1, column=0, sticky=tk.EW)
        self.preview_frame.rowconfigure(0, weight=1)
        self.preview_frame.columnconfigure(0, weight=1)
        return frame

    # --- final deck events -------------------------------------------------------------

    def load_preset(self):
        self.model.load_preset(self.preset_var.get())

    def _on_text_modified(self, _event):
        if not self.final_text.edit_modified():
            return
        self.final_text.edit_modified(False)
        if self._syncing_text:
            return
        if self._text_job is not None:
            self.root.after_cancel(self._text_job)
        self._text_job = self.root.after(TEXT_DEBOUNCE_MS, self.apply_text)

    def apply_text(self):
        """Parse the shorthand box into the grid (also called after debounce)."""
        self._text_job = None
        self._text_is_source = True
        try:
            self.model.set_final_from_text(self.final_text.get("1.0", tk.END))
        finally:
            self._text_is_source = False

    def _fill_slot_choices(self, index):
        # Offer only cards not already placed in another slot.
        used = {c.key for i, c in enumerate(self.model.slots) if c is not None and i != index}
        self.slot_boxes[index]["values"] = [
            lbl for lbl, key in zip(ALL_CARD_LABELS, deck.FULL_DECK_KEYS) if key not in used
        ]

    def _commit_slot(self, index):
        text = self.slot_vars[index].get().strip()
        if not text:
            self.model.set_slot(index, None)
            return
        try:
            cards = deck.parse_cards(text)
            if len(cards) != 1:
                raise ValueError("one card per slot")
        except ValueError:
            self.slot_boxes[index].configure(style="Bad.TCombobox")
            return
        self.model.set_slot(index, cards[0])
        self.refresh()  # normalise the slot's text even when nothing changed

    # --- sequence events ------------------------------------------------------------------

    def _selected_step(self):
        sel = self.step_list.curselection()
        return sel[0] if sel else None

    def _select_step(self, index):
        self.step_list.selection_clear(0, tk.END)
        if index is not None and 0 <= index < self.step_list.size():
            self.step_list.selection_set(index)
            self.step_list.see(index)
        self._on_step_select()

    def _add_step(self, kind):
        x = None
        if kind in ops.KINDS_WITH_X:
            try:
                x = int(self.new_x_var.get())
                solver.Step(kind, x).validate(DECK_SIZE)
            except (ValueError, TypeError) as exc:
                self.seq_error.config(text=f"Can't add step: {exc}")
                return
        self.seq_error.config(text="")
        sel = self._selected_step()
        index = len(self.model.steps) if sel is None else sel + 1
        self.model.add_step(solver.Step(kind, x), index)
        self._select_step(index)

    def _move_step(self, delta):
        sel = self._selected_step()
        if sel is not None:
            self._select_step(self.model.move_step(sel, delta))

    def _duplicate_step(self):
        sel = self._selected_step()
        if sel is not None:
            self.model.duplicate_step(sel)
            self._select_step(sel + 1)

    def _delete_step(self):
        sel = self._selected_step()
        if sel is not None:
            self.model.remove_step(sel)
            self._select_step(min(sel, len(self.model.steps) - 1))

    def _on_step_select(self):
        sel = self._selected_step()
        step = self.model.steps[sel] if sel is not None else None
        if step is not None and step.kind in ops.KINDS_WITH_X:
            lo, hi = ops.x_bounds(step.kind)
            self.edit_x.configure(state=tk.NORMAL, from_=lo, to=hi)
            self.edit_x_var.set(str(step.x))
        else:
            self.edit_x_var.set("")
            self.edit_x.configure(state=tk.DISABLED)

    def _commit_edit_x(self):
        sel = self._selected_step()
        if sel is None or self.model.steps[sel].kind not in ops.KINDS_WITH_X:
            return
        try:
            self.model.set_step_x(sel, int(self.edit_x_var.get()))
            self.seq_error.config(text="")
        except (ValueError, TypeError) as exc:
            self.seq_error.config(text=f"Invalid X: {exc}")
            return
        self._select_step(sel)

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
            self.final_text.delete("1.0", tk.END)
            self.final_text.insert("1.0", m.final_text())
            self.final_text.edit_modified(False)
            self._syncing_text = False
        self.text_error.config(text=f"⚠ {m.input_error}" if m.input_error else "")

        dups = m.duplicate_slots()
        for i, card in enumerate(m.slots):
            box = self.slot_boxes[i]
            if self.root.focus_get() is not box or card is not None:
                self.slot_vars[i].set(card.pretty() if card else "")
            box.configure(style="Dup.TCombobox" if i in dups else "TCombobox")

        report = m.deck_report()
        if report.ok:
            self.deck_status.config(text="✓ Full 52-card deck, no duplicates.",
                                    foreground="#1e7b34")
        else:
            self.deck_status.config(text="\n".join(report.messages()), foreground="#b00020")

        sel = self._selected_step()
        self.step_list.delete(0, tk.END)
        for k, step in enumerate(m.steps, 1):
            self.step_list.insert(tk.END, f"{k:>2}. {step.label()}")
        if sel is not None and sel < len(m.steps):
            self.step_list.selection_set(sel)
        self._on_step_select()

        res = m.result
        text, color = BADGES[res.status]
        self.badge.config(text=text, bg=color)
        self.result_msg.config(text=" ".join(res.messages))
        self._set_text(self.start_text, self._start_numbered() if res.has_answer else "")
        self._render_preview()

    def _toggle_preview(self):
        if self.preview_var.get():
            self.preview_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.preview_frame.pack_forget()
        self._render_preview()

    def _render_preview(self):
        res = self.model.result
        if self.preview_var.get() and res.has_answer:
            self._set_text(self.preview_text, format_preview(res.states, self.model.steps))
        else:
            self._set_text(self.preview_text, "")

    @staticmethod
    def _set_text(widget, text):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.config(state=tk.DISABLED)

    # --- output -------------------------------------------------------------------------------

    def _start_shorthand(self):
        res = self.model.result
        return deck.format_cards(res.start) if res.has_answer and res.verified else ""

    def _start_numbered(self):
        res = self.model.result
        return deck.format_numbered(res.start) if res.has_answer else ""

    def _copy(self, text):
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def export_start(self):
        res = self.model.result
        if not (res.has_answer and res.verified):
            messagebox.showinfo("Export", "There is no verified starting order to export yet.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                            filetypes=[("Text", "*.txt"), ("All files", "*")])
        if not path:
            return
        steps = ", ".join(s.label() for s in self.model.steps) or "(none)"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"Shuffle sequence: {steps}\n\nStarting order (top first):\n")
            fh.write(self._start_numbered() + "\n\nShorthand:\n" + self._start_shorthand() + "\n")

    def save_setup(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("Shuffle setup", "*.json")])
        if path:
            self.model.save(path)

    def open_setup(self):
        path = filedialog.askopenfilename(filetypes=[("Shuffle setup", "*.json"),
                                                     ("All files", "*")])
        if not path:
            return
        try:
            self.model.load(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Open setup", f"Could not load {path}:\n{exc}")

    def show_syntax_help(self):
        messagebox.showinfo("Shorthand syntax", deck.__doc__)


def main():
    root = tk.Tk()
    ShuffleSolverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
