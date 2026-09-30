"""Toolkit-independent application state behind the window.

Holds the 52 final-deck slots and the ordered shuffle steps, and recomputes
the result on every change so a stale answer is never kept around. It talks
to ``deck`` and ``solver`` through plain data only; there is no shuffle math
here and no Tk, so it is unit-tested directly.
"""

import json
import random
from dataclasses import dataclass, field

from .. import deck, path_finder, solver, stacking, tracking
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


class StepList:
    """Editing of an ordered ``self.steps`` list; subclasses provide ``_changed()``."""

    def _check(self, step, index):
        """Raise ValueError/TypeError unless ``step`` can be done at position ``index``."""
        step.validate(DECK_SIZE)

    def _rebuilt(self, old, x, y):
        """Step ``old`` with a new X and Y."""
        return solver.Step(old.kind, x, y)

    def _inserted(self, index, copy_of=None):
        """A step was inserted at ``index`` (a copy of step ``copy_of``, if given)."""

    def _removed(self, index):
        """Step ``index`` was removed (None: every step was)."""

    def add_step(self, step, index=None):
        index = len(self.steps) if index is None else index
        self._check(step, index)
        self.steps.insert(index, step)
        self._inserted(index)
        self._changed()

    def remove_step(self, index):
        del self.steps[index]
        self._removed(index)
        self._changed()

    def duplicate_step(self, index):
        self.steps.insert(index + 1, self.steps[index])
        self._inserted(index + 1, copy_of=index)
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
        old = self.steps[index]
        # A packet run keeps its Y while it still leaves cards in hand, else runs them all.
        y = old.y if old.y is not None and isinstance(x, int) and old.y < x else None
        step = self._rebuilt(old, x, y)
        self._check(step, index)
        if step != self.steps[index]:
            self.steps[index] = step
            self._changed()

    def set_step_y(self, index, y):
        """Cards run in a packet run; None (or X) runs the whole packet."""
        old = self.steps[index]
        step = self._rebuilt(old, old.x, None if y == old.x else y)
        self._check(step, index)
        if step != self.steps[index]:
            self.steps[index] = step
            self._changed()

    def clear_steps(self):
        self.steps = []
        self._removed(None)
        self._changed()


class AppModel(StepList):
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
            self.set_final_cards(deck.parse_cards(text, allow_indifferent=True))
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
            "steps": [{"kind": s.kind, "x": s.x, **({"y": s.y} if s.y is not None else {})}
                      for s in self.steps],
        }

    def load_dict(self, data):
        if data.get("type") == TRACKER_FILE_TYPE:
            raise ValueError("this is a Free Tracking project, not a Starting Order setup")
        slots = []
        for text in data.get("final", []):
            if text is None:
                slots.append(None)
            else:
                cards = deck.parse_cards(text, allow_indifferent=True)
                if len(cards) != 1:
                    raise ValueError(f"bad card {text!r} in saved file")
                slots.append(cards[0])
        if len(slots) > DECK_SIZE:
            raise ValueError("saved deck has too many cards")
        steps = [solver.Step(s["kind"], s.get("x"), s.get("y")) for s in data.get("steps", [])]
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


def split_cards(step, before):
    """(card above, card below) the split of a step done on the deck ``before``, else None.

    Faros, cuts and packet runs (the packet picked up) split the deck; see
    ``ops.split_point``.

    The first is the bottom card of the upper packet, the face you see when the
    deck is split in the right place; the second is the top card of the rest.
    """
    at = ops.split_point(step.kind, step.x, len(before))
    return None if at is None else (before[at - 1], before[at])


def split_note(step, before):
    """``"split 7♠|K♦"`` for a step that splits (see ``split_cards``), else ``""``."""
    cards = split_cards(step, before)
    return "" if cards is None else f"split {cards[0].pretty()}|{cards[1].pretty()}"


def step_line(k, step, before=None):
    """`` 3. Out-Faro  (split 7♠|K♦)``; the split is left out when ``before`` is None."""
    note = split_note(step, before) if before is not None else ""
    return f"{k:>2}. {step.label()}" + (f"  ({note})" if note else "")


