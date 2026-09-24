import pytest

from shuffle_solver import deck
from shuffle_solver import shuffle_ops as ops
from shuffle_solver.solver import Step, simulate
from shuffle_solver.tracking import (AddCards, Gather, Place, Rearrange, Shuffle, Split, Table,
                                     TakeOut, format_piles, parse_piles, pile_name, replay)

NDO = deck.PRESETS["New deck order"]


def cards(text):
    """Shorthand, with spaces also separating entries."""
    return tuple(deck.parse_cards(", ".join(text.replace(",", " ").split())))


def piles(table):
    return {p.name: list(p.cards) for p in table.piles}


def test_pile_names():
    assert [pile_name(i) for i in (0, 1, 25, 26, 27)] == ["A", "B", "Z", "AA", "AB"]


def test_aces_example_rebuilds_four_packets():
    start = cards("AC AH AS AD, 2-KC, 2-KH, 2-KS, 2-KD")
    steps = [Split("A", (1, 1, 1, 1, 12, 12, 12, 12)),
             Place("E", "A"), Place("F", "B"), Place("G", "C"), Place("H", "D"),
             Gather(("A", "B", "C", "D"))]
    tables, error = replay(start, steps)
    assert error is None
    assert piles(tables[1]) == {"A": [start[0]], "B": [start[1]], "C": [start[2]],
                                "D": [start[3]], "E": list(start[4:16]),
                                "F": list(start[16:28]), "G": list(start[28:40]),
                                "H": list(start[40:52])}
    assert piles(tables[2])["A"] == list(cards("2-KC AC"))
    assert piles(tables[-1]) == {"A": list(cards("2-KC AC 2-KH AH 2-KS AS 2-KD AD"))}


def test_take_out_modes():
    table = Table.start(cards("A-5S"))
    assert piles(TakeOut(cards("4S 2S"), "pile").apply(table)) == {
        "A": list(cards("AS 3S 5S")), "B": list(cards("4S 2S"))}
    assert piles(TakeOut(cards("4S 2S"), "each").apply(table)) == {
        "A": list(cards("AS 3S 5S")), "B": list(cards("4S")), "C": list(cards("2S"))}
    assert piles(TakeOut(cards("4S 2S"), "discard").apply(table)) == {
        "A": list(cards("AS 3S 5S"))}
    with pytest.raises(ValueError, match="not on the table: K♠"):
        TakeOut(cards("KS")).apply(table)
    emptied = TakeOut(cards("A-5S"), "pile").apply(table)
    assert piles(emptied) == {"B": list(cards("A-5S"))}  # an empty pile leaves the table


def test_take_out_keeps_a_face_up_card_face_up():
    table = Table.start(cards("AS 2S` 3S"))
    assert TakeOut(cards("2S")).apply(table).pile("B").cards[0].face_up


def test_add_cards():
    table = Table.start(cards("AS 2S 3S"))
    assert piles(AddCards(cards("KH QH"), "A", 2).apply(table)) == {
        "A": list(cards("AS KH QH 2S 3S"))}
    assert piles(AddCards(cards("KH"), "A", 4).apply(table))["A"][-1] == cards("KH")[0]
    assert piles(AddCards(cards("KH"), None).apply(table))["B"] == list(cards("KH"))
    with pytest.raises(ValueError, match="already in play: 2♠"):
        AddCards(cards("2S")).apply(table)
    with pytest.raises(ValueError, match="between 1 and 4"):
        AddCards(cards("KH"), "A", 5).apply(table)


def test_split_sizes():
    table = Table.start(cards("A-6S"))
    assert piles(Split("A", (2, 1)).apply(table)) == {
        "A": list(cards("AS 2S")), "B": list(cards("3S")), "C": list(cards("4-6S"))}
    for sizes, message in (((7,), "has 6 cards"), ((6,), "one piece"), ((0, 2), "at least 1")):
        with pytest.raises(ValueError, match=message):
            Split("A", sizes).apply(table)


def test_new_piles_sit_next_to_the_split_pile():
    table = Split("A", (1,)).apply(Table.start(cards("A-4S")))  # A, B
    table = Split("A", (1,)).apply(AddCards(cards("KH"), "A", 1).apply(table))
    assert table.names == ["A", "C", "B"]


def test_place_under_and_errors():
    table = Split("A", (2,)).apply(Table.start(cards("A-4S")))
    assert piles(Place("B", "A", top=False).apply(table)) == {"A": list(cards("A-4S"))}
    with pytest.raises(ValueError, match="itself"):
        Place("A", "A").apply(table)
    with pytest.raises(ValueError, match="no pile Z"):
        Place("Z", "A").apply(table)


def test_gather_all_in_table_order():
    table = Split("A", (1, 1)).apply(Table.start(cards("A-4S")))
    assert piles(Gather().apply(table)) == {"A": list(cards("A-4S"))}
    assert piles(Gather(("C", "A")).apply(table)) == {"C": list(cards("3S 4S AS")),
                                                      "B": list(cards("2S"))}


