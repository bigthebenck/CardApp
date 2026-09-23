import pytest

from shuffle_solver import shuffle_ops as ops

N = 52


def deck_after(perm):
    """Apply a position permutation to the deck 0..n-1 (value = starting position)."""
    out = [None] * len(perm)
    for i, dest in enumerate(perm):
        out[dest] = i
    return out


# --- reference implementations, written as a card handler would do them ----

def ref_out_faro(deck):
    top, bottom = deck[: len(deck) // 2], deck[len(deck) // 2 :]
    return [c for pair in zip(top, bottom) for c in pair]


def ref_in_faro(deck):
    top, bottom = deck[: len(deck) // 2], deck[len(deck) // 2 :]
    return [c for pair in zip(bottom, top) for c in pair]


def ref_overhand_run(deck, x):
    pile = []
    for card in deck[:x]:
        pile.insert(0, card)  # each peeled card lands on top of the pile
    return deck[x:] + pile  # the remaining block is dropped on top


def ref_cut(deck, x):
    return deck[x:] + deck[:x]


# --- hand-verified small cases ---------------------------------------------

def test_out_faro_known_order():
    result = deck_after(ops.permutation(ops.OUT_FARO))
    assert result[:6] == [0, 26, 1, 27, 2, 28]
    assert result[-2:] == [25, 51]
    assert result[0] == 0 and result[-1] == 51  # top and bottom stay put


def test_in_faro_known_order():
    result = deck_after(ops.permutation(ops.IN_FARO))
    assert result[:6] == [26, 0, 27, 1, 28, 2]
    assert result[-2:] == [51, 25]
    assert result[1] == 0  # original top card becomes second


def test_out_faro_formula_points():
    assert ops.out_faro(0) == 0
    assert ops.out_faro(25) == 50
    assert ops.out_faro(26) == 1
    assert ops.out_faro(51) == 51


def test_in_faro_formula_points():
    assert ops.in_faro(0) == 1
    assert ops.in_faro(25) == 51
    assert ops.in_faro(26) == 0
    assert ops.in_faro(51) == 50


def test_overhand_run_known_order():
    result = deck_after(ops.permutation(ops.OVERHAND_RUN, 5))
    assert result == list(range(5, 52)) + [4, 3, 2, 1, 0]


def test_cut_known_order():
    result = deck_after(ops.permutation(ops.CUT, 10))
    assert result == list(range(10, 52)) + list(range(10))


# --- agreement with reference simulations ------------------------------------

@pytest.mark.parametrize("n", [2, 4, 10, 52])
def test_faros_match_reference(n):
    deck = list(range(n))
    assert deck_after(ops.permutation(ops.OUT_FARO, n=n)) == ref_out_faro(deck)
    assert deck_after(ops.permutation(ops.IN_FARO, n=n)) == ref_in_faro(deck)


@pytest.mark.parametrize("x", range(1, 53))
def test_overhand_run_matches_reference(x):
    deck = list(range(N))
    assert deck_after(ops.permutation(ops.OVERHAND_RUN, x)) == ref_overhand_run(deck, x)


@pytest.mark.parametrize("x", range(1, 52))
def test_cut_matches_reference(x):
    deck = list(range(N))
    assert deck_after(ops.permutation(ops.CUT, x)) == ref_cut(deck, x)


# --- every shuffle is a bijection ---------------------------------------------

@pytest.mark.parametrize(
    "kind,x",
    [(ops.OUT_FARO, None), (ops.IN_FARO, None)]
    + [(ops.OVERHAND_RUN, x) for x in (1, 5, 26, 51, 52)]
    + [(ops.CUT, x) for x in (1, 10, 26, 51)],
)
def test_permutation_is_bijection(kind, x):
    assert sorted(ops.permutation(kind, x)) == list(range(N))


# --- boundaries and validation -----------------------------------------------

def test_overhand_run_x1_moves_top_card_to_bottom():
    result = deck_after(ops.permutation(ops.OVERHAND_RUN, 1))
    assert result == list(range(1, 52)) + [0]


def test_overhand_run_x51():
    result = deck_after(ops.permutation(ops.OVERHAND_RUN, 51))
    assert result == [51] + list(range(50, -1, -1))


def test_overhand_run_x52_reverses_deck():
    assert deck_after(ops.permutation(ops.OVERHAND_RUN, 52)) == list(range(51, -1, -1))


@pytest.mark.parametrize("x", [0, 53, -1])
def test_overhand_run_rejects_out_of_range_x(x):
    with pytest.raises(ValueError):
        ops.overhand_run(0, x)


@pytest.mark.parametrize("x", [0, 52, 53, -1])
def test_cut_rejects_no_op_and_out_of_range_x(x):
    with pytest.raises(ValueError):
        ops.cut(0, x)


@pytest.mark.parametrize("x", [None, 2.0, "3", True])
def test_x_must_be_int(x):
    with pytest.raises(TypeError):
        ops.overhand_run(0, x)
    with pytest.raises(TypeError):
        ops.cut(0, x)


def test_x_bounds():
    assert ops.x_bounds(ops.OVERHAND_RUN) == (1, 52)
    assert ops.x_bounds(ops.CUT) == (1, 51)
    with pytest.raises(ValueError):
        ops.x_bounds(ops.OUT_FARO)


@pytest.mark.parametrize("fn", [ops.out_faro, ops.in_faro])
def test_faro_rejects_bad_position_and_odd_deck(fn):
    with pytest.raises(ValueError):
        fn(52)
    with pytest.raises(ValueError):
        fn(-1)
    with pytest.raises(ValueError):
        fn(0, n=51)


def test_unknown_kind():
    with pytest.raises(ValueError):
        ops.apply("riffle", 0)


# --- partial faros ----------------------------------------------------------------


def ref_partial_faro(deck, x, out=True):
    packet, rest = deck[:x], deck[x:]
    woven = [c for pair in zip(packet, rest) for c in (pair if out else pair[::-1])]
    return woven + rest[x:]


@pytest.mark.parametrize("x", [2, 5, 18, 25, 26])
def test_partial_out_faro_matches_reference(x):
    deck = list(range(N))
    assert deck_after(ops.permutation(ops.PARTIAL_OUT_FARO, x)) == ref_partial_faro(deck, x)


@pytest.mark.parametrize("x", [1, 5, 18, 26])
def test_partial_in_faro_matches_reference(x):
    deck = list(range(N))
    assert deck_after(ops.permutation(ops.PARTIAL_IN_FARO, x)) == ref_partial_faro(deck, x, False)


def test_partial_faro_of_half_is_full_faro():
    assert ops.permutation(ops.PARTIAL_OUT_FARO, 26) == ops.permutation(ops.OUT_FARO)
    assert ops.permutation(ops.PARTIAL_IN_FARO, 26) == ops.permutation(ops.IN_FARO)


def test_partial_faro_bounds():
    assert ops.x_bounds(ops.PARTIAL_OUT_FARO) == (2, 26)
    assert ops.x_bounds(ops.PARTIAL_IN_FARO) == (1, 26)
    with pytest.raises(ValueError, match="partial out-faro X"):
        ops.partial_out_faro(0, 27)
    with pytest.raises(ValueError):
        ops.partial_in_faro(0, 0)


# --- partial faros from/into either end --------------------------------------------


def ref_partial_any(deck, x, source, dest, out):
    """Cut X off ``source``, weave into X cards at ``dest`` of the rest, by hand."""
    if source == ops.TOP:
        packet, rest = deck[:x], deck[x:]
    else:
        packet, rest = deck[-x:], deck[:-x]
    if dest == ops.TOP:
        region, keep = rest[:x], rest[x:]
        woven = [c for p, r in zip(packet, region) for c in ((p, r) if out else (r, p))]
        return woven + keep
    keep, region = rest[:-x], rest[-x:]
    woven = [c for p, r in zip(packet, region) for c in ((r, p) if out else (p, r))]
    return keep + woven


@pytest.mark.parametrize("kind", list(ops.PARTIAL_FAROS))
def test_every_partial_faro_matches_reference(kind):
    source, dest, out = ops.PARTIAL_FAROS[kind]
    lo, hi = ops.x_bounds(kind)
    deck = list(range(N))
    for x in range(lo, hi + 1):
        assert deck_after(ops.permutation(kind, x)) == ref_partial_any(deck, x, source, dest, out)


def test_partial_faro_small_known_orders():
    deck10 = [ops.permutation(k, 3, 10) for k in (
        ops.PARTIAL_OUT_FARO_TOP_BOTTOM, ops.PARTIAL_IN_FARO_BOTTOM_TOP,
        ops.PARTIAL_OUT_FARO_BOTTOM_BOTTOM)]
    assert [deck_after(p) for p in deck10] == [
        [3, 4, 5, 6, 7, 0, 8, 1, 9, 2],
        [0, 7, 1, 8, 2, 9, 3, 4, 5, 6],
        [0, 1, 2, 3, 4, 7, 5, 8, 6, 9],
    ]


@pytest.mark.parametrize("out", [True, False])
@pytest.mark.parametrize("x", [2, 7, 26])
def test_bottom_into_bottom_is_mirror_of_top_into_top(x, out):
    top = ops.permutation(ops.partial_faro_kind(ops.TOP, ops.TOP, out), x)
    bottom = ops.permutation(ops.partial_faro_kind(ops.BOTTOM, ops.BOTTOM, out), x)
    assert bottom == [N - 1 - top[N - 1 - i] for i in range(N)]


def test_partial_faro_equivalences():
    out_tb = ops.PARTIAL_OUT_FARO_TOP_BOTTOM
    assert ops.permutation(out_tb, 1) == ops.permutation(ops.CUT, 1)
    assert ops.permutation(ops.PARTIAL_OUT_FARO_BOTTOM_TOP, 1) == ops.permutation(ops.CUT, 51)
    assert ops.permutation(ops.PARTIAL_OUT_FARO_BOTTOM_BOTTOM, 26) == ops.permutation(ops.OUT_FARO)
    assert ops.permutation(out_tb, 26) == ops.permutation(ops.IN_FARO)


def test_new_partial_faro_bounds_and_errors():
    assert ops.x_bounds(ops.PARTIAL_OUT_FARO_BOTTOM_BOTTOM) == (2, 26)  # 1 is a no-op
    for kind in (ops.PARTIAL_IN_FARO_BOTTOM_BOTTOM, ops.PARTIAL_OUT_FARO_TOP_BOTTOM,
                 ops.PARTIAL_IN_FARO_TOP_BOTTOM, ops.PARTIAL_OUT_FARO_BOTTOM_TOP,
                 ops.PARTIAL_IN_FARO_BOTTOM_TOP):
        assert ops.x_bounds(kind) == (1, 26)
    with pytest.raises(ValueError, match=r"partial in-faro \(bottom into top\) X"):
        ops.apply(ops.PARTIAL_IN_FARO_BOTTOM_TOP, 0, 27)
    assert ops.partial_faro_kind(ops.TOP, ops.BOTTOM, False) == ops.PARTIAL_IN_FARO_TOP_BOTTOM
