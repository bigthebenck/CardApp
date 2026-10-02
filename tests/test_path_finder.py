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


def x_matches(got, want):
    return all(w.indifferent or g.key == w.key for g, w in zip(got, want))


def test_indifferent_target_cards_are_not_tracked():
    end = simulate(NDO, [OUT, Step(ops.CUT, 10), Step(ops.OVERHAND_RUN, 7)])
    loose = [c if c.key in ("AS", "KD") else deck.indifferent_card() for c in end]
    result = path_finder.find_path(NDO, loose, depth=3)
    assert result.shortest and not result.paired
    assert x_matches(simulate(NDO, result.steps), loose) and len(result.steps) <= 3


def test_indifferent_start_cards_stand_for_needed_cards():
    tracked = path_finder.tracked_cards([deck.indifferent_card()] + NDO[1:], NDO)
    assert len(tracked.goals) == 51 and 0 not in tracked.sources and not tracked.paired
    x = deck.indifferent_card()
    assert path_finder.find_path([x] + NDO[1:], NDO).steps == []
    # the X and the ace of clubs must swap roles: the X becomes the ace at the bottom
    result = path_finder.find_path(NDO[1:] + [x], NDO)
    assert simulate(list(range(52)), result.steps)[0] == 51 and result.shortest


def test_indifferent_cards_on_both_sides_are_paired():
    x = deck.indifferent_card()
    start, end = [x] + NDO[1:], NDO[:-1] + [x]
    tracked = path_finder.tracked_cards(start, end)
    assert tracked.paired and None in tracked.keys
    result = path_finder.find_path(start, end, deck.PRESETS.values(), depth=2)
    assert result.paired and not result.shortest and result.steps == []


def test_indifferent_cards_must_cover_the_differences():
    x = deck.indifferent_card()
    assert path_finder.find_path(NDO, [x] * 52).steps == []  # anything will do
    with pytest.raises(ValueError, match="same cards"):
        path_finder.find_path(NDO, [x] * 51)
    with pytest.raises(ValueError, match="same cards"):
        path_finder.tracked_cards(NDO[:-1] + [NDO[0]], [x] * 52)  # duplicate in the start


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


def test_depth_six_finds_shortest_route():
    rng = random.Random(3)
    seq = [rng.choice(path_finder.all_steps()) for _ in range(6)]
    end = simulate(NDO, seq)
    result = path_finder.find_path(NDO, end, depth=6)
    assert keys(simulate(NDO, result.steps)) == keys(end)
    assert result.shortest and len(result.steps) <= 6


def distances(n):
    """The fewest shuffles to reach every order of an n-card deck (breadth-first)."""
    perms = [ops.permutation(s.kind, s.x, n) for s in path_finder.all_steps(n)]
    start = tuple(range(n))
    dist, layer = {start: 0}, [start]
    while layer:
        nxt = []
        for order in layer:
            for perm in perms:
                new = [0] * n
                for i, card in enumerate(order):
                    new[perm[i]] = card
                new = tuple(new)
                if new not in dist:
                    dist[new] = dist[order] + 1
                    nxt.append(new)
        layer = nxt
    return dist


@pytest.mark.parametrize("collide", [False, True])
def test_small_deck_routes_are_shortest_at_every_depth(monkeypatch, collide):
    # One stored layer per side sends even these short routes through the bulk
    # matching, up to four forward layers deep. Keys of a single card make most
    # decks share a key, so every match has to be checked on the whole deck.
    monkeypatch.setattr(path_finder, "STORED_DEPTH", 1)
    if collide:
        monkeypatch.setattr(path_finder, "_sample", lambda n: [0])
    cards = NDO[:8]
    dist = distances(8)
    for order in random.Random(8).sample(sorted(dist), 25):
        end = [cards[i] for i in order]
        for depth in range(1, path_finder.MAX_DEPTH + 1):
            result = path_finder.find_path(cards, end, depth=depth)
            assert keys(simulate(cards, result.steps)) == keys(end)
            if dist[order] <= depth:
                assert result.shortest and len(result.steps) == dist[order]
            else:
                assert not result.shortest


def test_search_uses_packet_run_reversals():
    steps = path_finder.all_steps()
    assert Step(ops.PACKET_RUN, 12) in steps
    assert not any(s.kind == ops.PACKET_RUN and s.y is not None for s in steps)
    end = simulate(NDO, [Step(ops.PACKET_RUN, 12)])
    result = path_finder.find_path(NDO, end, depth=2)
    assert result.steps == [Step(ops.PACKET_RUN, 12)] and result.shortest


def test_packet_run_with_y_reached_in_a_few_shuffles():
    end = simulate(NDO, [Step(ops.PACKET_RUN, 20, 7)])
    result = path_finder.find_path(NDO, end, depth=3)
    assert keys(simulate(NDO, result.steps)) == keys(end)
