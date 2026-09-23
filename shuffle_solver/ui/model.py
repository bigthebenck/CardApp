"""Toolkit-independent application state behind the window.

Holds the 52 final-deck slots and the ordered shuffle steps, and recomputes
the result on every change so a stale answer is never kept around. It talks
to ``deck`` and ``solver`` through plain data only; there is no shuffle math
here and no Tk, so it is unit-tested directly.
"""

import json
from dataclasses import dataclass, field

from .. import deck, path_finder, solver
from .. import shuffle_ops as ops

DECK_SIZE = ops.DECK_SIZE


@dataclass(frozen=True)
class Result:
    status: str  # "ok", "empty_sequence", "invalid_deck", "invalid_steps", "failed"
    messages: list = field(default_factory=list)
    start: list | None = None
    states: list | None = None
    verified: bool = False

    @property
    def has_answer(self):
        return self.start is not None


class AppModel:
    def __init__(self):
        self.slots = [None] * DECK_SIZE  # Card or None, position 0 = top
        self.steps = []
        self.input_error = None  # last shorthand parse error, blocks solving
        self.revision = 0
        self.result = None
        self._listeners = []
        self._recompute()

    # --- change notification ---------------------------------------------------

    def subscribe(self, callback):
        """``callback(model)`` runs after every change and recompute."""
        self._listeners.append(callback)

    def _changed(self):
        self.revision += 1
        self._recompute()
        for cb in list(self._listeners):
            cb(self)

    # --- final deck ---------------------------------------------------------------

    def filled_cards(self):
        return [c for c in self.slots if c is not None]

    def deck_report(self):
        return deck.validate_deck(self.filled_cards())

    def duplicate_slots(self):
        """Slot indexes whose card also appears in another slot."""
        dups = set(self.deck_report().duplicates)
        return {i for i, c in enumerate(self.slots) if c is not None and c.key in dups}

    def set_slot(self, index, card):
        if self.slots[index] != card:
            self.slots[index] = card
            self.input_error = None
            self._changed()

    def set_final_cards(self, cards):
        if len(cards) > DECK_SIZE:
            raise ValueError(f"{len(cards)} cards entered; the deck only has {DECK_SIZE} slots.")
        new = list(cards) + [None] * (DECK_SIZE - len(cards))
        if new != self.slots or self.input_error:
            self.slots = new
            self.input_error = None
            self._changed()

    def set_final_from_text(self, text):
        """Parse shorthand into the slots.

        On a parse error the slots are left alone, but the error is recorded
        and the result is invalidated until the text is fixed; the error
        message is returned (None on success).
        """
        try:
            self.set_final_cards(deck.parse_cards(text))
        except ValueError as exc:  # includes ParseError
            if self.input_error != str(exc):
                self.input_error = str(exc)
                self._changed()
            return self.input_error
        return None

    def load_preset(self, name):
        self.set_final_cards(deck.PRESETS[name])

    def clear_final(self):
        self.set_final_cards([])

    def final_text(self, compress=True):
        """Shorthand of the filled slots in order (empty slots are skipped)."""
        return deck.format_cards(self.filled_cards(), compress)

    # --- shuffle sequence ---------------------------------------------------------

    def add_step(self, step, index=None):
        step.validate(DECK_SIZE)
        if index is None:
            self.steps.append(step)
        else:
            self.steps.insert(index, step)
        self._changed()

    def remove_step(self, index):
        del self.steps[index]
        self._changed()

    def duplicate_step(self, index):
        self.steps.insert(index + 1, self.steps[index])
        self._changed()

    def move_step(self, index, delta):
        """Move a step up (delta -1) or down (+1). Returns its new index."""
        new = index + delta
        if not 0 <= new < len(self.steps):
            return index
        self.steps[index], self.steps[new] = self.steps[new], self.steps[index]
        self._changed()
        return new

    def set_step_x(self, index, x):
        step = solver.Step(self.steps[index].kind, x)
        step.validate(DECK_SIZE)
        if step != self.steps[index]:
            self.steps[index] = step
            self._changed()

    def clear_steps(self):
        self.steps = []
        self._changed()

    # --- result ----------------------------------------------------------------------

    def _recompute(self):
        self.result = self._compute()

    def _compute(self):
        if self.input_error:
            return Result("invalid_deck", [f"Shorthand error: {self.input_error}"])
        report = self.deck_report()
        if not report.ok:
            msgs = report.messages()
            empty = self.slots.count(None)
            if empty:
                msgs.insert(0, f"{empty} empty slot{'s' if empty != 1 else ''}.")
            return Result("invalid_deck", msgs)
        try:
            solver.validate_steps(self.steps, DECK_SIZE)
        except (ValueError, TypeError) as exc:
            return Result("invalid_steps", [str(exc)])
        final = list(self.slots)
        res = solver.solve_and_verify(final, self.steps)
        if not res.verified:
            return Result("failed", ["Round-trip check failed: the computed start does not "
                                     "reproduce the final deck."], res.start, res.states, False)
        if not self.steps:
            return Result("empty_sequence", ["No shuffles yet: the starting order is simply "
                                             "the final order."], res.start, res.states, True)
        n = len(self.steps)
        verb = "reproduces" if n == 1 else "reproduce"
        return Result("ok", [f"Verified: {n} shuffle{'s' if n != 1 else ''} {verb} the "
                             "final deck."], res.start, res.states, True)

    # --- persistence -------------------------------------------------------------------

    def to_dict(self):
        return {
            "version": 1,
            "final": [str(c) if c else None for c in self.slots],
            "steps": [{"kind": s.kind, "x": s.x} for s in self.steps],
        }

    def load_dict(self, data):
        slots = []
        for text in data.get("final", []):
            if text is None:
                slots.append(None)
            else:
                cards = deck.parse_cards(text)
                if len(cards) != 1:
                    raise ValueError(f"bad card {text!r} in saved file")
                slots.append(cards[0])
        if len(slots) > DECK_SIZE:
            raise ValueError("saved deck has too many cards")
        steps = [solver.Step(s["kind"], s.get("x")) for s in data.get("steps", [])]
        solver.validate_steps(steps, DECK_SIZE)
        self.slots = slots + [None] * (DECK_SIZE - len(slots))
        self.steps = steps
        self.input_error = None
        self._changed()

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    def load(self, path):
        with open(path, encoding="utf-8") as fh:
            self.load_dict(json.load(fh))


