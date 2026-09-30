"""Tkinter window: a menu bar and a strip of tabs the user opens as needed.

The window starts with no tabs. Each tab is one of five kinds, and any kind
can be open more than once: "Starting Order" (``SolverTab``) works out how to
set up a deck for a shuffle sequence; "X to Y" finds shuffles from one order to
another; "Free Tracking" follows a deck through shuffles you pick; "Stack
Trainer" quizzes you on a stack; "Stacking" builds the stack that deals chosen
poker hands. Each tab keeps its own state in its own model; this module only
routes the menu, files and cross-tab hand-offs to the right tab. It contains no
shuffle math.

The open tabs are saved as a session (their kind, title and model state, and
which one is on show) every ``AUTOSAVE_MS`` and on quitting, and reopened the
next time the app starts. Closing every tab before quitting starts it empty.
"""

import json
import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as tb

from .. import deck, updater
from . import theme
from .model import TRACKER_FILE_TYPE
from .solver_tab import SolverTab, write_file
from .stacking import StackingTab
from .tabs import TabKind, TabManager
from .tracker import TrackerTab
from .trainer import TrainerTab
from .update_dialog import UpdateChecker
from .x_to_y import XToYTab

APP_TITLE = "Faro/Overhand Shuffle Solver"

SOLVER, X_TO_Y, TRACKER, TRAINER, STACKING = (
    "solver", "x_to_y", "tracker", "trainer", "stacking")
TAB_TITLES = {
    SOLVER: "Starting Order",
    X_TO_Y: "X to Y",
    TRACKER: "Free Tracking",
    TRAINER: "Stack Trainer",
    STACKING: "Stacking",
}
SAVABLE = {SOLVER: "Save setup", TRACKER: "Save tracking project"}

SESSION_PATH = Path.home() / ".shuffle_solver_session.json"
SESSION_VERSION = 1
AUTOSAVE_MS = 30_000


