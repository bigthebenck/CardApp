import pytest

from shuffle_solver import deck
from shuffle_solver import shuffle_ops as ops
from shuffle_solver.solver import Step, simulate
from shuffle_solver.ui.model import (AppModel, PathOutcome, XToYModel, cancelled_outcome,
                                     format_instructions, format_preview, search_outcome)

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
    assert err and "unexpected character" in err
    assert model.result.status == "invalid_deck"
    assert not model.result.has_answer
    assert model.slots == NDO  # grid untouched
    assert model.set_final_from_text("A-KH, A-KC, K-AD, K-AS") is None
    assert model.result.status == "ok"


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
    assert lines[0] == "#1 = Out-Faro"
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


def test_x_to_y_shorthand_error_and_swap():
    m = XToYModel()
    assert m.set_from_text("start", "A-KC, ZZ") is not None
    m.load_preset("end", "New deck order")
    m.swap()
    assert m.errors["end"] and m.cards["start"] == NDO
    assert any("Ending order shorthand error" in p for p in m.problems())


def test_format_instructions():
    assert format_instructions([Step(ops.IN_FARO), Step(ops.CUT, 3)]) == " 1. In-Faro\n 2. Cut 3"


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
