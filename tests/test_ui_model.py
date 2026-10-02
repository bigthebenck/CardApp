import random

import pytest

from shuffle_solver import deck, tracking
from shuffle_solver import shuffle_ops as ops
from shuffle_solver.solver import Step, simulate
from shuffle_solver.ui.model import (AFTER, BEFORE, CARD_AT, POSITION_OF, AppModel,
                                     PathOutcome, TrackerModel, TrainerModel, XToYModel,
                                     cancelled_outcome, format_columns, format_instructions,
                                     format_preview, format_table, search_outcome)

NDO = deck.PRESETS["New deck order"]


@pytest.fixture
def model():
    m = AppModel()
    m.load_preset("New deck order")
    return m


def test_starts_waiting_for_deck():
    m = AppModel()
    assert m.result.status == "invalid_deck"
    assert not m.result.has_answer
    assert "52 empty slots." in m.result.messages


def test_empty_sequence_is_valid_and_says_so(model):
    assert model.result.status == "empty_sequence"
    assert model.result.verified
    assert model.result.start == NDO
    assert "simply the final order" in model.result.messages[0]


def test_solves_and_verifies(model):
    model.add_step(Step(ops.OUT_FARO))
    model.add_step(Step(ops.OVERHAND_RUN, 7))
    r = model.result
    assert r.status == "ok" and r.verified
    assert simulate(r.start, model.steps) == NDO


def test_duplicate_card_is_flagged(model):
    model.set_slot(5, deck.Card("A", "H"))  # AH already at slot 0
    assert model.result.status == "invalid_deck"
    assert not model.result.has_answer
    assert model.duplicate_slots() == {0, 5}
    text = " ".join(model.result.messages)
    assert "Duplicated: AH" in text and "Missing: 6H" in text


def test_duplicate_via_shorthand_flagged():
    m = AppModel()
    assert m.set_final_from_text("A-KCHS, A-QD, AC") is None
    assert m.result.status == "invalid_deck"
    assert m.deck_report().duplicates == ["AC"]


def test_reordering_steps_changes_result(model):
    model.add_step(Step(ops.OUT_FARO))
    model.add_step(Step(ops.OVERHAND_RUN, 5))
    before = model.result.start
    assert model.move_step(1, -1) == 0
    assert model.steps == [Step(ops.OVERHAND_RUN, 5), Step(ops.OUT_FARO)]
    after = model.result.start
    assert before != after
    assert simulate(after, model.steps) == NDO


def test_move_step_out_of_bounds_is_noop(model):
    model.add_step(Step(ops.IN_FARO))
    rev = model.revision
    assert model.move_step(0, -1) == 0
    assert model.revision == rev


def test_editing_deck_after_result_recomputes(model):
    model.add_step(Step(ops.OUT_FARO))
    first = model.result.start
    model.load_preset("Aronson stack")
    second = model.result.start
    assert first != second
    assert simulate(second, model.steps) == deck.PRESETS["Aronson stack"]


def test_editing_step_x_recomputes(model):
    model.add_step(Step(ops.CUT, 10))
    first = model.result.start
    model.set_step_x(0, 11)
    assert model.steps[0] == Step(ops.CUT, 11)
    assert model.result.start != first
    assert model.result.verified


def test_invalid_x_rejected(model):
    model.add_step(Step(ops.CUT, 10))
    with pytest.raises(ValueError):
        model.set_step_x(0, 52)
    with pytest.raises(ValueError):
        model.add_step(Step(ops.OVERHAND_RUN, 0))
    assert model.steps == [Step(ops.CUT, 10)]


def test_breaking_the_deck_clears_the_stale_result(model):
    model.add_step(Step(ops.OUT_FARO))
    assert model.result.has_answer
    model.set_slot(51, None)
    assert model.result.status == "invalid_deck"
    assert not model.result.has_answer


def test_shorthand_error_invalidates_result_until_fixed(model):
    model.add_step(Step(ops.OUT_FARO))
    err = model.set_final_from_text("A-KH, A-KC, K-AD, K-AX")
    assert err and "expected a suit letter" in err
    assert model.result.status == "invalid_deck"
    assert not model.result.has_answer
    assert model.slots == NDO  # grid untouched
    assert model.set_final_from_text("A-KH, A-KC, K-AD, K-AS") is None
    assert model.result.status == "ok"


