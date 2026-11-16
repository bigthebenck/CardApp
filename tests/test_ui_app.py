"""Smoke tests for the Qt window, drawn off screen (see conftest.py)."""

import json
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from shuffle_solver import deck, solver  # noqa: E402
from shuffle_solver import shuffle_ops as ops  # noqa: E402
from shuffle_solver.ui import app as app_module  # noqa: E402
from shuffle_solver.ui import dialogs, theme  # noqa: E402
from shuffle_solver.ui import tabs as tabs_module  # noqa: E402
from shuffle_solver.ui.app import (SOLVER, STACKING, TRACKER, TRAINER, X_TO_Y,  # noqa: E402
                                   ShuffleSolverApp)
from shuffle_solver.ui.model import format_table  # noqa: E402
from shuffle_solver.ui.widgets import tone  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


@pytest.fixture(autouse=True)
def no_animation(monkeypatch):
    monkeypatch.setattr(tabs_module, "ANIMATION_MS", 0)


@pytest.fixture
def windows(qapp):
    """Make windows; each is closed (and deleted) after the test."""
    made = []

    def make(**kwargs):
        window = ShuffleSolverApp(**kwargs)
        made.append(window)
        return window
    yield make
    for window in made:
        window.close()
        window.deleteLater()
    pump(lambda: True)
    # deleteLater only happens once its event is handled; without this the windows of
    # every earlier test pile up (and each theme switch restyles them all).
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def app(windows):
    return windows()


@pytest.fixture
def st(app):
    """A Starting Order tab (``SolverTab``), the only tab open."""
    return app.new_tab(SOLVER)


@pytest.fixture
def shown_dialogs(monkeypatch):
    """Record message boxes instead of showing them; answer every question no."""
    shown = []
    for name in ("info", "error"):
        monkeypatch.setattr(dialogs, name,
                            lambda parent, title, text, name=name: shown.append((name, title,
                                                                                 text)))
    monkeypatch.setattr(dialogs, "ask_yes_no",
                        lambda parent, title, text: shown.append(("ask_yes_no", title,
                                                                  text)) or False)
    return shown


def pump(until, timeout=5):
    end = time.monotonic() + timeout
    while True:
        QApplication.processEvents()
        if until():
            return
        assert time.monotonic() < end, "timed out"
        time.sleep(0.005)


def wait_for_search(tab, timeout=60):
    pump(lambda: not tab.searching, timeout)


def start_text(tab):
    return tab.start_text.toPlainText().strip()


def steps_shown(tab):
    """The step list's step rows as (shuffle, card you see) pairs."""
    return [(item.text(0), item.text(1)) for item in tab.sequence.step_list.all_items()
            if item.data(0, Qt.UserRole).startswith("s")]


def step_texts(seq):
    return [item.text(0) for item in seq.step_list.all_items()
            if item.data(0, Qt.UserRole).startswith("s")]


def test_preset_add_steps_and_result(st):
    st.load_preset()
    assert st.badge.text() == "PASS" and tone(st.badge) == "success"
    st.sequence.new_x.setValue(7)
    st.sequence.add_step(ops.OUT_FARO)
    st.sequence.add_step(ops.OVERHAND_RUN)
    see = st.model.result.start[25].pretty()  # bottom card of the upper half
    assert steps_shown(st) == [("1. Out-Faro", see), ("2. Overhand Run of 7", "")]
    assert st.badge.text() == "PASS"
    assert start_text(st).splitlines()[0].startswith("1.")


def test_reorder_in_ui_changes_result(st):
    st.load_preset()
    st.sequence.add_step(ops.OUT_FARO)
    st.sequence.add_step(ops.CUT)
    before = start_text(st)
    st.sequence.select_step(1)
    st.sequence._move_step(-1)
    assert steps_shown(st)[0] == ("1. Cut 5", st.model.result.start[4].pretty())
    assert st.sequence.selected_step() == 0  # the moved step stays selected
    assert start_text(st) != before


def test_duplicate_slot_highlighted_and_result_cleared(st):
    st.load_preset()
    st.slot_boxes[3].setEditText("AH")
    st._commit_slot(3)
    assert tone(st.slot_boxes[0]) == "dup" and tone(st.slot_boxes[3]) == "dup"
    assert tone(st.slot_boxes[1]) is None
    assert st.badge.text() == "WAITING"
    assert start_text(st) == ""
    assert "Duplicated: AH" in st.deck_status.text()
    assert tone(st.deck_status) == "danger"


def test_unreadable_slot_is_marked(st):
    st.slot_boxes[0].setEditText("ZZ")
    st._commit_slot(0)
    assert tone(st.slot_boxes[0]) == "bad" and st.model.slots[0] is None


def test_slot_choices_leave_out_placed_cards(st):
    st.load_preset()
    choices = st._slot_choices(0)
    assert choices[:3] == ["X", "B", "L"]
    assert "A♥" in choices and "2♥" not in choices  # 2H is placed in slot 2


def test_shorthand_box_drives_grid(st):
    st.final_text.setPlainText("A-KCHSD`")
    st.apply_text()
    assert st.slot_boxes[0].text() == "A♣"
    assert st.slot_boxes[51].text() == "K♦`"
    assert st.badge.text() == "PASS"
    # The user's own formatting is kept after an unrelated edit.
    st.sequence.add_step(ops.IN_FARO)
    assert st.final_text.toPlainText().strip() == "A-KCHSD`"


def test_typing_applies_after_a_pause(st):
    st.final_text.setPlainText("A-KH, A-KC, K-AD, K-AS")
    assert st._text_job.pending and st.model.filled_cards() == []
    pump(lambda: not st._text_job.pending)
    assert len(st.model.filled_cards()) == 52


def test_shorthand_error_shown(st):
    st.load_preset()
    st.final_text.setPlainText("A-KC, ZZ")
    st.apply_text()
    assert "unexpected character" in st.text_error.text()
    assert st.badge.text() == "WAITING"


def test_grid_edit_rewrites_shorthand(st):
    st.load_preset()
    st.slot_boxes[0].setEditText("")
    st._commit_slot(0)
    assert st.final_text.toPlainText().strip().startswith("2-KH")


def test_edit_selected_x(st):
    st.load_preset()
    st.sequence.add_step(ops.CUT)
    st.sequence.select_step(0)
    seq = st.sequence
    assert seq.edit_x.isEnabled() and (seq.edit_x.minimum(), seq.edit_x.maximum()) == (1, 51)
    seq.edit_x.setValue(26)  # as typing 26 and pressing Enter does
    assert st.model.steps[0].x == 26
    seq.commit_edit_x(52)
    assert st.model.steps[0].x == 26
    assert "Invalid X" in seq.seq_error.text()
    seq.select_step(None)
    assert not seq.edit_x.isEnabled() and seq.edit_x.text() == "–"


def test_faro_splits_shown_under_step_list(st):
    st.sequence.add_step(ops.OUT_FARO)
    assert st.sequence.split_label.text() == ""  # no deck yet, so nothing to split
    st.load_preset()
    st.sequence.add_step(ops.CUT)
    st.sequence.add_step(ops.OVERHAND_RUN)
    start, mid = st.model.result.start, st.model.result.states[1]
    lines = st.sequence.split_label.text().splitlines()
    assert lines[0].startswith("Where to split")
    assert lines[1:] == [f"#1  {start[25].pretty():>4} | {start[26].pretty()}",
                         f"#2  {mid[4].pretty():>4} | {mid[5].pretty()}"]  # not the run
    assert steps_shown(st) == [("1. Out-Faro", start[25].pretty()),
                                ("2. Cut 5", mid[4].pretty()), ("3. Overhand Run of 5", "")]


def test_partial_faro_direction_picker(st):
    st.sequence.new_x.setValue(9)
    st.sequence.add_step(st.sequence.partial_kind(True))
    st.sequence.partial_dir.setCurrentText("bottom into top")
    st.sequence.add_step(st.sequence.partial_kind(False))
    assert [step for step, _see in steps_shown(st)] == [
        "1. Partial Out-Faro of top 9 into top", "2. Partial In-Faro of bottom 9 into top"]


def test_preview_toggle(st):
    st.load_preset()
    st.sequence.add_step(ops.OUT_FARO)
    assert st.preview_text.isHidden()
    st.preview_check.setChecked(True)
    assert not st.preview_text.isHidden()
    text = st.preview_text.toPlainText()
    assert "Out-Faro" in text and len(text.splitlines()) >= 53
    st.preview_check.setChecked(False)
    assert st.preview_text.isHidden() and st.preview_text.toPlainText() == ""


def test_copy_shorthand_parses_back(st):
    st.load_preset()
    st.sequence.add_step(ops.OUT_FARO)
    text = st._start_shorthand()
    assert deck.parse_cards(text) == st.model.result.start


def test_delete_key_removes_the_selected_step(st):
    st.sequence.add_step(ops.OUT_FARO)
    st.sequence.add_step(ops.CUT)
    st.sequence.select_step(0)
    tree = st.sequence.step_list
    tree.on_delete()
    assert [s for s, _see in steps_shown(st)] == ["1. Cut 5"]
    assert st.sequence.selected_step() == 0