def format_preview(states, steps):
    """A fixed-width table: one column per state (start, after each step)."""
    legend = [f"#{k} = {s.label()}" for k, s in enumerate(steps, 1)]
    headers = ["Start"] + [f"#{k}" for k in range(1, len(steps) + 1)]
    width = 8
    lines = legend + ([""] if legend else [])
    lines.append("Pos  " + "".join(h.ljust(width) for h in headers))
    for pos in range(len(states[0])):
        row = "".join(states[k][pos].pretty().ljust(width) for k in range(len(states)))
        lines.append(f"{pos + 1:>3}  " + row)
    return "\n".join(line.rstrip() for line in lines)


# --- X to Y ------------------------------------------------------------------------------


@dataclass(frozen=True)
class PathOutcome:
    status: str  # "waiting", "ok", "failed"
    messages: list = field(default_factory=list)
    steps: list | None = None
    states: list | None = None  # start, after each step, ..., end
    verified: bool = False
    shortest: bool = False

    @property
    def has_answer(self):
        return self.steps is not None


class XToYModel:
    """Two deck orders and the shuffles found to get from the first to the second.

    Finding a path takes seconds (minutes above depth 5), so it only runs on
    ``solve()``, or ``search()`` on a worker thread; any edit to either order
    clears the old answer.
    """

    SIDES = ("start", "end")

    def __init__(self):
        self.cards = {"start": [], "end": []}
        self.errors = {"start": None, "end": None}  # shorthand parse errors
        self.depth = path_finder.SHORTEST_DEPTH
        self.outcome = None
        self._listeners = []
        self._invalidate()

    def subscribe(self, callback):
        self._listeners.append(callback)

    def _changed(self):
        for cb in list(self._listeners):
            cb(self)

    def _invalidate(self):
        self.outcome = PathOutcome("waiting", self.problems() or ["Press Find shuffles."])

    def set_cards(self, side, cards):
        if list(cards) != self.cards[side] or self.errors[side]:
            self.cards[side] = list(cards)
            self.errors[side] = None
            self._invalidate()
            self._changed()

    def set_from_text(self, side, text):
        """Parse shorthand for one side; returns the error message or None."""
        try:
            self.set_cards(side, deck.parse_cards(text))
        except ValueError as exc:
            if self.errors[side] != str(exc):
                self.errors[side] = str(exc)
                self._invalidate()
                self._changed()
            return self.errors[side]
        return None

    def load_preset(self, side, name):
        self.set_cards(side, deck.PRESETS[name])

    def swap(self):
        self.cards["start"], self.cards["end"] = self.cards["end"], self.cards["start"]
        self.errors["start"], self.errors["end"] = self.errors["end"], self.errors["start"]
        self._invalidate()
        self._changed()

    def report(self, side):
        return deck.validate_deck(self.cards[side])

    def problems(self):
        """Why the orders can't be solved yet (empty list when they can)."""
        out = []
        for side, title in (("start", "Starting order"), ("end", "Ending order")):
            if self.errors[side]:
                out.append(f"{title} shorthand error: {self.errors[side]}")
            elif not self.report(side).ok:
                out.append(f"{title}: " + " ".join(self.report(side).messages()))
        return out

    def solve(self, cancel=None, progress=None):
        """Search now (on this thread) and store the outcome."""
        problems = self.problems()
        if problems:
            return self.set_outcome(PathOutcome("waiting", problems))
        return self.set_outcome(search_outcome(self.cards["start"], self.cards["end"],
                                               self.depth, cancel, progress))

    def set_outcome(self, outcome):
        self.outcome = outcome
        self._changed()
        return outcome

    def set_depth(self, depth):
        """How many shuffles the next search covers exhaustively.

        A shown answer is kept: its message already names the depth it used.
        """
        if not 1 <= depth <= path_finder.MAX_DEPTH:
            raise ValueError(f"search depth must be between 1 and {path_finder.MAX_DEPTH}")
        self.depth = depth


def search_outcome(start, end, depth, cancel=None, progress=None):
    """Search from ``start`` to ``end`` (two full decks) and describe the result.

    Touches no model state, so it can run on a worker thread with copies of
    the cards. Raises path_finder.SearchCancelled when ``cancel()`` returns True.
    """
    found = path_finder.find_path(start, end, deck.PRESETS.values(), depth, cancel, progress)
    states = solver.intermediate_states(start, found.steps)
    verified = [c.key for c in states[-1]] == [c.key for c in end]
    n = len(found.steps)
    if not verified:
        msg = "Check failed: these shuffles do not produce the ending order."
    elif n == 0:
        msg = "The two orders are already the same; no shuffles needed."
    elif found.shortest:
        msg = f"Verified. {n} shuffle{'s' if n != 1 else ''}, the fewest possible."
    else:
        msg = (f"Verified. {n} shuffles. No sequence of {depth} or fewer exists; this "
               "is the shortest route found, not necessarily the shortest possible.")
    return PathOutcome("ok" if verified else "failed", [msg], found.steps, states,
                       verified, found.shortest)


def format_instructions(steps):
    return "\n".join(f"{k:>2}. {s.label()}" for k, s in enumerate(steps, 1))