def test_indifferent_cards_in_final_deck():
    m = AppModel()
    assert m.set_final_from_text("AS, X50, KH") is None
    m.add_step(Step(ops.OUT_FARO))
    res = m.result
    assert res.status == "ok" and res.verified
    assert res.start[0] == deck.Card("A", "S") and res.start[-1] == deck.Card("K", "H")
    assert sum(c.indifferent for c in res.start) == 50
    assert m.final_text() == "AS, X50, KH"


def test_indifferent_cards_saved_and_loaded(tmp_path):
    m = AppModel()
    m.set_final_from_text("X10, A-KC, K-AD, K-AS, X3")
    path = tmp_path / "setup.json"
    m.save(path)
    m2 = AppModel()
    m2.load(path)
    assert m2.slots == m.slots


def test_x_to_y_accepts_indifferent_cards():
    m = XToYModel()
    assert m.set_from_text("end", "AS, X51") is None
    assert m.report("end").ok and m.report("end").indifferent == 51


def test_too_many_cards_is_an_error():
    m = AppModel()
    assert "only has 52 slots" in m.set_final_from_text("A-KCHSD, AC")


def test_step_list_operations(model):
    model.add_step(Step(ops.OUT_FARO))
    model.add_step(Step(ops.CUT, 3))
    model.duplicate_step(1)
    assert model.steps == [Step(ops.OUT_FARO), Step(ops.CUT, 3), Step(ops.CUT, 3)]
    model.add_step(Step(ops.IN_FARO), index=0)
    assert model.steps[0] == Step(ops.IN_FARO)
    model.remove_step(0)
    assert model.steps[0] == Step(ops.OUT_FARO)
    model.clear_steps()
    assert model.steps == [] and model.result.status == "empty_sequence"


def test_listeners_notified(model):
    seen = []
    model.subscribe(lambda m: seen.append(m.result.status))
    model.add_step(Step(ops.OUT_FARO))
    assert seen == ["ok"]


def test_final_text_round_trip(model):
    assert model.final_text() == "A-KH, A-KC, K-AD, K-AS"


def test_save_and_load(tmp_path, model):
    model.set_final_from_text("(A-8, 9-K)`C, A-KH, K-AD, K-AS")
    model.add_step(Step(ops.OUT_FARO))
    model.add_step(Step(ops.OVERHAND_RUN, 52))
    path = tmp_path / "setup.json"
    model.save(path)
    other = AppModel()
    other.load(path)
    assert other.slots == model.slots
    assert other.steps == model.steps
    assert other.result.start == model.result.start
    assert other.slots[0].face_up


def test_load_rejects_bad_data():
    m = AppModel()
    with pytest.raises(ValueError):
        m.load_dict({"final": ["AC"], "steps": [{"kind": "cut", "x": 0}]})
    with pytest.raises(ValueError):
        m.load_dict({"final": ["A-KC"], "steps": []})


def test_format_preview(model):
    model.add_step(Step(ops.OUT_FARO))
    text = format_preview(model.result.states, model.steps)
    lines = text.splitlines()
    start = model.result.states[0]
    assert lines[0] == f"#1 = Out-Faro  (split {start[25].pretty()}|{start[26].pretty()})"
    assert lines[2].split() == ["Pos", "Start", "#1"]
    assert len(lines) == 55
    assert lines[3].split() == ["1", "A\u2665", "A\u2665"]
    assert lines[4].split() == ["2", "3\u2665", "2\u2665"]


def test_format_preview_without_steps(model):
    lines = format_preview(model.result.states, []).splitlines()
    assert lines[0].split() == ["Pos", "Start"] and len(lines) == 53


# --- X to Y -------------------------------------------------------------------------------


def test_x_to_y_waits_for_full_decks():
    m = XToYModel()
    assert m.outcome.status == "waiting"
    m.load_preset("start", "New deck order")
    assert any("Ending order" in msg for msg in m.solve().messages)
    assert not m.outcome.has_answer


def test_x_to_y_solves_and_edits_clear_the_answer():
    m = XToYModel()
    m.load_preset("start", "New deck order")
    m.set_cards("end", simulate(NDO, [Step(ops.OUT_FARO), Step(ops.CUT, 10)]))
    out = m.solve()
    assert out.status == "ok" and out.verified and out.shortest
    assert len(out.steps) == 2
    assert out.states[0] == NDO and len(out.states) == 3
    assert "the fewest possible" in out.messages[0]
    m.load_preset("end", "Aronson stack")
    assert m.outcome.status == "waiting" and not m.outcome.has_answer