def test_starts_with_no_tabs_and_a_new_tab_button(app):
    tabs = app.tabs
    assert tabs.tabs == [] and tabs.current is None
    assert not tabs.empty.isHidden() and tabs.bar.isHidden() and tabs.body.isHidden()
    assert [a.text() for a in tabs.new_menu.actions()] == [
        "Starting Order", "X to Y", "Free Tracking", "Stack Trainer", "Stacking"]
    assert not app.save_action.isEnabled() and not app.close_action.isEnabled()
    tabs.new_menu.actions()[1].trigger()
    assert [t.kind for t in tabs.tabs] == [X_TO_Y] and tabs.current is tabs.tabs[0]
    assert tabs.empty.isHidden() and not tabs.bar.isHidden()
    assert app.windowTitle().startswith("X to Y — ")
    assert not app.save_action.isEnabled() and app.close_action.isEnabled()
    app.new_tab(TRACKER)
    assert app.save_action.isEnabled() and not app.export_action.isEnabled()
    app.new_tab(SOLVER)
    assert app.export_action.isEnabled()


def test_tabs_of_any_kind_can_repeat_and_get_their_own_titles(app):
    first, second = app.new_tab(SOLVER), app.new_tab(SOLVER)
    app.new_tab(STACKING)
    app.new_tab(SOLVER, "Mine")
    assert app.tabs.titles() == ["Starting Order", "Starting Order 2", "Stacking", "Mine"]
    assert [app.tabs.strip.tabText(i) for i in range(4)] == app.tabs.titles()
    first.load_preset()
    assert first.badge.text() == "PASS" and second.model.slots != first.model.slots


def random_order(seed):
    cards = list(deck.PRESETS["New deck order"])
    __import__("random").Random(seed).shuffle(cards)
    return cards


def test_close_shows_a_neighbour_and_stops_the_tab(app):
    tabs = app.tabs
    for kind in (SOLVER, X_TO_Y, TRAINER):
        app.new_tab(kind)
    a, b, c = tabs.tabs
    tabs.select(b)
    x_to_y = b.content
    x_to_y.load_preset("start")
    x_to_y.model.set_cards("end", random_order(3))
    x_to_y.set_depth(7)
    x_to_y.solve()
    job = x_to_y._job
    tabs.close(b)  # the one on show: the tab to its right takes its place
    assert job.cancel.is_set() and not x_to_y._poll_timer.isActive()
    assert tabs.tabs == [a, c] and tabs.current is c
    assert tabs.body.currentWidget() is c.content.frame and tabs.body.count() == 2
    assert tabs.strip.currentIndex() == 1 and tabs.strip.count() == 2
    tabs.close(c)  # the last one: the one to its left
    assert tabs.current is a and tabs.strip.currentIndex() == 0
    tabs.close(a)
    assert tabs.tabs == [] and tabs.current is None
    assert not tabs.empty.isHidden() and app.windowTitle() == app_module.APP_TITLE
    pump(lambda: True)  # no stray callbacks into the deleted tabs


def test_close_others_and_ctrl_w(app):
    for kind in (SOLVER, X_TO_Y, TRACKER):
        app.new_tab(kind)
    keep = app.tabs.tabs[1]
    app.tabs.close_others(keep)
    assert app.tabs.tabs == [keep] and app.tabs.current is keep
    app.close_current()
    assert app.tabs.tabs == []
    app.close_current()  # nothing open: nothing happens


def test_tabs_reorder(app):
    for kind in (SOLVER, X_TO_Y, TRACKER):
        app.new_tab(kind)
    tabs = app.tabs
    a, b, c = tabs.tabs
    tabs.move(a, 2)
    assert tabs.tabs == [b, c, a]
    assert [tabs.strip.tabText(i) for i in range(3)] == tabs.titles()
    tabs.move(a, -5)  # clamped to the ends
    assert tabs.tabs == [a, b, c]
    assert tabs.current is c and tabs.strip.currentIndex() == 2
    tabs.select_next(-1)
    assert tabs.current is b  # c was on show; Ctrl+Shift+Tab goes left
    tabs.select_next(2)
    assert tabs.current is a  # round past the end


def test_dragging_a_tab_moves_it_in_the_list(app):
    for kind in (SOLVER, X_TO_Y, TRACKER):
        app.new_tab(kind)
    tabs = app.tabs
    a, b, c = tabs.tabs
    tabs.strip.moveTab(0, 2)  # what a drag across the strip does
    assert tabs.tabs == [b, c, a] and tabs.current is c
    tabs.strip.setCurrentIndex(2)  # a click on a tab
    assert tabs.current is a and tabs.body.currentWidget() is a.content.frame


def test_a_dragged_tab_swaps_with_each_neighbour_it_passes(app):
    for kind in (SOLVER, X_TO_Y, TRACKER):
        app.new_tab(kind)
    app.show()
    pump(lambda: app.tabs.strip.isVisible())
    tabs, strip = app.tabs, app.tabs.strip
    assert not strip.isMovable()  # Qt's own drag draws the styled tabs out of place
    a, b, c = tabs.tabs
    middle = strip.tabRect(1).center().x()
    strip.start_drag(0, strip.tabRect(0).center().x())
    strip.drag_to(middle - 2)  # not past b's middle yet
    assert tabs.tabs == [a, b, c]
    strip.drag_to(strip.tabRect(2).center().x() + 2)  # past both
    assert tabs.tabs == [b, c, a]
    strip.drag_to(-50)  # far off to the left: all the way back
    assert tabs.tabs == [a, b, c]
    strip.end_drag()
    assert [strip.tabText(i) for i in range(3)] == tabs.titles()


def test_dragging_with_the_mouse(app):
    from PySide6.QtTest import QTest
    for kind in (SOLVER, X_TO_Y, TRACKER):
        app.new_tab(kind)
    app.show()
    pump(lambda: app.tabs.strip.isVisible())
    strip, (a, b, c) = app.tabs.strip, app.tabs.tabs
    start = strip.tabRect(0).center()
    QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, start)
    assert app.tabs.current is a
    QTest.mouseMove(strip, QPoint(start.x() + 2, start.y()))  # too little to be a drag
    assert not strip.dragging
    end = QPoint(strip.tabRect(2).center().x() + 5, start.y())
    for x in range(start.x(), end.x(), 8):
        QTest.mouseMove(strip, QPoint(x, start.y()))
    QTest.mouseMove(strip, end)
    QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, end)
    assert app.tabs.tabs == [b, c, a] and app.tabs.current is a and not strip.dragging


def test_middle_click_closes_a_tab(app):
    for kind in (SOLVER, X_TO_Y):
        app.new_tab(kind)
    app.show()
    pump(lambda: app.tabs.strip.isVisible())
    strip, first = app.tabs.strip, app.tabs.tabs[0]
    pos = strip.tabRect(0).center()
    event = QMouseEvent(QMouseEvent.MouseButtonRelease, pos, strip.mapToGlobal(pos),
                        Qt.MiddleButton, Qt.NoButton, Qt.NoModifier)
    strip.mouseReleaseEvent(event)
    assert first not in app.tabs.tabs and len(app.tabs.tabs) == 1


def test_close_button_on_each_tab(app):
    app.new_tab(SOLVER)
    app.new_tab(TRAINER)
    first, second = app.tabs.tabs
    assert second.close_button.property("onAccent") and not first.close_button.property(
        "onAccent")
    first.close_button.click()
    assert app.tabs.tabs == [second]


def test_the_close_button_sits_inside_its_tab(app):
    app.new_tab(SOLVER)
    app.show()
    pump(lambda: app.tabs.strip.isVisible())
    strip, button = app.tabs.strip, app.tabs.tabs[0].close_button
    tab_rect = strip.tabRect(0)
    top_left = button.mapTo(strip, QPoint(0, 0))
    assert button.size().toTuple() == (18, 18)
    assert tab_rect.left() < top_left.x() and top_left.x() + 18 <= tab_rect.right() - 4
    assert tab_rect.top() <= top_left.y() and top_left.y() + 18 <= tab_rect.bottom() + 1


def test_tooltips_use_the_theme(app):
    from PySide6.QtGui import QHelpEvent
    app.new_tab(SOLVER)
    tips = QApplication.instance().themed_tips
    button = app.tabs.tabs[0].close_button
    event = QHelpEvent(QEvent.ToolTip, QPoint(2, 2), QPoint(100, 100))
    assert tips.eventFilter(button, event)  # handled: no system tooltip as well
    assert tips.tip.isVisible() and tips.tip.text() == "Close tab (Ctrl+W)"
    tips.tip.grab()  # draws its rounded shape without trouble
    tips.eventFilter(button, QEvent(QEvent.Leave))
    assert not tips.tip.isVisible()


def test_the_strip_grows_with_its_tabs(app):
    app.show()
    for _ in range(3):
        app.new_tab(TRAINER)
    pump(lambda: True)
    strip = app.tabs.strip
    total = sum(strip.tabRect(i).width() for i in range(strip.count()))
    assert strip.width() >= total  # every tab shows, not just the first
    add = app.tabs.add_button
    assert add.geometry().left() >= strip.geometry().right()  # "+" right after the tabs