class ShuffleSolverApp:
    def __init__(self, root, settings_path=None, check_updates=False, session_path=None):
        """``session_path``: where the open tabs are kept between runs (None: nowhere)."""
        self.root = root
        root.title(APP_TITLE)
        root.minsize(1200, 700)
        self.settings_path = settings_path  # None: don't load or save the theme choice
        self.theme = theme.ThemeChoice.load(settings_path)
        self.theme.apply()
        self.updates = UpdateChecker(root, settings_path)
        self._build_menu()

        factories = {
            SOLVER: SolverTab,
            X_TO_Y: XToYTab,
            TRACKER: TrackerTab,
            TRAINER: TrainerTab,
            STACKING: lambda parent: StackingTab(parent, use_as_final=self.use_as_final),
        }
        self.tabs = TabManager(root, {kind: TabKind(TAB_TITLES[kind], factories[kind])
                                      for kind in TAB_TITLES}, on_change=self._on_tabs_changed)
        self.tabs.frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._on_tabs_changed()

        self.session_path = session_path
        self._saved_session = None  # the JSON last written, to skip unchanged saves
        self._autosave_job = None
        if session_path is not None:
            self.restore_session()
            root.protocol("WM_DELETE_WINDOW", self.quit)
            self._autosave_job = root.after(AUTOSAVE_MS, self._autosave)

        if check_updates and self.updates.check_on_startup:
            self.updates.check(manual=False)  # quiet unless a newer version is out

    # --- setup ----------------------------------------------------------------------

    def _build_menu(self):
        menubar = tb.Menu(self.root)
        self.filemenu = filemenu = tb.Menu(menubar, tearoff=False)
        newmenu = tb.Menu(filemenu, tearoff=False)
        for kind, title in TAB_TITLES.items():
            newmenu.add_command(label=title, command=lambda k=kind: self.new_tab(k))
        filemenu.add_cascade(label="New tab", menu=newmenu)
        filemenu.add_command(label="Open…", command=self.open_file, accelerator="Ctrl+O")
        filemenu.add_command(label="Save…", command=self.save_current, accelerator="Ctrl+S")
        filemenu.add_separator()
        filemenu.add_command(label="Export starting order…", command=self.export_start)
        filemenu.add_separator()
        filemenu.add_command(label="Close tab", command=self.close_current, accelerator="Ctrl+W")
        filemenu.add_command(label="Quit", command=self.quit)
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
        self.root.bind("<Control-t>", lambda e: self.tabs.post_new_menu())
        # In a text box Ctrl+T would also swap two letters first; "break" stops that.
        self.root.bind_class("Text", "<Control-t>", lambda e: self.tabs.post_new_menu() or "break")
        self.root.bind("<Control-w>", lambda e: self.close_current())
        self.root.bind("<Control-Tab>", lambda e: self.tabs.select_next(1))
        for seq in ("<Control-Shift-Tab>", "<Control-ISO_Left_Tab>"):
            try:
                self.root.bind(seq, lambda e: self.tabs.select_next(-1))
            except tk.TclError:
                pass  # ISO_Left_Tab is an X11 keysym; not every Tk knows it

    # --- tabs -----------------------------------------------------------------------

    def new_tab(self, kind, title=None):
        """Open a tab of ``kind`` and show it; returns its content (e.g. a ``SolverTab``)."""
        return self.tabs.add(kind, title).content

    def close_current(self):
        if self.tabs.current is not None:
            self.tabs.close(self.tabs.current)

    def current(self, kind=None):
        """The tab on show, if any (and if it is of ``kind``, when given)."""
        tab = self.tabs.current
        return tab if tab is not None and kind in (None, tab.kind) else None

    def _on_tabs_changed(self):
        tab = self.tabs.current
        self.root.title(f"{tab.title} — {APP_TITLE}" if tab else APP_TITLE)
        self.filemenu.entryconfig("Save…", state=tk.NORMAL if tab and tab.kind in SAVABLE
                                  else tk.DISABLED)
        self.filemenu.entryconfig("Export starting order…",
                                  state=tk.NORMAL if tab and tab.kind == SOLVER else tk.DISABLED)
        self.filemenu.entryconfig("Close tab", state=tk.NORMAL if tab else tk.DISABLED)

    def use_as_final(self, cards):
        """Make ``cards`` the final deck of the last Starting Order tab shown (or a new one)."""
        tab = self.tabs.latest(SOLVER) or self.tabs.add(SOLVER)
        tab.content.model.set_final_cards(cards)
        self.tabs.select(tab)

    def _name_after_file(self, tab, path):
        """Title a tab after its file, unless the user already named the tab."""
        base = TAB_TITLES[tab.kind]
        if re.fullmatch(re.escape(base) + r"( \d+)?", tab.title):
            self.tabs.rename(tab, Path(path).stem)

    # --- files ----------------------------------------------------------------------

    def save_current(self):
        """Ctrl+S: save the tab on show (a Starting Order setup or a tracking project)."""
        tab = self.tabs.current
        if tab is None or tab.kind not in SAVABLE:
            return
        if tab.kind == TRACKER:
            tab.content.apply_text()  # include what was just typed in the deck box
            path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".json",
                                                filetypes=[("Tracking project", "*.json")])
            if path:
                write_file(self.root, SAVABLE[TRACKER], path,
                           lambda: tab.content.model.save(path))
        else:
            path = tab.content.save()
        if path:
            self._name_after_file(tab, path)

    def export_start(self):
        tab = self.current(SOLVER)
        if tab is not None:
            tab.content.export_start()

    def open_file(self):
        """Open a setup or a tracking project, each in a new tab of its kind."""
        path = filedialog.askopenfilename(parent=self.root,
                                          filetypes=[("Setup or tracking project", "*.json"),
                                                     ("All files", "*")])
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            kind = TRACKER if data.get("type") == TRACKER_FILE_TYPE else SOLVER
        except (OSError, ValueError, AttributeError) as exc:
            messagebox.showerror("Open", f"Could not load {path}:\n{exc}", parent=self.root)
            return None
        tab = self.tabs.add(kind, Path(path).stem)
        try:
            tab.content.model.load_dict(data)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            self.tabs.close(tab)
            messagebox.showerror("Open", f"Could not load {path}:\n{exc}", parent=self.root)
            return None
        return tab.content

    # --- session ------------------------------------------------------------------------

    def session_dict(self):
        """The open tabs, in order, and which one is on show."""
        tabs = self.tabs.tabs
        return {
            "version": SESSION_VERSION,
            "current": tabs.index(self.tabs.current) if self.tabs.current in tabs else None,
            "tabs": [{"kind": t.kind, "title": t.title, "state": t.content.model.to_dict()}
                     for t in tabs],
        }

    def save_session(self):
        """Write the session file if anything changed since the last write."""
        if self.session_path is None:
            return
        text = json.dumps(self.session_dict())
        if text == self._saved_session:
            return
        path = Path(self.session_path)
        tmp = path.with_name(path.name + ".tmp")
        try:  # write a copy, then swap it in, so a crash mid-write can't lose the old one
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            return  # try again at the next autosave
        self._saved_session = text

    def restore_session(self):
        """Reopen the tabs saved last time; any that can't be read are left out."""
        try:
            data = json.loads(Path(self.session_path).read_text(encoding="utf-8"))
            entries = list(data["tabs"]) if data.get("version") == SESSION_VERSION else []
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return
        restored = {}  # index in the file -> Tab
        for i, entry in enumerate(entries):
            try:
                kind, title = entry["kind"], str(entry["title"])
                if kind not in TAB_TITLES:
                    continue
                tab = self.tabs.add(kind, title, select=False)
            except (KeyError, TypeError):
                continue
            try:
                tab.content.model.load_dict(entry.get("state") or {})
            except (ValueError, KeyError, TypeError, AttributeError):
                self.tabs.close(tab)
                continue
            restored[i] = tab
        current = restored.get(data.get("current"))
        if current is not None:
            self.tabs.select(current)
        self._saved_session = json.dumps(self.session_dict())

    def _autosave(self):
        self.save_session()
        self._autosave_job = self.root.after(AUTOSAVE_MS, self._autosave)

    def quit(self):
        """Save the session (with anything just typed) and close the window."""
        if self._autosave_job is not None:
            self.root.after_cancel(self._autosave_job)
            self._autosave_job = None
        for tab in self.tabs.tabs:
            apply_text = getattr(tab.content, "apply_text", None)
            if apply_text is not None:
                apply_text()  # typed in the last moment, before the box was read
        self.save_session()
        self.root.destroy()

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
                     check_updates=updater.is_installed(), session_path=SESSION_PATH)
    root.mainloop()


if __name__ == "__main__":
    main()
