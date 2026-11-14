"""A tab strip the user fills: add tabs of any kind, close, rename and reorder them.

``TabManager`` pairs a ``QTabBar`` with a stack of tab pages, adding what a
plain ``QTabWidget`` lacks: a × on each tab, a "+" after the last one, renaming
in place and a right-click menu. Each tab holds a *content* object: anything
with a ``frame`` widget, made by the factory registered for its kind, and
optionally a ``close()`` method that stops pending work before the frame is
deleted. With no tab open, the body shows one large "New tab" button instead.

Mouse: click a tab to show it, drag it sideways to move it (it swaps places
with each neighbour it passes), double-click its title to rename it, click its × (or
middle-click the tab) to close it, and right-click it for a menu of all of
these (and, if the owner can copy tabs, "Duplicate"). When the tabs don't fit,
the strip scrolls with the arrows at its end. A newly shown tab's page fades in.
"""

from dataclasses import dataclass, field

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLineEdit, QMenu,
                               QSizePolicy, QStackedWidget, QTabBar, QToolButton, QVBoxLayout,
                               QWidget)

from .widgets import button, label, repolish

ANIMATION_MS = 140  # how long a newly shown page takes to fade in; 0: no animation
DRAG_START = 4  # pixels the mouse must move before a pressed tab starts to drag


@dataclass
class TabKind:
    title: str  # the default title of a new tab of this kind
    create: object  # create(parent) -> content with a ``frame``


@dataclass(eq=False)
class Tab:
    kind: str
    title: str
    content: object
    close_button: object = field(default=None, repr=False)
    entry: object = field(default=None, repr=False)  # the rename box, while renaming


class _Bar(QTabBar):
    """The strip itself: drag a tab to move it, middle-click one to close it.

    Dragging is done here rather than with ``setMovable``: Qt's own animated drag
    draws a stylesheet's tabs out of place (a tab's text left behind its shape).
    Here the dragged tab swaps places with a neighbour as soon as the mouse
    passes that neighbour's middle, so a tab is always drawn whole.
    """

    def __init__(self, on_middle_click):
        super().__init__()
        self._on_middle_click = on_middle_click
        self._drag_index = None  # the tab the left button went down on, while held
        self._press_x = None  # where it went down, until it has moved DRAG_START
        self.dragging = False

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            index = self.tabAt(event.position().toPoint())
            self._drag_index = index if index >= 0 else None
            self._press_x = event.position().x()
            self.dragging = False

    def mouseMoveEvent(self, event):
        if self._drag_index is None or not event.buttons() & Qt.LeftButton:
            super().mouseMoveEvent(event)
            return
        x = event.position().x()
        if not self.dragging:
            if abs(x - self._press_x) < DRAG_START:
                return
            self.dragging = True
            self.setCursor(Qt.SizeHorCursor)
        self.drag_to(x)

    def drag_to(self, x):
        """Move the dragged tab past each neighbour whose middle ``x`` has crossed."""
        i = self._drag_index
        while True:
            if i + 1 < self.count() and x > self.tabRect(i + 1).center().x():
                self.moveTab(i, i + 1)
                i += 1
            elif i > 0 and x < self.tabRect(i - 1).center().x():
                self.moveTab(i, i - 1)
                i -= 1
            else:
                break
        self._drag_index = i

    def start_drag(self, index, x):
        """As if the left button went down on tab ``index`` at ``x`` (for tests)."""
        self._drag_index, self._press_x, self.dragging = index, x, False

    def end_drag(self):
        self._drag_index = self._press_x = None
        if self.dragging:
            self.dragging = False
            self.unsetCursor()

    # QTabBar doesn't tell its layout when it grows or shrinks; without this the
    # strip keeps the width it had for its first tab.
    def tabInserted(self, index):
        super().tabInserted(index)
        self.updateGeometry()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self.updateGeometry()

    def tabLayoutChange(self):
        super().tabLayoutChange()
        self.updateGeometry()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange):  # e.g. a new theme
            self.updateGeometry()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.end_drag()
        if event.button() == Qt.MiddleButton:
            index = self.tabAt(event.position().toPoint())
            if index >= 0:
                self._on_middle_click(index)
                return
        super().mouseReleaseEvent(event)