def test_closing_a_tab_never_shows_two_at_once(app):
    app.new_tab(TRACKER)
    app.new_tab(X_TO_Y)
    tabs = app.tabs
    seen = []
    tabs.on_change = lambda: seen.append(tabs.body.count())
    tabs.close(tabs.current)
    assert seen and set(seen) == {1}


def test_tabs_dont_resize_the_window(app):
    app.show()
    pump(lambda: True)
    size = app.size()
    for kind in (TRAINER, SOLVER, STACKING, TRACKER, X_TO_Y):
        app.new_tab(kind)
        pump(lambda: True)
        assert app.size() == size
    app.close_current()
    pump(lambda: True)
    assert app.size() == size


def test_pages_fade_in_when_shown(app, monkeypatch):
    monkeypatch.setattr(tabs_module, "ANIMATION_MS", 40)
    app.show()
    first = app.new_tab(TRAINER)
    pump(lambda: first.frame.graphicsEffect() is None)
    second = app.new_tab(SOLVER)
    assert second.frame.graphicsEffect() is not None  # fading in...
    pump(lambda: second.frame.graphicsEffect() is None)  # ...then drawn plainly again


def test_rename_a_tab_in_place(app):
    app.new_tab(SOLVER)
    tab = app.tabs.tabs[0]
    entry = app.tabs.start_rename(tab)
    assert entry.text() == "Starting Order" and tab.entry is entry
    entry.setText("  Aronson opener ")
    app.tabs.finish_rename(tab)
    assert tab.title == "Aronson opener" and app.tabs.label_text(tab) == "Aronson opener"
    assert tab.entry is None
    assert app.windowTitle().startswith("Aronson opener — ")
    app.tabs.start_rename(tab).setText("Nope")
    app.tabs.finish_rename(tab, keep=False)  # Escape
    assert tab.title == "Aronson opener"
    app.tabs.start_rename(tab).setText("   ")
    app.tabs.finish_rename(tab)  # blank: kept as it was
    assert tab.title == "Aronson opener"
    entry = app.tabs.start_rename(tab)
    entry.setText("Via Enter")
    entry.editingFinished.emit()
    assert tab.title == "Via Enter" and tab.entry is None


def test_x_to_y_tab_finds_shuffles(app):
    tab = app.new_tab(X_TO_Y)
    tab.load_preset("start")
    tab.texts["end"].setPlainText(deck.format_cards(
        solver.simulate(deck.PRESETS["New deck order"], [solver.Step(ops.IN_FARO)])))
    tab.solve()  # parses the pending text first
    assert tab.searching and not tab.find_button.isEnabled()
    assert not tab.progress_row.isHidden()
    wait_for_search(tab)
    assert tab.find_button.isEnabled() and tab.progress_row.isHidden()
    assert tab.badge.text() == "PASS"
    assert tab.steps_text.toPlainText().strip() == "1. In-Faro  (split K♣|K♦)"
    assert "1. In-Faro" in tab._instructions()


def test_x_to_y_swap_keeps_typed_text(app):
    tab = app.new_tab(X_TO_Y)
    tab.texts["start"].setPlainText("A-KCHSD")
    tab.apply_text("start")
    tab.load_preset("end")
    tab.swap()
    assert tab.texts["end"].toPlainText().strip() == "A-KCHSD"
    assert tab.model.cards["end"] == deck.parse_cards("A-KCHSD")
    assert tab.badge.text() == "WAITING"


def images_on(viewer):
    return viewer.canvas.images()


def test_card_image_for_every_card():
    from shuffle_solver.ui.card_viewer import image_path

    for key in deck.FULL_DECK_KEYS:
        assert image_path(deck.Card(key[0], key[1])).is_file(), key


def test_view_final_cards_follows_edits(st):
    st.load_preset()
    viewer = st.viewers.open("final", "Final deck", lambda: st.model.slots)
    assert len(images_on(viewer)) == 52
    st.model.set_slot(51, None)  # trailing empty slot is dropped
    assert len(images_on(viewer)) == 51
    st.model.set_slot(0, None)  # inner empty slot is drawn as a placeholder
    assert len(images_on(viewer)) == 50
    assert "50 cards" in viewer.summary.text()
    viewer.canvas.grab()  # draws without trouble
    viewer.close()
    st.model.clear_final()  # refresh with the popup closed must not fail
    assert st.viewers.get("final") is None


def test_closing_the_viewer_window_forgets_it(st):
    st.view_final_cards()
    viewer = st.viewers.get("final")
    viewer.win.close()  # the window's own close button
    assert st.viewers.get("final") is None
    st.load_preset()


def test_view_final_cards_uses_pending_text(st):
    st.final_text.setPlainText("AC`, 2H")  # debounce scheduled, not yet applied
    st.view_final_cards()
    viewer = st.viewers.get("final")
    assert len(images_on(viewer)) == 2
    assert "1 face up" in viewer.summary.text()
    st.view_final_cards()  # a second click reuses the same window
    assert st.viewers.get("final") is viewer


def test_view_start_cards(st):
    st.view_start_cards()
    viewer = st.viewers.get("start")
    assert images_on(viewer) == []
    st.load_preset()
    st.sequence.add_step(ops.OUT_FARO)
    assert len(images_on(viewer)) == 52


def test_x_to_y_view_cards(app):
    tab = app.new_tab(X_TO_Y)
    tab.load_preset("start")
    tab.view_cards("start")
    tab.view_cards("end")
    assert len(images_on(tab.viewers.get("start"))) == 52
    assert images_on(tab.viewers.get("end")) == []
    tab.swap()
    assert images_on(tab.viewers.get("start")) == []
    assert len(images_on(tab.viewers.get("end"))) == 52


def test_x_to_y_depth_slider_warns_above_six(app):
    tab = app.new_tab(X_TO_Y)
    assert tab.depth_scale.value() == 5 and "⚠" not in tab.depth_note.text()
    assert tone(tab.depth_note) == "muted"
    tab.depth_scale.setValue(6)  # as dragging the slider does
    assert tab.model.depth == 6 and "⚠" not in tab.depth_note.text()
    assert tab.depth_label.text() == "6"
    tab.set_depth(7)
    assert tab.model.depth == 7 and tone(tab.depth_note) == "danger"
    assert "⚠" in tab.depth_note.text() and "minutes" in tab.depth_note.text()


def test_x_to_y_cancel_long_search(app):
    tab = app.new_tab(X_TO_Y)
    tab.load_preset("start")
    tab.model.set_cards("end", random_order(5))
    tab.set_depth(7)
    tab.solve()
    assert not tab.progress_row.isHidden() and not tab.depth_scale.isEnabled()
    tab.cancel_search()
    wait_for_search(tab)
    assert tab.progress_row.isHidden() and tab.depth_scale.isEnabled()
    assert tab.badge.text() == "WAITING"
    assert "cancelled" in tab.result_msg.text()


def test_x_to_y_edit_during_search_cancels_it(app):
    tab = app.new_tab(X_TO_Y)
    tab.load_preset("start")
    tab.model.set_cards("end", random_order(6))
    tab.set_depth(7)
    tab.solve()
    job = tab._job
    tab.load_preset("end")  # a different ending order
    assert job.cancel.is_set()
    wait_for_search(tab)
    assert tab.badge.text() == "WAITING" and not tab.model.outcome.has_answer


def test_theme_menu_switches_and_remembers_theme(windows, tmp_path):
    path = tmp_path / "settings.json"
    a = windows(settings_path=path)
    assert theme.current() == theme.palette(theme.DEFAULT_FAMILY, False)
    assert a.style_actions[theme.GLASS].isChecked()
    a.theme_actions["ocean"].trigger()
    a.toggle_dark()
    assert theme.current() == theme.palette("ocean", True)
    assert a.dark_action.isChecked() and a.theme_actions["ocean"].isChecked()
    assert theme.ThemeChoice.load(path) == theme.ThemeChoice(glass_family="ocean", dark=True)
    assert theme.palette("ocean", True).accent in QApplication.instance().styleSheet()
    tab = a.new_tab(SOLVER)
    tab.load_preset()
    assert tab.badge.text() == "PASS" and tone(tab.badge) == "success"
    a.set_theme(see_through=False)
    assert not theme.ThemeChoice.load(path).see_through
    a.set_theme(family=theme.DEFAULT_FAMILY, dark=False, see_through=True)


