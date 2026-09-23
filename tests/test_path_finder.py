import random

import pytest

from shuffle_solver import deck, path_finder
from shuffle_solver import shuffle_ops as ops
from shuffle_solver.solver import Step, simulate

NDO = deck.PRESETS["New deck order"]
OUT = Step(ops.OUT_FARO)
IN = Step(ops.IN_FARO)


def keys(cards):
    return [c.key for c in cards]


def check(start, end):
    result = path_finder.find_path(start, end)
    assert keys(simulate(start, result.steps)) == keys(end)
    return result


def test_same_order_needs_nothing():
    result = check(NDO, NDO)
    assert result.steps == [] and result.shortest


def test_face_up_flags_are_ignored():
    flipped = [c.with_face_up(True) for c in NDO]
    assert check(NDO, flipped).steps == []


@pytest.mark.parametrize("seq", [
    [OUT],
    [IN, IN],
    [Step(ops.CUT, 17), IN, Step(ops.OVERHAND_RUN, 9), OUT],
    [OUT, Step(ops.CUT, 5), IN, Step(ops.OVERHAND_RUN, 30), OUT],
])
def test_short_sequences_found_at_most_as_long(seq):
    result = check(NDO, simulate(NDO, seq))
    assert len(result.steps) <= len(seq)
    assert result.shortest == (len(seq) <= path_finder.SHORTEST_DEPTH)


def test_eight_out_faros_is_identity():
    assert check(NDO, simulate(NDO, [OUT] * 8)).steps == []


def test_single_reverse_is_one_step():
    # An overhand run of 51 or 52 both reverse the deck.
    assert len(check(NDO, NDO[::-1]).steps) == 1


@pytest.mark.parametrize("name", list(deck.PRESETS))
def test_every_preset_reachable(name):
    check(NDO, deck.PRESETS[name])


def test_random_orders_reachable_with_valid_steps():
    rng = random.Random(7)
    for _ in range(3):
        a, b = NDO[:], NDO[:]
        rng.shuffle(a)
        rng.shuffle(b)
        result = check(a, b)
        assert not result.shortest
        for step in result.steps:
            step.validate()
        assert len(result.steps) < 2 * len(NDO)


def test_constructive_methods_sort_directly():
    rng = random.Random(3)
    v = list(range(52))
    rng.shuffle(v)
    for method in (path_finder._greedy_reversals, path_finder._selection):
        assert simulate(v, method(v)) == list(range(52))


PREP = deck.PRESETS["Mnemonica prep (A-KC, A-KD, K-AH, K-AS)"]
MNEMONICA = deck.PRESETS["Mnemonica (Tamariz)"]


def test_tamariz_recipe_found_from_prep():
    recipe = [OUT] * 4 + [Step(ops.OVERHAND_RUN, 26), Step(ops.PARTIAL_OUT_FARO, 18),
                          Step(ops.CUT, 9)]
    assert keys(simulate(PREP, recipe)) == keys(MNEMONICA)
    assert len(check(PREP, MNEMONICA).steps) <= len(recipe)


def test_partial_faro_found_in_short_search():
    seq = [Step(ops.PARTIAL_IN_FARO, 13), Step(ops.CUT, 20)]
    result = check(NDO, simulate(NDO, seq))
    assert result.shortest and len(result.steps) == 2


def test_bottom_partial_faros_found_in_short_search():
    seq = [Step(ops.PARTIAL_OUT_FARO_BOTTOM_BOTTOM, 9), Step(ops.PARTIAL_IN_FARO_BOTTOM_TOP, 20),
           Step(ops.PARTIAL_OUT_FARO_TOP_BOTTOM, 14)]
    result = check(NDO, simulate(NDO, seq))
    assert result.shortest and len(result.steps) <= 3


def test_all_steps_are_distinct_shuffles():
    perms = [tuple(ops.permutation(s.kind, s.x)) for s in path_finder.all_steps()]
    assert len(perms) == len(set(perms))
    assert Step(ops.PARTIAL_OUT_FARO_TOP_BOTTOM, 1) not in path_finder.all_steps()  # = cut 1


def test_stepping_stone_shortens_route():
    without = check(NDO, MNEMONICA)
    result = path_finder.find_path(NDO, MNEMONICA, [PREP])
    assert keys(simulate(NDO, result.steps)) == keys(MNEMONICA)
    assert len(result.steps) <= 11 < len(without.steps)


def test_mismatched_cards_rejected():
    other = NDO[:-1] + [NDO[0]]
    with pytest.raises(ValueError, match="same cards"):
        path_finder.find_path(NDO, other)


def test_depth_limits_what_counts_as_shortest():
    seq = [Step(ops.OUT_FARO), Step(ops.CUT, 10), Step(ops.OVERHAND_RUN, 7)]
    end = simulate(NDO, seq)
    for depth in (1, 2):
        result = path_finder.find_path(NDO, end, depth=depth)
        assert keys(simulate(NDO, result.steps)) == keys(end) and not result.shortest
    result = path_finder.find_path(NDO, end, depth=3)
    assert result.shortest and len(result.steps) == 3


@pytest.mark.parametrize("depth", [0, path_finder.MAX_DEPTH + 1])
def test_depth_out_of_range(depth):
    with pytest.raises(ValueError, match="search depth"):
        path_finder.find_path(NDO, NDO, depth=depth)


def test_progress_reported_and_cancel_raises():
    calls = []
    end = random.Random(4).sample(NDO, len(NDO))
    with pytest.raises(path_finder.SearchCancelled):
        path_finder.find_path(NDO, end, depth=6, cancel=lambda: len(calls) >= 3,
                              progress=lambda f, text: calls.append((f, text)))
    assert calls[0] == (None, "Building search tables…")


def test_improved_reports_ever_shorter_routes_while_searching():
    rng = random.Random(11)
    seq = [rng.choice(path_finder.all_steps()) for _ in range(5)]
    end = simulate(NDO, seq)
    seen = []
    result = path_finder.find_path(NDO, end, deck.PRESETS.values(), depth=5,
                                   improved=seen.append)
    lengths = [len(steps) for steps in seen]
    assert len(seen) >= 2  # the fallback first, then the 5-shuffle route
    assert lengths == sorted(set(lengths), reverse=True)
    for steps in seen:
        assert keys(simulate(NDO, steps)) == keys(end)
    assert result.shortest and len(result.steps) == lengths[-1] == 5


def test_improved_not_called_without_slow_layers():
    seen = []
    end = simulate(NDO, [OUT, Step(ops.CUT, 10)])
    path_finder.find_path(NDO, end, depth=4, improved=seen.append)
    assert seen == []
