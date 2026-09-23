"""Popup windows that show a deck order as card images instead of shorthand.

Each shorthand field gets a "View cards" button; the popup it opens stays in
sync with that field until it is closed. Images are the PNGs in
``card_images/`` (see the README there for their source).
"""

import tkinter as tk
from pathlib import Path
from tkinter import ttk

IMAGE_DIR = Path(__file__).with_name("card_images")
CARD_W, CARD_H = 96, 139
COLUMNS = 13
GAP = 6
LABEL_H = 16
PAD = 10
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

        self.summary = ttk.Label(self.win, text="", padding=(PAD, 6, PAD, 0))
        self.summary.pack(anchor=tk.W)
        body = ttk.Frame(self.win)
        body.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(body, highlightthickness=0, background="#1f6b3a")
        sb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.canvas.yview)
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
        """Redraw with ``cards`` (top first); trailing empty slots are dropped."""
        cards = list(cards)
        while cards and cards[-1] is None:
            cards.pop()
        c = self.canvas
        c.delete("all")
        filled = sum(card is not None for card in cards)
        face_up = sum(card is not None and card.face_up for card in cards)
        text = f"{filled} card{'s' if filled != 1 else ''}, top first"
        if face_up:
            text += f"  ·  {face_up} face up (orange outline)"
        self.summary.config(text=text if cards else "No cards to show.")

        cell_w, cell_h = CARD_W + GAP, LABEL_H + CARD_H + GAP
        for i, card in enumerate(cards):
            x = PAD + (i % COLUMNS) * cell_w
            y = PAD + (i // COLUMNS) * cell_h
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

        cols = min(COLUMNS, max(len(cards), 1))
        rows = max((len(cards) + COLUMNS - 1) // COLUMNS, 1)
        width = 2 * PAD + cols * cell_w - GAP
        height = 2 * PAD + rows * cell_h - GAP
        c.config(scrollregion=(0, 0, width, height))
        if not self._sized:  # size to the first contents; the user may resize after
            self._sized = True
            max_w = int(self.win.winfo_screenwidth() * 0.95)
            max_h = int(self.win.winfo_screenheight() * 0.8)
            c.config(width=min(2 * PAD + COLUMNS * cell_w - GAP, max_w),
                     height=min(max(height, 4 * cell_h), max_h))


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