def format_splits(steps, states):
    """One line per step that splits: where to split its deck ("" if none do).

    ``states`` are start, after step 1, ...; step k splits states[k - 1]. A None
    state (a step that isn't done to a single deck) has nothing to split.
    """
    lines = []
    for k, step in enumerate(steps, 1):
        cards = split_cards(step, states[k - 1]) if states[k - 1] is not None else None
        if cards is not None:
            lines.append(f"#{k:<2} {cards[0].pretty():>4} | {cards[1].pretty()}")
    if not lines:
        return ""
    return ("Where to split: the card you should see on the bottom of the upper packet "
            "| the top card of the rest\n" + "\n".join(lines))


def format_preview(states, steps):
    """A fixed-width table: one column per state (start, after each step)."""
    legend = []
    for k, step in enumerate(steps, 1):
        note = split_note(step, states[k - 1])
        legend.append(f"#{k} = {step.label()}" + (f"  ({note})" if note else ""))
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
    status: str  # "waiting", "ok", "failed", or "searching" (best route so far)
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

    Finding a path takes seconds (minutes at depth 7), so it only runs on
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

    def to_dict(self):
        """Both orders and the search depth; a found answer is not kept (search again)."""
        return {"version": 1, "depth": self.depth,
                **{side: [str(c) for c in self.cards[side]] for side in self.SIDES}}

    def load_dict(self, data):
        cards = {side: [_card(t, allow_indifferent=False) for t in data.get(side, [])]
                 for side in self.SIDES}
        self.set_depth(int(data.get("depth", path_finder.SHORTEST_DEPTH)))
        self.cards, self.errors = cards, {side: None for side in self.SIDES}
        self._invalidate()
        self._changed()


def _shuffles(n):
    return f"{n} shuffle{'s' if n != 1 else ''}"


def best_so_far(start, end, steps):
    """A "searching" outcome for a route found while a search is still running."""
    states = solver.intermediate_states(start, steps)
    verified = [c.key for c in states[-1]] == [c.key for c in end]
    msg = (f"Best so far: {_shuffles(len(steps))} (verified). Still looking for a "
           "shorter route; you can use this one or cancel and keep it.")
    if not verified:
        msg = "Check failed: these shuffles do not produce the ending order."
    return PathOutcome("searching", [msg], steps, states, verified)


def cancelled_outcome(best):
    """What to show when a search is cancelled, keeping its best route if it had one."""
    if best is None or not best.verified:
        return PathOutcome("waiting", ["Search cancelled."])
    return PathOutcome("ok", [f"Search cancelled. Best route found: {_shuffles(len(best.steps))}"
                              " (verified); a shorter one may exist."],
                       best.steps, best.states, True)


def search_outcome(start, end, depth, cancel=None, progress=None, improved=None):
    """Search from ``start`` to ``end`` (two full decks) and describe the result.

    Touches no model state, so it can run on a worker thread with copies of
    the cards. Raises path_finder.SearchCancelled when ``cancel()`` returns True.
    ``improved(outcome)`` gets a ``best_so_far`` outcome each time the search
    finds a shorter route before it is done.
    """
    on_route = None if improved is None else (lambda s: improved(best_so_far(start, end, s)))
    found = path_finder.find_path(start, end, deck.PRESETS.values(), depth, cancel, progress,
                                  on_route)
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


def format_instructions(steps, states=None):
    """Numbered steps; with ``states`` (start, after each step, ...) splits are shown."""
    return "\n".join(step_line(k, s, states[k - 1] if states else None)
                     for k, s in enumerate(steps, 1))


# --- free tracking -------------------------------------------------------------------------


