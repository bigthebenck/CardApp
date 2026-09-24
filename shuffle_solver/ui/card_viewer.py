"""Popup windows that show a deck order as card images instead of shorthand.

Each shorthand field gets a "View cards" button; the popup it opens stays in
sync with that field until it is closed. Images are the PNGs in
``card_images/`` (see the README there for their source).
"""

import tkinter as tk
from pathlib import Path

import ttkbootstrap as tb

IMAGE_DIR = Path(__file__).with_name("card_images")
CARD_W, CARD_H = 96, 139
COLUMNS = 13
GAP = 6
LABEL_H = 16
TITLE_H = 26  # a pile's heading, when the cards come in piles
PAD = 10
FELT_COLOR = "#1f6b3a"
FACE_UP_COLOR = "#e07000"
EMPTY_COLOR = "#999"


def image_path(card):
    return IMAGE_DIR / f"{card.key}.png"


class CardViewer:
    """A Toplevel that draws a list of cards (``None`` = empty slot) in rows of 13."""

    def __init__(self, master, title):
        self.win = tk.Toplevel(master)
        self.win.title(title)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda e: self.close())
        self._images = {}  # card key -> PhotoImage, loaded on first use

        self.summary = tb.Label(self.win, text="", padding=(PAD, 6, PAD, 0))
        self.summary.pack(anchor=tk.W)
        body = tb.Frame(self.win)
        body.pack(fill=tk.BOTH, expand=True)
        # The felt stays green in every theme (autostyle=False keeps ttkbootstrap off it).
        self.canvas = tb.Canvas(body, highlightthickness=0, background=FELT_COLOR,
                                autostyle=False)
        sb = tb.Scrollbar(body, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.config(yscrollcommand=sb.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))
        self._sized = False

    def is_open(self):
        return self.win is not None and bool(self.win.winfo_exists())

    def close(self):
        if self.win is not None:
            self.win.destroy()
            self.win = None

    def lift(self):
        self.win.deiconify()
        self.win.lift()
        self.win.focus_set()

    def _image(self, card):
        img = self._images.get(card.key)
        if img is None:
            img = tk.PhotoImage(master=self.win, file=str(image_path(card)))
            self._images[card.key] = img
        return img

    def _on_wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def show(self, cards):
        """Redraw with ``cards`` (top first); trailing empty slots are dropped.

        ``cards`` can instead be groups, ``[(title, cards), ...]``: each group
        (a pile) starts on a new row under its title.
        """
        cards = list(cards)
        groups = cards if cards and isinstance(cards[0], tuple) else [(None, cards)]
        groups = [(title, _trimmed(group)) for title, group in groups]
        every = [card for _title, group in groups for card in group]
        c = self.canvas
        c.delete("all")
        filled = sum(card is not None for card in every)
        face_up = sum(card is not None and card.face_up for card in every)
        text = f"{filled} card{'s' if filled != 1 else ''}, top first"
        if len(groups) > 1:
            text += f", in {len(groups)} piles"
        if face_up:
            text += f"  ·  {face_up} face up (orange outline)"
        self.summary.config(text=text if every else "No cards to show.")

        cell_w, cell_h = CARD_W + GAP, LABEL_H + CARD_H + GAP
        top_y = PAD
        for title, group in groups:
            if title is not None:
                c.create_text(PAD, top_y + TITLE_H / 2, text=title, fill="white",
                              anchor=tk.W, font=("TkDefaultFont", 11, "bold"))
                top_y += TITLE_H
            self._draw(group, top_y)
            top_y += max((len(group) + COLUMNS - 1) // COLUMNS, 1 if title else 0) * cell_h
        cols = min(COLUMNS, max(max((len(g) for _t, g in groups), default=0), 1))
        width = 2 * PAD + cols * cell_w - GAP
        height = max(top_y + PAD - GAP, 2 * PAD + cell_h - GAP)
        c.config(scrollregion=(0, 0, width, height))
        if not self._sized:  # size to the first contents; the user may resize after
            self._sized = True
            max_w = int(self.win.winfo_screenwidth() * 0.95)
            max_h = int(self.win.winfo_screenheight() * 0.8)
            c.config(width=min(2 * PAD + COLUMNS * cell_w - GAP, max_w),
                     height=min(max(height, 4 * cell_h), max_h))

    def _draw(self, cards, top_y):
        """Cards in rows of 13, numbered from 1, the first row starting at ``top_y``."""
        c = self.canvas
        cell_w, cell_h = CARD_W + GAP, LABEL_H + CARD_H + GAP
        for i, card in enumerate(cards):
            x = PAD + (i % COLUMNS) * cell_w
            y = top_y + (i // COLUMNS) * cell_h
            color = FACE_UP_COLOR if card is not None and card.face_up else "white"
            c.create_text(x + CARD_W / 2, y + LABEL_H / 2, text=str(i + 1), fill=color,
                          font=("TkDefaultFont", 9, "bold"))
            top = y + LABEL_H
            if card is None:
                c.create_rectangle(x + 1, top + 1, x + CARD_W - 1, top + CARD_H - 1,
                                   outline=EMPTY_COLOR, dash=(4, 3))
                c.create_text(x + CARD_W / 2, top + CARD_H / 2, text="empty", fill=EMPTY_COLOR)
                continue
            c.create_image(x, top, image=self._image(card), anchor=tk.NW)
            if card.face_up:
                c.create_rectangle(x - 2, top - 2, x + CARD_W + 2, top + CARD_H + 2,
                                   outline=FACE_UP_COLOR, width=3)


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
