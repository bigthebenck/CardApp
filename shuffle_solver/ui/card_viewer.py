"""Popup windows that show a deck order as card images instead of shorthand.

Each shorthand field gets a "View cards" button; the popup it opens stays in
sync with that field until it is closed. Images are the PNGs in
``card_images/`` (see the README there for their source). An indifferent
card (X) is shown as a card back; a high (B) or low (L) one has its letter on it.
"""

from collections import Counter
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

IMAGE_DIR = Path(__file__).with_name("card_images")
CARD_W, CARD_H = 96, 139
COLUMNS = 13
GAP = 6
LABEL_H = 16
TITLE_H = 26  # a pile's heading, when the cards come in piles
PAD = 10
FELT_COLOR = "#1f6b3a"
FACE_UP_COLOR = "#e07000"
EMPTY_COLOR = "#999999"

_pixmaps = {}  # path -> QPixmap, loaded on first use


def image_path(card):
    return IMAGE_DIR / ("back.png" if card.indifferent else f"{card.key}.png")


def _pixmap(card):
    path = str(image_path(card))
    pix = _pixmaps.get(path)
    if pix is None:
        pix = _pixmaps[path] = QPixmap(path).scaled(
            CARD_W, CARD_H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return pix


class CardCanvas(QWidget):
    """The felt the cards lie on: draws ``items``, a list of drawing steps."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []  # (kind, ...): see paintEvent
        self.content = QSize(1, 1)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def background(self):
        return FELT_COLOR

    def sizeHint(self):
        return self.content

    def set_items(self, items, width, height):
        self.items = items
        self.content = QSize(width, height)
        self.setFixedSize(self.content)
        self.update()

    def images(self):
        return [item for item in self.items if item[0] == "image"]

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(FELT_COLOR))
        for item in self.items:
            kind = item[0]
            if kind == "image":
                _k, x, y, card = item
                p.drawPixmap(int(x), int(y), _pixmap(card))
            elif kind == "text":
                _k, x, y, w, h, text, color, size, bold, align = item
                font = QFont(self.font())
                font.setPointSize(size)
                font.setBold(bold)
                p.setFont(font)
                p.setPen(QColor(color))
                p.drawText(QRectF(x, y, w, h), align, text)
            elif kind == "rect":
                _k, x, y, w, h, color, width, dashed = item
                pen = QPen(QColor(color), width)
                if dashed:
                    pen.setDashPattern([4, 3])
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(QRectF(x, y, w, h), 5, 5)
            elif kind == "badge":  # B or L on a card back
                _k, cx, cy, letter = item
                p.setPen(QPen(QColor("black"), 2))
                p.setBrush(QColor("white"))
                p.drawEllipse(QRectF(cx - 22, cy - 22, 44, 44))
                font = QFont(self.font())
                font.setPointSize(22)
                font.setBold(True)
                p.setFont(font)
                p.drawText(QRectF(cx - 22, cy - 22, 44, 44), Qt.AlignCenter, letter)
        p.end()


class _Window(QWidget):
    def __init__(self, parent, on_close):
        super().__init__(parent, Qt.Window)
        self._on_close = on_close

    def closeEvent(self, event):
        self._on_close()
        super().closeEvent(event)


class CardViewer:
    """A window that draws a list of cards (``None`` = empty slot) in rows of 13."""

    def __init__(self, master, title):
        self.win = _Window(master, self._closed)
        self.win.setObjectName("cardViewer")
        self.win.setAttribute(Qt.WA_StyledBackground)
        self.win.setWindowTitle(title)
        QShortcut(QKeySequence(Qt.Key_Escape), self.win, self.close)
        layout = QVBoxLayout(self.win)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.summary = QLabel("")
        self.summary.setContentsMargins(PAD, 6, PAD, 6)
        layout.addWidget(self.summary)
        self.canvas = CardCanvas()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setStyleSheet(f"QScrollArea {{ background: {FELT_COLOR}; border: none; }}")
        self.scroll.viewport().setStyleSheet(f"background: {FELT_COLOR};")
        self.scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self.scroll, 1)
        self._sized = False
        self.win.show()

    def is_open(self):
        return self.win is not None

    def _closed(self):
        self.win = None

    def close(self):
        if self.win is not None:
            win, self.win = self.win, None
            win.close()
            win.deleteLater()

    def lift(self):
        self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()

    def set_title(self, title):
        if self.win is not None:
            self.win.setWindowTitle(title)

    def show(self, cards):
        """Redraw with ``cards`` (top first); trailing empty slots are dropped.

        ``cards`` can instead be groups, ``[(title, cards), ...]``: each group
        (a pile) starts on a new row under its title.
        """
        cards = list(cards)
        groups = cards if cards and isinstance(cards[0], tuple) else [(None, cards)]
        groups = [(title, _trimmed(group)) for title, group in groups]
        every = [card for _title, group in groups for card in group]
        filled = sum(card is not None for card in every)
        face_up = sum(card is not None and card.face_up for card in every)
        kinds = Counter(card.rank for card in every if card is not None and card.indifferent)
        text = f"{filled} card{'s' if filled != 1 else ''}, top first"
        if len(groups) > 1:
            text += f", in {len(groups)} piles"
        if kinds:
            split = ", ".join(f"{kinds[r]} {r}" for r in "XBL" if kinds[r])
            text += (f"  ·  {sum(kinds.values())} indifferent ({split}, shown as a card back"
                     + (" marked B or L" if kinds["B"] or kinds["L"] else "") + ")")
        if face_up:
            text += f"  ·  {face_up} face up (orange outline)"
        self.summary.setText(text if every else "No cards to show.")

        items = []
        cell_w, cell_h = CARD_W + GAP, LABEL_H + CARD_H + GAP
        top_y = PAD
        for title, group in groups:
            if title is not None:
                items.append(("text", PAD, top_y, 13 * cell_w, TITLE_H, title, "white", 11,
                              True, Qt.AlignLeft | Qt.AlignVCenter))
                top_y += TITLE_H
            items += _draw(group, top_y)
            top_y += max((len(group) + COLUMNS - 1) // COLUMNS, 1 if title else 0) * cell_h
        cols = min(COLUMNS, max(max((len(g) for _t, g in groups), default=0), 1))
        width = 2 * PAD + cols * cell_w - GAP
        height = max(top_y + PAD - GAP, 2 * PAD + cell_h - GAP)
        self.canvas.set_items(items, width, height)
        if not self._sized and self.win is not None:  # size to the first contents
            self._sized = True
            screen = self.win.screen().availableGeometry()
            full_w = 2 * PAD + COLUMNS * cell_w - GAP + 14
            self.win.resize(min(full_w, int(screen.width() * 0.95)),
                            min(max(height, 4 * cell_h) + 40, int(screen.height() * 0.8)))


def _draw(cards, top_y):
    """Drawing steps for cards in rows of 13, numbered from 1, starting at ``top_y``."""
    items = []
    cell_w, cell_h = CARD_W + GAP, LABEL_H + CARD_H + GAP
    for i, card in enumerate(cards):
        x = PAD + (i % COLUMNS) * cell_w
        y = top_y + (i // COLUMNS) * cell_h
        color = FACE_UP_COLOR if card is not None and card.face_up else "white"
        items.append(("text", x, y, CARD_W, LABEL_H, str(i + 1), color, 9, True, Qt.AlignCenter))
        top = y + LABEL_H
        if card is None:
            items.append(("rect", x + 1, top + 1, CARD_W - 2, CARD_H - 2, EMPTY_COLOR, 1, True))
            items.append(("text", x, top, CARD_W, CARD_H, "empty", EMPTY_COLOR, 9, False,
                          Qt.AlignCenter))
            continue
        items.append(("image", x, top, card))
        if card.indifferent and card.category is not None:  # B or L on the back
            items.append(("badge", x + CARD_W / 2, top + CARD_H / 2, card.rank))
        if card.face_up:
            items.append(("rect", x - 2, top - 2, CARD_W + 4, CARD_H + 4, FACE_UP_COLOR, 3,
                          False))
    return items


def _trimmed(cards):
    """``cards`` as a list without its trailing empty slots."""
    cards = list(cards)
    while cards and cards[-1] is None:
        cards.pop()
    return cards


class CardViewers:
    """At most one popup per field, each refreshed from its field's getter."""

    def __init__(self, master):
        self.master = master
        self._open = {}  # name -> (CardViewer, get_cards)

    def open(self, name, title, get_cards):
        entry = self._open.get(name)
        if entry is not None and entry[0].is_open():
            viewer = entry[0]
            viewer.lift()
        else:
            viewer = CardViewer(self.master, title)
        self._open[name] = (viewer, get_cards)
        viewer.show(get_cards())
        return viewer

    def refresh(self):
        for name, (viewer, get_cards) in list(self._open.items()):
            if viewer.is_open():
                viewer.show(get_cards())
            else:
                del self._open[name]

    def get(self, name):
        entry = self._open.get(name)
        return entry[0] if entry is not None and entry[0].is_open() else None
