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

SHUFFLE_KINDS = (OUT_FARO, IN_FARO, OVERHAND_RUN, CUT)
KINDS_WITH_X = (OVERHAND_RUN, CUT)


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
    """
    if kind == OVERHAND_RUN:
        return 1, n
    if kind == CUT:
        return 1, n - 1
    raise ValueError(f"{kind!r} does not take an X value")


def check_x(kind, x, n=DECK_SIZE):
    """Raise ValueError unless ``x`` is a valid X for ``kind`` on an n-card deck."""
    if isinstance(x, bool) or not isinstance(x, int):
        raise TypeError(f"X must be an int, got {x!r}")
    lo, hi = x_bounds(kind, n)
    if not lo <= x <= hi:
        name = "overhand run" if kind == OVERHAND_RUN else "cut"
        raise ValueError(f"{name} X must be between {lo} and {hi}, got {x}")


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
    raise ValueError(f"unknown shuffle kind {kind!r}")


def permutation(kind, x=None, n=DECK_SIZE):
    """The whole shuffle as a list: ``perm[i]`` is where position i goes."""
    return [apply(kind, i, x, n) for i in range(n)]
