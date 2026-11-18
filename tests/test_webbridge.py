"""The phone web app's JSON bridge (web/webbridge.py), run here in plain CPython."""

import importlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture
def bridge():
    sys.path.insert(0, str(WEB))
    try:
        sys.modules.pop("webbridge", None)
        module = importlib.import_module("webbridge")  # a fresh model each test
    finally:
        sys.path.remove(str(WEB))

    def call(op, **args):
        return json.loads(module.handle(op, json.dumps(args)))
    return call


def test_meta_lists_presets_and_x_bounds(bridge):
    meta = bridge("meta")
    assert "New deck order" in meta["presets"]
    kinds = {k["kind"]: k for k in meta["kinds"]}
    assert (kinds["cut"]["min"], kinds["cut"]["max"]) == (1, 51)
    assert not kinds["out_faro"]["hasX"]
    assert kinds["packet_run"]["hasY"]
    assert kinds["partial_out_faro_bottom_top"]["source"] == "bottom"


def test_tamariz_sequence_solves_to_mnemonica_prep(bridge):
    bridge("set_text", text="4C 2H 7D 3C 4H 6D AS 5H 9S 2S QH 3D QC 8H 6S 5S 9H KC 2D JH 3S "
                            "8S 6H TC 5D KD 2C 3H 8D 5C KS JD 8C TS KH JC 7S TH AD 4S 7H 4D "
                            "AC 9C JS QD 7C QS TD 6C AH 9D".replace(" ", ","))
    for _ in range(4):
        bridge("add_step", kind="out_faro")
    bridge("add_step", kind="overhand_run", x=26)
    bridge("add_step", kind="partial_out_faro", x=18)
    state = bridge("add_step", kind="cut", x=9)["state"]
    assert state["result"]["status"] == "ok" and state["result"]["verified"]
    prep = bridge("start_text", kind="shorthand")["text"]
    assert prep == "A-KC, A-KD, K-AH, K-AS"
    assert [s["split"] for s in state["steps"]][0].startswith("split ")
    assert len(state["result"]["states"]) == 8


def test_bad_input_reports_error_with_state(bridge):
    reply = bridge("set_slot", index=0, card="QQ")
    assert "error" in reply and reply["state"]["slots"][0] is None
    state = bridge("set_text", text="A-KH, Z")["state"]
    assert state["inputError"] and state["result"]["status"] == "invalid_deck"


def test_step_editing_and_setup_round_trip(bridge):
    bridge("preset", name="New deck order")
    bridge("add_step", kind="packet_run", x=10, y=4)
    bridge("add_step", kind="cut", x=5, index=0)
    assert bridge("move_step", index=0, delta=1)["state"]["steps"][1]["kind"] == "cut"
    state = bridge("set_x", index=0, x=3)["state"]  # Y 4 no longer fits under X 3
    assert (state["steps"][0]["x"], state["steps"][0]["y"]) == (3, None)
    setup = state["setup"]
    bridge("clear_steps")
    bridge("clear_final")
    restored = bridge("load", setup=setup)["state"]
    assert restored["setup"] == setup and restored["result"]["verified"]


def test_export_text_needs_a_verified_answer(bridge):
    assert "error" in bridge("export_text")
    bridge("preset", name="New deck order")
    bridge("add_step", kind="in_faro")
    text = bridge("export_text", notes="table 3")["text"]
    assert text.startswith("Shuffle sequence:\n 1. In-Faro  (split")
    assert text.endswith("Notes:\ntable 3\n")


# --- Free Tracking -------------------------------------------------------------------------


