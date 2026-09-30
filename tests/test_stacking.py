import pytest
from hypothesis import given
from hypothesis import strategies as st

from shuffle_solver import deck, stacking
from shuffle_solver.stacking import FIVE_CARD, HOLDEM, build_stack, deal, layout
from shuffle_solver.ui.model import StackingModel


def cards(text):
    return deck.parse_cards(text, allow_indifferent=True)


def keys(cards_):
    return [c.key for c in cards_]


def test_five_card_deals_round_the_table():
    spots = layout(FIVE_CARD, 3)
    assert len(spots) == 15
    assert [(s.hand, s.index) for s in spots[:4]] == [
        ("Player 1", 0), ("Player 2", 0), ("Player 3", 0), ("Player 1", 1)]
    assert spots[-1] == stacking.Spot("Player 3", 4)


def test_holdem_layout_with_and_without_burns():
    names = [s.hand for s in layout(HOLDEM, 2)]
    assert names == ["Player 1", "Player 2"] * 2 + [
        "Burn", "Flop", "Flop", "Flop", "Burn", "Turn", "Burn", "River"]
    names = [s.hand for s in layout(HOLDEM, 2, burns=False)]
    assert names == ["Player 1", "Player 2"] * 2 + ["Flop"] * 3 + ["Turn", "River"]


def test_hands_lists_players_then_board():
    assert stacking.hands(FIVE_CARD, 2) == [("Player 1", 5), ("Player 2", 5)]
    assert stacking.hands(HOLDEM, 2)[2:] == [("Flop", 3), ("Turn", 1), ("River", 1)]


def test_build_stack_places_each_hand():
    wanted = {"Player 1": cards("AS, AH"), "Player 2": cards("KS, KH"),
              "Flop": cards("AD, 7C, 2H"), "Turn": cards("AC"), "River": cards("KD")}
    stack = build_stack(HOLDEM, 2, wanted)
    assert len(stack) == 52
    assert keys(stack[:13]) == ["AS", "KS", "AH", "KH", "X", "AD", "7C", "2H", "X", "AC",
                                "X", "KD", "X"]
    assert all(c.indifferent for c in stack[12:])
    dealt = deal(stack, HOLDEM, 2)
    for name, want in wanted.items():
        assert keys(dealt[name]) == keys(want)


def test_short_hands_and_x_leave_any_card():
    stack = build_stack(FIVE_CARD, 2, {"Player 2": cards("X, QS")})
    assert keys(deal(stack, FIVE_CARD, 2)["Player 2"]) == ["X", "QS", "X", "X", "X"]


def test_fill_uses_every_card_once():
    stack = build_stack(FIVE_CARD, 4, {"Player 4": cards("A-5S")}, fill=True)
    assert deck.validate_deck(stack).ok and not any(c.indifferent for c in stack)
    assert keys(deal(stack, FIVE_CARD, 4)["Player 4"]) == ["AS", "2S", "3S", "4S", "5S"]
    assert keys(stack[:3]) == ["AH", "2H", "3H"]  # the spare cards, in new deck order


def test_face_up_flag_is_dropped():
    stack = build_stack(FIVE_CARD, 2, {"Player 1": cards("AS`")})
    assert not stack[0].face_up


def test_errors():
    with pytest.raises(ValueError, match="holds 2 cards, not 3"):
        build_stack(HOLDEM, 2, {"Player 1": cards("AS, KS, QS")})
    with pytest.raises(ValueError, match=r"A♠ \(Player 1 and River\)"):
        build_stack(HOLDEM, 2, {"Player 1": cards("AS"), "River": cards("AS")})
    with pytest.raises(ValueError, match=r"twice in Player 1"):
        build_stack(FIVE_CARD, 2, {"Player 1": cards("AS, AS")})
    with pytest.raises(ValueError, match="no hand called"):
        build_stack(FIVE_CARD, 2, {"Flop": cards("AS")})
    with pytest.raises(ValueError, match="players"):
        layout(FIVE_CARD, 11)


@given(st.sampled_from([FIVE_CARD, HOLDEM]), st.integers(2, 10), st.booleans(),
       st.permutations(deck.FULL_DECK_KEYS))
def test_any_full_choice_deals_back(game, players, burns, order):
    pool = iter(deck.Card(k[0], k[1]) for k in order)
    wanted = {name: [next(pool) for _ in range(size)]
              for name, size in stacking.hands(game, players)}
    stack = build_stack(game, players, wanted, burns, fill=True)
    assert deck.validate_deck(stack).ok
    dealt = deal(stack, game, players, burns)
    assert all(dealt[name] == want for name, want in wanted.items())


# --- the model -----------------------------------------------------------------------


def test_model_builds_and_labels_the_stack():
    m = StackingModel()
    m.set_players(3)
    m.set_hand_text("Player 3", "KS, KH")
    m.set_hand_text("River", "AD")
    lines = m.numbered().splitlines()
    assert lines[2] == " 3. K♠   Player 3 (dealer), card 1"
    assert lines[6] == " 7. X    Burn"
    assert lines[13] == "14. A♦   River"
    assert lines[14].endswith("not dealt")
    assert m.summary().startswith("The deal takes the top 14 cards; 3 of them are chosen.")
    assert m.shorthand().startswith("X2, KS, X2, KH, X7, AD")


def test_model_reports_parse_errors_and_duplicates():
    m = StackingModel()
    m.set_hand_text("Flop", "ZZ")
    assert "Flop" in m.errors and m.stack is None
    assert m.problem == "Fix the shorthand for Flop."
    m.set_hand_text("Flop", "AS")
    m.set_hand_text("Turn", "AS")
    assert m.stack is None and "Wanted twice" in m.problem
    m.clear()
    assert m.stack is not None and m.texts == {}


def test_model_keeps_hands_when_they_are_hidden():
    m = StackingModel()
    m.set_hand_text("Player 4", "AS, KS")
    m.set_players(2)
    assert m.stack is not None
    m.set_players(4)
    assert keys(deal(m.stack, HOLDEM, 4)["Player 4"]) == ["AS", "KS"]
    m.set_game(FIVE_CARD)
    assert keys(m.stack[3::4][:2]) == ["AS", "KS"]


def test_model_notifies_and_rejects_bad_settings():
    m = StackingModel()
    seen = []
    m.subscribe(seen.append)
    m.set_burns(False)
    m.set_fill(True)
    assert len(seen) == 2 and not any(c.indifferent for c in m.stack)
    with pytest.raises(ValueError):
        m.set_players(1)
    with pytest.raises(ValueError):
        m.set_game("bridge")