class TrackerModel(StepList):
    """A deck entered by hand and the steps done to it, followed pile by pile.

    Nothing is solved here: the cards are simply pushed forward through the
    steps (see ``tracking``). ``states`` is [table at start, after step 1, ...]
    up to the first step that can't be done, whose (index, message) is kept in
    ``problem``; ``states`` is None while there is no usable deck.
    """

    def __init__(self):
        self.cards = []
        self.error = None  # shorthand parse error
        self.steps = []
        self.states = None
        self.problem = None
        self.target_pile = tracking.START_PILE  # the pile new shuffles are done to
        self.groups = []  # of StepGroup, in step order, never overlapping
        self._next_group_id = 1
        self._listeners = []

    def subscribe(self, callback):
        self._listeners.append(callback)

    def _changed(self):
        self._recompute()
        for cb in list(self._listeners):
            cb(self)

    def _recompute(self):
        if self.error is None and not self.deck_problems():
            self.states, self.problem = tracking.replay(self.cards, self.steps)
        else:
            self.states, self.problem = None, None

    # --- the starting deck ---------------------------------------------------------

    def set_cards(self, cards):
        if list(cards) != self.cards or self.error:
            self.cards = list(cards)
            self.error = None
            self._changed()

    def set_from_text(self, text):
        """Parse shorthand into the deck; returns the error message or None."""
        try:
            self.set_cards(deck.parse_cards(text, allow_indifferent=True))
        except ValueError as exc:
            if self.error != str(exc):
                self.error = str(exc)
                self._changed()
            return self.error
        return None

    def load_preset(self, name):
        self.set_cards(deck.PRESETS[name])

    def deck_problems(self):
        """Why the deck can't be tracked (empty list when it can).

        Any number of cards will do, since steps can add and remove them, but
        each card only once (indifferent cards, X, as many as you like).
        """
        if not self.cards:
            return ["No cards yet."]
        dups = deck.validate_deck(self.cards).duplicates
        return ["Duplicated: " + ", ".join(dups)] if dups else []

    # --- steps -------------------------------------------------------------------------

    def table_before(self, index):
        """The table a step at ``index`` is done on, or None if it isn't known."""
        if self.states is None or index >= len(self.states):
            return None
        return self.states[index]

    def _check(self, step, index):
        table = self.table_before(index)
        if table is not None:
            step.apply(table)
        elif isinstance(step, tracking.Shuffle):
            step.step.validate(DECK_SIZE)

    def _rebuilt(self, old, x, y):
        return tracking.Shuffle(solver.Step(old.kind, x, y), old.pile)

    def add_step(self, step, index=None):
        """Add a step; a plain shuffle (``solver.Step``) is done to ``target_pile``."""
        if isinstance(step, solver.Step):
            step = tracking.Shuffle(step, self.target_pile)
        super().add_step(step, index)

    def replace_step(self, index, step):
        """Put ``step`` in place of step ``index`` (e.g. an edited rearrangement)."""
        self._check(step, index)
        if step != self.steps[index]:
            self.steps[index] = step
            self._changed()

    # --- groups ------------------------------------------------------------------------

    def _inserted(self, index, copy_of=None):
        for g in self.groups:
            if g.first < index <= g.last or (copy_of is not None
                                             and g.first <= copy_of <= g.last):
                g.last += 1
            elif index <= g.first:
                g.first += 1
                g.last += 1

    def _removed(self, index):
        if index is None:
            self.groups = []
            return
        for g in self.groups:
            if index < g.first:
                g.first -= 1
                g.last -= 1
            elif index <= g.last:
                g.last -= 1
        self.groups = [g for g in self.groups if g.first <= g.last]

    def add_group(self, first, last, title, color):
        """Group steps ``first``..``last`` (inclusive) under a title and colour."""
        if not 0 <= first <= last < len(self.steps):
            raise ValueError("pick the steps to group first")
        clash = [g for g in self.groups if g.first <= last and first <= g.last]
        if clash:
            raise ValueError(f"those steps overlap the group \"{clash[0].title}\"; "
                             "ungroup it first")
        group = StepGroup(self._next_group_id, title.strip() or "Group", color, first, last)
        self._next_group_id += 1
        self.groups = sorted(self.groups + [group], key=lambda g: g.first)
        self._changed()
        return group

    def edit_group(self, group_id, title, color):
        g = self.group(group_id)
        g.title, g.color = title.strip() or "Group", color
        self._changed()

    def remove_group(self, group_id):
        """Ungroup: the steps stay, only the grouping goes."""
        self.groups = [g for g in self.groups if g.id != group_id]
        self._changed()

    def group(self, group_id):
        return next(g for g in self.groups if g.id == group_id)

    def group_of(self, index):
        """The group step ``index`` belongs to, or None."""
        return next((g for g in self.groups if g.first <= index <= g.last), None)

    # --- tables ------------------------------------------------------------------------

    def piles_at(self, index):
        """Names of the piles a step at ``index`` would find on the table."""
        table = self.table_before(index)
        return table.names if table is not None else [tracking.START_PILE]

    def size_at(self, index, pile=None):
        """How many cards pile ``pile`` (default: ``target_pile``) holds for a step at
        ``index``; None when that isn't known."""
        table = self.table_before(index)
        name = self.target_pile if pile is None else pile
        if table is None or name not in table.names:
            return None
        return len(table.pile(name))

    def step_decks(self):
        """For each step, the cards of the pile it shuffles as they were just before it.

        None for steps that aren't shuffles, and for the step that fails and those after it.
        """
        out = []
        for i, step in enumerate(self.steps):
            table = self.table_before(i)
            ok = (isinstance(step, tracking.Shuffle) and table is not None
                  and self.step_problem(i) is None)
            out.append(list(table.pile(step.pile).cards) if ok else None)
        return out

    def step_problem(self, index):
        """The message for step ``index`` if it is the one that can't be done."""
        return self.problem[1] if self.problem and self.problem[0] == index else None

    def missing_reason(self):
        """What to show in place of a table that can't be worked out."""
        if self.states is None:
            return "Enter a deck on the left (any number of cards, each once)."
        if self.problem:
            return f"Step {self.problem[0] + 1} can't be done: {self.problem[1]}"
        return ""

    def around(self, index=None, last=None):
        """(before title, before table, after title, after table) for step ``index``,
        or for the steps ``index``..``last`` when ``last`` is given.

        With no step picked it is the whole run: the starting table and the
        table after the last step. A table is None when it can't be worked out
        (no deck, or a step on the way can't be done).
        """
        n = len(self.steps)
        if index is None:
            titles = ("Starting order", f"After all {n} step{'s' if n != 1 else ''}"
                      if n else "After the steps (none yet)")
            first, end = 0, n
        elif last is None or last == index:
            label = self.steps[index].label()
            titles = (f"Before #{index + 1}: {label}", f"After #{index + 1}: {label}")
            first, end = index, index + 1
        else:
            span = f"#{index + 1}\u2013#{last + 1}"
            group = self.group_of(index)
            if group is not None and (group.first, group.last) == (index, last):
                span = f"{group.title} ({span})"
            titles = (f"Before {span}", f"After {span}")
            first, end = index, last + 1
        return titles[0], self.table_before(first), titles[1], self.table_before(end)

    # --- persistence -------------------------------------------------------------------

    def to_dict(self):
        """Everything on the tab: the deck, every step, the groups and the shuffle pile."""
        return {
            "type": TRACKER_FILE_TYPE,
            "version": 1,
            "cards": [str(c) for c in self.cards],
            "target_pile": self.target_pile,
            "steps": [_step_to_dict(s) for s in self.steps],
            "groups": [{"title": g.title, "color": g.color, "first": g.first, "last": g.last}
                       for g in self.groups],
        }

    def load_dict(self, data):
        """Replace everything with a saved project; raises ValueError if it isn't one."""
        if data.get("type") != TRACKER_FILE_TYPE:
            raise ValueError("this is not a Free Tracking project")
        cards = [_card(text) for text in data.get("cards", [])]
        steps = [_step_from_dict(s) for s in data.get("steps", [])]
        groups = []
        for i, g in enumerate(data.get("groups", []), 1):
            first, last = int(g["first"]), int(g["last"])
            if not 0 <= first <= last < len(steps):
                raise ValueError(f"group {g.get('title')!r} covers steps that aren't there")
            if groups and first <= groups[-1].last:
                raise ValueError("saved groups overlap")
            groups.append(StepGroup(i, str(g.get("title") or "Group"),
                                    str(g.get("color", "")), first, last))
        self.cards, self.error, self.steps = cards, None, steps
        self.groups, self._next_group_id = groups, len(groups) + 1
        self.target_pile = str(data.get("target_pile") or tracking.START_PILE)
        self._changed()

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    def load(self, path):
        with open(path, encoding="utf-8") as fh:
            self.load_dict(json.load(fh))


