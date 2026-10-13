"""Deck presets: the built-in stacks plus any the user saves, and the bar that offers them.

``PresetStore`` holds the user's own presets next to ``deck.PRESETS`` and keeps
them in the settings file (see ``theme.read_settings``) as shorthand, one entry
per name, so they survive restarts and can be edited by hand. Every tab with a
deck shows a ``PresetBar``: pick a preset and Load it, Save the tab's deck as a
new preset, or Delete a saved one. All bars share one store, so a preset saved
in one tab shows up in the others straight away.
"""

import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as tb
from ttkbootstrap.dialogs import Querybox

from .. import deck
from . import theme

SETTINGS_KEY = "presets"
TITLE = "Presets"


class PresetStore:
    """The built-in presets (fixed) and the user's saved ones, in that order."""

    def __init__(self, settings_path=None):
        """``settings_path``: where saved presets are kept (None: only in memory)."""
        self.settings_path = settings_path
        self.user = {}  # name -> list of Cards
        saved = theme.read_settings(settings_path).get(SETTINGS_KEY)
        for name, text in (saved.items() if isinstance(saved, dict) else ()):
            try:
                cards = deck.parse_cards(str(text), allow_indifferent=True)
            except ValueError:
                continue  # a preset edited into nonsense by hand is left out
            if cards and name not in deck.PRESETS:
                self.user[str(name)] = cards
        self._listeners = []

    def subscribe(self, callback):
        """``callback(store)`` runs after every save or delete."""
        self._listeners.append(callback)

    def unsubscribe(self, callback):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _changed(self):
        theme.write_settings(self.settings_path, **{
            SETTINGS_KEY: {name: deck.format_cards(cards) for name, cards in self.user.items()}})
        for cb in list(self._listeners):
            cb(self)

    def names(self):
        return list(deck.PRESETS) + list(self.user)

    def is_builtin(self, name):
        return name in deck.PRESETS

    def cards(self, name):
        return list(deck.PRESETS[name] if name in deck.PRESETS else self.user[name])

    def save(self, name, cards):
        """Save ``cards`` as preset ``name``, replacing a saved preset of that name."""
        name = name.strip()
        if not name:
            raise ValueError("give the preset a name")
        if self.is_builtin(name):
            raise ValueError(f"\"{name}\" is a built-in preset; pick another name")
        if not cards:
            raise ValueError("there are no cards to save")
        self.user[name] = list(cards)
        self._changed()
        return name

    def delete(self, name):
        if self.is_builtin(name):
            raise ValueError("built-in presets can't be deleted")
        if self.user.pop(name, None) is not None:
            self._changed()


class PresetBar:
    """A "Preset:" row: a list of presets with Load, Save as… and Delete buttons.

    ``get_cards()`` returns the tab's deck to save (or raises ValueError saying
    why there is none); ``load_cards(cards)`` puts a preset's cards in the tab.
    ``frame`` is packed by the caller, which may add buttons of its own to it.
    """

    def __init__(self, parent, store, get_cards, load_cards, width=20):
        self.store, self.get_cards, self.load_cards = store, get_cards, load_cards
        self.frame = top = tb.Frame(parent)
        tb.Label(top, text="Preset:").pack(side=tk.LEFT)
        self.var = tk.StringVar(value=next(iter(store.names())))
        self.combo = tb.Combobox(top, textvariable=self.var, values=store.names(),
                                 state="readonly", width=width)
        self.combo.pack(side=tk.LEFT, padx=4)
        self.combo.bind("<<ComboboxSelected>>", lambda e: self._update_delete())
        tb.Button(top, text="Load", command=self.load).pack(side=tk.LEFT)
        tb.Button(top, text="Save as…", bootstyle="secondary",
                  command=self.save_as).pack(side=tk.LEFT, padx=(4, 0))
        self.delete_button = tb.Button(top, text="Delete", bootstyle="secondary-outline",
                                       command=self.delete)
        self.delete_button.pack(side=tk.LEFT, padx=(4, 0))
        self._update_delete()
        store.subscribe(self._on_store_changed)
        top.bind("<Destroy>", lambda e: store.unsubscribe(self._on_store_changed))

    def _on_store_changed(self, store):
        self.combo.config(values=store.names())
        if self.var.get() not in store.names():
            self.var.set(next(iter(store.names())))
        self._update_delete()

    def _update_delete(self):
        builtin = self.store.is_builtin(self.var.get())
        self.delete_button.config(state=tk.DISABLED if builtin else tk.NORMAL)

    def load(self):
        try:
            self.load_cards(self.store.cards(self.var.get()))
        except ValueError as exc:
            messagebox.showerror(TITLE, f"Could not load this preset: {exc}", parent=self.frame)

    def save_as(self, name=None):
        """Save the tab's deck as a preset, asking for its name unless ``name`` is given.

        Returns the name saved under, or None if nothing was saved.
        """
        try:
            cards = self.get_cards()
            if not cards:
                raise ValueError("there are no cards to save")
        except ValueError as exc:
            messagebox.showerror(TITLE, f"Can't save a preset: {exc}", parent=self.frame)
            return None
        asked = name is None
        if asked:
            initial = "" if self.store.is_builtin(self.var.get()) else self.var.get()
            name = Querybox.get_string("Name for the new preset:", TITLE, initial,
                                       parent=self.frame)
            if name is None:
                return None
        name = name.strip()
        if asked and name in self.store.user and not messagebox.askyesno(
                TITLE, f"Replace the saved preset \"{name}\"?", parent=self.frame):
            return None
        try:
            name = self.store.save(name, cards)
        except ValueError as exc:
            messagebox.showerror(TITLE, f"Can't save a preset: {exc}", parent=self.frame)
            return None
        self.var.set(name)
        self._update_delete()
        return name

    def delete(self, confirm=True):
        name = self.var.get()
        if self.store.is_builtin(name):
            return
        if confirm and not messagebox.askyesno(TITLE, f"Delete the preset \"{name}\"?",
                                               parent=self.frame):
            return
        self.store.delete(name)