def test_classic_style_brings_back_the_old_look(windows, tmp_path):
    path = tmp_path / "settings.json"
    a = windows(settings_path=path)
    a.style_actions[theme.CLASSIC].trigger()
    assert theme.current().style == theme.CLASSIC
    assert theme.current() == theme.palette(theme.DEFAULT_CLASSIC_FAMILY, False, theme.CLASSIC)
    assert theme.current().accent == theme.CLASSIC_THEMES["sandstone-light"]["primary"]
    # The theme menu now lists the classic families, and see-through is off.
    assert list(a.theme_actions) == theme.classic_families()
    assert a.theme_actions["sandstone"].isChecked() and "nord" in a.theme_actions
    assert not a.see_through_action.isEnabled() and not a.see_through_action.isChecked()
    a.theme_actions["nord"].trigger()
    a.toggle_dark()
    assert theme.current() == theme.palette("nord", True, theme.CLASSIC)
    saved = theme.read_settings(path)
    assert (saved["style"], saved["theme"], saved["dark"]) == ("classic", "nord", True)
    # Each style keeps its own family: back to glass finds the glass one again.
    a.style_actions[theme.GLASS].trigger()
    assert theme.current() == theme.palette(theme.DEFAULT_FAMILY, True)
    assert list(a.theme_actions) == theme.families()
    again = windows(settings_path=path)
    assert again.theme == theme.ThemeChoice(theme.GLASS, theme.DEFAULT_FAMILY, "nord", True)
    tab = a.new_tab(TRACKER)  # everything draws in both styles
    a.set_theme(style=theme.CLASSIC)
    tab.frame.grab()
    a.set_theme(style=theme.GLASS, dark=False)


def test_a_theme_saved_before_the_glass_look_comes_back_as_classic_family(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"theme": "nord", "dark": true}', encoding="utf-8")  # the Tk app's
    choice = theme.ThemeChoice.load(path)
    assert choice == theme.ThemeChoice(theme.GLASS, theme.DEFAULT_FAMILY, "nord", True)
    path.write_text('{"theme": "ocean", "dark": false}', encoding="utf-8")  # first Qt build's
    assert theme.ThemeChoice.load(path).glass_family == "ocean"


def test_theme_settings_fall_back_to_default(tmp_path):
    path = tmp_path / "settings.json"
    assert theme.ThemeChoice.load(path) == theme.ThemeChoice()  # missing
    for bad in ("not json", '{"theme": "no-such", "dark": false}', '{"theme": "ocean"}',
                '{"theme": "ocean", "dark": "yes"}',
                '{"style": "neon", "glass_theme": "no-such", "dark": false}'):
        path.write_text(bad, encoding="utf-8")
        assert theme.ThemeChoice.load(path) == theme.ThemeChoice()
    assert theme.DEFAULT_FAMILY in theme.families() and "ocean" in theme.families()
    assert theme.DEFAULT_CLASSIC_FAMILY in theme.classic_families()


def test_every_theme_builds_a_stylesheet(qapp):
    for style, fams in ((theme.GLASS, theme.families()),
                        (theme.CLASSIC, theme.classic_families())):
        for family in fams:
            for dark in (False, True):
                sheet = theme.stylesheet(theme.palette(family, dark, style))
                assert "$" not in sheet and "QGroupBox" in sheet and "image: url(" in sheet


def test_see_through_needs_windows_11(app):
    # Off screen (as in these tests) there is nothing to see through.
    assert not theme.see_through_supported() and not app.see_through_action.isEnabled()
    app.set_see_through(True)
    assert not app.see_through
    app.grab()  # paints the backdrop without trouble


def test_card_viewer_felt_survives_theme_switch(app, st):
    from shuffle_solver.ui.card_viewer import FELT_COLOR
    st.load_preset()
    st.view_final_cards()
    app.toggle_dark()
    assert st.viewers.get("final").canvas.background() == FELT_COLOR
    app.toggle_dark()


def test_export_writes_file_and_confirms(st, tmp_path, monkeypatch, shown_dialogs):
    path = tmp_path / "start.txt"
    monkeypatch.setattr(dialogs, "save_path", lambda *a: str(path))
    monkeypatch.setattr(st, "_ask_export_notes", lambda: "")
    st.load_preset()
    st.model.add_step(solver.Step(ops.OUT_FARO), 0)
    st.export_start()
    text = path.read_text(encoding="utf-8")
    assert "Shuffle sequence:\n 1. Out-Faro  (split " in text
    assert "A is the card you see on the bottom of the upper packet" in text
    assert "Notes:" not in text
    assert shown_dialogs == [("info", "Export", f"Saved to {path}")]

    shown_dialogs.clear()
    monkeypatch.setattr(st, "_ask_export_notes", lambda: "Force the 7S.\nSecond line")
    st.export_start()
    assert path.read_text(encoding="utf-8").endswith("\nNotes:\nForce the 7S.\nSecond line\n")

    shown_dialogs.clear()
    path.unlink()
    monkeypatch.setattr(st, "_ask_export_notes", lambda: None)  # cancelled
    st.export_start()
    assert not path.exists() and shown_dialogs == []
    monkeypatch.setattr(st, "_ask_export_notes", lambda: "")

    shown_dialogs.clear()
    bad = tmp_path / "no-such-dir" / "start.txt"
    monkeypatch.setattr(dialogs, "save_path", lambda *a: str(bad))
    st.export_start()
    assert shown_dialogs[0][1] == "Export" and "Could not save" in shown_dialogs[0][2]


def test_export_with_nothing_to_export_says_so(st, shown_dialogs):
    st.export_start()
    assert shown_dialogs == [("info", "Export",
                              "There is no verified starting order to export yet.")]


def test_save_path_adds_the_suffix(monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("C:/x/routine", ""))
    assert dialogs.save_path(None, "Save", "Setup (*.json)", ".json") == "C:/x/routine.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("C:/x/notes.txt", ""))
    assert dialogs.save_path(None, "Save", "Setup (*.json)", ".json") == "C:/x/notes.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
    assert dialogs.save_path(None, "Save", "Setup (*.json)", ".json") is None


def test_x_to_y_shows_best_so_far_and_keeps_it_on_cancel(app):
    tab = app.new_tab(X_TO_Y)
    tab.load_preset("start")
    tab.model.set_cards("end", random_order(7))
    tab.set_depth(7)
    tab.solve()
    pump(lambda: tab.model.outcome.status == "searching" or not tab.searching, 60)
    assert tab.searching, "no best-so-far route shown"
    assert tab.badge.text() == "SEARCHING" and tone(tab.badge) == "info"
    assert "Best so far" in tab.result_msg.text()
    shown = tab._instructions()
    assert shown.startswith(" 1.")
    tab.cancel_search()
    wait_for_search(tab)
    assert tab.badge.text() == "PASS"
    assert "cancelled" in tab.result_msg.text()
    assert tab._instructions() == shown


# --- update check ---------------------------------------------------------------------

def newer_release():
    from shuffle_solver import updater
    return updater.Release("99.0.0", "https://example/releases/v99", "Notes",
                           "https://dl/CardApp-Setup-99.0.0.exe", "CardApp-Setup-99.0.0.exe",
                           "https://dl/CardApp-Setup-99.0.0.exe.sha256")


def update_checker(owner, tmp_path, release, installed=False):
    from shuffle_solver.ui.update_dialog import UpdateChecker

    def fetch():
        if isinstance(release, Exception):
            raise release
        return release
    return UpdateChecker(owner, tmp_path / "settings.json", fetch, lambda: installed)


def wait_for_check(checker, timeout=10):
    pump(lambda: not checker.checking, timeout)


def test_update_check_is_off_unless_asked_for(app):
    assert not app.updates.checking and app.updates.dialog is None


def test_manual_update_check_reports_up_to_date_and_errors(app, tmp_path, shown_dialogs):
    from shuffle_solver import __version__, updater
    checker = update_checker(app, tmp_path, updater.Release(__version__, "u", ""))
    checker.check()
    wait_for_check(checker)
    assert shown_dialogs == [("info", "Check for updates",
                              f"You have the latest version ({__version__}).")]
    assert checker.dialog is None

    shown_dialogs.clear()
    checker = update_checker(app, tmp_path, updater.UpdateError("offline"))
    checker.check(manual=False)
    wait_for_check(checker)
    assert shown_dialogs == []  # startup checks fail quietly
    checker.check()
    wait_for_check(checker)
    assert shown_dialogs == [("error", "Check for updates", "offline")]


def test_newer_version_offers_update_and_can_be_skipped(app, tmp_path, shown_dialogs):
    checker = update_checker(app, tmp_path, newer_release())
    checker.check(manual=False)
    wait_for_check(checker)
    dialog = checker.dialog
    assert dialog is not None and not dialog.will_install  # not the packaged app
    assert dialog.install_button.text() == "Open release page"
    dialog.skip()
    assert checker.dialog is None
    assert theme.read_settings(checker.settings_path)["skip_version"] == "99.0.0"

    checker.check(manual=False)
    wait_for_check(checker)
    assert checker.dialog is None  # skipped versions stay quiet at startup...
    checker.check()
    wait_for_check(checker)
    assert checker.dialog is not None  # ...but not when asked
    checker.dialog.not_now()
    assert checker.dialog is None and shown_dialogs == []


def test_update_settings_keep_the_theme(app, tmp_path):
    checker = update_checker(app, tmp_path, newer_release())
    theme.ThemeChoice(glass_family="ocean", dark=True).save(checker.settings_path)
    assert checker.check_on_startup
    checker.check_on_startup = False
    checker.skip("2.0.0")
    assert not checker.check_on_startup
    assert theme.ThemeChoice.load(checker.settings_path) == theme.ThemeChoice(
        glass_family="ocean", dark=True)