TRACKER_FILE_TYPE = "free_tracking"


def _card(text, allow_indifferent=True):
    cards = deck.parse_cards(text, allow_indifferent=allow_indifferent)
    if len(cards) != 1:
        raise ValueError(f"bad card {text!r} in saved file")
    return cards[0]


def _cards_of(texts):
    return tuple(_card(t) for t in texts)


def _step_to_dict(step):
    """A tracking step as plain JSON data (see ``_step_from_dict``)."""
    if isinstance(step, tracking.Shuffle):
        return {"kind": step.kind, "x": step.x, **({"y": step.y} if step.y is not None else {}),
                "pile": step.pile}
    if isinstance(step, tracking.TakeOut):
        return {"kind": step.kind, "cards": [str(c) for c in step.cards], "mode": step.mode}
    if isinstance(step, (tracking.AddCards, tracking.NameCards)):
        return {"kind": step.kind, "cards": [str(c) for c in step.cards], "pile": step.pile,
                "position": step.position}
    if isinstance(step, tracking.Split):
        return {"kind": step.kind, "pile": step.pile, "sizes": list(step.sizes)}
    if isinstance(step, tracking.Place):
        return {"kind": step.kind, "pile": step.pile, "onto": step.onto, "top": step.top}
    if isinstance(step, tracking.Gather):
        return {"kind": step.kind, "names": list(step.names)}
    if isinstance(step, tracking.Rearrange):
        return {"kind": step.kind, "title": step.title,
                "piles": [[name, [str(c) for c in cards]] for name, cards in step.piles]}
    raise TypeError(f"can't save a {type(step).__name__} step")