def test_x_to_y_depth_setting():
    m = XToYModel()
    m.load_preset("start", "New deck order")
    m.set_cards("end", simulate(NDO, [Step(ops.OUT_FARO), Step(ops.CUT, 10)]))
    m.set_depth(1)
    out = m.solve()
    assert out.verified and not out.shortest
    assert "No sequence of 1 or fewer exists" in out.messages[0]
    m.set_depth(4)
    assert m.outcome is out  # changing the depth keeps the shown answer
    assert m.solve().shortest
    with pytest.raises(ValueError):
        m.set_depth(0)


def test_x_to_y_indifferent_end_only_places_named_cards():
    m = XToYModel()
    m.load_preset("start", "New deck order")
    m.set_from_text("end", "X9, AS, X42")  # ace of spades 10th, anything else anywhere
    out = m.solve()
    assert out.status == "ok" and out.verified and out.shortest
    assert out.states[-1][9].key == "AS" and len(out.steps) <= 2
    assert out.states[0] == NDO and len(out.messages) == 1  # no X in the start to fill


def test_x_to_y_fills_indifferent_start_cards():
    m = XToYModel()
    m.set_from_text("start", "X, A-QS, X39")  # king of spades unknown, at the top
    m.set_from_text("end", "A-KS, X39")
    out = m.solve()
    assert out.status == "ok" and out.verified and out.shortest
    assert [c.key for c in out.states[-1][:13]] == [c.key for c in deck.parse_cards("A-KS")]
    assert m.cards["start"] == out.states[0]  # the starting order is filled in
    assert sum(c.key == "KS" for c in m.cards["start"]) == 1  # an X became the king
    assert sum(c.indifferent for c in m.cards["start"]) == 39  # the rest stay X
    assert "filled in" in out.messages[1]
    assert m.outcome is out and m.solve().steps == out.steps  # solving again: same route


def test_x_to_y_pairs_x_cards_when_both_sides_need_them():
    m = XToYModel()
    m.set_from_text("start", "X, A-KC, A-KH, A-KS, 2-KD")  # AD unknown
    m.set_from_text("end", "A-KH, A-KS, 2-QD, X, AD, A-KC")  # cut 14; KD doesn't matter
    out = m.solve()
    assert out.status == "ok" and out.verified and not out.shortest
    assert out.steps == [Step(ops.CUT, 14)] and out.states[-1][38].key == "AD"
    assert "paired up" in out.messages[0] and m.cards["start"][0].key == "AD"


def test_x_to_y_shorthand_error_and_swap():
    m = XToYModel()
    assert m.set_from_text("start", "A-KC, ZZ") is not None
    m.load_preset("end", "New deck order")
    m.swap()
    assert m.errors["end"] and m.cards["start"] == NDO
    assert any("Ending order shorthand error" in p for p in m.problems())


def test_format_instructions():
    assert format_instructions([Step(ops.IN_FARO), Step(ops.CUT, 3)]) == " 1. In-Faro\n 2. Cut 3"


def test_split_cards():
    from shuffle_solver.ui.model import split_cards, split_note

    names = lambda pair: tuple(c.key for c in pair)  # noqa: E731
    assert names(split_cards(Step(ops.OUT_FARO), NDO)) == ("KC", "KD")
    assert names(split_cards(Step(ops.PARTIAL_IN_FARO, 18), NDO)) == ("5C", "6C")
    assert names(split_cards(Step(ops.PARTIAL_OUT_FARO_BOTTOM_TOP, 9), NDO)) == ("TS", "9S")
    assert names(split_cards(Step(ops.CUT, 5), NDO)) == ("5H", "6H")
    assert names(split_cards(Step(ops.PACKET_RUN, 3, 2), NDO)) == ("3H", "4H")
    assert split_cards(Step(ops.OVERHAND_RUN, 5), NDO) is None
    assert split_note(Step(ops.IN_FARO), NDO) == "split K♣|K♦"
    assert split_note(Step(ops.CUT, 5), NDO) == "split 5♥|6♥"
    assert split_note(Step(ops.OVERHAND_RUN, 5), NDO) == ""


