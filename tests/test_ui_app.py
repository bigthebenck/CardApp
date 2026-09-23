"""Smoke tests for the Tk window. Skipped when Tk or a display is unavailable."""

import pytest

tk = pytest.importorskip("tkinter")

from shuffle_solver import deck  # noqa: E402
from shuffle_solver import shuffle_ops as ops  # noqa: E402
from shuffle_solver.ui.app import ShuffleSolverApp  # noqa: E402


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    a = ShuffleSolverApp(root)
    yield a
    root.destroy()


def start_text(app):
    return app.start_text.get("1.0", "end").strip()


def test_preset_add_steps_and_result(app):
    app.load_preset()
    assert app.badge.cget("text") == "PASS"
    app.new_x_var.set("7")
    app._add_step(ops.OUT_FARO)
    app._add_step(ops.OVERHAND_RUN)
    assert app.step_list.get(0, "end") == (" 1. Out-Faro", " 2. Overhand Run of 7")
    assert app.badge.cget("text") == "PASS"
    assert start_text(app).splitlines()[0].startswith("1.")


def test_reorder_in_ui_changes_result(app):
    app.load_preset()
    app._add_step(ops.OUT_FARO)
    app._add_step(ops.CUT)
    before = start_text(app)
    app._select_step(1)
    app._move_step(-1)
    assert app.step_list.get(0) == " 1. Cut 5"
    assert start_text(app) != before


def test_duplicate_slot_highlighted_and_result_cleared(app):
    app.load_preset()
    app.slot_vars[3].set("AH")
    app._commit_slot(3)
    assert str(app.slot_boxes[0].cget("style")) == "Dup.TCombobox"
    assert str(app.slot_boxes[3].cget("style")) == "Dup.TCombobox"
    assert app.badge.cget("text") == "WAITING"
    assert start_text(app) == ""
    assert "Duplicated: AH" in app.deck_status.cget("text")


def test_shorthand_box_drives_grid(app):
    app.final_text.delete("1.0", "end")
    app.final_text.insert("1.0", "A-KCHSD`")
    app.apply_text()
    assert app.slot_vars[0].get() == "A♣"
    assert app.slot_vars[51].get() == "K♦`"
    assert app.badge.cget("text") == "PASS"
    # The user's own formatting is kept after an unrelated edit.
    app._add_step(ops.IN_FARO)
    assert app.final_text.get("1.0", "end").strip() == "A-KCHSD`"


def test_shorthand_error_shown(app):
    app.load_preset()
    app.final_text.delete("1.0", "end")
    app.final_text.insert("1.0", "A-KC, ZZ")
    app.apply_text()
    assert "unexpected character" in app.text_error.cget("text")
    assert app.badge.cget("text") == "WAITING"


def test_grid_edit_rewrites_shorthand(app):
    app.load_preset()
    app.slot_vars[0].set("")
    app._commit_slot(0)
    assert app.final_text.get("1.0", "end").strip().startswith("2-KH")


def test_edit_selected_x(app):
    app.load_preset()
    app._add_step(ops.CUT)
    app._select_step(0)
    app.edit_x_var.set("26")
    app._commit_edit_x()
    assert app.model.steps[0].x == 26
    app.edit_x_var.set("52")
    app._commit_edit_x()
    assert app.model.steps[0].x == 26
    assert "Invalid X" in app.seq_error.cget("text")


def test_preview_toggle(app):
    app.load_preset()
    app._add_step(ops.OUT_FARO)
    app.preview_var.set(True)
    app._toggle_preview()
    text = app.preview_text.get("1.0", "end")
    assert "Out-Faro" in text and len(text.splitlines()) >= 53


def test_copy_shorthand_parses_back(app):
    app.load_preset()
    app._add_step(ops.OUT_FARO)
    text = app._start_shorthand()
    assert deck.parse_cards(text) == app.model.result.start
