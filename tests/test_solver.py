import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from shuffle_solver import shuffle_ops as ops
from shuffle_solver.solver import (
    Step,
    composed_positions,
    intermediate_states,
    simulate,
    solve,
    solve_and_verify,
    verify,
)

N = 52
DECK = list(range(N))
OUT = Step(ops.OUT_FARO)
IN = Step(ops.IN_FARO)


def run(x):
    return Step(ops.OVERHAND_RUN, x)


def cut(x):
    return Step(ops.CUT, x)


# --- known identities -----------------------------------------------------------

def test_eight_out_faros_restore_order():
    assert simulate(DECK, [OUT] * 8) == DECK
    for k in range(1, 8):
        assert simulate(DECK, [OUT] * k) != DECK


def test_fifty_two_in_faros_restore_order():
    # Verified by direct simulation, one step at a time.
    deck = DECK
    for k in range(1, 53):
        deck = simulate(deck, [IN])
        if k < 52:
            assert deck != DECK
    assert deck == DECK


def test_full_overhand_run_twice_restores_order():
    assert simulate(DECK, [run(52)]) == DECK[::-1]
    assert simulate(DECK, [run(52), run(52)]) == DECK


def test_cut_26_twice_restores_order():
    assert simulate(DECK, [cut(26), cut(26)]) == DECK


def test_two_same_size_cuts_do_not_generally_cancel():
    once = simulate(DECK, [cut(10), cut(10)])
    assert once != DECK
    assert once == simulate(DECK, [cut(20)])  # two cuts of X == one cut of 2X mod 52


@pytest.mark.parametrize("x", [1, 13, 25, 27, 40, 51])
def test_double_cut_composes_to_2x_mod_52(x):
    twice = simulate(DECK, [cut(x), cut(x)])
    two_x = (2 * x) % N
    assert twice == (DECK if two_x == 0 else simulate(DECK, [cut(two_x)]))
    assert twice != DECK


# --- solve -----------------------------------------------------------------------

def test_empty_sequence_start_equals_final():
    final = random.Random(1).sample(DECK, N)
    assert solve(final, []) == final
    result = solve_and_verify(final, [])
    assert result.verified and result.states == [final]


def test_single_out_faro_solution():
    final = list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    start = solve(final, [OUT])
    # Out-faro sends start[0] -> 0, start[26] -> 1, start[1] -> 2 ...
    assert start[0] == final[0]
    assert start[26] == final[1]
    assert start[1] == final[2]
    assert start[51] == final[51]
    assert simulate(start, [OUT]) == final


def test_single_in_faro_solution():
    final = list(range(100, 152))
    start = solve(final, [IN])
    assert start[0] == final[1]
    assert start[26] == final[0]
    assert simulate(start, [IN]) == final


def test_long_alternating_sequence_composition_order():
    steps = [OUT, IN, run(5), OUT, run(20), IN, cut(17), run(52), OUT, cut(3), IN, run(1)]
    final = random.Random(7).sample(DECK, N)
    start = solve(final, steps)
    assert verify(start, final, steps)
    # Walking step by step by hand gives the same answer as composing.
    deck = start
    for step in steps:
        deck = simulate(deck, [step])
    assert deck == final


def test_order_of_steps_matters():
    final = DECK
    a = solve(final, [OUT, run(5)])
    b = solve(final, [run(5), OUT])
    assert a != b
    assert verify(a, final, [OUT, run(5)])
    assert not verify(a, final, [run(5), OUT])


def test_composed_positions_is_permutation():
    pi = composed_positions([OUT, run(9), cut(30), IN])
    assert sorted(pi) == DECK


def test_intermediate_states():
    steps = [OUT, cut(5)]
    states = intermediate_states(DECK, steps)
    assert len(states) == 3
    assert states[0] == DECK
    assert states[1] == simulate(DECK, [OUT])
    assert states[2] == simulate(DECK, steps)


def test_verify_detects_wrong_start():
    steps = [OUT, run(3)]
    final = DECK
    start = solve(final, steps)
    bad = start[:]
    bad[0], bad[1] = bad[1], bad[0]
    assert verify(start, final, steps)
    assert not verify(bad, final, steps)


def test_solve_does_not_mutate_inputs():
    final = DECK[:]
    steps = [OUT, run(4)]
    solve(final, steps)
    assert final == DECK and steps == [OUT, run(4)]


# --- step validation ---------------------------------------------------------------

@pytest.mark.parametrize(
    "step",
    [run(0), run(53), cut(0), cut(52), Step("riffle"), Step(ops.OUT_FARO, 3), Step(ops.CUT)],
)
def test_invalid_steps_rejected(step):
    with pytest.raises((ValueError, TypeError)):
        solve(DECK, [step])


def test_valid_boundary_steps_accepted():
    for step in [run(1), run(51), run(52), cut(1), cut(51)]:
        step.validate()


def test_step_labels():
    assert OUT.label() == "Out-Faro"
    assert IN.label() == "In-Faro"
    assert run(7).label() == "Overhand Run of 7"
    assert cut(12).label() == "Cut 12"
    assert Step(ops.PARTIAL_OUT_FARO, 18).label() == "Partial Out-Faro of top 18 into top"
    assert (Step(ops.PARTIAL_IN_FARO_BOTTOM_TOP, 5).label()
            == "Partial In-Faro of bottom 5 into top")


# --- property-based round trip ----------------------------------------------------

step_strategy = st.one_of(
    st.just(OUT),
    st.just(IN),
    st.integers(1, 52).map(run),
    st.integers(1, 51).map(cut),
    st.tuples(st.sampled_from(list(ops.PARTIAL_FAROS)), st.integers(2, 26)).map(
        lambda kx: Step(*kx)),
)


@settings(max_examples=500, deadline=None)
@given(
    steps=st.lists(step_strategy, max_size=25),
    final=st.permutations(DECK),
)
def test_round_trip_property(steps, final):
    result = solve_and_verify(final, steps)
    assert result.verified
    assert simulate(result.start, steps) == final
    assert sorted(result.start) == DECK
    assert result.states[0] == result.start and result.states[-1] == final