def _step_from_dict(d):
    kind = d["kind"]
    if kind == "take_out":
        return tracking.TakeOut(_cards_of(d["cards"]), d.get("mode", "pile"))
    if kind == "add_cards":
        return tracking.AddCards(_cards_of(d["cards"]), d.get("pile"), int(d.get("position", 1)))
    if kind == "name_cards":
        return tracking.NameCards(_cards_of(d["cards"]), d.get("pile", tracking.START_PILE),
                                  int(d.get("position", 1)))
    if kind == "split":
        return tracking.Split(d["pile"], tuple(int(s) for s in d["sizes"]))
    if kind == "place":
        return tracking.Place(d["pile"], d["onto"], bool(d.get("top", True)))
    if kind == "gather":
        return tracking.Gather(tuple(d.get("names", ())))
    if kind == "rearrange":
        return tracking.Rearrange(d.get("title", ""),
                                  tuple((name, _cards_of(cards)) for name, cards in d["piles"]))
    step = solver.Step(kind, d.get("x"), d.get("y"))
    step.validate(DECK_SIZE)
    return tracking.Shuffle(step, d.get("pile", tracking.START_PILE))


@dataclass
class StepGroup:
    """A titled, coloured run of steps (``first``..``last``, inclusive), e.g. one trick."""

    id: int
    title: str
    color: str  # a name from theme.GROUP_COLORS
    first: int
    last: int


def format_table(table):
    """Every pile on ``table``: a heading with its size, then its cards in columns."""
    blocks = []
    for pile in table.piles:
        n = len(pile)
        blocks.append(f"Pile {pile.name} — {n} card{'s' if n != 1 else ''}\n"
                      + format_columns(list(pile.cards)))
    return "\n\n".join(blocks) if blocks else "(no cards left on the table)"


def format_columns(cards, rows=13):
    """Numbered cards in columns of ``rows``, top first down each column."""
    cols = [cards[i:i + rows] for i in range(0, len(cards), rows)]
    lines = []
    for r in range(min(rows, len(cards))):
        cells = [f"{c * rows + r + 1:>2} {col[r].pretty():<4}"
                 for c, col in enumerate(cols) if r < len(col)]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


# --- stack trainer ---------------------------------------------------------------------

POSITION_OF, CARD_AT, BEFORE, AFTER = "position_of", "card_at", "before", "after"
_OFFSETS = {BEFORE: -1, AFTER: 1}  # where the answer card sits from the card asked about
QUESTION_KINDS = {  # kind -> label for the choice of what to ask
    POSITION_OF: "Position of a card",
    CARD_AT: "Card at a position",
    BEFORE: "Card before a card",
    AFTER: "Card after a card",
}