def test_install_downloads_verifies_runs_installer_and_quits(app, tmp_path, shown_dialogs,
                                                             monkeypatch):
    import hashlib
    from shuffle_solver import updater
    from shuffle_solver.ui import update_dialog
    data = b"installer" * 50_000
    monkeypatch.setattr(update_dialog.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater, "fetch_checksum", lambda url: hashlib.sha256(data).hexdigest())

    def download(url, dest, progress, cancelled):
        with open(dest, "wb") as f:
            f.write(data)
        progress(len(data), len(data))
    monkeypatch.setattr(updater, "download", download)
    ran, quit_ = [], []
    monkeypatch.setattr(updater, "run_installer", ran.append)
    monkeypatch.setattr(app, "close", lambda: quit_.append(True))

    checker = update_checker(app, tmp_path, newer_release(), installed=True)
    checker.check()
    wait_for_check(checker)
    dialog = checker.dialog
    assert dialog.will_install and dialog.install_button.text() == "Download and install"
    dialog.install()
    assert not dialog.progress.isHidden() and dialog.later_button.text() == "Cancel"
    pump(lambda: quit_, 10)
    assert ran == [str(tmp_path / "CardApp-Setup-99.0.0.exe")]
    assert shown_dialogs == []


def test_damaged_download_is_deleted_and_not_run(app, tmp_path, shown_dialogs, monkeypatch):
    from shuffle_solver import updater
    from shuffle_solver.ui import update_dialog
    monkeypatch.setattr(update_dialog.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater, "fetch_checksum", lambda url: "0" * 64)
    monkeypatch.setattr(updater, "download",
                        lambda url, dest, progress, cancelled: open(dest, "wb").close())
    ran = []
    monkeypatch.setattr(updater, "run_installer", ran.append)

    checker = update_checker(app, tmp_path, newer_release(), installed=True)
    checker.check()
    wait_for_check(checker)
    dialog = checker.dialog
    dialog.install()
    pump(lambda: dialog.worker is None, 10)
    assert ran == [] and checker.dialog is None
    assert not (tmp_path / "CardApp-Setup-99.0.0.exe").exists()
    assert shown_dialogs and shown_dialogs[0][0] == "ask_yes_no"
    assert "damaged" in shown_dialogs[0][2]


def test_add_and_edit_packet_run(st):
    st.load_preset()
    seq = st.sequence
    seq.new_x.setValue(10)
    seq.new_y.setValue(0)  # "all"
    assert seq.new_y.text() == "all"
    seq.add_step(ops.PACKET_RUN)
    seq.new_y.setValue(3)
    seq.add_step(ops.PACKET_RUN)
    assert [s for s, _see in steps_shown(st)] == ["1. Packet Run: reverse top 10",
                                                   "2. Packet Run: pick up 10, run 3"]
    assert st.badge.text() == "PASS"
    seq.select_step(0)
    assert seq.edit_y.isEnabled() and seq.edit_y.text() == "all"
    assert seq.edit_y.maximum() == 10
    seq.edit_y.setValue(4)
    assert st.model.steps[0] == solver.Step(ops.PACKET_RUN, 10, 4)
    seq.commit_edit_y(11)
    assert "Invalid Y" in seq.seq_error.text()
    seq.new_y.setValue(12)
    seq.add_step(ops.PACKET_RUN)
    assert "Can't add step" in seq.seq_error.text() and len(st.model.steps) == 2
    seq.add_step(ops.CUT)  # Y is ignored for other shuffles; goes after the selected step
    assert st.model.steps[1] == solver.Step(ops.CUT, 10)
    seq.select_step(1)
    assert not seq.edit_y.isEnabled()


def shown(tab, side):
    return tab.boxes[side].title(), tab.views[side].toPlainText()


def test_tracker_shows_whole_run_or_one_step(app):
    tab = app.new_tab(TRACKER)
    assert "Enter a deck" in shown(tab, "before")[1]
    tab.preset_bar.set("New deck order")
    tab.load_preset()
    tab.sequence.add_step(ops.OUT_FARO)
    tab.sequence.new_x.setValue(10)
    tab.sequence.add_step(ops.CUT)
    states = tab.model.states
    # A newly added step is selected, so the sides show its before and after.
    assert shown(tab, "before") == ("Before #2: Cut 10", format_table(states[1]))
    assert shown(tab, "after") == ("After #2: Cut 10", format_table(states[2]))
    tab.sequence.select_step(0)
    assert shown(tab, "before") == ("Before #1: Out-Faro", format_table(states[0]))
    assert tab.shorthand("after") == deck.format_cards(list(states[1].pile("A").cards))
    tab.sequence.step_list.on_escape()
    assert shown(tab, "before") == ("Starting order", format_table(states[0]))
    assert shown(tab, "after") == ("After all 2 steps", format_table(states[2]))
    cards = states[0].pile("A").cards
    see = f"{cards[25].pretty()} | {cards[26].pretty()}"  # the faro's split: both cards
    assert steps_shown(tab)[0][1] == see


def test_tracker_typed_deck_and_card_viewer(app):
    tab = app.new_tab(TRACKER)
    tab.deck_text.setPlainText("A-KH, A-KC, K-AD, K-AS")  # the debounce starts
    tab.sequence.add_step(ops.OUT_FARO)
    tab.view_cards("after")  # applies the pending text first
    assert tab.model.cards == deck.PRESETS["New deck order"]
    assert tab._shown["after"] == tab.model.states[1]
    tab.show_whole_run()
    assert tab.viewers.get("after").win.windowTitle() == "After all 1 step"


def test_tracker_view_buttons_stay_visible_in_a_small_window(app):
    app.resize(1200, 700)
    tracker = app.new_tab(TRACKER)
    app.show()
    pump(lambda: True)
    for side in ("before", "after"):
        frame = tracker.boxes[side]
        buttons = [b for b in frame.findChildren(QPushButton) if b.menu() is None]
        assert [b.text() for b in buttons] == ["Copy shorthand", "View cards"]
        for b in buttons:
            assert b.isVisible()
            bottom = b.mapTo(app, QPoint(0, b.height())).y()
            assert bottom <= app.height()


def test_tracker_aces_example_with_card_and_packet_steps(app):
    tab = app.new_tab(TRACKER)
    seq = tab.sequence
    tab.deck_text.setPlainText("AC, AH, AS, AD, 2-KC, 2-KH, 2-KS, 2-KD")
    tab.apply_text()
    tab.sizes_edit.setText("1,1,1,1, 12 12 12 12")
    assert tab.split()
    assert tab.model.piles_at(1) == list("ABCDEFGH")
    box = tab.place_pile_box
    assert [box.itemText(i) for i in range(box.count())] == list("ABCDEFGH")
    for pile, onto in zip("EFGH", "ABCD"):
        tab.place_pile_box.setCurrentText(pile)
        tab.place_onto_box.setCurrentText(onto)
        assert tab.place()
    tab.gather_edit.setText("a b c d")
    assert tab.gather()
    assert [t.split(". ", 1)[1] for t in step_texts(seq)] == [
        "Split pile A into 1, 1, 1, 1, 12, 12, 12, 12", "Put pile E on top of pile A",
        "Put pile F on top of pile B", "Put pile G on top of pile C",
        "Put pile H on top of pile D", "Gather piles A, B, C, D"]
    assert tab.shorthand("after") == deck.format_cards(deck.parse_cards(
        "2-KC, AC, 2-KH, AH, 2-KS, AS, 2-KD, AD"))
    seq.select_step(0)
    assert shown(tab, "after")[1].count("Pile ") == 8
    assert len(tab._groups("after")) == 8
    tab.view_cards("after")  # the grouped popup draws without trouble
    viewer = tab.viewers.get("after")
    assert "in 8 piles" in viewer.summary.text()
    viewer.canvas.grab()


def test_tracker_pile_choice(app):
    tab = app.new_tab(TRACKER)
    tab.load_preset()
    tab.sizes_edit.setText("26")
    assert tab.split()
    assert [tab.pile_box.itemText(i) for i in range(tab.pile_box.count())] == ["A", "B"]
    tab.pile_box.setCurrentText("B")
    assert tab.model.target_pile == "B"
    tab.sequence.new_x.setValue(3)
    tab.sequence.add_step(ops.CUT)
    assert step_texts(tab.sequence)[-1].endswith("pile B")


def test_tracker_card_steps_and_the_odd_pile_rule(app):
    tab = app.new_tab(TRACKER)
    seq = tab.sequence
    tab.load_preset()
    tab.cards_edit.setText("AS")
    assert tab.take_out("discard")  # 51 cards left
    assert "Odd number of cards (51): partial faros only." == seq.odd_note.text()
    assert [b.isEnabled() for b in seq.faro_buttons] == [False, False]
    assert tab.take_out("pile") is False  # they're gone now
    assert "not on the table" in seq.seq_error.text()
    tab.add_pos.setValue(26)
    assert tab.add_cards()
    assert [b.isEnabled() for b in seq.faro_buttons] == [True, True]
    assert tab.model.states[-1].pile("A").cards[25] == deck.parse_cards("AS")[0]
    seq.add_step(ops.OUT_FARO)
    assert len(tab.model.steps) == 3
    seq.select_step(0)  # now the faro is on 51 cards: refused, and the button is off
    assert not seq.faro_buttons[0].isEnabled()
    seq.add_step(ops.OUT_FARO)
    assert len(tab.model.steps) == 3 and "full faro needs an even" in seq.seq_error.text()
    seq.select_step(1)
    seq._delete_step()  # the faro after it is now on 51 cards and can't be done
    assert step_texts(seq)[1].startswith("⚠ 2. Out-Faro")
    assert "Step 2 can't be done" in seq.seq_error.text()
    tab.show_whole_run()
    assert shown(tab, "after")[1].startswith("Step 2 can't be done")


