"""The "Open in new tab" button shown next to a deck.

Every deck a tab shows (one it takes or one it works out) can be handed to a
fresh tab of another kind. ``OpenInTabButton`` lists the places a deck can go
(``TARGETS``) and passes the choice and the cards to the app, which opens the
tab; this module knows nothing about the tabs themselves.
"""

from PySide6.QtWidgets import QMenu

from . import dialogs
from .widgets import button

TITLE = "Open in new tab"
TARGETS = {  # key -> menu label, in menu order
    "final": "Starting Order (as final deck)",
    "x": "X to Y (as starting order)",
    "y": "X to Y (as ending order)",
    "tracker": "Free Tracking",
    "trainer": "Stack Trainer",
}


class OpenInTabButton:
    """A menu button that opens a deck in a new tab of the kind picked.

    ``get_cards()`` returns the deck (or raises ValueError saying why there is
    none); ``open_in(target, cards)`` opens the tab, ``target`` being a key of
    ``TARGETS``. ``button`` is placed by the caller; ``text`` is a shorter label
    for a row with little room.
    """

    def __init__(self, parent, get_cards, open_in, text=TITLE):
        self.get_cards, self.open_in = get_cards, open_in
        self.button = button(text)
        self.button.setParent(parent)
        self.button.setProperty("menu", True)
        self.menu = QMenu(self.button)
        for target, label in TARGETS.items():
            self.menu.addAction(label, lambda t=target: self.open(t))
        self.button.setMenu(self.menu)

    def open(self, target):
        """Open the deck in a new tab; returns the tab's content, or None if it couldn't."""
        try:
            cards = list(self.get_cards())
            if not cards:
                raise ValueError("there are no cards to open")
        except ValueError as exc:
            dialogs.error(self.button, TITLE, f"Can't open this in a new tab: {exc}")
            return None
        return self.open_in(target, cards)
