"""The main window: a menu bar and a strip of tabs the user opens as needed.

The window starts with no tabs. Each tab is one of five kinds, and any kind
can be open more than once: "Starting Order" (``SolverTab``) works out how to
set up a deck for a shuffle sequence; "X to Y" finds shuffles from one order to
another; "Free Tracking" follows a deck through shuffles you pick; "Stack
Trainer" quizzes you on a stack; "Stacking" builds the stack that deals chosen
poker hands. Each tab keeps its own state in its own model; this module only
routes the menu, files and cross-tab hand-offs to the right tab. It contains no
shuffle math.

Two things make new tabs out of open ones: the "Open in new tab" button next
to a deck hands its cards to a fresh tab of another kind, and "Duplicate" in a
tab's right-click menu copies the whole tab.

The open tabs are saved as a session (their kind, title and model state, and
which one is on show) every ``AUTOSAVE_MS`` and on quitting, and reopened the
next time the app starts. Closing every tab before quitting starts it empty.
"""

import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from .. import deck, updater
from . import dialogs, search_process, theme
from .model import TRACKER_FILE_TYPE
from .open_in import TITLE as OPEN_IN_TITLE
from .presets import PresetStore
from .solver_tab import SolverTab, write_file
from .stacking import StackingTab
from .tabs import TabKind, TabManager
from .tracker import TrackerTab
from .trainer import TrainerTab
from .update_dialog import UpdateChecker
from .widgets import ThemedToolTips
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