class _RenameBox(QLineEdit):
    """The box over a tab's title while renaming it: Escape cancels."""

    def __init__(self, parent, on_escape):
        super().__init__(parent)
        self._on_escape = on_escape

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._on_escape()
        else:
            super().keyPressEvent(event)


class TabManager:
    def __init__(self, parent, kinds, on_change=None, on_duplicate=None):
        """``kinds``: {kind: TabKind}, in the order the "New tab" menu lists them.

        ``on_change()``, if given, runs after tabs are added, closed, renamed,
        moved or selected. ``on_duplicate(tab)``, if given, adds "Duplicate" to
        a tab's right-click menu; it is the owner's job to open the copy.
        """
        self.kinds = dict(kinds)
        self.on_change = on_change
        self.on_duplicate = on_duplicate
        self.tabs = []
        self.current = None
        self._recent = []  # tabs, the most recently shown last
        self._fade = None

        self.frame = QWidget(parent)
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.bar = QWidget()
        bar_layout = QHBoxLayout(self.bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(2)
        self.strip = _Bar(lambda i: self.close(self.tabs[i]))
        self.strip.setMovable(False)  # see _Bar: it does its own dragging
        self.strip.setExpanding(False)
        self.strip.setUsesScrollButtons(True)
        self.strip.setElideMode(Qt.ElideNone)
        self.strip.setDrawBase(False)
        self.strip.setDocumentMode(True)
        self.strip.setContextMenuPolicy(Qt.CustomContextMenu)
        self.strip.currentChanged.connect(self._on_current_changed)
        self.strip.tabMoved.connect(self._on_tab_moved)
        self.strip.tabBarDoubleClicked.connect(
            lambda i: i >= 0 and self.start_rename(self.tabs[i]))
        self.strip.customContextMenuRequested.connect(self._on_context_menu)
        bar_layout.addWidget(self.strip)
        self.add_button = QToolButton()
        self.add_button.setObjectName("tabAdd")
        self.add_button.setText("+")
        self.add_button.setToolTip("New tab (Ctrl+T)")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(lambda: self.post_new_menu(self.add_button))
        bar_layout.addWidget(self.add_button)
        bar_layout.addStretch(1)
        layout.addWidget(self.bar)

        self.body = QStackedWidget()
        self.body.setObjectName("tabBody")
        # Each kind of tab asks for a different size; don't let that resize the window.
        self.body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        layout.addWidget(self.body, 1)

        self.new_menu = QMenu(self.frame)
        for kind, spec in self.kinds.items():
            self.new_menu.addAction(spec.title, lambda k=kind: self.add(k))
        self.tab_menu = QMenu(self.frame)
        self._build_empty()
        layout.addWidget(self.empty, 1)
        self._show_body()

    def _build_empty(self):
        self.empty = QWidget()
        outer = QVBoxLayout(self.empty)
        outer.addStretch(9)
        inner = QVBoxLayout()
        inner.setSpacing(10)
        title = label("No tabs open", role="heading")
        title.setAlignment(Qt.AlignCenter)
        inner.addWidget(title)
        self.empty_button = button("+  New tab", lambda: self.post_new_menu(self.empty_button),
                                   kind="big")
        inner.addWidget(self.empty_button, 0, Qt.AlignHCenter)
        for text in ("Pick what the tab is for: "
                     + ", ".join(spec.title for spec in self.kinds.values()) + ".",
                     "Ctrl+T opens a new tab, Ctrl+W closes one."):
            hint = label(text, tone="muted")
            hint.setAlignment(Qt.AlignCenter)
            inner.addWidget(hint)
        outer.addLayout(inner)
        outer.addStretch(11)

    # --- tabs -------------------------------------------------------------------------

    def add(self, kind, title=None, select=True):
        """Open a new tab of ``kind`` after the last one; returns its ``Tab``."""
        spec = self.kinds[kind]
        content = spec.create(self.body)
        tab = Tab(kind, title or self.unused_title(spec.title), content)
        self.body.addWidget(content.frame)
        self.tabs.append(tab)
        self.strip.blockSignals(True)
        index = self.strip.addTab(tab.title)
        tab.close_button = QToolButton()
        tab.close_button.setObjectName("tabClose")
        tab.close_button.setText("×")
        # A small fixed circle, so its red hover stays inside the tab's rounded shape.
        tab.close_button.setFixedSize(18, 18)
        tab.close_button.setToolTip("Close tab (Ctrl+W)")
        tab.close_button.setCursor(Qt.PointingHandCursor)
        tab.close_button.clicked.connect(lambda: self.close(tab))
        # Held a little in from the tab's right end, clear of its rounded corner.
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 5, 0)
        holder_layout.addWidget(tab.close_button)
        self.strip.setTabButton(index, QTabBar.RightSide, holder)
        if self.current is not None:
            self.strip.setCurrentIndex(self.tabs.index(self.current))
        self.strip.blockSignals(False)
        if select or self.current is None:
            self.select(tab)
        else:
            self._changed()
        return tab

    def unused_title(self, base):
        """``base``, or ``base 2``, ``base 3``, ... if another tab already has it."""
        used = {t.title for t in self.tabs}
        n = 1
        while (title := base if n == 1 else f"{base} {n}") in used:
            n += 1
        return title

    def select(self, tab):
        if tab is self.current:
            return
        self.current = tab
        if tab in self._recent:
            self._recent.remove(tab)
        self._recent.append(tab)
        self.strip.blockSignals(True)
        self.strip.setCurrentIndex(self.tabs.index(tab))
        self.strip.blockSignals(False)
        self.body.setCurrentWidget(tab.content.frame)
        self._fade_in(tab.content.frame)
        self._style_headers()
        self._show_body()
        self._changed()

    def close(self, tab):
        """Close ``tab``; the one to its right (else its left) is shown instead."""
        if tab not in self.tabs:
            return
        if tab.entry is not None:
            self.finish_rename(tab, keep=False)
        index = self.tabs.index(tab)
        self.tabs.remove(tab)
        if tab in self._recent:  # a tab never shown isn't in it
            self._recent.remove(tab)
        was_current = tab is self.current
        if was_current:
            self.current = None
        close = getattr(tab.content, "close", None)
        if close is not None:
            close()
        # Gone before the next tab is shown, so the two are never drawn together.
        self.strip.blockSignals(True)
        self.strip.removeTab(index)
        if self.current is not None:
            self.strip.setCurrentIndex(self.tabs.index(self.current))
        self.strip.blockSignals(False)
        self.body.removeWidget(tab.content.frame)
        tab.content.frame.hide()
        tab.content.frame.deleteLater()
        if was_current and self.tabs:
            self.select(self.tabs[min(index, len(self.tabs) - 1)])
        self._show_body()
        self._changed()

    def close_others(self, keep):
        for tab in [t for t in self.tabs if t is not keep]:
            self.close(tab)

    def move(self, tab, index):
        """Put ``tab`` at ``index`` in the strip (clamped to the ends)."""
        index = max(0, min(index, len(self.tabs) - 1))
        old = self.tabs.index(tab)
        if old == index:
            return
        self.strip.moveTab(old, index)  # tabMoved puts it in its place in self.tabs

    def rename(self, tab, title):
        """Give ``tab`` a new title; a blank one is ignored. Returns whether it changed."""
        title = title.strip()
        if not title or title == tab.title:
            return False
        tab.title = title
        self.strip.setTabText(self.tabs.index(tab), title)
        self._changed()
        return True

    def select_next(self, step=1):
        if self.tabs:
            i = self.tabs.index(self.current) if self.current in self.tabs else -1
            self.select(self.tabs[(i + step) % len(self.tabs)])

    def latest(self, kind):
        """The most recently shown tab of ``kind``, or None."""
        return next((t for t in reversed(self._recent) if t.kind == kind), None)

    def titles(self):
        return [t.title for t in self.tabs]

    def label_text(self, tab):
        """The title the strip shows for ``tab``."""
        return self.strip.tabText(self.tabs.index(tab))

    def _changed(self):
        if self.on_change is not None:
            self.on_change()

    # --- the strip's signals ----------------------------------------------------------

    def _on_current_changed(self, index):
        if 0 <= index < len(self.tabs):
            self.select(self.tabs[index])

    def _on_tab_moved(self, old, new):
        tab = self.tabs.pop(old)
        self.tabs.insert(new, tab)
        self._changed()

    def _on_context_menu(self, pos):
        index = self.strip.tabAt(pos)
        if index >= 0:
            self.build_tab_menu(self.tabs[index]).popup(self.strip.mapToGlobal(pos))

    # --- drawing ----------------------------------------------------------------------

    def _style_headers(self):
        for tab in self.tabs:
            on_accent = tab is self.current
            if tab.close_button.property("onAccent") != on_accent:
                tab.close_button.setProperty("onAccent", on_accent)
                repolish(tab.close_button)

    def _show_body(self):
        """The strip and the current tab, or the "New tab" button when none is open."""
        has_tabs = bool(self.tabs)
        self.bar.setVisible(has_tabs)
        self.body.setVisible(has_tabs)
        self.empty.setVisible(not has_tabs)

    def _fade_in(self, widget):
        """Fade a newly shown page in (only while the window is on screen)."""
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        if ANIMATION_MS <= 0 or not self.frame.isVisible():
            return
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        fade = self._fade = QPropertyAnimation(effect, b"opacity", widget)
        fade.setDuration(ANIMATION_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)

        def done():
            # The effect draws the page through an image; drop it to keep text crisp.
            widget.setGraphicsEffect(None)
            if self._fade is fade:
                self._fade = None
        fade.finished.connect(done)
        fade.start()

    # --- menus ------------------------------------------------------------------------

    def post_new_menu(self, anchor=None):
        """Show the list of tab kinds under ``anchor`` (a widget), or under the "+"."""
        if anchor is None:
            anchor = self.add_button if self.tabs else self.empty_button
        self.new_menu.popup(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def build_tab_menu(self, tab):
        """The right-click menu for ``tab``."""
        m = self.tab_menu
        m.clear()
        i = self.tabs.index(tab)
        m.addAction("Rename…", lambda: self.start_rename(tab))
        if self.on_duplicate is not None:
            m.addAction("Duplicate", lambda: self.on_duplicate(tab))
        m.addAction("Move left", lambda: self.move(tab, i - 1)).setEnabled(i > 0)
        m.addAction("Move right", lambda: self.move(tab, i + 1)).setEnabled(
            i < len(self.tabs) - 1)
        m.addSeparator()
        m.addAction("Close", lambda: self.close(tab)).setShortcut("Ctrl+W")
        m.addAction("Close other tabs", lambda: self.close_others(tab)).setEnabled(
            len(self.tabs) > 1)
        return m

    # --- renaming in place ------------------------------------------------------------

    def start_rename(self, tab):
        """Put a box over the tab's title: Enter or clicking away keeps, Escape cancels."""
        if tab.entry is not None or tab not in self.tabs:
            return tab.entry
        self.select(tab)
        entry = tab.entry = _RenameBox(self.strip, lambda: self.finish_rename(tab, keep=False))
        entry.setText(tab.title)
        rect = self.strip.tabRect(self.tabs.index(tab))
        entry.setGeometry(rect.adjusted(6, 4, -26, -4))
        entry.selectAll()
        entry.show()
        entry.setFocus()
        entry.editingFinished.connect(lambda: self.finish_rename(tab))
        return entry

    def finish_rename(self, tab, keep=True):
        entry = tab.entry
        if entry is None:
            return
        tab.entry = None  # first, so the focus leaving the box does nothing more
        title = entry.text()
        entry.hide()
        entry.deleteLater()
        if keep:
            self.rename(tab, title)
