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
PACKET_RUN = "packet_run"  # overhand run inside the top X cards
CUT = "cut"
PARTIAL_OUT_FARO = "partial_out_faro"  # top packet into the top of the rest
PARTIAL_IN_FARO = "partial_in_faro"
PARTIAL_OUT_FARO_TOP_BOTTOM = "partial_out_faro_top_bottom"  # top packet into the bottom
PARTIAL_IN_FARO_TOP_BOTTOM = "partial_in_faro_top_bottom"
PARTIAL_OUT_FARO_BOTTOM_TOP = "partial_out_faro_bottom_top"  # bottom packet into the top
PARTIAL_IN_FARO_BOTTOM_TOP = "partial_in_faro_bottom_top"
PARTIAL_OUT_FARO_BOTTOM_BOTTOM = "partial_out_faro_bottom_bottom"  # bottom into the bottom
PARTIAL_IN_FARO_BOTTOM_BOTTOM = "partial_in_faro_bottom_bottom"

TOP, BOTTOM = "top", "bottom"
# kind -> (where the packet is cut from, which end of the rest it is woven into, out?)
PARTIAL_FAROS = {
    PARTIAL_OUT_FARO: (TOP, TOP, True),
    PARTIAL_IN_FARO: (TOP, TOP, False),
    PARTIAL_OUT_FARO_TOP_BOTTOM: (TOP, BOTTOM, True),
    PARTIAL_IN_FARO_TOP_BOTTOM: (TOP, BOTTOM, False),
    PARTIAL_OUT_FARO_BOTTOM_TOP: (BOTTOM, TOP, True),
    PARTIAL_IN_FARO_BOTTOM_TOP: (BOTTOM, TOP, False),
    PARTIAL_OUT_FARO_BOTTOM_BOTTOM: (BOTTOM, BOTTOM, True),
    PARTIAL_IN_FARO_BOTTOM_BOTTOM: (BOTTOM, BOTTOM, False),
}


def partial_faro_kind(source, dest, out):
    """The partial faro kind for a (source, dest, out) combination."""
    return next(k for k, v in PARTIAL_FAROS.items() if v == (source, dest, out))


SHUFFLE_KINDS = (OUT_FARO, IN_FARO, OVERHAND_RUN, PACKET_RUN, CUT, *PARTIAL_FAROS)
KINDS_WITH_X = (OVERHAND_RUN, PACKET_RUN, CUT, *PARTIAL_FAROS)
KINDS_WITH_Y = (PACKET_RUN,)

