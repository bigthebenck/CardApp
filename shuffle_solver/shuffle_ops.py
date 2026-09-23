"""Position permutations for each supported shuffle.

Positions are numbered 0 (top of the deck) through n - 1 (bottom). Every
function here answers one question: "the card currently at position i -- where
does it land after this shuffle?" They operate on plain integers and know
nothing about cards, so any deck contents can be pushed through them.
"""

DECK_SIZE = 52

OUT_FARO = "out_faro"
IN_FARO = "in_faro"
OVERHAND_RUN = "overhand_run"
CUT = "cut"
PARTIAL_OUT_FARO = "partial_out_faro"
PARTIAL_IN_FARO = "partial_in_faro"

SHUFFLE_KINDS = (OUT_FARO, IN_FARO, OVERHAND_RUN, CUT, PARTIAL_OUT_FARO, PARTIAL_IN_FARO)
KINDS_WITH_X = (OVERHAND_RUN, CUT, PARTIAL_OUT_FARO, PARTIAL_IN_FARO)

_X_NAMES = {
    OVERHAND_RUN: "overhand run",
    CUT: "cut",
    PARTIAL_OUT_FARO: "partial out-faro",
    PARTIAL_IN_FARO: "partial in-faro",
}


def _check_position(i, n):
    if isinstance(i, bool) or not isinstance(i, int):
        raise TypeError(f"position must be an int, got {i!r}")
    if not 0 <= i < n:
        raise ValueError(f"position {i} is outside 0..{n - 1}")


def _check_faro_deck(n):
    if n <= 0 or n % 2:
        raise ValueError(f"a faro needs a non-empty even-sized deck, got {n}")


def x_bounds(kind, n=DECK_SIZE):
    """Inclusive (min, max) range of X accepted by a shuffle that takes one.

    Overhand run: 1..n. X = 0 peels nothing (a no-op); X = n peels every card,
    which reverses the deck and is a genuine, useful step.
    Cut: 1..n-1. Both X = 0 and X = n leave the deck unchanged.
    Partial faros: X is the packet cut off the top, which must fit into the
    rest (X <= n/2). A partial out-faro of 1 changes nothing, so it starts at 2.
    """
    if kind == OVERHAND_RUN:
        return 1, n
    if kind == CUT:
        return 1, n - 1
    if kind == PARTIAL_OUT_FARO:
        return 2, n // 2
    if kind == PARTIAL_IN_FARO:
        return 1, n // 2
    raise ValueError(f"{kind!r} does not take an X value")


def check_x(kind, x, n=DECK_SIZE):
    """Raise ValueError unless ``x`` is a valid X for ``kind`` on an n-card deck."""
    if isinstance(x, bool) or not isinstance(x, int):
        raise TypeError(f"X must be an int, got {x!r}")
    lo, hi = x_bounds(kind, n)
    if not lo <= x <= hi:
        raise ValueError(f"{_X_NAMES[kind]} X must be between {lo} and {hi}, got {x}")


def out_faro(i, n=DECK_SIZE):
    """Perfect out-faro: top and bottom cards stay put."""
    _check_faro_deck(n)
    _check_position(i, n)
    half = n // 2
    return 2 * i if i < half else 2 * (i - half) + 1


def in_faro(i, n=DECK_SIZE):
    """Perfect in-faro: the original top card becomes the second card."""
    _check_faro_deck(n)
    _check_position(i, n)
    half = n // 2
    return 2 * i + 1 if i < half else 2 * (i - half)


def overhand_run(i, x, n=DECK_SIZE):
    """Run X singles off the top, then drop the remaining block on top of them.

    The untouched block ends up on top in its original order; the X peeled
    cards end up underneath it, reversed.
    """
    check_x(OVERHAND_RUN, x, n)
    _check_position(i, n)
    return i - x if i >= x else n - 1 - i


def cut(i, x, n=DECK_SIZE):
    """Move the top X cards to the bottom, both packets keeping their order."""
    check_x(CUT, x, n)
    _check_position(i, n)
    return i - x if i >= x else i + (n - x)


def partial_out_faro(i, x, n=DECK_SIZE):
    """Cut off the top X cards and weave them into the top of the rest.

    The packet's top card stays on top: the result starts packet, rest,
    packet, rest, ... for 2X cards, and the rest of the deck is untouched.
    X = n/2 is a full out-faro.
    """
    check_x(PARTIAL_OUT_FARO, x, n)
    _check_position(i, n)
    if i < x:
        return 2 * i
    return 2 * (i - x) + 1 if i < 2 * x else i


def partial_in_faro(i, x, n=DECK_SIZE):
    """As partial_out_faro, but the packet's top card becomes the second card."""
    check_x(PARTIAL_IN_FARO, x, n)
    _check_position(i, n)
    if i < x:
        return 2 * i + 1
    return 2 * (i - x) if i < 2 * x else i


def apply(kind, i, x=None, n=DECK_SIZE):
    """Dispatch to the position function for ``kind``."""
    if kind == OUT_FARO:
        return out_faro(i, n)
    if kind == IN_FARO:
        return in_faro(i, n)
    if kind == OVERHAND_RUN:
        return overhand_run(i, x, n)
    if kind == CUT:
        return cut(i, x, n)
    if kind == PARTIAL_OUT_FARO:
        return partial_out_faro(i, x, n)
    if kind == PARTIAL_IN_FARO:
        return partial_in_faro(i, x, n)
    raise ValueError(f"unknown shuffle kind {kind!r}")


def permutation(kind, x=None, n=DECK_SIZE):
    """The whole shuffle as a list: ``perm[i]`` is where position i goes."""
    return [apply(kind, i, x, n) for i in range(n)]