def test_tracker_piles_bounds_and_tables(bridge):
    bridge("t_preset", name="New deck order")
    bridge("t_add", step={"kind": "split", "pile": "A", "sizes": "26"})
    bridge("t_add", step={"kind": "out_faro", "pile": "B"})
    reply = bridge("t_add", step={"kind": "cut", "x": 40, "pile": "B"})
    assert "between 1 and 25" in reply["error"]  # bounded by pile B's 26 cards
    assert bridge("t_bounds", index=2, pile="B")["bounds"]["cut"] == [1, 25]
    t = bridge("t_add", step={"kind": "take_out", "cards": "AH AS", "mode": "each"})["tracker"]
    assert [s["label"] for s in t["steps"]][1] == "Out-Faro on pile B"
    assert t["steps"][1]["split"].startswith("split ")
    assert [(p["name"], len(p["cards"])) for p in t["tables"][-1]] == [
        ("A", 25), ("B", 25), ("C", 1), ("D", 1)]
    assert [p["name"] for p in t["pilesAt"][3]] == ["A", "B", "C", "D"]
    assert t["targetPile"] == "B"


def test_tracker_checks_steps_without_adding_them(bridge):
    bridge("t_preset", name="New deck order")
    ok = bridge("t_check", index=0, step={"kind": "rearrange", "title": "", "text": "A-KC | A-KH, "
                                                                              "K-AD, K-AS"})
    assert ok == {"ok": True, "message": "52 cards in 2 piles"}
    bad = bridge("t_check", index=0, step={"kind": "split", "pile": "A", "sizes": "60"})
    assert not bad["ok"] and "60" in bad["message"]
    assert bridge("t_state")["tracker"]["steps"] == []


def test_tracker_editing_a_named_card(bridge):
    bridge("t_set_text", text="A-KH, X26, A-KS")
    bridge("t_add", step={"kind": "in_faro", "pile": "A"})
    t = bridge("t_add", step={"kind": "name_cards", "cards": "AC", "pile": "A",
                              "position": 1})["tracker"]
    assert "AC" in t["tables"][0][0]["cards"]  # named back to the start
    form = {**t["steps"][1]["form"], "cards": "AD"}
    assert bridge("t_check", index=1, step=form, edit=True)["ok"]
    t = bridge("t_replace", index=1, step=form)["tracker"]
    assert t["steps"][1]["label"].endswith("as A♦")
    assert "AC" not in t["tables"][0][0]["cards"]


def test_tracker_groups_and_project_round_trip(bridge):
    bridge("t_preset", name="New deck order")
    for x in (10, 20, 30):
        bridge("t_add", step={"kind": "cut", "x": x, "pile": "A"})
    bridge("t_group_add", first=0, last=1, title="Trick 1", color="Green")
    t = bridge("t_duplicate", first=0, last=1)["tracker"]
    assert [(g["title"], g["first"], g["last"]) for g in t["groups"]] == [
        ("Trick 1", 0, 1), ("Trick 1 (copy)", 2, 3)]
    setup = t["setup"]
    assert setup["type"] == "free_tracking"
    bridge("t_remove_range", first=0, last=1)
    bridge("t_clear_steps")
    t = bridge("t_load", setup=setup)["tracker"]
    assert t["setup"] == setup and len(t["steps"]) == 5
    assert "error" in bridge("load", setup=setup)  # not a Starting Order setup


def test_tracker_table_text_feeds_starting_order(bridge):
    bridge("t_preset", name="Mnemonica (Tamariz)")
    text = bridge("t_table_text", index=0)["text"]
    state = bridge("set_text", text=text)["state"]
    assert state["deckOk"]


def test_build_bundles_only_qt_free_modules(tmp_path, monkeypatch):
    # By path: "build" is also the name of a PyPI package.
    spec = importlib.util.spec_from_file_location("web_build", WEB / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    monkeypatch.setattr(build, "OUT", tmp_path / "web")
    build.build()
    with zipfile.ZipFile(tmp_path / "web" / "py" / "solver.zip") as z:
        sources = {n: z.read(n).decode("utf-8") for n in z.namelist()}
    assert "webbridge.py" in sources
    assert not any("PySide6" in src for src in sources.values())
    sw = (tmp_path / "web" / "sw.js").read_text(encoding="utf-8")
    assert "__VERSION__" not in sw