_X_NAMES = {
    OVERHAND_RUN: "overhand run",
    PACKET_RUN: "packet run",
    CUT: "cut",
    **{kind: f"partial {'out' if out else 'in'}-faro"
       + ("" if (source, dest) == (TOP, TOP) else f" ({source} into {dest})")
       for kind, (source, dest, out) in PARTIAL_FAROS.items()},
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
    Packet run: 2..n. A packet of 1 card has nothing to rearrange.
    Cut: 1..n-1. Both X = 0 and X = n leave the deck unchanged.
    Partial faros: X is the packet cut off, which must fit into the rest
    (X <= n/2). An out-faro of 1 packet card woven in at the end it came from
    (top into top, bottom into bottom) changes nothing, so those start at 2.
    """
    if kind == OVERHAND_RUN:
        return 1, n
    if kind == PACKET_RUN:
        return 2, n
    if kind == CUT:
        return 1, n - 1
    if kind in PARTIAL_FAROS:
        source, dest, out = PARTIAL_FAROS[kind]
        return (2 if out and source == dest else 1), n // 2
    raise ValueError(f"{kind!r} does not take an X value")


def check_x(kind, x, n=DECK_SIZE):
    """Raise ValueError unless ``x`` is a valid X for ``kind`` on an n-card deck."""
    if isinstance(x, bool) or not isinstance(x, int):
        raise TypeError(f"X must be an int, got {x!r}")
    lo, hi = x_bounds(kind, n)
    if not lo <= x <= hi:
        raise ValueError(f"{_X_NAMES[kind]} X must be between {lo} and {hi}, got {x}")


def check_y(kind, x, y, n=DECK_SIZE):
    """Raise ValueError unless ``y`` is a valid Y for ``kind`` with this X.

    Only a packet run takes one: the number of cards run, 1..X, or None to run
    them all (the same as Y = X).
    """
    if kind not in KINDS_WITH_Y:
        if y is not None:
            raise ValueError(f"{_X_NAMES.get(kind, kind)} does not take a Y value")
        return
    check_x(kind, x, n)
    if y is None:
        return
    if isinstance(y, bool) or not isinstance(y, int):
        raise TypeError(f"Y must be an int, got {y!r}")
    if not 1 <= y <= x:
        raise ValueError(f"{_X_NAMES[kind]} Y must be between 1 and X ({x}), got {y}")


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


def packet_run(i, x, y=None, n=DECK_SIZE):
    """Pick up the top X cards, run Y of them singly onto the deck, drop the rest on top.

    The run cards land reversed on top of the cards left on the table, and the
    X - Y still in hand go on top of them in their original order. Running all
    X (Y None or X) reverses the top X cards in place. The rest of the deck is
    untouched. It is an overhand run of Y done on just the top X cards.
    """
    check_y(PACKET_RUN, x, y, n)
    _check_position(i, n)
    if i >= x:
        return i
    y = x if y is None else y
    return i - y if i >= y else x - 1 - i


def cut(i, x, n=DECK_SIZE):
    """Move the top X cards to the bottom, both packets keeping their order."""
    check_x(CUT, x, n)
    _check_position(i, n)
    return i - x if i >= x else i + (n - x)


def partial_faro(kind, i, x, n=DECK_SIZE):
    """Cut off X cards from one end and weave them into X cards at one end of the rest.

    The packet comes from the top or bottom of the deck (``source``) and is
    woven into the top or bottom X cards of what is left (``dest``); the rest
    of the deck keeps its order. "Out" keeps the packet's outer card on the
    outside of the deck: its top card on top when woven into the top, its
    bottom card on the bottom when woven into the bottom. "In" tucks that card
    one place inside. Top into top with X = n/2 is a full faro (out or in).
    """
    source, dest, out = PARTIAL_FAROS[kind]
    check_x(kind, x, n)
    _check_position(i, n)
    start = n - x if source == BOTTOM else 0  # first position of the packet
    if start <= i < start + x:
        slot, packet = i - start, True
    else:
        r = i - x if source == TOP else i  # position within the rest (n - x cards)
        if dest == TOP and r >= x:
            return r + x
        if dest == BOTTOM and r < n - 2 * x:
            return r
        slot, packet = (r if dest == TOP else r - (n - 2 * x)), False
    base = 0 if dest == TOP else n - 2 * x
    packet_first = out == (dest == TOP)  # which of each woven pair comes first
    return base + 2 * slot + (0 if packet == packet_first else 1)


def partial_out_faro(i, x, n=DECK_SIZE):
    """Cut off the top X cards and weave them into the top of the rest.

    The packet's top card stays on top: the result starts packet, rest,
    packet, rest, ... for 2X cards, and the rest of the deck is untouched.
    X = n/2 is a full out-faro.
    """
    return partial_faro(PARTIAL_OUT_FARO, i, x, n)


def partial_in_faro(i, x, n=DECK_SIZE):
    """As partial_out_faro, but the packet's top card becomes the second card."""
    return partial_faro(PARTIAL_IN_FARO, i, x, n)


def apply(kind, i, x=None, n=DECK_SIZE, y=None):
    """Dispatch to the position function for ``kind``."""
    if kind == OUT_FARO:
        return out_faro(i, n)
    if kind == IN_FARO:
        return in_faro(i, n)
    if kind == OVERHAND_RUN:
        return overhand_run(i, x, n)
    if kind == PACKET_RUN:
        return packet_run(i, x, y, n)
    if kind == CUT:
        return cut(i, x, n)
    if kind in PARTIAL_FAROS:
        return partial_faro(kind, i, x, n)
    raise ValueError(f"unknown shuffle kind {kind!r}")


def split_point(kind, x=None, n=DECK_SIZE):
    """How many cards are above the split (the upper packet); None if there is no split.

    A full faro splits at n/2. A partial faro splits off its packet: below the
    top X cards when the packet comes from the top, above the bottom X when it
    comes from the bottom. A cut splits below the top X cards, and so does a
    packet run, which picks them up -- unless X is the whole deck, when there
    is nothing to split off.
    """
    if kind == CUT:
        check_x(kind, x, n)
        return x
    if kind == PACKET_RUN:
        check_x(kind, x, n)
        return x if x < n else None
    if kind in (OUT_FARO, IN_FARO):
        _check_faro_deck(n)
        return n // 2
    if kind in PARTIAL_FAROS:
        check_x(kind, x, n)
        return x if PARTIAL_FAROS[kind][0] == TOP else n - x
    return None


def permutation(kind, x=None, n=DECK_SIZE, y=None):
    """The whole shuffle as a list: ``perm[i]`` is where position i goes."""
    return [apply(kind, i, x, n, y) for i in range(n)]
