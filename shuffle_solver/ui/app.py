"""Tkinter window with three tabs.

The first tab holds the Final Deck, Shuffle Sequence and Result panels; the
second ("X to Y") finds shuffles from one order to another; the third ("Free
Tracking") follows a deck through shuffles you pick. All state lives in
``AppModel``, ``XToYModel`` and ``TrackerModel``; this module only draws it and
forwards user edits. It contains no shuffle math.
"""

import json
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as tb

from .. import deck, updater
from .. import shuffle_ops as ops
from . import theme
from .card_viewer import CardViewers
from .model import DECK_SIZE, TRACKER_FILE_TYPE, AppModel, format_instructions, format_preview
from .sequence_panel import SequencePanel
from .tracker import TrackerTab
from .update_dialog import UpdateChecker
from .x_to_y import XToYTab

TEXT_DEBOUNCE_MS = 400
GRID_ROWS = 13
MONO = ("Courier", 10)

ALL_CARD_LABELS = [deck.Card(r, s).pretty() for s in deck.SUITS for r in deck.RANKS]

SOLVER_TAB_TITLE = "Starting Order"
X_TO_Y_TAB_TITLE = "X to Y"
TRACKER_TAB_TITLE = "Free Tracking"

BADGES = {  # status -> (text, bootstyle)
    "ok": ("PASS", "success"),
    "empty_sequence": ("PASS", "success"),
    "failed": ("FAIL", "danger"),
    "invalid_deck": ("WAITING", "warning"),
    "invalid_steps": ("WAITING", "warning"),
}


