"""Small Qt helpers the tabs share: glass panels, toned labels, text boxes, debounces."""

import atexit

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

TEXT_DEBOUNCE_MS = 400


def mono_font(size=10):
    font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    for family in ("Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono"):
        if family in QFontDatabase.families():
            font = QFont(family)
            break
    font.setPointSize(size)
    font.setStyleHint(QFont.Monospace)
    return font


def repolish(widget):
    """Re-apply the stylesheet after a property it matches on changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_tone(widget, tone):
    """Colour ``widget`` as "success", "danger", "warning", "info", "muted" (None: plain)."""
    tone = tone or ""
    if widget.property("tone") != tone:
        widget.setProperty("tone", tone)
        repolish(widget)


def tone(widget):
    return widget.property("tone") or None


def label(text="", tone=None, wrap=False, role=None, mono=False):
    w = QLabel(text)
    if wrap:
        w.setWordWrap(True)
    if role:
        w.setProperty("role", role)
    if tone:
        w.setProperty("tone", tone)
    if mono:
        w.setFont(mono_font())
    w.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return w


def button(text, slot=None, kind=None):
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if slot is not None:
        b.clicked.connect(lambda _checked=False: slot())
    b.setCursor(Qt.PointingHandCursor)
    return b


def row(*items, spacing=6):
    """A widget laying ``items`` out left to right: widgets, ``None`` for a stretch,
    or an int for that much extra space."""
    w = QWidget()
    layout = QHBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for item in items:
        if item is None:
            layout.addStretch(1)
        elif isinstance(item, int):
            layout.addSpacing(item)
        else:
            layout.addWidget(item)
    return w


def column(parent=None, spacing=6, margins=0):
    """A plain widget with a top-to-bottom layout; returns (widget, layout)."""
    w = QWidget(parent)
    layout = QVBoxLayout(w)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    return w, layout


class Panel(QGroupBox):
    """A frosted-glass card with a title; add to ``layout``."""

    def __init__(self, title="", parent=None, spacing=6):
        super().__init__(title, parent)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(spacing)

    @property
    def body(self):
        return self.layout_

    def text(self):
        return self.title()


def text_box(lines=None, mono=True, read_only=False, wrap=True):
    """A plain-text box ``lines`` lines tall (None: as tall as there is room)."""
    box = QPlainTextEdit()
    if mono:
        box.setFont(mono_font())
    box.setLineWrapMode(QPlainTextEdit.WidgetWidth if wrap else QPlainTextEdit.NoWrap)
    if read_only:
        box.setReadOnly(True)
    if lines is not None:
        height = box.fontMetrics().lineSpacing() * lines + 18
        box.setFixedHeight(height)
    return box


def text_of(box):
    return box.toPlainText()


def set_text(box, text):
    """Replace a text box's contents (read-only ones too), keeping the scroll at the top."""
    if box.toPlainText() != text:
        box.setPlainText(text)


def copy(text):
    if text:
        QApplication.clipboard().setText(text)


class ThemedToolTips(QObject):
    """Shows tooltips in the theme's own look instead of the system's.

    Windows draws Qt's tooltips as plain square popups with its own shadow, which
    no stylesheet can round off. Installed on the application, this answers each
    tooltip request with a small frameless popup painted from ``theme.current()``.
    """

    HIDE_AFTER_MS = 6000

    def __init__(self, app):
        super().__init__(app)
        self.tip = _TipLabel()
        self._shown = False  # kept here: asking a widget during shutdown can recurse
        self._hide = QTimer(self)
        self._hide.setSingleShot(True)
        self._hide.timeout.connect(self.hide)
        self._app = app
        app.installEventFilter(self)
        app.aboutToQuit.connect(self.detach)
        atexit.register(self.detach)  # also when the app never ran its event loop

    def detach(self):
        try:
            self._app.removeEventFilter(self)
        except RuntimeError:
            pass  # already gone

    def hide(self):
        if self._shown:
            self._shown = False
            try:
                self.tip.hide()
            except RuntimeError:
                pass

    def show_text(self, pos, text):
        if not text:
            self.hide()
            return
        from . import theme
        self.tip.setStyleSheet(f"QLabel {{ color: {theme.current().fg}; background: transparent; }}")
        self.tip.setText(text)
        self.tip.adjustSize()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(pos.x() + 2, area.left()), area.right() - self.tip.width())
        y = pos.y() + 20
        if y + self.tip.height() > area.bottom():
            y = pos.y() - self.tip.height() - 6
        self.tip.move(x, y)
        self.tip.show()
        self.tip.raise_()
        self._shown = True
        self._hide.start(self.HIDE_AFTER_MS)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.ToolTip and isinstance(obj, QWidget):
            self.show_text(event.globalPos(), obj.toolTip())
            return True  # not the system's tooltip as well
        if self._shown and kind in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Wheel,
                                    QEvent.KeyPress, QEvent.WindowDeactivate):
            self.hide()
        return False


class _TipLabel(QLabel):
    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setObjectName("themedTip")
        self.setContentsMargins(10, 6, 10, 6)

    def paintEvent(self, event):
        from . import theme
        p = theme.current()
        classic = p.style == theme.CLASSIC
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        fill = QColor(p.inputbg if classic else p.bg)
        if not classic:
            fill = fill.lighter(112) if p.dark else QColor("#ffffff")
            fill.setAlphaF(0.97)
        edge = QColor(p.border) if classic else QColor(p.fg)
        if not classic:
            edge.setAlphaF(0.18)
        painter.setPen(QPen(edge, 1))
        painter.setBrush(fill)
        radius = 0 if classic else 8
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                radius, radius)
        painter.end()
        super().paintEvent(event)


class Debounce:
    """Calls ``fn()`` once, ``ms`` after the last ``start()``; ``stop()`` cancels it."""

    def __init__(self, parent, fn, ms=TEXT_DEBOUNCE_MS):
        self.timer = QTimer(parent)
        self.timer.setSingleShot(True)
        self.timer.setInterval(ms)
        self.timer.timeout.connect(fn)

    def start(self):
        self.timer.start()

    def stop(self):
        self.timer.stop()

    @property
    def pending(self):
        return self.timer.isActive()