def test_full_faro_needs_an_even_pile_but_partial_faros_do_not():
    table = TakeOut(cards("AS"), "discard").apply(Table.start(NDO))  # 51 cards
    with pytest.raises(ValueError, match="51 cards; a full faro needs an even number"):
        Shuffle(Step(ops.OUT_FARO)).apply(table)
    after = Shuffle(Step(ops.PARTIAL_OUT_FARO, 20)).apply(table)
    assert len(after.pile("A")) == 51
    with pytest.raises(ValueError, match="between 2 and 25"):
        Shuffle(Step(ops.PARTIAL_OUT_FARO, 26)).apply(table)


def test_shuffle_on_another_pile_matches_the_solver():
    table = Split("A", (26,)).apply(Table.start(NDO))
    after = Shuffle(Step(ops.OUT_FARO), "B").apply(table)
    assert list(after.pile("B").cards) == simulate(NDO[26:], [Step(ops.OUT_FARO)])
    assert Shuffle(Step(ops.OUT_FARO), "B").label() == "Out-Faro on pile B"
    assert Shuffle(Step(ops.OUT_FARO)).label() == "Out-Faro"


def test_replay_stops_at_the_first_bad_step():
    steps = [Split("A", (26,)), Place("B", "A"), Place("B", "A"), Gather()]
    tables, error = replay(NDO, steps)
    assert len(tables) == 3 and error == (2, "there is no pile B on the table")


def test_letters_stay_stable_when_an_earlier_step_goes():
    steps = [TakeOut(cards("AS")), Split("A", (10,)), Place("C", "B")]
    assert replay(NDO, steps)[1] is None
    tables, error = replay(NDO, steps[1:])  # without the take-out, the split makes B
    assert error == (1, "there is no pile C on the table")


# --- several piles in shorthand, and rearranging ---------------------------------------


def test_parse_piles_named_unnamed_and_on_new_lines():
    assert parse_piles("A: 2-KC, AC | b: KH") == (("A", cards("2-KC AC")), ("B", cards("KH")))
    assert parse_piles("AH, 2H | 3H") == ((None, cards("AH 2H")), (None, cards("3H")))
    assert parse_piles("A: AH,\n2H\nC: 3H") == (("A", cards("AH 2H")), ("C", cards("3H")))
    assert parse_piles("AH, 2H") == ((None, cards("AH 2H")),)
    for text, message in (("A: AH | 2H", "name every pile"), ("A: AH | A: 2H", "named twice"),
                          ("AH | ", "pile 2 has no cards"), ("", "no cards given"),
                          ("A: AH | B: ZZ", "pile B: ")):
        with pytest.raises(ValueError, match=message):
            parse_piles(text)


def test_format_piles_round_trips():
    table = Split("A", (13,)).apply(Table.start(NDO))
    text = format_piles(table.piles)
    assert text.startswith("A: A-KH |\nB: ")
    assert parse_piles(text) == tuple((p.name, p.cards) for p in table.piles)
    assert format_piles(Table.start(NDO[:3]).piles) == "A-3H"  # a lone pile stays plain
    assert format_piles((("C", cards("AH")),)) == "C: AH"  # ... unless it was typed named


def test_rearrange_to_several_piles():
    table = Table.start(cards("A-4H"))
    step = Rearrange("Card revelations", parse_piles("4H, 3H | 2H, AH`"))
    after = step.apply(table)
    assert piles(after) == {"A": list(cards("4H 3H")), "B": list(cards("2H AH`"))}
    assert after.pile("B").cards[1].face_up  # cards may turn over
    assert step.label() == "Rearrange: Card revelations (2 piles)"
    assert Rearrange("", parse_piles("A-4H")).label() == "Rearrange: new order"
    # the next new pile gets a fresh letter
    assert Split("A", (1,)).apply(after).names == ["A", "C", "B"]


def test_rearrange_unnamed_piles_take_the_table_names_in_order():
    table = Split("A", (1, 1)).apply(Table.start(cards("A-4H")))  # A, B, C
    table = Place("B", "C").apply(table)  # A, C
    after = Rearrange("", parse_piles("4H | 3H, 2H | AH")).apply(table)
    assert after.names == ["A", "C", "D"]
    named = Rearrange("", parse_piles("Z: 4H, 3H, 2H, AH")).apply(table)
    assert named.names == ["Z"] and pile_name(named.next_name) == "AA"


def test_rearrange_must_keep_exactly_the_same_cards():
    table = Table.start(cards("A-4H"))
    with pytest.raises(ValueError, match="missing 3♥ 4♥; not on the table 5♥; given twice 5♥"):
        Rearrange("", parse_piles("AH, 2H, 5H, 5H")).apply(table)