def test_tracker_names_x_cards(app):
    tab = app.new_tab(TRACKER)
    tab.model.set_from_text("AC, X3")
    tab.cards_edit.setText("KS")
    tab.name_pos.setValue(1)
    assert tab.name_cards() is False and "not an indifferent card" in tab.sequence.seq_error.text()
    tab.name_pos.setValue(3)
    assert tab.name_cards()
    assert [str(c) for c in tab.model.states[-1].pile("A").cards] == ["AC", "X", "KS", "X"]


def test_tracker_rearrange_dialog_adds_and_edits_a_step(app):
    tab = app.new_tab(TRACKER)
    tab.load_preset()
    dialog = tab.open_rearrange()
    assert dialog.text.toPlainText() == deck.format_cards(tab.model.cards)  # prefilled
    dialog.title_edit.setText("Card revelations")
    dialog.set_text("A-KH, A-KC | K-AD, K-AS`")
    assert dialog.status.text() == "✓ 52 cards in 2 piles" and tone(dialog.status) == "success"
    assert dialog.ok() and tab.dialog is None and dialog.win is None
    step = tab.model.steps[0]
    assert step.label() == "Rearrange: Card revelations (2 piles)"
    assert shown(tab, "after")[1].startswith("Pile A \u2014 26 cards")
    assert tab.shorthand("after") == "A: A-KH, A-KC |\nB: K-AD, K-AS`"
    item = tab.sequence.step_list.item_of("s0")
    tab._on_double_click(item, 0)  # edit it: prefilled with what was typed
    dialog = tab.dialog
    assert dialog.title_edit.text() == "Card revelations" and dialog.edit == 0
    dialog.set_text("A-KH, A-KC, K-AD")  # 13 cards short
    assert "missing" in dialog.status.text() and dialog.ok() is False
    assert tone(dialog.status) == "danger"
    dialog.set_text("A-KH, A-KC, K-AD, K-AS")  # back to one pile
    assert dialog.ok()
    assert len(tab.model.steps) == 1 and tab.model.states[1].names == ["A"]
    tab.open_rearrange().win.reject()  # Escape closes it
    assert tab.dialog is None


def test_tracker_groups_steps_by_range(app):
    tab = app.new_tab(TRACKER)
    seq = tab.sequence
    tab.load_preset()
    for x in range(1, 6):
        seq.new_x.setValue(x)
        seq.add_step(ops.CUT)
    seq.select_step(None)
    assert tab.open_group_dialog() is None and "select the steps" in seq.seq_error.text()
    seq.select_range(1, 3)
    assert seq.selected_range() == (1, 3) and seq.selected_step() is None
    assert shown(tab, "before")[0] == "Before #2\u2013#4"
    dialog = tab.open_group_dialog()
    dialog.title_edit.setText("Trick 1")
    dialog.color_box.setCurrentText("Red")
    assert dialog.ok()
    t = seq.step_list
    assert t.children_of() == ("s0", "g1", "s4")
    assert t.children_of("g1") == ("s1", "s2", "s3")
    group_row = t.item_of("g1")
    assert group_row.text(0) == "Trick 1   (#2\u2013#4)"
    assert group_row.background(0).color() == theme.tint("Red", 0.55)
    seq.select_rows(["g1"])
    assert seq.selected_range() == (1, 3)
    assert shown(tab, "after")[0] == "After Trick 1 (#2\u2013#4)"
    seq.new_x.setValue(7)
    seq.add_step(ops.CUT)  # goes after the group, outside it
    assert t.children_of("g1") == ("s1", "s2", "s3") and seq.selected_step() == 4
    t.item_of("g1").setExpanded(False)  # folded groups stay folded
    seq.select_step(0)
    seq.add_step(ops.OUT_FARO)  # before the group: its rows move down
    assert t.children_of("g1") == ("s2", "s3", "s4") and not t.item_of("g1").isExpanded()
    tab._on_double_click(t.item_of("g1"), 0)  # a group is edited, not regrouped
    dialog = tab.dialog
    assert dialog.title_edit.text() == "Trick 1"
    dialog.ungroup()
    assert tab.model.groups == [] and t.children_of() == tuple(f"s{i}" for i in range(7))


def test_tracker_duplicates_a_group(app):
    tab = app.new_tab(TRACKER)
    seq = tab.sequence
    tab.load_preset()
    for x in range(1, 5):
        seq.new_x.setValue(x)
        seq.add_step(ops.CUT)
    seq.select_range(1, 2)
    dialog = tab.open_group_dialog()
    dialog.title_edit.setText("Trick 1")
    dialog.color_box.setCurrentText("Red")
    dialog.ok()
    t = seq.step_list
    seq.select_rows(["g1"])
    seq._duplicate_step()
    assert t.children_of() == ("s0", "g1", "g2", "s5")
    assert t.children_of("g2") == ("s3", "s4")
    copy = tab.model.group(2)
    assert (copy.title, copy.color) == ("Trick 1 (copy)", "Red")
    assert tab.model.steps[3:5] == tab.model.steps[1:3]
    assert seq.selected_group() == 2
    seq.select_range(0, 1)  # plain steps across the group's edge: just the steps
    seq._duplicate_step()
    assert len(tab.model.steps) == 8 and len(tab.model.groups) == 2
    assert seq.selected_range() == (2, 3)


def test_open_puts_each_kind_of_file_in_its_tab(app, windows, tmp_path):
    tab = app.new_tab(TRACKER)
    tab.load_preset()
    tab.sequence.add_step(ops.OUT_FARO)
    tab.sequence.select_range(0, 0)
    tab.open_group_dialog().ok()
    project = tmp_path / "project.json"
    tab.model.save(project)
    order = app.new_tab(SOLVER)
    order.model.load_preset("New deck order")
    setup = tmp_path / "setup.json"
    order.model.save(setup)

    fresh = windows()
    tracker = fresh.open_path(str(project))
    assert fresh.tabs.current.kind == TRACKER and fresh.tabs.current.title == "project"
    assert tracker.model.steps == tab.model.steps
    assert tracker.sequence.step_list.children_of() == ("g1",)
    assert tracker.deck_text.toPlainText() == deck.format_cards(tab.model.cards)
    opened = fresh.open_path(str(setup))
    assert fresh.tabs.titles() == ["project", "setup"] and fresh.tabs.current.content is opened
    assert opened.model.slots == order.model.slots


def test_open_a_broken_file_leaves_no_tab(app, tmp_path, shown_dialogs):
    bad = tmp_path / "bad.json"
    for text in ("not json", '{"final": 7}'):
        bad.write_text(text, encoding="utf-8")
        assert app.open_path(str(bad)) is None
        assert app.tabs.tabs == [] and "Could not load" in shown_dialogs[-1][2]


def test_save_names_the_tab_after_its_file(app, tmp_path, monkeypatch, shown_dialogs):
    monkeypatch.setattr(dialogs, "save_path", lambda *a: str(tmp_path / "routine.json"))
    tracker = app.new_tab(TRACKER)
    tracker.load_preset()
    app.save_current()
    assert app.tabs.current.title == "routine" and (tmp_path / "routine.json").is_file()
    app.new_tab(SOLVER, "Kept name")
    app.save_current()
    assert app.tabs.current.title == "Kept name"  # the user's own name stays
    assert [d[0] for d in shown_dialogs] == ["info", "info"]


def test_trainer_asks_checks_and_scores(app):
    tab = app.new_tab(TRAINER)
    assert tab.question_label.text() == "No cards yet."
    assert not tab.answer_entry.isEnabled()
    tab.deck_text.setPlainText("A-KH")
    tab.apply_text()
    assert tab.last_box.value() == 13 and tab.range_total.text() == "of 13"
    assert tab.last_box.maximum() == 13
    tab.first_box.setValue(2)
    tab.last_box.setValue(5)
    assert (tab.model.first, tab.model.last) == (2, 5)
    q = tab.model.question
    assert tab.question_label.text() == q.prompt() and tab.answer_entry.isEnabled()
    tab.answer_entry.setText(str(q.answer) if q.kind == "position_of" else q.answer.pretty())
    assert tab.submit().correct
    assert tab.feedback.text().startswith("✓") and tab.answer_entry.text() == ""
    assert tone(tab.feedback) == "success"
    assert tab.give_up() is not None
    assert tab.feedback.text().startswith("✗") and tone(tab.feedback) == "danger"
    assert tab.stats_label.text().startswith("Session: 1 / 2 right (50%)")
    tab.answer_entry.setText("")
    assert tab.submit() is None and tab.model.asked == 2
    assert tab.feedback.text().startswith("⚠") and tone(tab.feedback) == "warning"
    tab.answer_entry.setText("nonsense")
    assert not tab.submit().correct and tab.model.asked == 3
    assert tab.feedback.text().startswith("✗ You said nonsense.")
    tab.first_box.blockSignals(True)
    tab.first_box.setValue(9)
    tab.first_box.blockSignals(False)
    assert not tab.apply_range() and tab.range_error.text()
    tab.whole_deck()
    assert (tab.model.first, tab.model.last) == (1, 13) and not tab.range_error.text()
    tab.model.reset_stats()
    assert tab.stats_label.text() == "Session: no answers yet"


