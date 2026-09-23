"""Compose a shuffle sequence and solve for the starting order.

If a card starting at position m ends at position Pi(m) after the whole
sequence, then the card that must start at m is whatever card is wanted at
Pi(m) in the final deck: ``start[m] = final[Pi(m)]``. No inversion is needed.

Everything here works on plain lists; deck contents can be any objects.
"""

from dataclasses import dataclass

from . import shuffle_ops as ops

_LABELS = {
    ops.OUT_FARO: "Out-Faro",
    ops.IN_FARO: "In-Faro",
    ops.OVERHAND_RUN: "Overhand Run",
    ops.CUT: "Cut",
    ops.PARTIAL_OUT_FARO: "Partial Out-Faro",
    ops.PARTIAL_IN_FARO: "Partial In-Faro",
}


@dataclass(frozen=True)
class Step:
    """One shuffle in the sequence. ``x`` is used by overhand runs and cuts only."""

    kind: str
    x: int | None = None

    def validate(self, n=ops.DECK_SIZE):
        if self.kind not in ops.SHUFFLE_KINDS:
            raise ValueError(f"unknown shuffle kind {self.kind!r}")
        if self.kind in ops.KINDS_WITH_X:
            ops.check_x(self.kind, self.x, n)
        elif self.x is not None:
            raise ValueError(f"{_LABELS[self.kind]} does not take an X value")
        else:
            ops.permutation(self.kind, None, n)  # surfaces odd-deck faro errors

    def label(self):
        if self.kind == ops.OVERHAND_RUN:
            return f"Overhand Run of {self.x}"
        if self.kind == ops.CUT:
            return f"Cut {self.x}"
        if self.kind in (ops.PARTIAL_OUT_FARO, ops.PARTIAL_IN_FARO):
            return f"{_LABELS[self.kind]} of top {self.x}"
        return _LABELS.get(self.kind, self.kind)


def kind_label(kind):
    return _LABELS[kind]


def validate_steps(steps, n=ops.DECK_SIZE):
    for step in steps:
        step.validate(n)


def final_position(m, steps, n=ops.DECK_SIZE):
    """Pi(m): walk a starting position forward through every step in order."""
    for step in steps:
        m = ops.apply(step.kind, m, step.x, n)
    return m


def composed_positions(steps, n=ops.DECK_SIZE):
    """Pi as a list: ``result[m]`` is where the card starting at m finishes."""
    validate_steps(steps, n)
    return [final_position(m, steps, n) for m in range(n)]


def apply_step(deck, step):
    """Forward-simulate a single shuffle on an actual deck (list of anything)."""
    n = len(deck)
    perm = ops.permutation(step.kind, step.x, n)
    out = [None] * n
    for i, card in enumerate(deck):
        out[perm[i]] = card
    return out


def simulate(deck, steps):
    """Forward-simulate the whole sequence; returns the deck after the last step."""
    return intermediate_states(deck, steps)[-1]


def intermediate_states(deck, steps):
    """[start, after step 1, after step 2, ..., final] as separate lists."""
    validate_steps(steps, len(deck))
    states = [list(deck)]
    for step in steps:
        states.append(apply_step(states[-1], step))
    return states


def solve(final, steps):
    """The starting order that becomes ``final`` after performing ``steps``."""
    n = len(final)
    pi = composed_positions(steps, n)
    return [final[pi[m]] for m in range(n)]


def verify(start, final, steps):
    """Round-trip check: does simulating ``steps`` on ``start`` give ``final``?"""
    return len(start) == len(final) and simulate(start, steps) == list(final)


@dataclass(frozen=True)
class SolveResult:
    start: list
    verified: bool
    states: list  # start, after each step, ..., final (by forward simulation)


def solve_and_verify(final, steps):
    """Solve, then forward-simulate the answer to confirm it reproduces ``final``."""
    start = solve(final, steps)
    states = intermediate_states(start, steps)
    return SolveResult(start=start, verified=states[-1] == list(final), states=states)