def test_format_instructions_with_splits():
    steps = [Step(ops.OUT_FARO), Step(ops.CUT, 3), Step(ops.OUT_FARO)]
    states = [NDO] + [simulate(NDO, steps[:k]) for k in (1, 2, 3)]
    lines = format_instructions(steps, states).splitlines()
    assert lines[0] == " 1. Out-Faro  (split K♣|K♦)"
    assert lines[1] == f" 2. Cut 3  (split {states[1][2].pretty()}|{states[1][3].pretty()})"
    top, rest = states[2][25].pretty(), states[2][26].pretty()
    assert lines[2] == f" 3. Out-Faro  (split {top}|{rest})"


def test_format_splits():
    from shuffle_solver.ui.model import format_splits

    steps = [Step(ops.CUT, 3), Step(ops.PARTIAL_OUT_FARO_BOTTOM_TOP, 9)]
    states = [NDO, simulate(NDO, steps[:1]), simulate(NDO, steps)]
    after_cut = states[1]
    lines = format_splits(steps, states).splitlines()
    assert lines[1:] == ["#1    3♥ | 4♥",
                         f"#2  {after_cut[42].pretty():>4} | {after_cut[43].pretty()}"]
    assert format_splits([Step(ops.OVERHAND_RUN, 3)], states[:2]) == ""


def test_search_outcome_reports_best_so_far():
    ndo = deck.PRESETS["New deck order"]
    end = __import__("random").Random(2).sample(ndo, len(ndo))
    seen = []
    final = search_outcome(ndo, end, 5, improved=seen.append)
    assert seen and all(o.status == "searching" and o.verified and o.states for o in seen)
    assert "Best so far" in seen[0].messages[0]
    assert len(final.steps) <= len(seen[-1].steps)


def test_cancelled_outcome_keeps_best_route():
    assert cancelled_outcome(None).status == "waiting"
    best = PathOutcome("searching", ["x"], [Step(ops.OUT_FARO)], [[], []], True)
    out = cancelled_outcome(best)
    assert out.status == "ok" and out.verified and out.steps == best.steps
    assert "Search cancelled" in out.messages[0] and "1 shuffle " in out.messages[0]


def test_step_line():
    from shuffle_solver.ui.model import step_line

    assert step_line(2, Step(ops.OUT_FARO), NDO) == " 2. Out-Faro  (split K♣|K♦)"
    assert step_line(3, Step(ops.CUT, 4), NDO) == " 3. Cut 4  (split 4♥|5♥)"
    assert step_line(4, Step(ops.OVERHAND_RUN, 4), NDO) == " 4. Overhand Run of 4"
    assert step_line(4, Step(ops.OUT_FARO)) == " 4. Out-Faro"


def test_packet_run_step_y_editing_and_save(tmp_path, model):
    model.add_step(Step(ops.PACKET_RUN, 10, 4))
    assert model.steps[0].label() == "Packet Run: pick up 10, run 4"
    model.set_step_x(0, 6)  # still leaves cards in hand, so Y is kept
    assert model.steps[0] == Step(ops.PACKET_RUN, 6, 4)
    model.set_step_x(0, 3)  # Y no longer fits: run them all
    assert model.steps[0] == Step(ops.PACKET_RUN, 3)
    assert model.steps[0].label() == "Packet Run: reverse top 3"
    model.set_step_x(0, 9)
    model.set_step_y(0, 2)
    assert model.steps[0] == Step(ops.PACKET_RUN, 9, 2)
    model.set_step_y(0, 9)  # running all of them is stored as no Y
    assert model.steps[0] == Step(ops.PACKET_RUN, 9)
    with pytest.raises(ValueError):
        model.set_step_y(0, 10)
    model.set_step_y(0, 5)
    path = tmp_path / "setup.json"
    model.save(path)
    other = AppModel()
    other.load(path)
    assert other.steps == [Step(ops.PACKET_RUN, 9, 5)]
    assert other.result.start == model.result.start


# --- free tracking -----------------------------------------------------------------------


