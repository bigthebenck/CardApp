"""The "X to Y" tab: enter a starting and an ending order, get the shuffles between them.

All state lives in ``XToYModel``; this module only draws it and forwards user
edits. It contains no shuffle math.
"""

import tkinter as tk
from tkinter import ttk

from .. import deck
from .model import XToYModel, format_instructions, format_preview

TEXT_DEBOUNCE_MS = 400
MONO = ("Courier", 10)

BADGES = {
    "ok": ("PASS", "#1e7b34"),
    "failed": ("FAIL", "#b00020"),
    "waiting": ("WAITING", "#8a6d00"),
}


class XToYTab:
    def __init__(self, parent, model=None):
        self.model = model or XToYModel()
        self.frame = ttk.Frame(parent, padding=6)
        self._jobs = {}
        self._syncing = False
        self._text_source = None  # side whose box is being parsed right now
        self._text_cards = {"start": None, "end": None}  # cards each box last described

        self.texts, self.errors, self.statuses, self.preset_vars = {}, {}, {}, {}
        left = ttk.Frame(self.frame)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._build_order_panel(left, "start", "X. Starting order (top first)")
        mid = ttk.Frame(left)
        mid.pack(fill=tk.X, pady=4)
        ttk.Button(mid, text="⇅ Swap", command=self.swap).pack(side=tk.LEFT)
        ttk.Button(mid, text="Find shuffles ▶", command=self.solve).pack(side=tk.RIGHT)
        self._build_order_panel(left, "end", "Y. Ending order (top first)")
        self._build_result_panel(self.frame).pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                                  padx=(6, 0))

        self.model.subscribe(lambda _m: self.refresh())
        self.refresh()

    # --- setup ----------------------------------------------------------------------

    def _build_order_panel(self, parent, side, title):
        frame = ttk.LabelFrame(parent, text=title, padding=6)
        frame.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(frame)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Preset:").pack(side=tk.LEFT)
        var = tk.StringVar(value=next(iter(deck.PRESETS)))
        self.preset_vars[side] = var
        ttk.Combobox(top, textvariable=var, values=list(deck.PRESETS), state="readonly",
                     width=24).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Load", command=lambda: self.load_preset(side)).pack(side=tk.LEFT)
        ttk.Button(top, text="Clear",
                   command=lambda: self.model.set_cards(side, [])).pack(side=tk.RIGHT)

        ttk.Label(frame, text="Shorthand (e.g.  A-KH, A-KC, K-AD, K-AS):").pack(
            anchor=tk.W, pady=(6, 0))
        text = tk.Text(frame, height=5, width=52, wrap=tk.WORD, font=MONO, undo=True)
        text.pack(fill=tk.BOTH, expand=True)
        text.bind("<<Modified>>", lambda e: self._on_text_modified(side))
        self.texts[side] = text
        self.errors[side] = ttk.Label(frame, text="", style="Error.TLabel", wraplength=440)
        self.errors[side].pack(anchor=tk.W)
        self.statuses[side] = ttk.Label(frame, text="", wraplength=440, justify=tk.LEFT)
        self.statuses[side].pack(anchor=tk.W)

    def _build_result_panel(self, parent):
        frame = ttk.LabelFrame(parent, text="Instructions (do these in order)", padding=6)

        head = ttk.Frame(frame)
        head.pack(fill=tk.X)
        self.badge = tk.Label(head, text="", fg="white", font=("TkDefaultFont", 11, "bold"),
                              padx=10, pady=2)
        self.badge.pack(side=tk.LEFT)
        self.result_msg = ttk.Label(head, text="", wraplength=380, justify=tk.LEFT)
        self.result_msg.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

        body = ttk.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True, pady=6)
        self.steps_text = tk.Text(body, height=18, width=30, font=MONO, state=tk.DISABLED)
        self.steps_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.steps_text.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.steps_text.config(yscrollcommand=sb.set)

        ttk.Button(frame, text="Copy instructions",
                   command=lambda: self._copy(self._instructions())).pack(anchor=tk.W)

        self.preview_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Show step-by-step preview", variable=self.preview_var,
                        command=self._toggle_preview).pack(anchor=tk.W, pady=(6, 0))
        self.preview_frame = ttk.Frame(frame)
        self.preview_text = tk.Text(self.preview_frame, height=14, font=MONO, wrap=tk.NONE,
                                    state=tk.DISABLED)
        xs = ttk.Scrollbar(self.preview_frame, orient=tk.HORIZONTAL,
                           command=self.preview_text.xview)
        ys = ttk.Scrollbar(self.preview_frame, orient=tk.VERTICAL,
                           command=self.preview_text.yview)
        self.preview_text.config(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.preview_text.grid(row=0, column=0, sticky=tk.NSEW)
        ys.grid(row=0, column=1, sticky=tk.NS)
        xs.grid(row=1, column=0, sticky=tk.EW)
        self.preview_frame.rowconfigure(0, weight=1)
        self.preview_frame.columnconfigure(0, weight=1)
        return frame

    # --- events -------------------------------------------------------------------------

    def load_preset(self, side):
        self.model.load_preset(side, self.preset_vars[side].get())

    def swap(self):
        """Swap the two orders, keeping each box's text exactly as typed."""
        self.apply_text()
        raw = {side: self.texts[side].get("1.0", "end-1c") for side in self.model.SIDES}
        self._text_cards = {"start": list(self.model.cards["end"]),
                            "end": list(self.model.cards["start"])}
        self.model.swap()
        self._syncing = True
        for side, other in (("start", "end"), ("end", "start")):
            self.texts[side].delete("1.0", tk.END)
            self.texts[side].insert("1.0", raw[other])
            self.texts[side].edit_modified(False)
        self._syncing = False

    def solve(self):
        self.apply_text()  # don't wait for the debounce if the user typed and clicked
        top = self.frame.winfo_toplevel()
        top.config(cursor="watch")
        top.update_idletasks()
        try:
            self.model.solve()
        finally:
            top.config(cursor="")

    def _on_text_modified(self, side):
        text = self.texts[side]
        if not text.edit_modified():
            return
        text.edit_modified(False)
        if self._syncing:
            return
        if self._jobs.get(side) is not None:
            self.frame.after_cancel(self._jobs[side])
        self._jobs[side] = self.frame.after(TEXT_DEBOUNCE_MS, lambda: self.apply_text(side))

    def apply_text(self, side=None):
        """Parse a box's shorthand into the model now (one side, or both)."""
        for s in (side,) if side else self.model.SIDES:
            if self._jobs.get(s) is not None:
                self.frame.after_cancel(self._jobs[s])
            self._jobs[s] = None
            self._text_source = s
            try:
                self.model.set_from_text(s, self.texts[s].get("1.0", tk.END))
            finally:
                self._text_source = None

    # --- refresh from model -------------------------------------------------------------

    def refresh(self):
        m = self.model
        for side in m.SIDES:
            # Rewrite a box only when its cards changed from somewhere else (preset,
            # swap, clear), so the user's own formatting survives.
            if side == self._text_source:
                self._text_cards[side] = list(m.cards[side])
            elif m.errors[side] is None and m.cards[side] != self._text_cards[side]:
                self._text_cards[side] = list(m.cards[side])
                self._syncing = True
                self.texts[side].delete("1.0", tk.END)
                self.texts[side].insert("1.0", deck.format_cards(m.cards[side]))
                self.texts[side].edit_modified(False)
                self._syncing = False
            self.errors[side].config(text=f"⚠ {m.errors[side]}" if m.errors[side] else "")
            report = m.report(side)
            if report.ok:
                self.statuses[side].config(text="✓ Full 52-card deck, no duplicates.",
                                           foreground="#1e7b34")
            else:
                self.statuses[side].config(text="\n".join(report.messages()),
                                           foreground="#b00020")

        out = m.outcome
        text, color = BADGES[out.status]
        self.badge.config(text=text, bg=color)
        self.result_msg.config(text=" ".join(out.messages))
        self._set_text(self.steps_text, self._instructions() or "")
        self._render_preview()

    def _toggle_preview(self):
        if self.preview_var.get():
            self.preview_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self.preview_frame.pack_forget()
        self._render_preview()

    def _render_preview(self):
        out = self.model.outcome
        if self.preview_var.get() and out.has_answer:
            self._set_text(self.preview_text, format_preview(out.states, out.steps))
        else:
            self._set_text(self.preview_text, "")

    def _instructions(self):
        out = self.model.outcome
        if not (out.has_answer and out.verified):
            return ""
        return format_instructions(out.steps) if out.steps else "(no shuffles needed)"

    @staticmethod
    def _set_text(widget, text):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.config(state=tk.DISABLED)

    def _copy(self, text):
        if text:
            self.frame.clipboard_clear()
            self.frame.clipboard_append(text)