def test_trainer_keys_answer_and_give_up(app):
    from PySide6.QtGui import QKeyEvent
    tab = app.new_tab(TRAINER)
    tab.load_preset()
    tab.answer_entry.setText("nonsense")
    tab.answer_entry.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return,
                                             Qt.NoModifier))
    assert tab.model.asked == 1
    tab.answer_entry.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape,
                                             Qt.NoModifier))
    assert tab.model.asked == 2


def test_stacking_tab_builds_a_stack_and_hands_it_on(app):
    tab = app.new_tab(STACKING)
    tab.players_box.setValue(2)
    assert tab.model.players == 2
    assert list(tab.hand_edits) == ["Player 1", "Player 2", "Flop", "Turn", "River"]
    tab.hand_edits["Player 2"].setText("AS, AH")
    tab.hand_edits["Flop"].setText("AD, AC, 2S")
    text = tab.stack_text.toPlainText()
    assert " 2. A♠   Player 2 (dealer), card 1" in text
    assert " 6. A♦   Flop, card 1" in text

    tab.hand_edits["Turn"].setText("AS")
    assert "Wanted twice" in tab.summary.text() and tone(tab.summary) == "danger"
    assert not tab.final_button.isEnabled()
    tab.hand_edits["Turn"].setText("")

    tab.game_buttons["five_card"].setChecked(True)
    assert tab.model.game == "five_card"
    assert list(tab.hand_edits) == ["Player 1", "Player 2"]
    assert tab.hand_edits["Player 2"].text() == "AS, AH"
    assert not tab.burns_check.isEnabled()

    tab.send_to_final()  # no Starting Order tab open: one is opened
    order = app.tabs.current.content
    assert app.tabs.current.kind == SOLVER
    assert order.model.slots[1].key == "AS" and order.model.slots[3].key == "AH"
    assert order.badge.text() == "PASS"

    other = app.new_tab(SOLVER)
    app.tabs.select(app.tabs.tabs[1])  # back to the first Starting Order tab
    app.tabs.select(app.tabs.tabs[0])  # and the Stacking tab
    tab.hand_edits["Player 1"].setText("KS")
    tab.send_to_final()  # goes to the Starting Order tab shown last
    assert app.tabs.current.content is order and order.model.slots[0].key == "KS"
    assert other.model.slots[0] is None


def test_stacking_tab_shows_bad_hands_and_clears(app):
    tab = app.new_tab(STACKING)
    tab.hand_edits["Player 1"].setText("ZZ")
    error = tab.hand_errors["Player 1"]
    assert not error.isHidden() and error.text().startswith("⚠")
    tab.model.clear()
    assert tab.hand_edits["Player 1"].text() == "" and error.isHidden()


def test_stacking_tab_rejects_bad_player_count(app):
    tab = app.new_tab(STACKING)
    assert tab.players_box.maximum() == 10  # the box itself stops at 10
    assert not tab.apply_players(11)
    assert "2 to 10" in tab.players_error.text()
    assert tab.model.players == 4


# --- the session: tabs kept between runs -------------------------------------------------

def test_tabs_come_back_after_quitting(windows, tmp_path):
    path = tmp_path / "session.json"
    app = windows(session_path=path)
    assert app.tabs.tabs == []  # no session yet: empty
    order = app.new_tab(SOLVER, "Opener")
    order.load_preset()
    order.sequence.add_step(ops.OUT_FARO)
    x_to_y = app.new_tab(X_TO_Y)
    x_to_y.load_preset("start")
    x_to_y.set_depth(3)
    tracker = app.new_tab(TRACKER)
    tracker.deck_text.setPlainText("A-KH")  # typed just before quitting
    trainer = app.new_tab(TRAINER)
    trainer.model.set_cards(deck.PRESETS["New deck order"][:10])
    trainer.model.set_kind(next(iter(trainer.kind_checks)), False)
    stack = app.new_tab(STACKING)
    stack.hand_edits["Player 1"].setText("AS, AH")
    app.tabs.select(app.tabs.tabs[1])
    app.quit()
    assert path.is_file() and not tracker._text_job.pending

    again = windows(session_path=path)
    tabs = again.tabs
    assert [(t.kind, t.title) for t in tabs.tabs] == [
        (SOLVER, "Opener"), (X_TO_Y, "X to Y"), (TRACKER, "Free Tracking"),
        (TRAINER, "Stack Trainer"), (STACKING, "Stacking")]
    assert tabs.current is tabs.tabs[1]
    order2, x_to_y2, tracker2, trainer2, stack2 = (t.content for t in tabs.tabs)
    assert order2.model.slots == order.model.slots and order2.badge.text() == "PASS"
    assert steps_shown(order2)[0][0] == "1. Out-Faro"
    assert x_to_y2.model.cards == x_to_y.model.cards and x_to_y2.depth_scale.value() == 3
    assert tracker2.model.cards == deck.parse_cards("A-KH")
    assert tracker2.deck_text.toPlainText() == deck.format_cards(tracker2.model.cards)
    assert trainer2.model.kinds == trainer.model.kinds
    assert {k: c.isChecked() for k, c in trainer2.kind_checks.items()} == {
        k: c.isChecked() for k, c in trainer.kind_checks.items()}
    assert stack2.hand_edits["Player 1"].text() == "AS, AH"
    assert stack2.model.numbered() == stack.model.numbered()

    for tab in list(tabs.tabs):  # closing everything: the next start is empty
        tabs.close(tab)
    again.quit()
    assert windows(session_path=path).tabs.tabs == []


def test_a_damaged_session_starts_empty_or_skips_the_bad_tab(windows, tmp_path):
    path = tmp_path / "session.json"
    for text in ("not json", "[]", '{"version": 99, "tabs": []}', '{"version": 1}'):
        path.write_text(text, encoding="utf-8")
        assert windows(session_path=path).tabs.tabs == []
    path.write_text(json.dumps({"version": 1, "current": 2, "tabs": [
        {"kind": "no-such-kind", "title": "?"},
        {"kind": SOLVER, "title": "Bad", "state": {"final": ["ZZ"]}},
        {"kind": TRAINER, "title": "Good", "state": {"cards": ["AS", "KH"]}},
        {"title": "no kind"},
    ]}), encoding="utf-8")
    app = windows(session_path=path)
    assert app.tabs.titles() == ["Good"] and app.tabs.current.title == "Good"
    assert app.tabs.current.content.model.cards == deck.parse_cards("AS, KH")
    path.write_text(json.dumps({"version": 1, "current": 0, "tabs": [  # bad tab never shown
        {"kind": TRAINER, "title": "Good", "state": {"cards": ["AS"]}},
        {"kind": SOLVER, "title": "Bad", "state": {"final": ["ZZ"]}},
    ]}), encoding="utf-8")
    app = windows(session_path=path)
    assert app.tabs.titles() == ["Good"]


def test_the_session_is_saved_every_so_often(windows, tmp_path, monkeypatch):
    path = tmp_path / "session.json"
    app = windows(session_path=path)
    timer = app._autosave_timer
    assert timer.isActive() and timer.interval() == app_module.AUTOSAVE_MS  # from the start
    app.new_tab(SOLVER, "Kept")
    app._autosave()
    assert json.loads(path.read_text(encoding="utf-8"))["tabs"][0]["title"] == "Kept"
    writes = []
    real = app_module.os.replace
    monkeypatch.setattr(app_module.os, "replace", lambda *a: writes.append(a) or real(*a))
    app._autosave()
    assert writes == []  # nothing changed: nothing written
    app.tabs.rename(app.tabs.current, "Renamed")
    app._autosave()
    assert len(writes) == 1 and "Renamed" in path.read_text(encoding="utf-8")
    assert not (tmp_path / "session.json.tmp").exists()
    app.close()
    assert not timer.isActive()


def test_no_session_path_means_no_session(app):
    assert app.session_path is None and app._autosave_timer is None
    app.new_tab(SOLVER)
    app.save_session()  # does nothing


# --- saved presets ---------------------------------------------------------------------


@pytest.fixture
def preset_dialogs(monkeypatch):
    """Answer the preset bar's name prompt and confirmations, and record its errors."""
    seen = {"name": None, "yes": True, "errors": []}
    monkeypatch.setattr(dialogs, "ask_string", lambda *a: seen["name"])
    monkeypatch.setattr(dialogs, "ask_yes_no", lambda *a: seen["yes"])
    monkeypatch.setattr(dialogs, "error", lambda parent, title, msg: seen["errors"].append(msg))
    return seen