def test_tracker_follows_the_deck_through_each_step():
    m = TrackerModel()
    m.load_preset("New deck order")
    m.add_step(Step(ops.OUT_FARO))
    m.add_step(Step(ops.CUT, 10))
    decks = [list(t.pile("A").cards) for t in m.states]
    assert decks == [NDO, simulate(NDO, [Step(ops.OUT_FARO)]),
                     simulate(NDO, [Step(ops.OUT_FARO), Step(ops.CUT, 10)])]
    assert m.steps == [tracking.Shuffle(Step(ops.OUT_FARO)), tracking.Shuffle(Step(ops.CUT, 10))]
    assert m.around() == ("Starting order", m.states[0], "After all 2 steps", m.states[2])
    assert m.around(1) == ("Before #2: Cut 10", m.states[1], "After #2: Cut 10", m.states[2])
    assert m.step_decks() == decks[:2]
    m.move_step(1, -1)  # edits recompute every state
    assert list(m.states[-1].pile("A").cards) == simulate(
        NDO, [Step(ops.CUT, 10), Step(ops.OUT_FARO)])


def test_tracker_takes_any_deck_without_duplicates():
    m = TrackerModel()
    m.add_step(Step(ops.OUT_FARO))
    assert m.states is None and m.deck_problems() == ["No cards yet."]
    assert m.around(0) == ("Before #1: Out-Faro", None, "After #1: Out-Faro", None)
    assert "Enter a deck" in m.missing_reason()
    m.set_from_text("A-KH, A-KC, K-AD, K-AS")
    assert list(m.states[0].pile("A").cards) == NDO and m.error is None
    assert m.set_from_text("A-KH, nonsense") is not None
    assert m.states is None and m.cards == NDO  # the last good deck is kept, but not used
    m.set_cards(NDO[:10])
    assert m.deck_problems() == [] and len(m.states) == 2
    m.set_cards(NDO[:10] + NDO[:1])
    assert m.deck_problems() == ["Duplicated: AH"] and m.states is None


def test_tracker_shuffles_the_target_pile_and_knows_its_size():
    m = TrackerModel()
    m.load_preset("New deck order")
    m.add_step(tracking.TakeOut(tuple(NDO[:1]), "pile"))  # A: 51 cards, B: 1
    assert m.piles_at(1) == ["A", "B"] and m.size_at(1) == 51 and m.size_at(0) == 52
    with pytest.raises(ValueError, match="full faro needs an even number"):
        m.add_step(Step(ops.OUT_FARO))
    assert len(m.steps) == 1  # refused, not added
    m.add_step(Step(ops.PARTIAL_OUT_FARO, 25))
    m.target_pile = "B"
    m.add_step(Step(ops.OVERHAND_RUN, 1))
    assert m.steps[2] == tracking.Shuffle(Step(ops.OVERHAND_RUN, 1), "B")
    m.set_step_x(1, 20)  # an edit keeps the pile
    assert m.steps[1] == tracking.Shuffle(Step(ops.PARTIAL_OUT_FARO, 20), "A")
    with pytest.raises(ValueError):
        m.set_step_x(1, 26)  # too big for 51 cards


def test_tracker_marks_a_step_an_earlier_edit_broke():
    m = TrackerModel()
    m.load_preset("New deck order")
    m.add_step(tracking.Split("A", (26,)))
    m.add_step(tracking.Place("B", "A"))
    m.add_step(Step(ops.OUT_FARO))
    m.remove_step(0)  # now there is no pile B to put anywhere
    assert m.problem == (0, "there is no pile B on the table")
    assert m.step_problem(0) and m.step_problem(1) is None
    assert m.step_decks() == [None, None] and len(m.states) == 1
    assert m.around(1)[1] is None
    assert m.missing_reason() == "Step 1 can't be done: there is no pile B on the table"


def test_format_table_heads_each_pile():
    table = tracking.Split("A", (2,)).apply(tracking.Table.start(NDO[:3]))
    assert format_table(table) == ("Pile A \u2014 2 cards\n 1 A\u2665\n 2 2\u2665\n\n"
                                   "Pile B \u2014 1 card\n 1 3\u2665")


def test_format_columns_numbers_down_each_column():
    lines = format_columns(NDO).splitlines()
    assert len(lines) == 13
    assert lines[0].split() == ["1", "A♥", "14", "A♣", "27", "K♦", "40", "K♠"]
    assert lines[12].split()[-2:] == ["52", "A♠"]
    assert format_columns(NDO[:3]).splitlines() == [" 1 A♥", " 2 2♥", " 3 3♥"]


def grouped_model(n=6):
    m = TrackerModel()
    m.load_preset("New deck order")
    for k in range(n):
        m.add_step(Step(ops.CUT, k + 1))
    return m


