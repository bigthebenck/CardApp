"""A tab strip the user fills: add tabs of any kind, close, rename and reorder them.

``TabManager`` draws its own strip rather than using ``ttk.Notebook``, which
can't hold a close button on each tab or a "+" button after the last one.
Each tab holds a *content* object: anything with a ``frame`` widget, made by
the factory registered for its kind, and optionally a ``close()`` method that
stops pending work before the frame is destroyed. With no tab open, the body
shows one large "New tab" button instead.

Mouse: click a tab to show it, drag it sideways to move it, double-click its
title to rename it, click its × (or middle-click the tab) to close it, and
right-click it for a menu of all of these.
"""

import tkinter as tk
from dataclasses import dataclass, field

import ttkbootstrap as tb

SELECTED, UNSELECTED = "TabSelected", "Tab"  # style prefixes, set up in theme.py


@dataclass
class TabKind:
    title: str  # the default title of a new tab of this kind
    create: object  # create(parent) -> content with a ``frame``


@dataclass(eq=False)
class Tab:
    kind: str
    title: str
    content: object
    header: object = field(default=None, repr=False)
    label: object = field(default=None, repr=False)
    close_label: object = field(default=None, repr=False)
    entry: object = field(default=None, repr=False)  # the rename box, while renaming


class TabManager:
    def __init__(self, parent, kinds, on_change=None):
        """``kinds``: {kind: TabKind}, in the order the "New tab" menu lists them.

        ``on_change()``, if given, runs after tabs are added, closed, renamed,
        moved or selected.
        """
        self.kinds = dict(kinds)
        self.on_change = on_change
        self.tabs = []
        self.current = None
        self._recent = []  # tabs, the most recently shown last
        self._drag = None

        self.frame = tb.Frame(parent)
        self.bar = tb.Frame(self.frame)
        self.strip = tb.Frame(self.bar)
        self.strip.pack(side=tk.LEFT)
        self.add_button = tb.Label(self.bar, text="+", style="TabAdd.TLabel", cursor="hand2")
        self.add_button.pack(side=tk.LEFT, fill=tk.Y)
        self.add_button.bind("<ButtonRelease-1>",
                             lambda e: self.post_new_menu(self.add_button))
        self.body = tb.Frame(self.frame, padding=(0, 6, 0, 0))
        self.body.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)

        self.new_menu = tb.Menu(self.frame, tearoff=False)
        for kind, spec in self.kinds.items():
            self.new_menu.add_command(label=spec.title, command=lambda k=kind: self.add(k))
        self.tab_menu = tb.Menu(self.frame, tearoff=False)
        self._build_empty()
        self._show_body()

    def _build_empty(self):
        self.empty = tb.Frame(self.body)
        inner = tb.Frame(self.empty)
        inner.place(relx=0.5, rely=0.45, anchor=tk.CENTER)
        tb.Label(inner, text="No tabs open", font=("TkDefaultFont", 16)).pack()
        self.empty_button = tb.Button(inner, text="+  New tab", style="Big.TButton",
                                      command=lambda: self.post_new_menu(self.empty_button))
        self.empty_button.pack(pady=16)
        tb.Label(inner, text="Pick what the tab is for: "
                 + ", ".join(spec.title for spec in self.kinds.values()) + ".",
                 style="Muted.TLabel").pack()
        tb.Label(inner, text="Ctrl+T opens a new tab, Ctrl+W closes one.",
                 style="Muted.TLabel").pack()

    # --- tabs -------------------------------------------------------------------------

    def add(self, kind, title=None, select=True):
        """Open a new tab of ``kind`` after the last one; returns its ``Tab``."""
        spec = self.kinds[kind]
        content = spec.create(self.body)
        tab = Tab(kind, title or self._unused_title(spec.title), content)
        self._build_header(tab)
        self.tabs.append(tab)
        self._pack_headers()
        if select or self.current is None:
            self.select(tab)
        else:
            self._changed()
        return tab

    def _unused_title(self, base):
        """``base``, or ``base 2``, ``base 3``, ... if another tab already has it."""
        used = {t.title for t in self.tabs}
        n = 1
        while (title := base if n == 1 else f"{base} {n}") in used:
            n += 1
        return title

    def select(self, tab):
        if tab is self.current:
            return
        if self.current is not None:
            self.current.content.frame.pack_forget()
        self.current = tab
        if tab in self._recent:
            self._recent.remove(tab)
        self._recent.append(tab)
        tab.content.frame.pack(fill=tk.BOTH, expand=True)
        self._style_headers()
        self._show_body()
        self._changed()

    def close(self, tab):
        """Close ``tab``; the one to its right (else its left) is shown instead."""
        if tab not in self.tabs:
            return
        index = self.tabs.index(tab)
        self.tabs.remove(tab)
        self._recent.remove(tab)
        if tab is self.current:
            self.current = None
            if self.tabs:
                self.select(self.tabs[min(index, len(self.tabs) - 1)])
        close = getattr(tab.content, "close", None)
        if close is not None:
            close()
        tab.header.destroy()
        tab.content.frame.destroy()
        self._show_body()
        self._changed()

    def close_others(self, keep):
        for tab in [t for t in self.tabs if t is not keep]:
            self.close(tab)

    def move(self, tab, index):
        """Put ``tab`` at ``index`` in the strip (clamped to the ends)."""
        index = max(0, min(index, len(self.tabs) - 1))
        if self.tabs.index(tab) == index:
            return
        self.tabs.remove(tab)
        self.tabs.insert(index, tab)
        self._pack_headers()
        self._changed()

    def rename(self, tab, title):
        """Give ``tab`` a new title; a blank one is ignored. Returns whether it changed."""
        title = title.strip()
        if not title or title == tab.title:
            return False
        tab.title = title
        tab.label.config(text=title)
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

    def _changed(self):
        if self.on_change is not None:
            self.on_change()

    # --- drawing ----------------------------------------------------------------------

    def _build_header(self, tab):
        tab.header = tb.Frame(self.strip, style=f"{UNSELECTED}.TFrame")
        tab.label = tb.Label(tab.header, text=tab.title, padding=(10, 5, 4, 5),
                             style=f"{UNSELECTED}.TLabel")
        tab.label.pack(side=tk.LEFT)
        tab.close_label = tb.Label(tab.header, text="×", padding=(5, 2), cursor="hand2",
                                   font=("TkDefaultFont", 11), style=f"{UNSELECTED}.TLabel")
        tab.close_label.pack(side=tk.LEFT, padx=(0, 4))
        tab.close_label.bind("<ButtonRelease-1>", lambda e: self._close_clicked(tab, e))
        tab.close_label.bind("<Enter>", lambda e: tab.close_label.config(
            style="TabClose.TLabel"))
        tab.close_label.bind("<Leave>", lambda e: self._style_header(tab))
        middle, right = ("<Button-3>", "<Button-2>") if self._is_aqua() else (
            "<Button-2>", "<Button-3>")
        for widget in (tab.header, tab.label):
            widget.bind("<ButtonPress-1>", lambda e: self._press(tab))
            widget.bind("<B1-Motion>", lambda e: self._drag_to(tab, e.x_root))
            widget.bind("<ButtonRelease-1>", lambda e: self._release())
            widget.bind("<Double-Button-1>", lambda e: self.start_rename(tab))
            widget.bind(middle, lambda e: self.close(tab))
            widget.bind(right, lambda e: self._post_tab_menu(tab, e))

    def _is_aqua(self):
        return self.frame.tk.call("tk", "windowingsystem") == "aqua"

    def _pack_headers(self):
        for tab in self.tabs:
            tab.header.pack_forget()
        for tab in self.tabs:
            tab.header.pack(side=tk.LEFT, padx=(0, 2))

    def _style_headers(self):
        for tab in self.tabs:
            self._style_header(tab)

    def _style_header(self, tab):
        prefix = SELECTED if tab is self.current else UNSELECTED
        tab.header.config(style=f"{prefix}.TFrame")
        tab.label.config(style=f"{prefix}.TLabel")
        tab.close_label.config(style=f"{prefix}.TLabel")

    def _show_body(self):
        """The strip and the current tab, or the "New tab" button when none is open."""
        if self.tabs:
            self.empty.pack_forget()
            if not self.bar.winfo_manager():
                self.bar.pack(side=tk.TOP, fill=tk.X, before=self.body)
        else:
            self.bar.pack_forget()
            self.empty.pack(fill=tk.BOTH, expand=True)

    # --- mouse ------------------------------------------------------------------------

    def _close_clicked(self, tab, event):
        # Like a button: only if the mouse is still on the × when released.
        w = tab.close_label
        if 0 <= event.x < w.winfo_width() and 0 <= event.y < w.winfo_height():
            self.close(tab)

    def _press(self, tab):
        self.select(tab)
        self._drag = tab

    def _drag_to(self, tab, x_root):
        """Move the dragged tab past a neighbour once the mouse crosses its middle."""
        if self._drag is not tab or tab.entry is not None:
            return
        tab.header.config(cursor="sb_h_double_arrow")
        tab.label.config(cursor="sb_h_double_arrow")
        while True:
            i = self.tabs.index(tab)
            if i + 1 < len(self.tabs) and x_root > self._middle(self.tabs[i + 1]):
                self.move(tab, i + 1)
            elif i > 0 and x_root < self._middle(self.tabs[i - 1]):
                self.move(tab, i - 1)
            else:
                return
            self.strip.update_idletasks()

    @staticmethod
    def _middle(tab):
        return tab.header.winfo_rootx() + tab.header.winfo_width() / 2

    def _release(self):
        if self._drag is not None and self._drag.header.winfo_exists():
            self._drag.header.config(cursor="")
            self._drag.label.config(cursor="")
        self._drag = None

    # --- menus ------------------------------------------------------------------------

    def post_new_menu(self, anchor=None):
        """Show the list of tab kinds under ``anchor`` (a widget), or under the "+"."""
        if anchor is None:
            anchor = self.add_button if self.tabs else self.empty_button
        anchor.update_idletasks()
        self.new_menu.tk_popup(anchor.winfo_rootx(),
                               anchor.winfo_rooty() + anchor.winfo_height())

    def _post_tab_menu(self, tab, event):
        m = self.tab_menu
        m.delete(0, tk.END)
        i = self.tabs.index(tab)
        m.add_command(label="Rename…", command=lambda: self.start_rename(tab))
        m.add_command(label="Move left", command=lambda: self.move(tab, i - 1),
                      state=tk.NORMAL if i > 0 else tk.DISABLED)
        m.add_command(label="Move right", command=lambda: self.move(tab, i + 1),
                      state=tk.NORMAL if i < len(self.tabs) - 1 else tk.DISABLED)
        m.add_separator()
        m.add_command(label="Close", command=lambda: self.close(tab), accelerator="Ctrl+W")
        m.add_command(label="Close other tabs", command=lambda: self.close_others(tab),
                      state=tk.NORMAL if len(self.tabs) > 1 else tk.DISABLED)
        m.tk_popup(event.x_root, event.y_root)

    # --- renaming in place ------------------------------------------------------------

    def start_rename(self, tab):
        """Swap the tab's title for a box: Enter or clicking away keeps, Escape cancels."""
        if tab.entry is not None or tab not in self.tabs:
            return
        self.select(tab)
        var = tk.StringVar(value=tab.title)
        tab.entry = tb.Entry(tab.header, textvariable=var, width=max(len(tab.title) + 2, 10))
        tab.entry.var = var
        tab.label.pack_forget()
        tab.entry.pack(side=tk.LEFT, padx=(4, 0), pady=2, before=tab.close_label)
        tab.entry.select_range(0, tk.END)
        tab.entry.icursor(tk.END)
        tab.entry.focus_set()
        tab.entry.bind("<Return>", lambda e: self.finish_rename(tab))
        tab.entry.bind("<KP_Enter>", lambda e: self.finish_rename(tab))
        tab.entry.bind("<FocusOut>", lambda e: self.finish_rename(tab))
        tab.entry.bind("<Escape>", lambda e: self.finish_rename(tab, keep=False))
        return tab.entry

    def finish_rename(self, tab, keep=True):
        entry = tab.entry
        if entry is None:
            return
        tab.entry = None  # first, so the FocusOut from destroying the box does nothing
        title = entry.var.get()
        entry.destroy()
        tab.label.pack(side=tk.LEFT, before=tab.close_label)
        if keep:
            self.rename(tab, title)