def combo_items(box):
    return [box.itemText(i) for i in range(box.count())]


def test_a_saved_preset_shows_in_every_tab_and_is_remembered(windows, tmp_path,
                                                             preset_dialogs):
    path = tmp_path / "settings.json"
    app = windows(settings_path=path)
    tracker, x_to_y = app.new_tab(TRACKER), app.new_tab(X_TO_Y)
    order = app.new_tab(SOLVER)
    order.final_text.setPlainText("X, AS`, 2-4H")
    preset_dialogs["name"] = "  My stack "
    assert order.preset_bar.save_as() == "My stack"  # typed text counts without waiting
    assert order.preset_bar.get() == "My stack"
    assert "My stack" in combo_items(tracker.preset_bar.combo)
    x_to_y.preset_bars["end"].set("My stack")
    x_to_y.load_preset("end")
    assert x_to_y.model.cards["end"] == deck.parse_cards("X, AS`, 2-4H", allow_indifferent=True)
    assert theme.read_settings(path)["presets"] == {"My stack": "X, AS`, 2-4H"}

    again = windows(settings_path=path)
    trainer = again.new_tab(TRAINER)
    trainer.preset_bar.set("My stack")
    trainer.load_preset()
    assert "can't be trained" in trainer.model.unavailable_reason()


def test_presets_are_not_saved_over_built_ins_or_from_bad_decks(app, preset_dialogs):
    tab = app.new_tab(TRACKER)
    assert tab.preset_bar.save_as("Anything") is None  # no cards yet
    tab.deck_text.setPlainText("AS, (")
    assert tab.preset_bar.save_as("Anything") is None
    assert "fix the shorthand" in preset_dialogs["errors"][-1]
    tab.deck_text.setPlainText("AS, KH")
    assert tab.preset_bar.save_as("New deck order") is None
    assert "built-in" in preset_dialogs["errors"][-1]
    assert app.presets.user == {}
    assert not tab.preset_bar.delete_button.isEnabled()


def test_saving_over_a_preset_asks_and_deleting_removes_it(app, preset_dialogs):
    tab = app.new_tab(TRAINER)
    other = app.new_tab(SOLVER)
    tab.deck_text.setPlainText("AS, KH")
    preset_dialogs["name"] = "Two"
    tab.preset_bar.save_as()
    tab.deck_text.setPlainText("QD")
    preset_dialogs["yes"] = False
    assert tab.preset_bar.save_as() is None  # declined to replace it
    assert app.presets.cards("Two") == deck.parse_cards("AS, KH")
    preset_dialogs["yes"] = True
    tab.preset_bar.save_as()
    assert app.presets.cards("Two") == deck.parse_cards("QD")

    other.preset_bar.set("Two")
    assert tab.preset_bar.delete_button.isEnabled()
    tab.preset_bar.delete()
    assert "Two" not in app.presets.names()
    assert other.preset_bar.get() == next(iter(deck.PRESETS))  # its pick went away


def test_closed_tabs_stop_listening_for_new_presets(app, preset_dialogs):
    for kind in (SOLVER, X_TO_Y, TRACKER, TRAINER):
        app.new_tab(kind)
        app.close_current()
    assert app.presets._listeners == []
    app.presets.save("After", deck.parse_cards("AS"))  # no dead tab to update


@pytest.fixture
def open_in_errors(monkeypatch):
    """Record what "Open in new tab" complains about, from a button or from the app."""
    errors = []
    monkeypatch.setattr(dialogs, "error", lambda parent, title, msg: errors.append(msg))
    return errors


def test_open_a_deck_in_a_new_tab_of_each_kind(app, open_in_errors):
    order = app.new_tab(SOLVER)
    order.load_preset()
    order.sequence.add_step(ops.OUT_FARO)
    start = list(order.model.result.start)
    final = order.model.filled_cards()

    tracker = order.open_start.open("tracker")
    assert app.tabs.current.kind == TRACKER and app.tabs.current.content is tracker
    assert tracker.model.cards == start
    x_to_y = order.open_start.open("x")
    assert x_to_y.model.cards == {"start": start, "end": []}
    assert order.open_final.open("y").model.cards == {"start": [], "end": final}
    assert order.open_final.open("trainer").model.cards == final
    again = order.open_final.open("final")
    assert again is not order and again.model.filled_cards() == final
    assert again.model.steps == []  # only the cards are carried over
    assert app.tabs.titles() == ["Starting Order", "Free Tracking", "X to Y", "X to Y 2",
                                 "Stack Trainer", "Starting Order 2"]
    assert order.model.filled_cards() == final and len(order.model.steps) == 1
    assert open_in_errors == []
    labels = [a.text() for a in order.open_final.menu.actions()]
    assert labels[0] == "Starting Order (as final deck)" and len(labels) == 5

    # Decks other tabs work out or take can be opened too.
    tracker.sequence.add_step(ops.OUT_FARO)
    tracker.show_whole_run()
    after = list(tracker.model.states[-1].pile("A").cards)
    assert tracker.open_buttons["after"].open("final").model.filled_cards() == after
    assert tracker.open_buttons["deck"].open("trainer").model.cards == start
    x_to_y.texts["end"].setPlainText("AS, KH")  # typed text counts without waiting
    assert x_to_y.open_buttons["end"].open("tracker").model.cards == deck.parse_cards("AS, KH")
    trainer = app.new_tab(TRAINER)
    trainer.load_preset()
    assert trainer.open_button.open("x").model.cards["start"] == trainer.model.cards
    stacking = app.new_tab(STACKING)
    stacking.hand_edits["Player 1"].setText("AS, AH")
    assert stacking.open_button.open("tracker").model.cards == stacking.model.stack
    assert open_in_errors == []


def test_open_in_new_tab_says_why_it_cant(app, open_in_errors):
    order = app.new_tab(SOLVER)
    assert order.open_final.open("tracker") is None  # nothing entered
    assert "no cards" in open_in_errors[-1]
    assert order.open_start.open("tracker") is None
    assert "no verified starting order" in open_in_errors[-1]
    order.final_text.setPlainText("AS, (")
    assert order.open_final.open("tracker") is None
    assert "fix the shorthand" in open_in_errors[-1]

    tracker = app.new_tab(TRACKER)
    tracker.deck_text.setPlainText("A-KH, A-KC, K-AD, K-AS, AS, KH")  # 54 cards
    tracker.apply_text()
    assert tracker.open_buttons["deck"].open("final") is None  # too many for the 52 slots
    assert "52 slots" in open_in_errors[-1]
    assert app.tabs.titles() == ["Starting Order", "Free Tracking"]  # the new tab was closed
    assert app.tabs.current.content is tracker

    tracker.load_preset()
    tracker.sizes_edit.setText("10, 42")
    assert tracker.split()
    tracker.show_whole_run()
    assert tracker.open_buttons["after"].open("trainer") is None
    assert "several piles" in open_in_errors[-1]
    assert len(tracker.open_buttons["before"].open("trainer").model.cards) == 52
    assert len(open_in_errors) == 5

    stacking = app.new_tab(STACKING)
    stacking.hand_edits["Player 1"].setText("AS")
    stacking.hand_edits["Player 2"].setText("AS")
    assert stacking.open_button.open("final") is None
    assert "Wanted twice" in open_in_errors[-1]


def test_duplicate_a_tab(app):
    order = app.new_tab(SOLVER)
    app.new_tab(TRAINER)
    tab = app.tabs.tabs[0]
    app.tabs.rename(tab, "Aces")
    order.final_text.setPlainText("A-KH, A-KC, K-AD, K-AS")  # pending when the tab is copied
    order.sequence.add_step(ops.OUT_FARO)

    copy = app.duplicate_tab(tab)
    assert app.tabs.titles() == ["Aces", "Aces 2", "Stack Trainer"]
    assert app.tabs.current.content is copy and copy is not order
    assert copy.model.to_dict() == order.model.to_dict()
    assert copy.badge.text() == "PASS" and len(copy.model.steps) == 1
    copy.model.clear_final()
    assert len(order.model.filled_cards()) == 52  # the two don't share anything

    menu = app.tabs.build_tab_menu(tab)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels[:2] == ["Rename…", "Duplicate"]
    menu.actions()[1].trigger()
    assert app.tabs.titles() == ["Aces", "Aces 3", "Aces 2", "Stack Trainer"]


def test_tab_menu_moves_and_closes(app):
    for kind in (SOLVER, X_TO_Y, TRACKER):
        app.new_tab(kind)
    a, b, c = app.tabs.tabs
    menu = {act.text(): act for act in app.tabs.build_tab_menu(a).actions()}
    assert not menu["Move left"].isEnabled() and menu["Move right"].isEnabled()
    menu["Move right"].trigger()
    assert app.tabs.tabs == [b, a, c]
    menu = {act.text(): act for act in app.tabs.build_tab_menu(a).actions()}
    menu["Close other tabs"].trigger()
    assert app.tabs.tabs == [a]
    menu = {act.text(): act for act in app.tabs.build_tab_menu(a).actions()}
    assert not menu["Close other tabs"].isEnabled()
    menu["Close"].trigger()
    assert app.tabs.tabs == []