def test_groups_follow_inserts_removals_and_duplicates():
    m = grouped_model()
    g = m.add_group(1, 3, " Trick 1 ", "Red")
    assert (g.title, g.color, g.first, g.last) == ("Trick 1", "Red", 1, 3)
    m.add_step(Step(ops.OUT_FARO), 0)  # before the group: it moves down
    assert (g.first, g.last) == (2, 4)
    m.add_step(Step(ops.OUT_FARO), 3)  # inside: it grows
    assert (g.first, g.last) == (2, 5)
    m.add_step(Step(ops.OUT_FARO), 6)  # right after its last step: outside
    assert (g.first, g.last) == (2, 5)
    m.duplicate_step(5)  # a copy of its last step joins it
    assert (g.first, g.last) == (2, 6)
    m.remove_step(0)
    assert (g.first, g.last) == (1, 5)
    for _ in range(5):
        m.remove_step(1)
    assert m.groups == []  # its last step went, so the group did too
    m.add_group(0, 1, "", "Blue")
    assert m.groups[0].title == "Group"
    m.clear_steps()
    assert m.groups == []


def test_groups_cannot_overlap_and_can_be_edited_or_removed():
    m = grouped_model()
    g = m.add_group(0, 2, "Trick 1", "Red")
    with pytest.raises(ValueError, match='overlap the group "Trick 1"'):
        m.add_group(2, 4, "Trick 2", "Blue")
    with pytest.raises(ValueError, match="pick the steps"):
        m.add_group(4, 9, "Trick 2", "Blue")
    h = m.add_group(3, 5, "Trick 2", "Blue")
    assert m.groups == [g, h] and m.group_of(4) is h and m.group_of(9) is None
    m.edit_group(g.id, "Opener", "Green")
    assert (g.title, g.color) == ("Opener", "Green")
    m.remove_group(g.id)
    assert m.groups == [h] and len(m.steps) == 6


def test_around_a_range_and_a_group():
    m = grouped_model()
    m.add_group(1, 3, "Trick 1", "Red")
    assert m.around(1, 3) == ("Before Trick 1 (#2\u2013#4)", m.states[1],
                              "After Trick 1 (#2\u2013#4)", m.states[4])
    assert m.around(0, 1)[::2] == ("Before #1\u2013#2", "After #1\u2013#2")
    assert m.around(2, 2) == m.around(2)


def test_replace_step_checks_it_first():
    m = grouped_model(1)
    new = tracking.Rearrange("Reveal", tracking.parse_piles(
        "A: " + deck.format_cards(NDO[::-1])))
    m.replace_step(0, new)
    assert list(m.states[1].pile("A").cards) == NDO[::-1]
    with pytest.raises(ValueError, match="exactly the cards"):
        m.replace_step(0, tracking.Rearrange("", tracking.parse_piles("AH")))


def test_tracker_saves_and_loads_the_whole_tab(tmp_path):
    m = TrackerModel()
    m.set_from_text("A-KH, A-KC, K-AD, K-AS`")
    ah, ac = deck.parse_cards("AH, AC")
    for step in (Step(ops.OUT_FARO), Step(ops.PACKET_RUN, 10, 4),
                 tracking.TakeOut((ah,), "discard"), tracking.AddCards((ah,), "A", 3),
                 tracking.TakeOut((ac,), "each"), tracking.Split("A", (5, 5)),
                 tracking.Place("D", "A", False), tracking.Gather(())):
        m.add_step(step)
    cards = m.states[-1].pile("A").cards
    m.add_step(tracking.Rearrange("Reveal", (("A", cards[:20]), ("B", cards[20:]))))
    m.target_pile = "B"
    m.add_step(Step(ops.CUT, 3))
    m.add_group(1, 3, "Trick 1", "Red")
    m.add_group(5, 6, "Trick 2", "Blue")
    assert m.problem is None
    path = tmp_path / "project.json"
    m.save(path)
    other = TrackerModel()
    other.load(path)
    assert other.cards == m.cards and other.cards[-1].face_up
    assert other.steps == m.steps
    assert other.states == m.states
    assert other.target_pile == "B"
    assert [(g.title, g.color, g.first, g.last) for g in other.groups] == [
        ("Trick 1", "Red", 1, 3), ("Trick 2", "Blue", 5, 6)]
    other.add_group(8, 8, "Trick 3", "Red")  # new groups still get their own id
    assert len({g.id for g in other.groups}) == 3