class ShuffleSolverApp:
    def __init__(self, root, model=None, x_to_y_model=None, tracker_model=None,
                 settings_path=None, check_updates=False):
        self.root = root
        self.model = model or AppModel()
        self._text_job = None
        self._syncing_text = False
        self._text_is_source = False
        self._text_slots = None  # slots the shorthand box last described
        self.viewers = CardViewers(root)

        root.title("Faro/Overhand Shuffle Solver")
        root.minsize(1200, 700)
        self.settings_path = settings_path  # None: don't load or save the theme choice
        self.theme = theme.ThemeChoice.load(settings_path)
        self.theme.apply()
        self.updates = UpdateChecker(root, settings_path)
        self._build_menu()

        self.notebook = tb.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        panes = tb.Panedwindow(self.notebook, orient=tk.HORIZONTAL)
        self.notebook.add(panes, text=SOLVER_TAB_TITLE)
        panes.add(self._build_final_panel(panes), weight=2)
        self.sequence = SequencePanel(panes, self.model,
                                      "2. Shuffle sequence (first → last)", self._states)
        panes.add(self.sequence.frame, weight=1)
        panes.add(self._build_result_panel(panes), weight=2)
        self.x_to_y = XToYTab(self.notebook, x_to_y_model)
        self.notebook.add(self.x_to_y.frame, text=X_TO_Y_TAB_TITLE)
        self.tracker = TrackerTab(self.notebook, tracker_model)
        self.notebook.add(self.tracker.frame, text=TRACKER_TAB_TITLE)

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()
        if check_updates and self.updates.check_on_startup:
            self.updates.check(manual=False)  # quiet unless a newer version is out

    # --- setup ----------------------------------------------------------------------

    def _build_menu(self):
        menubar = tb.Menu(self.root)
        filemenu = tb.Menu(menubar, tearoff=False)
        filemenu.add_command(label="Open…", command=self.open_file, accelerator="Ctrl+O")
        filemenu.add_command(label="Save setup…", command=self.save_setup)
        filemenu.add_command(label="Save tracking project…", command=self.save_tracker)
        filemenu.add_separator()
        filemenu.add_command(label="Export starting order…", command=self.export_start)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        viewmenu = tb.Menu(menubar, tearoff=False)
        self.theme_var = tk.StringVar(value=self.theme.family)
        self.dark_var = tk.BooleanVar(value=self.theme.dark)
        thememenu = tb.Menu(viewmenu, tearoff=False)
        for family in theme.families():
            thememenu.add_radiobutton(label=theme.display_name(family), value=family,
                                      variable=self.theme_var, command=self.set_theme)
        viewmenu.add_cascade(label="Theme", menu=thememenu)
        viewmenu.add_checkbutton(label="Dark mode", variable=self.dark_var,
                                 command=self.set_theme, accelerator="Ctrl+D")
        menubar.add_cascade(label="View", menu=viewmenu)
        helpmenu = tb.Menu(menubar, tearoff=False)
        helpmenu.add_command(label="Shorthand syntax", command=self.show_syntax_help)
        helpmenu.add_separator()
        helpmenu.add_command(label="Check for updates…", command=self.updates.check)
        self.check_updates_var = tk.BooleanVar(value=self.updates.check_on_startup)
        helpmenu.add_checkbutton(label="Check for updates on startup",
                                 variable=self.check_updates_var,
                                 command=self.toggle_update_check)
        menubar.add_cascade(label="Help", menu=helpmenu)
        self.root.config(menu=menubar)
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-s>", lambda e: self.save_current())
        self.root.bind("<Control-d>", lambda e: self.toggle_dark())

    def _build_final_panel(self, parent):
        frame = tb.LabelFrame(parent, text="1. Final deck (desired order, top first)", padding=6)

        top = tb.Frame(frame)
        top.pack(fill=tk.X)
        tb.Label(top, text="Preset:").pack(side=tk.LEFT)
        self.preset_var = tk.StringVar(value=next(iter(deck.PRESETS)))
        tb.Combobox(top, textvariable=self.preset_var, values=list(deck.PRESETS),
                    state="readonly", width=20).pack(side=tk.LEFT, padx=4)
        tb.Button(top, text="Load", command=self.load_preset).pack(side=tk.LEFT)
        tb.Button(top, text="Clear", command=self.model.clear_final).pack(side=tk.RIGHT)

        label_row = tb.Frame(frame)
        label_row.pack(fill=tk.X, pady=(6, 0))
        tb.Label(label_row, text="Shorthand (e.g.  A-KH, (A-8, 9-K)`C, K-AD, ACHSD):").pack(
            side=tk.LEFT)
        tb.Button(label_row, text="View cards", command=self.view_final_cards).pack(
            side=tk.RIGHT)
        self.final_text = tb.Text(frame, height=4, width=44, wrap=tk.WORD, font=MONO, undo=True)
        self.final_text.pack(fill=tk.X)
        self.final_text.bind("<<Modified>>", self._on_text_modified)
        self.text_error = tb.Label(frame, text="", bootstyle="danger", wraplength=420)
        self.text_error.pack(anchor=tk.W)

        grid = tb.Frame(frame)
        grid.pack(anchor=tk.W, pady=(4, 0))
        self.slot_boxes = []
        self.slot_vars = []
        for i in range(DECK_SIZE):
            row, col = i % GRID_ROWS, (i // GRID_ROWS) * 2
            tb.Label(grid, text=f"{i + 1:>2}", font=MONO).grid(row=row, column=col, sticky=tk.E,
                                                                 padx=(6, 2))
            var = tk.StringVar()
            box = tb.Combobox(grid, textvariable=var, width=6, font=MONO,
                              postcommand=lambda i=i: self._fill_slot_choices(i))
            box.grid(row=row, column=col + 1, pady=1, sticky=tk.W)
            for seq in ("<<ComboboxSelected>>", "<Return>", "<FocusOut>"):
                box.bind(seq, lambda e, i=i: self._commit_slot(i))
            self.slot_boxes.append(box)
            self.slot_vars.append(var)

        self.deck_status = tb.Label(frame, text="", wraplength=420, justify=tk.LEFT)
        self.deck_status.pack(anchor=tk.W, pady=(6, 0))
        return frame

    def _build_result_panel(self, parent):
        frame = tb.LabelFrame(parent, text="3. Starting order (set up like this)",
                              padding=6)

        head = tb.Frame(frame)
        head.pack(fill=tk.X)
        self.badge = tb.Label(head, text="", font=("TkDefaultFont", 11, "bold"),
                              padding=(10, 2))
        self.badge.pack(side=tk.LEFT)
        self.result_msg = tb.Label(head, text="", wraplength=360, justify=tk.LEFT)
        self.result_msg.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

        self.start_text = tb.Text(frame, height=18, width=34, font=MONO, state=tk.DISABLED)
        self.start_text.pack(fill=tk.BOTH, expand=True, pady=6)

        btns = tb.Frame(frame)
        btns.pack(fill=tk.X)
        tb.Button(btns, text="Copy shorthand",
                  command=lambda: self._copy(self._start_shorthand())).pack(side=tk.LEFT)
        tb.Button(btns, text="Copy list",
                  command=lambda: self._copy(self._start_numbered())).pack(side=tk.LEFT, padx=4)
        tb.Button(btns, text="Export…", command=self.export_start).pack(side=tk.LEFT)
        tb.Button(btns, text="View cards", command=self.view_start_cards).pack(side=tk.RIGHT)

        self.preview_var = tk.BooleanVar(value=False)
        tb.Checkbutton(frame, text="Show step-by-step preview", variable=self.preview_var,
                       command=self._toggle_preview).pack(anchor=tk.W, pady=(6, 0))
        self.preview_frame = tb.Frame(frame)
        self.preview_text = tb.Text(self.preview_frame, height=14, font=MONO, wrap=tk.NONE,
                                    state=tk.DISABLED)
        xs = tb.Scrollbar(self.preview_frame, orient=tk.HORIZONTAL,
                          command=self.preview_text.xview)
        ys = tb.Scrollbar(self.preview_frame, orient=tk.VERTICAL,
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
                                    bootstyle="success")
        else:
            self.deck_status.config(text="\n".join(report.messages()), bootstyle="danger")

        self.sequence.refresh()

        res = m.result
        text, style = BADGES[res.status]
        self.badge.config(text=text, bootstyle=f"@{style}")
        self.result_msg.config(text=" ".join(res.messages))
        self._set_text(self.start_text, self._start_numbered() if res.has_answer else "")
        self._render_preview()
        self.viewers.refresh()

    def _states(self):
        res = self.model.result
        return res.states if res.has_answer else None

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

    # --- card image popups ------------------------------------------------------------------

    def view_final_cards(self):
        if self._text_job is not None:  # show what was just typed, not the pre-debounce slots
            self.root.after_cancel(self._text_job)
            self.apply_text()
        self.viewers.open("final", "Final deck (top first)", lambda: self.model.slots)

    def view_start_cards(self):
        self.viewers.open("start", "Starting order (top first)", self._start_cards)

    def _start_cards(self):
        res = self.model.result
        return res.start if res.has_answer else []

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
            messagebox.showinfo("Export", "There is no verified starting order to export yet.",
                                parent=self.root)
            return
        notes = self._ask_export_notes()
        if notes is None:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".txt",
                                            filetypes=[("Text", "*.txt"), ("All files", "*")])
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
        self._write_file("Export", path, write)

    def _ask_export_notes(self):
        """Ask for optional notes to end the export with; None if the user cancels."""
        dialog = tb.Toplevel(self.root)
        dialog.title("Export notes")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        tb.Label(dialog, text="Notes (optional) — added to the end of the file:").pack(
            anchor=tk.W, padx=10, pady=(10, 4))
        box = tk.Text(dialog, width=50, height=6, wrap=tk.WORD)
        box.pack(padx=10)
        result = {"notes": None}

        def ok(_event=None):
            result["notes"] = box.get("1.0", tk.END).strip()
            dialog.destroy()

        btns = tb.Frame(dialog)
        btns.pack(fill=tk.X, padx=10, pady=10)
        tb.Button(btns, text="Cancel", bootstyle="secondary",
                  command=dialog.destroy).pack(side=tk.RIGHT)
        tb.Button(btns, text="Choose file…", command=ok).pack(side=tk.RIGHT, padx=(0, 6))
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.bind("<Control-Return>", ok)
        box.focus_set()
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result["notes"]

    def save_setup(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                            filetypes=[("Shuffle setup", "*.json")])
        if path:
            self._write_file("Save setup", path, lambda: self.model.save(path))

    def _write_file(self, title, path, write):
        """Run ``write`` and tell the user where the file went, or why it failed."""
        try:
            write()
        except OSError as exc:
            messagebox.showerror(title, f"Could not save {path}:\n{exc}", parent=self.root)
        else:
            messagebox.showinfo(title, f"Saved to {path}", parent=self.root)

    def save_tracker(self):
        """Save the whole Free Tracking tab: deck, steps, groups and shuffle pile."""
        self.tracker.apply_text()  # include what was just typed in the deck box
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                            filetypes=[("Tracking project", "*.json")])
        if path:
            self._write_file("Save tracking project", path, lambda: self.tracker.model.save(path))

    def save_current(self):
        """Ctrl+S: save the tab in view (the Free Tracking tab, else the setup)."""
        if self.notebook.select() == str(self.tracker.frame):
            self.save_tracker()
        else:
            self.save_setup()

    def open_file(self):
        """Open a setup or a tracking project, into the tab it belongs to."""
        path = filedialog.askopenfilename(parent=self.root,
                                          filetypes=[("Setup or tracking project", "*.json"),
                                                     ("All files", "*")])
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("type") == TRACKER_FILE_TYPE:
                self.tracker.model.load_dict(data)
                self.notebook.select(self.tracker.frame)
            else:
                self.model.load_dict(data)
                self.notebook.select(0)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            messagebox.showerror("Open", f"Could not load {path}:\n{exc}", parent=self.root)

    # --- theme ---------------------------------------------------------------------------------

    def set_theme(self):
        """Apply the View menu's theme and dark-mode choice, and remember it."""
        self.theme = theme.ThemeChoice(self.theme_var.get(), self.dark_var.get())
        self.theme.apply()
        self.theme.save(self.settings_path)

    def toggle_dark(self):
        self.dark_var.set(not self.dark_var.get())
        self.set_theme()

    def show_syntax_help(self):
        messagebox.showinfo("Shorthand syntax", deck.__doc__)

    def toggle_update_check(self):
        self.updates.check_on_startup = self.check_updates_var.get()


def main():
    root = tb.Window()
    # Only the installed app checks by itself; running from source, use Help > Check for updates.
    ShuffleSolverApp(root, settings_path=theme.SETTINGS_PATH,
                     check_updates=updater.is_installed())
    root.mainloop()


if __name__ == "__main__":
    main()