@dataclass(frozen=True)
class Question:
    kind: str
    position: int  # 1-based position of the card asked about
    card: deck.Card  # the card at ``position``
    answer: object  # a position (int) or a Card

    def prompt(self):
        if self.kind == POSITION_OF:
            return f"What position is {self.card.pretty()}?"
        if self.kind == CARD_AT:
            return f"Which card is at position {self.position}?"
        where = "before" if self.kind == BEFORE else "after"
        return f"Which card comes {where} {self.card.pretty()}?"

    def answer_text(self):
        return str(self.answer) if self.kind == POSITION_OF else self.answer.pretty()

    def check(self, text):
        """Whether ``text`` answers the question; ValueError if it isn't a position/card."""
        text = text.strip()
        if self.kind == POSITION_OF:
            try:
                return int(text) == self.answer
            except ValueError:
                raise ValueError("type a position, e.g. 12") from None
        cards = deck.parse_cards(text) if text else []
        if len(cards) != 1:
            raise ValueError("type one card, e.g. 7H or 10S")
        return cards[0].key == self.answer.key


@dataclass(frozen=True)
class Outcome:
    question: Question
    given: str  # what was typed; empty for a give-up
    correct: bool


class TrainerModel:
    """Quizzes a stack with random questions about the cards in a range of it.

    The deck is any number of cards, each once. Questions are about the cards at
    positions ``first``..``last`` (1-based, inclusive); a before/after question
    only asks about a card whose neighbour is in the range too. The same card is
    not asked about twice in a row when the range holds another. The session
    score counts every answer and every give-up until it is reset.
    """

    def __init__(self, rng=None):
        self.cards = []
        self.error = None  # shorthand parse error
        self.first, self.last = 1, 0
        self.kinds = set(QUESTION_KINDS)
        self.question = None
        self.last_outcome = None
        self.asked = self.correct = self.streak = self.best_streak = 0
        self._rng = rng or random.Random()
        self._listeners = []

    def subscribe(self, callback):
        self._listeners.append(callback)

    def _changed(self, new_question=True):
        if new_question:
            self.next_question()
        for cb in list(self._listeners):
            cb(self)

    # --- the deck and the range ------------------------------------------------------

    def set_cards(self, cards):
        cards = [c.with_face_up(False) for c in cards]
        if cards == self.cards and not self.error:
            return
        old = len(self.cards)
        self.cards, self.error = cards, None
        # A range over the whole deck follows its length; any other is kept while it fits.
        if self.last in (0, old) or self.last > len(cards):
            self.last = len(cards)
        self.first = min(self.first, max(self.last, 1))
        self._changed()

    def set_from_text(self, text):
        """Parse shorthand into the deck; returns the error message or None."""
        try:
            self.set_cards(deck.parse_cards(text))
        except ValueError as exc:
            if self.error != str(exc):
                self.error = str(exc)
                self._changed()
            return self.error
        return None

    def load_preset(self, name):
        self.set_cards(deck.PRESETS[name])

    def deck_problems(self):
        """Why the deck can't be trained (empty list when it can)."""
        if not self.cards:
            return ["No cards yet."]
        dups = deck.validate_deck(self.cards).duplicates
        return ["Duplicated: " + ", ".join(dups)] if dups else []

    def set_range(self, first, last):
        """Ask about positions ``first``..``last``; ValueError if that isn't in the deck."""
        n = len(self.cards)
        if not n:
            raise ValueError("enter a deck first")
        if not 1 <= first <= last <= n:
            raise ValueError(f"pick positions from 1 to {n}, the first no later than the last")
        if (first, last) != (self.first, self.last):
            self.first, self.last = first, last
            self._changed()

    def whole_deck(self):
        self.set_range(1, len(self.cards))

    def set_kind(self, kind, on):
        if on != (kind in self.kinds):
            (self.kinds.add if on else self.kinds.discard)(kind)
            self._changed()

    # --- questions ---------------------------------------------------------------------

    def _candidates(self, kind):
        """0-based positions a ``kind`` question can ask about."""
        lo, hi = self.first - 1, self.last - 1
        if kind == BEFORE:
            lo += 1
        elif kind == AFTER:
            hi -= 1
        return range(lo, hi + 1)

    def unavailable_reason(self):
        """Why no question can be asked, or None."""
        if self.error:
            return "Fix the deck's shorthand first."
        problems = self.deck_problems()
        if problems:
            return " ".join(problems)
        if not self.kinds:
            return "Pick at least one kind of question."
        if not any(self._candidates(k) for k in self.kinds):
            return "A range of one card has no card before or after it to ask about."
        return None

    def next_question(self):
        """Pick a new random question (None when none can be asked)."""
        if self.unavailable_reason() is not None:
            self.question = None
            return None
        previous = self.question.position if self.question else None
        kinds = sorted(k for k in self.kinds
                       if any(i + 1 != previous for i in self._candidates(k)))
        if not kinds:  # the only card that can be asked about is the one just asked
            kinds = sorted(k for k in self.kinds if self._candidates(k))
        kind = self._rng.choice(kinds)
        spots = [i for i in self._candidates(kind) if i + 1 != previous] \
            or list(self._candidates(kind))
        i = self._rng.choice(spots)
        answer = i + 1 if kind == POSITION_OF else self.cards[i + _OFFSETS.get(kind, 0)]
        self.question = Question(kind, i + 1, self.cards[i], answer)
        return self.question

    def answer(self, text):
        """Score ``text`` as the answer and ask the next question.

        Text that isn't a position or a card counts as a wrong answer. Blank
        text raises ValueError, leaving the question and the score as they were.
        """
        if not text.strip():
            raise ValueError("type an answer first, or press Don't know")
        try:
            correct = self.question.check(text)
        except ValueError:
            correct = False
        return self._score(text, correct)

    def give_up(self):
        """Count the question as missed and ask the next one."""
        return self._score("", False)

    def _score(self, given, correct):
        outcome = Outcome(self.question, given.strip(), correct)
        self.asked += 1
        self.correct += correct
        self.streak = self.streak + 1 if correct else 0
        self.best_streak = max(self.best_streak, self.streak)
        self.last_outcome = outcome
        self._changed()
        return outcome

    @property
    def accuracy(self):
        """Share of questions answered right this session, or None before the first."""
        return self.correct / self.asked if self.asked else None

    def reset_stats(self):
        self.asked = self.correct = self.streak = self.best_streak = 0
        self.last_outcome = None
        self._changed(new_question=False)

    def to_dict(self):
        """The stack, the range and the kinds of question; not the score."""
        return {"version": 1, "cards": [str(c) for c in self.cards],
                "first": self.first, "last": self.last, "kinds": sorted(self.kinds)}

    def load_dict(self, data):
        cards = [_card(t, allow_indifferent=False) for t in data.get("cards", [])]
        first, last = int(data.get("first", 1)), int(data.get("last", len(cards)))
        if cards and not 1 <= first <= last <= len(cards):
            raise ValueError("saved range is outside the stack")
        kinds = set(data.get("kinds", QUESTION_KINDS)) & set(QUESTION_KINDS)
        self.cards = [c.with_face_up(False) for c in cards]
        self.error = None
        self.first, self.last = (first, last) if cards else (1, 0)
        self.kinds = kinds
        self._changed()