def test_tracker_and_setup_files_are_not_mixed_up():
    tracker = TrackerModel()
    tracker.load_preset("New deck order")
    with pytest.raises(ValueError, match="Free Tracking"):
        AppModel().load_dict(tracker.to_dict())
    with pytest.raises(ValueError, match="not a Free Tracking"):
        TrackerModel().load_dict(AppModel().to_dict())
    bad = tracker.to_dict() | {"groups": [{"title": "X", "color": "Red", "first": 0,
                                           "last": 0}]}  # there are no steps to group
    with pytest.raises(ValueError, match="aren't there"):
        tracker.load_dict(bad)
    assert tracker.cards == NDO  # a failed load leaves the tab as it was


# --- stack trainer ---------------------------------------------------------------------


def trainer(preset="Mnemonica (Tamariz)", seed=1):
    m = TrainerModel(random.Random(seed))
    m.load_preset(preset)
    return m


def test_trainer_waits_for_a_deck():
    m = TrainerModel()
    assert m.question is None and m.unavailable_reason() == "No cards yet."
    m.set_from_text("AC, AC")
    assert m.question is None and "Duplicated: AC" in m.unavailable_reason()
    m.set_from_text("AC, (")
    assert m.question is None and m.error


def test_trainer_questions_match_the_stack():
    m = trainer()
    cards = deck.PRESETS["Mnemonica (Tamariz)"]
    seen = set()
    for _ in range(200):
        q = m.question
        seen.add(q.kind)
        assert cards[q.position - 1].key == q.card.key
        if q.kind == POSITION_OF:
            assert q.answer == q.position
        else:
            offset = {CARD_AT: 0, BEFORE: -1, AFTER: 1}[q.kind]
            assert q.answer == cards[q.position - 1 + offset]
        m.give_up()
    assert seen == {POSITION_OF, CARD_AT, BEFORE, AFTER}


def test_trainer_stays_in_range_and_never_repeats_a_card():
    m = trainer()
    m.set_range(5, 8)
    last = None
    for _ in range(200):
        q = m.question
        assert 5 <= q.position <= 8
        if q.kind == BEFORE:
            assert q.position > 5  # the card before is in the range too
        if q.kind == AFTER:
            assert q.position < 8
        assert q.position != last
        last = q.position
        m.give_up()


def test_trainer_repeats_only_when_unavoidable():
    m = trainer()
    m.set_range(10, 10)
    assert {m.give_up().question.position for _ in range(5)} == {10}
    assert m.question.kind in (POSITION_OF, CARD_AT)  # no neighbour in a range of one
    for kind in (POSITION_OF, CARD_AT):
        m.set_kind(kind, False)
    assert m.question is None and "range of one card" in m.unavailable_reason()
    m.set_range(10, 11)  # before 11 and after 10 are the only questions left
    positions = [m.give_up().question.position for _ in range(20)]
    assert all(a != b for a, b in zip(positions, positions[1:]))


def test_trainer_checks_answers_and_keeps_score():
    m = trainer()
    q = m.question
    good = str(q.answer) if q.kind == POSITION_OF else q.answer.pretty()
    assert m.answer(good).correct
    q = m.question
    wrong = "99" if q.kind == POSITION_OF else ("AC" if q.answer.key != "AC" else "2C")
    outcome = m.answer(wrong)
    assert not outcome.correct and outcome.given == wrong and outcome.question == q
    assert m.give_up().given == ""
    assert (m.asked, m.correct, m.streak, m.best_streak) == (3, 1, 0, 1)
    assert m.accuracy == pytest.approx(1 / 3)
    m.reset_stats()
    assert (m.asked, m.correct, m.accuracy, m.last_outcome) == (0, 0, None, None)


def test_trainer_reads_cards_any_way_and_counts_junk_as_wrong():
    m = trainer()
    m.set_kind(POSITION_OF, False)
    q = m.question
    r, s = q.answer.rank, q.answer.suit
    for text in (r + s, (r + s).lower(), f" {q.answer.pretty()} ",
                 ("10" + s) if r == "T" else r + s):
        assert q.check(text)
    for blank in ("", "   "):
        with pytest.raises(ValueError):
            m.answer(blank)
    assert m.question == q and m.asked == 0  # a blank answer isn't scored
    for junk in ("banana", "AC, AH"):
        outcome = m.answer(junk)
        assert not outcome.correct and outcome.given == junk
    m.set_kind(POSITION_OF, True)
    for kind in (CARD_AT, BEFORE, AFTER):
        m.set_kind(kind, False)
    assert not m.answer("seven").correct
    assert (m.asked, m.correct, m.streak) == (3, 0, 0)