class ShuffleSolverApp(theme.GlassWindow):
    def __init__(self, settings_path=None, check_updates=False, session_path=None):
        """``settings_path``: where the theme, presets and update choices are kept;
        ``session_path``: where the open tabs are kept between runs (None: nowhere)."""
        choice = theme.ThemeChoice.load(settings_path)
        # Translucent only if it starts see-through: see GlassWindow.
        super().__init__(translucent=choice.see_through and choice.style == theme.GLASS)
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1200, 700)
        self.resize(1380, 800)  # fits the largest kind of tab; tabs don't resize the window
        self._closed = False
        self.settings_path = settings_path  # None: don't load or save the theme choice
        self.theme = choice
        self.theme.apply(self)
        app = QApplication.instance()
        if getattr(app, "themed_tips", None) is None:  # one per app, shared by its windows
            app.themed_tips = ThemedToolTips(app)
        self.updates = UpdateChecker(self, settings_path)
        self.presets = PresetStore(settings_path)  # shared, so every tab sees new presets
        self._build_menu()

        factories = {
            SOLVER: lambda parent: SolverTab(parent, presets=self.presets,
                                             open_in=self.open_in_new_tab),
            X_TO_Y: lambda parent: XToYTab(parent, presets=self.presets,
                                           open_in=self.open_in_new_tab),
            TRACKER: lambda parent: TrackerTab(parent, presets=self.presets,
                                               open_in=self.open_in_new_tab),
            TRAINER: lambda parent: TrainerTab(parent, presets=self.presets,
                                               open_in=self.open_in_new_tab),
            STACKING: lambda parent: StackingTab(parent, use_as_final=self.use_as_final,
                                                 open_in=self.open_in_new_tab),
        }
        central = QWidget()
        central.setObjectName("central")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 4, 12, 12)
        self.tabs = TabManager(central, {kind: TabKind(TAB_TITLES[kind], factories[kind])
                                         for kind in TAB_TITLES},
                               on_change=self._on_tabs_changed, on_duplicate=self.duplicate_tab)
        layout.addWidget(self.tabs.frame)
        self.setCentralWidget(central)
        self._on_tabs_changed()

        self.session_path = session_path
        self._saved_session = None  # the JSON last written, to skip unchanged saves
        self._autosave_timer = None
        if session_path is not None:
            self.restore_session()
            self._autosave_timer = QTimer(self)
            self._autosave_timer.timeout.connect(self._autosave)
            self._autosave_timer.start(AUTOSAVE_MS)

        if check_updates and self.updates.check_on_startup:
            self.updates.check(manual=False)  # quiet unless a newer version is out

    # --- setup ----------------------------------------------------------------------

    def _action(self, menu, text, slot, shortcut=None, checkable=False):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        action.triggered.connect(lambda _checked=False: slot())
        menu.addAction(action)
        return action

    def _build_menu(self):
        bar = self.menuBar()
        filemenu = bar.addMenu("&File")
        newmenu = filemenu.addMenu("New tab")
        for kind, title in TAB_TITLES.items():
            self._action(newmenu, title, lambda k=kind: self.new_tab(k))
        self._action(filemenu, "Open…", self.open_file, "Ctrl+O")
        self.save_action = self._action(filemenu, "Save…", self.save_current, "Ctrl+S")
        filemenu.addSeparator()
        self.export_action = self._action(filemenu, "Export starting order…",
                                          self.export_start)
        filemenu.addSeparator()
        self.close_action = self._action(filemenu, "Close tab", self.close_current, "Ctrl+W")
        self._action(filemenu, "Quit", self.quit, "Ctrl+Q")
        # Ctrl+T shows the kinds of tab under the "+" (or the big "New tab" button).
        QShortcut(QKeySequence("Ctrl+T"), self, lambda: self.tabs.post_new_menu())

        viewmenu = bar.addMenu("&View")
        stylemenu = viewmenu.addMenu("Style")
        group = QActionGroup(self)
        self.style_actions = {}
        for style, name in theme.STYLES.items():
            action = self._action(stylemenu, name, lambda s=style: self.set_theme(style=s),
                                  checkable=True)
            group.addAction(action)
            self.style_actions[style] = action
        self.theme_menu = viewmenu.addMenu("Theme")
        self.theme_actions = {}
        self._fill_theme_menu()
        self.dark_action = self._action(viewmenu, "Dark mode", self.toggle_dark, "Ctrl+D",
                                        checkable=True)
        self.dark_action.setChecked(self.theme.dark)
        self.see_through_action = self._action(
            viewmenu, "See-through window", self.toggle_see_through, checkable=True)
        self._show_theme_choice()
        viewmenu.addSeparator()
        self._action(viewmenu, "Next tab", lambda: self.tabs.select_next(1), "Ctrl+Tab")
        self._action(viewmenu, "Previous tab", lambda: self.tabs.select_next(-1),
                     "Ctrl+Shift+Tab")
        QShortcut(QKeySequence("Ctrl+PgDown"), self, lambda: self.tabs.select_next(1))
        QShortcut(QKeySequence("Ctrl+PgUp"), self, lambda: self.tabs.select_next(-1))

        helpmenu = bar.addMenu("&Help")
        self._action(helpmenu, "Shorthand syntax", self.show_syntax_help)
        helpmenu.addSeparator()
        self._action(helpmenu, "Check for updates…", self.updates.check)
        self.check_updates_action = self._action(helpmenu, "Check for updates on startup",
                                                 self.toggle_update_check, checkable=True)
        self.check_updates_action.setChecked(self.updates.check_on_startup)

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
        self.setWindowTitle(f"{tab.title} — {APP_TITLE}" if tab else APP_TITLE)
        self.save_action.setEnabled(bool(tab and tab.kind in SAVABLE))
        self.export_action.setEnabled(bool(tab and tab.kind == SOLVER))
        self.close_action.setEnabled(tab is not None)

    def use_as_final(self, cards):
        """Make ``cards`` the final deck of the last Starting Order tab shown (or a new one)."""
        tab = self.tabs.latest(SOLVER) or self.tabs.add(SOLVER)
        tab.content.model.set_final_cards(cards)
        self.tabs.select(tab)

    def open_in_new_tab(self, target, cards):
        """Open ``cards`` in a new tab; ``target`` (a key of ``open_in.TARGETS``) says
        which kind and which of its decks. Returns the tab's content, or None."""
        kind, load = {
            "final": (SOLVER, lambda m: m.set_final_cards(cards)),
            "x": (X_TO_Y, lambda m: m.set_cards("start", cards)),
            "y": (X_TO_Y, lambda m: m.set_cards("end", cards)),
            "tracker": (TRACKER, lambda m: m.set_cards(cards)),
            "trainer": (TRAINER, lambda m: m.set_cards(cards)),
        }[target]
        previous = self.tabs.current
        tab = self.tabs.add(kind)
        try:
            load(tab.content.model)
        except ValueError as exc:
            self.tabs.close(tab)
            if previous is not None:
                self.tabs.select(previous)
            dialogs.error(self, OPEN_IN_TITLE, f"Can't open this in a new tab: {exc}")
            return None
        return tab.content

    def duplicate_tab(self, tab):
        """Open a copy of ``tab`` (what a saved session would keep of it) right after it."""
        apply_text = getattr(tab.content, "apply_text", None)
        if apply_text is not None:
            apply_text()  # include what was just typed in a deck box
        state = tab.content.model.to_dict()
        copy = self.tabs.add(tab.kind, self.tabs.unused_title(tab.title))
        copy.content.model.load_dict(state)
        self.tabs.move(copy, self.tabs.tabs.index(tab) + 1)
        return copy.content

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
            path = dialogs.save_path(self, SAVABLE[TRACKER], "Tracking project (*.json)",
                                     ".json")
            if path:
                write_file(self, SAVABLE[TRACKER], path, lambda: tab.content.model.save(path))
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
        path = dialogs.open_path(self, "Open",
                                 "Setup or tracking project (*.json);;All files (*)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            kind = TRACKER if data.get("type") == TRACKER_FILE_TYPE else SOLVER
        except (OSError, ValueError, AttributeError) as exc:
            dialogs.error(self, "Open", f"Could not load {path}:\n{exc}")
            return None
        tab = self.tabs.add(kind, Path(path).stem)
        try:
            tab.content.model.load_dict(data)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            self.tabs.close(tab)
            dialogs.error(self, "Open", f"Could not load {path}:\n{exc}")
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

    def quit(self):
        """Save the session (with anything just typed) and close the window."""
        self.close()

    def closeEvent(self, event):
        if not self._closed:
            self._closed = True
            if self._autosave_timer is not None:
                self._autosave_timer.stop()
            for tab in self.tabs.tabs:
                apply_text = getattr(tab.content, "apply_text", None)
                if apply_text is not None:
                    apply_text()  # typed in the last moment, before the box was read
            self.save_session()
            for tab in self.tabs.tabs:  # stop searches and pending edits
                close = getattr(tab.content, "close", None)
                if close is not None:
                    close()
            search_process.shutdown()
        super().closeEvent(event)

    # --- theme ---------------------------------------------------------------------------------

    def _fill_theme_menu(self):
        """List the theme families of the style in use."""
        self.theme_menu.clear()
        group = QActionGroup(self.theme_menu)
        self.theme_actions = {}
        for family in self.theme.families():
            action = self._action(self.theme_menu, theme.display_name(family),
                                  lambda f=family: self.set_theme(family=f), checkable=True)
            group.addAction(action)
            self.theme_actions[family] = action

    def _show_theme_choice(self):
        """Tick the View menu's entries for the theme in use."""
        t = self.theme
        self.style_actions[t.style].setChecked(True)
        self.theme_actions[t.family].setChecked(True)
        self.dark_action.setChecked(t.dark)
        self.see_through_action.setChecked(t.see_through and t.style == theme.GLASS)
        # Only glass can be see-through, and only where Windows can blur what's behind.
        self.see_through_action.setEnabled(theme.see_through_supported()
                                           and t.style == theme.GLASS)

    def set_theme(self, family=None, dark=None, see_through=None, style=None):
        """Switch the style, theme family, dark mode or see-through, and remember it.

        ``family`` is one of the families of the style in use (after ``style``)."""
        t = self.theme
        if style is not None and style != t.style:
            t = replace(t, style=style)
        if family is not None:
            t = t.with_family(family)
        if dark is not None:
            t = replace(t, dark=dark)
        if see_through is not None:
            t = replace(t, see_through=see_through)
        style_changed = t.style != self.theme.style
        self.theme = t
        self.theme.apply(self)
        self.theme.save(self.settings_path)
        if style_changed:
            self._fill_theme_menu()
        self._show_theme_choice()
        if (t.see_through and t.style == theme.GLASS and not self.translucent
                and theme.see_through_supported() and (see_through or style_changed)):
            dialogs.info(self, "See-through window",
                         "The window will be see-through the next time you start the app.")
        for tab in self.tabs.tabs:  # group tints and the like are drawn from the theme
            refresh = getattr(tab.content, "refresh", None)
            if refresh is not None:
                refresh()

    def toggle_dark(self):
        self.set_theme(dark=not self.theme.dark)

    def toggle_see_through(self):
        self.set_theme(see_through=not self.theme.see_through)

    def show_syntax_help(self):
        dialogs.info(self, "Shorthand syntax", deck.__doc__)

    def toggle_update_check(self):
        self.updates.check_on_startup = self.check_updates_action.isChecked()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")  # draws the same everywhere, under the glass stylesheet
    icon = Path(__file__).with_name("card_images") / "AS.png"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    # Only the installed app checks by itself; running from source, use Help > Check for updates.
    window = ShuffleSolverApp(settings_path=theme.SETTINGS_PATH,
                              check_updates=updater.is_installed(), session_path=SESSION_PATH)
    window.show()
    window.set_see_through(window.theme.see_through and window.theme.style == theme.GLASS)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