# --- stacking -------------------------------------------------------------------------


class StackingModel:
    """The cards wanted in each hand of a poker deal, and the stack that deals them.

    Each hand is typed as shorthand; X (or leaving a hand short) means any card
    will do there. Changing the game or the number of players keeps what was
    typed for every hand, so a hand shown again comes back as it was.
    """

    def __init__(self):
        self.game = stacking.HOLDEM
        self.players = 4
        self.burns = True
        self.fill = False  # fill the indifferent spots with the unused cards
        self.texts = {}  # hand name -> the shorthand typed for it
        self._cards = {}  # hand name -> its parsed cards
        self.errors = {}  # hand name -> why its shorthand doesn't parse
        self.problem = None  # why there is no stack, when every hand parses
        self.stack = None
        self._listeners = []
        self._recompute()

    def subscribe(self, callback):
        self._listeners.append(callback)

    def _changed(self):
        self._recompute()
        for cb in list(self._listeners):
            cb(self)

    # --- edits ------------------------------------------------------------------------

    def set_game(self, game):
        if game not in stacking.GAMES:
            raise ValueError(f"unknown game {game!r}")
        if game != self.game:
            self.game = game
            self._changed()

    def set_players(self, players):
        if not stacking.MIN_PLAYERS <= players <= stacking.MAX_PLAYERS:
            raise ValueError(f"pick {stacking.MIN_PLAYERS} to {stacking.MAX_PLAYERS} players")
        if players != self.players:
            self.players = players
            self._changed()

    def set_burns(self, on):
        if on != self.burns:
            self.burns = on
            self._changed()

    def set_fill(self, on):
        if on != self.fill:
            self.fill = on
            self._changed()

    def set_hand_text(self, name, text):
        """Parse shorthand for one hand; returns the error message or None."""
        if text == self.texts.get(name, "") and name not in self.errors:
            return None
        self.texts[name] = text
        try:
            self._cards[name] = deck.parse_cards(text, allow_indifferent=True)
            self.errors.pop(name, None)
        except ValueError as exc:
            self._cards.pop(name, None)
            self.errors[name] = str(exc)
        self._changed()
        return self.errors.get(name)

    def clear(self):
        self.texts, self._cards, self.errors = {}, {}, {}
        self._changed()

    def to_dict(self):
        """The deal and what was typed for every hand, shown or not."""
        return {"version": 1, "game": self.game, "players": self.players,
                "burns": self.burns, "fill": self.fill,
                "texts": {name: text for name, text in self.texts.items() if text}}

    def load_dict(self, data):
        game = data.get("game", stacking.HOLDEM)
        players = int(data.get("players", 4))
        if game not in stacking.GAMES:
            raise ValueError(f"unknown game {game!r}")
        if not stacking.MIN_PLAYERS <= players <= stacking.MAX_PLAYERS:
            raise ValueError(f"bad player count {players}")
        self.game, self.players = game, players
        self.burns, self.fill = bool(data.get("burns", True)), bool(data.get("fill", False))
        self.texts, self._cards, self.errors = {}, {}, {}
        for name, text in dict(data.get("texts", {})).items():
            self.texts[name] = str(text)
            try:
                self._cards[name] = deck.parse_cards(str(text), allow_indifferent=True)
            except ValueError as exc:
                self.errors[name] = str(exc)
        self._changed()

    # --- the stack --------------------------------------------------------------------

    def hands(self):
        """(name, size) of each hand in the current game."""
        return stacking.hands(self.game, self.players)

    def hand_label(self, name):
        return f"{name} (dealer)" if name == stacking.player_name(self.players) else name

    def _recompute(self):
        self.stack, self.problem = None, None
        names = [name for name, _size in self.hands()]
        broken = [name for name in names if name in self.errors]
        if broken:
            self.problem = "Fix the shorthand for " + ", ".join(broken) + "."
            return
        wanted = {name: self._cards[name] for name in names if self._cards.get(name)}
        try:
            self.stack = stacking.build_stack(self.game, self.players, wanted,
                                              self.burns, self.fill)
        except ValueError as exc:
            self.problem = str(exc)

    def dealt(self):
        """How many cards the deal takes off the top."""
        return len(stacking.layout(self.game, self.players, self.burns))

    def summary(self):
        if self.stack is None:
            return self.problem
        named = sum(not c.indifferent for c in self.stack[:self.dealt()])
        return (f"The deal takes the top {self.dealt()} cards; {named} of them are "
                f"chosen. Deal from the top, one card at a time, starting on the "
                f"dealer's left.")

    def numbered(self):
        """The stack, one card per line with the hand it is dealt to."""
        if self.stack is None:
            return ""
        sizes = dict(self.hands())
        spots = stacking.layout(self.game, self.players, self.burns)
        lines = []
        for n, card in enumerate(self.stack, 1):
            if n <= len(spots):
                spot = spots[n - 1]
                role = self.hand_label(spot.hand)
                if sizes.get(spot.hand, 1) > 1:
                    role += f", card {spot.index + 1}"
            else:
                role = "not dealt"
            lines.append(f"{n:>2}. {card.pretty():<4} {role}")
        return "\n".join(lines)

    def shorthand(self):
        return deck.format_cards(self.stack) if self.stack is not None else ""