def test_trainer_range_follows_the_deck():
    m = TrainerModel()
    with pytest.raises(ValueError):
        m.set_range(1, 5)
    m.load_preset("New deck order")
    assert (m.first, m.last) == (1, 52)
    m.set_from_text("A-KH")  # a whole-deck range shrinks with the deck
    assert (m.first, m.last) == (1, 13)
    m.set_range(3, 6)
    m.load_preset("Aronson stack")  # any other range is kept
    assert (m.first, m.last) == (3, 6)
    m.set_from_text("A-3H")
    assert (m.first, m.last) == (3, 3)
    for bad in ((0, 2), (3, 2), (1, 4)):
        with pytest.raises(ValueError):
            m.set_range(*bad)
    m.whole_deck()
    assert (m.first, m.last) == (1, 3)


def test_trainer_ignores_face_up_flags():
    m = TrainerModel(random.Random(0))
    m.set_from_text("AC`, 2C, 3C")
    assert not any(c.face_up for c in m.cards)



def test_tracker_takes_indifferent_cards_and_saves_them(tmp_path):
    m = TrackerModel()
    assert m.set_from_text("A-KH, X6, X`") is None
    assert m.deck_problems() == [] and len(m.cards) == 20
    m.add_step(Step(ops.OUT_FARO))
    m.add_step(tracking.NameCards(deck.parse_cards("5S"), "A", 8))
    path = tmp_path / "t.json"
    m.save(path)
    loaded = TrackerModel()
    loaded.load(path)
    assert loaded.cards == m.cards and loaded.states[-1] == m.states[-1]


# --- saving the tabs without files (the session) ---------------------------------------

def test_x_to_y_round_trip_keeps_orders_and_depth():
    m = XToYModel()
    m.load_preset("start", "New deck order")
    m.set_from_text("end", "AS`, 2S")
    m.set_depth(3)
    m.set_outcome(PathOutcome("ok", ["found"], []))
    again = XToYModel()
    again.load_dict(m.to_dict())
    assert again.cards == m.cards and again.depth == 3
    assert again.cards["end"][0].face_up
    assert again.outcome.status == "waiting"  # an answer is found again, not saved
    m.set_from_text("end", "X`, AS, X50")
    again.load_dict(m.to_dict())
    assert again.cards == m.cards and again.cards["end"][0].indifferent
    with pytest.raises(ValueError):
        again.load_dict({"depth": 99})


def test_trainer_round_trip_keeps_stack_range_and_kinds_but_not_score():
    m = TrainerModel(random.Random(1))
    m.set_cards(NDO[:13])
    m.set_range(2, 9)
    m.set_kind(BEFORE, False)
    m.give_up()
    again = TrainerModel(random.Random(1))
    again.load_dict(m.to_dict())
    assert again.cards == m.cards and (again.first, again.last) == (2, 9)
    assert again.kinds == m.kinds and again.asked == 0
    assert again.question is not None and 2 <= again.question.position <= 9
    with pytest.raises(ValueError):
        again.load_dict({"cards": ["AS"], "first": 1, "last": 5})
    empty = TrainerModel()
    empty.load_dict(TrainerModel().to_dict())
    assert empty.cards == [] and empty.question is None


def test_stacking_round_trip_keeps_every_typed_hand():
    from shuffle_solver.ui.model import StackingModel
    m = StackingModel()
    m.set_players(3)
    m.set_hand_text("Player 1", "AS, AH")
    m.set_hand_text("Flop", "zz")  # a typo is kept as typed
    m.set_burns(False)
    m.set_game("five_card")  # the Flop is kept, though five-card draw has none
    again = StackingModel()
    again.load_dict(m.to_dict())
    assert (again.game, again.players, again.burns, again.fill) == (
        m.game, 3, False, False)
    assert again.texts == {"Player 1": "AS, AH", "Flop": "zz"}
    assert "Flop" in again.errors
    assert again.numbered() == m.numbered()
    with pytest.raises(ValueError):
        again.load_dict({"players": 1})
