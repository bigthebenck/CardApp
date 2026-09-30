"""Smoke tests for the Tk window. Skipped when Tk or a display is unavailable."""

import time

import pytest

tk = pytest.importorskip("tkinter")
tb = pytest.importorskip("ttkbootstrap")

from shuffle_solver import deck, solver  # noqa: E402
from shuffle_solver import shuffle_ops as ops  # noqa: E402
from shuffle_solver.ui import theme  # noqa: E402
from shuffle_solver.ui.app import ShuffleSolverApp  # noqa: E402
from shuffle_solver.ui.model import format_table  # noqa: E402


def _forget_failed_root():
    """Drop the Style a half-built ``tb.Window`` left behind.

    Otherwise it stays bound to that root, and every later window is refused
    with "ttkbootstrap supports a single application root window".
    """
    style = tb.Style.get_instance()
    master = getattr(style, "master", None)
    tb.Style.instance = None
    if master is not None:
        try:
            master.destroy()
        except tk.TclError:
            pass


@pytest.fixture
def root():
    try:
        root = tb.Window()
    except tk.TclError as exc:
        _forget_failed_root()
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(root):
    return ShuffleSolverApp(root)


def wait_for_search(tab, timeout=60):
    end = time.monotonic() + timeout
    while tab.searching:
        assert time.monotonic() < end, "search did not finish"
        tab.frame.update()
        time.sleep(0.02)


def start_text(app):
    return app.start_text.get("1.0", "end").strip()


def steps_shown(app):
    """The step table's rows as (shuffle, card you see) pairs."""
    t = app.sequence.step_list
    return [tuple(t.set(row, col) for col in ("step", "see")) for row in t.get_children()]


def test_preset_add_steps_and_result(app):
    app.load_preset()
    assert app.badge.cget("text") == "PASS"
    app.sequence.new_x_var.set("7")
    app.sequence.add_step(ops.OUT_FARO)
    app.sequence.add_step(ops.OVERHAND_RUN)
    see = app.model.result.start[25].pretty()  # bottom card of the upper half
    assert steps_shown(app) == [("1. Out-Faro", see), ("2. Overhand Run of 7", "")]
    assert app.badge.cget("text") == "PASS"
    assert start_text(app).splitlines()[0].startswith("1.")


def test_reorder_in_ui_changes_result(app):
    app.load_preset()
    app.sequence.add_step(ops.OUT_FARO)
    app.sequence.add_step(ops.CUT)
    before = start_text(app)
    app.sequence.select_step(1)
    app.sequence._move_step(-1)
    assert steps_shown(app)[0] == ("1. Cut 5", app.model.result.start[4].pretty())
    assert app.sequence.selected_step() == 0  # the moved step stays selected
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
    app.sequence.add_step(ops.IN_FARO)
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
    app.sequence.add_step(ops.CUT)
    app.sequence.select_step(0)
    app.sequence.edit_x_var.set("26")
    app.sequence.commit_edit_x()
    assert app.model.steps[0].x == 26
    app.sequence.edit_x_var.set("52")
    app.sequence.commit_edit_x()
    assert app.model.steps[0].x == 26
    assert "Invalid X" in app.sequence.seq_error.cget("text")


def test_faro_splits_shown_under_step_list(app):
    app.sequence.add_step(ops.OUT_FARO)
    assert app.sequence.split_label.cget("text") == ""  # no deck yet, so nothing to split
    app.load_preset()
    app.sequence.add_step(ops.CUT)
    app.sequence.add_step(ops.OVERHAND_RUN)
    start, mid = app.model.result.start, app.model.result.states[1]
    lines = app.sequence.split_label.cget("text").splitlines()
    assert lines[0].startswith("Where to split")
    assert lines[1:] == [f"#1  {start[25].pretty():>4} | {start[26].pretty()}",
                         f"#2  {mid[4].pretty():>4} | {mid[5].pretty()}"]  # not the run
    assert steps_shown(app) == [("1. Out-Faro", start[25].pretty()),
                                ("2. Cut 5", mid[4].pretty()), ("3. Overhand Run of 5", "")]


def test_partial_faro_direction_picker(app):
    app.sequence.new_x_var.set("9")
    app.sequence.add_step(app.sequence.partial_kind(True))
    app.sequence.partial_dir_var.set("bottom into top")
    app.sequence.add_step(app.sequence.partial_kind(False))
    assert [step for step, _see in steps_shown(app)] == [
        "1. Partial Out-Faro of top 9 into top", "2. Partial In-Faro of bottom 9 into top"]


def test_preview_toggle(app):
    app.load_preset()
    app.sequence.add_step(ops.OUT_FARO)
    app.preview_var.set(True)
    app._toggle_preview()
    text = app.preview_text.get("1.0", "end")
    assert "Out-Faro" in text and len(text.splitlines()) >= 53


def test_copy_shorthand_parses_back(app):
    app.load_preset()
    app.sequence.add_step(ops.OUT_FARO)
    text = app._start_shorthand()
    assert deck.parse_cards(text) == app.model.result.start


def test_tabs_present(app):
    tabs = [app.notebook.tab(t, "text") for t in app.notebook.tabs()]
    assert tabs == ["Starting Order", "X to Y", "Free Tracking", "Stack Trainer", "Stacking"]


def test_x_to_y_tab_finds_shuffles(app):
    tab = app.x_to_y
    tab.load_preset("start")
    tab.texts["end"].delete("1.0", "end")
    tab.texts["end"].insert("1.0", deck.format_cards(
        solver.simulate(deck.PRESETS["New deck order"], [solver.Step(ops.IN_FARO)])))
    tab.solve()  # parses the pending text first
    assert tab.searching and str(tab.find_button.cget("state")) == "disabled"
    wait_for_search(tab)
    assert str(tab.find_button.cget("state")) == "normal"
    assert tab.badge.cget("text") == "PASS"
    assert tab.steps_text.get("1.0", "end").strip() == "1. In-Faro  (split K♣|K♦)"
    assert "1. In-Faro" in tab._instructions()


def test_x_to_y_swap_keeps_typed_text(app):
    tab = app.x_to_y
    tab.texts["start"].insert("1.0", "A-KCHSD")
    tab.apply_text("start")
    tab.load_preset("end")
    tab.swap()
    assert tab.texts["end"].get("1.0", "end").strip() == "A-KCHSD"
    assert tab.model.cards["end"] == deck.parse_cards("A-KCHSD")
    assert tab.badge.cget("text") == "WAITING"


def images_on(viewer):
    c = viewer.canvas
    return [item for item in c.find_all() if c.type(item) == "image"]


def test_card_image_for_every_card():
    from shuffle_solver.ui.card_viewer import image_path

    for key in deck.FULL_DECK_KEYS:
        assert image_path(deck.Card(key[0], key[1])).is_file(), key


def test_view_final_cards_follows_edits(app):
    app.load_preset()
    viewer = app.viewers.open("final", "Final deck", lambda: app.model.slots)
    assert len(images_on(viewer)) == 52
    app.model.set_slot(51, None)  # trailing empty slot is dropped
    assert len(images_on(viewer)) == 51
    app.model.set_slot(0, None)  # inner empty slot is drawn as a placeholder
    assert len(images_on(viewer)) == 50
    assert "50 cards" in viewer.summary.cget("text")
    viewer.close()
    app.model.clear_final()  # refresh with the popup closed must not fail
    assert app.viewers.get("final") is None


def test_view_final_cards_uses_pending_text(app):
    app.final_text.insert("1.0", "AC`, 2H")
    app._on_text_modified(None)  # debounce scheduled, not yet applied
    app.view_final_cards()
    viewer = app.viewers.get("final")
    assert len(images_on(viewer)) == 2
    assert "1 face up" in viewer.summary.cget("text")
    app.view_final_cards()  # a second click reuses the same window
    assert app.viewers.get("final") is viewer


def test_view_start_cards(app):
    app.view_start_cards()
    viewer = app.viewers.get("start")
    assert images_on(viewer) == []
    app.load_preset()
    app.sequence.add_step(ops.OUT_FARO)
    assert len(images_on(viewer)) == 52


def test_x_to_y_view_cards(app):
    tab = app.x_to_y
    tab.load_preset("start")
    tab.view_cards("start")
    tab.view_cards("end")
    assert len(images_on(tab.viewers.get("start"))) == 52
    assert images_on(tab.viewers.get("end")) == []
    tab.swap()
    assert images_on(tab.viewers.get("start")) == []
    assert len(images_on(tab.viewers.get("end"))) == 52


def random_order(seed):
    cards = list(deck.PRESETS["New deck order"])
    __import__("random").Random(seed).shuffle(cards)
    return cards


def test_x_to_y_depth_slider_warns_above_six(app):
    tab = app.x_to_y
    assert tab.depth_var.get() == 5 and "⚠" not in tab.depth_note.cget("text")
    tab.depth_var.set(6)
    tab._on_depth("6")
    assert tab.model.depth == 6 and "⚠" not in tab.depth_note.cget("text")
    tab.depth_var.set(7)
    tab._on_depth("7")
    assert tab.model.depth == 7
    assert "⚠" in tab.depth_note.cget("text") and "minutes" in tab.depth_note.cget("text")


def test_x_to_y_cancel_long_search(app):
    tab = app.x_to_y
    tab.load_preset("start")
    tab.model.set_cards("end", random_order(5))
    tab.depth_var.set(7)
    tab._on_depth("7")
    tab.solve()
    assert tab.progress_row.winfo_manager() == "pack"
    tab.cancel_search()
    wait_for_search(tab)
    assert tab.progress_row.winfo_manager() == ""
    assert tab.badge.cget("text") == "WAITING"
    assert "cancelled" in tab.result_msg.cget("text")


def test_x_to_y_edit_during_search_cancels_it(app):
    tab = app.x_to_y
    tab.load_preset("start")
    tab.model.set_cards("end", random_order(6))
    tab.depth_var.set(7)
    tab._on_depth("7")
    tab.solve()
    job = tab._job
    tab.load_preset("end")  # a different ending order
    assert job.cancel.is_set()
    wait_for_search(tab)
    assert tab.badge.cget("text") == "WAITING" and not tab.model.outcome.has_answer


def test_theme_menu_switches_and_remembers_theme(root, tmp_path):
    path = tmp_path / "settings.json"
    a = ShuffleSolverApp(root, settings_path=path)
    assert tb.Style().theme_use() == f"{theme.DEFAULT_FAMILY}-light"
    a.theme_var.set("nord")
    a.set_theme()
    a.toggle_dark()
    assert tb.Style().theme_use() == "nord-dark"
    assert theme.ThemeChoice.load(path) == theme.ThemeChoice("nord", True)
    a.load_preset()
    assert a.badge.cget("text") == "PASS"
    assert str(a.badge.cget("style")) == "@success.TLabel"


def test_theme_settings_fall_back_to_default(root, tmp_path):
    path = tmp_path / "settings.json"
    assert theme.ThemeChoice.load(path) == theme.ThemeChoice()  # missing
    for bad in ("not json", '{"theme": "no-such", "dark": false}', '{"theme": "nord"}',
                '{"theme": "nord", "dark": "yes"}'):
        path.write_text(bad, encoding="utf-8")
        assert theme.ThemeChoice.load(path) == theme.ThemeChoice()
    assert theme.DEFAULT_FAMILY in theme.families() and "nord" in theme.families()


def test_card_viewer_felt_survives_theme_switch(app):
    from shuffle_solver.ui.card_viewer import FELT_COLOR
    app.load_preset()
    app.view_final_cards()
    app.dark_var.set(True)
    app.set_theme()
    assert app.viewers.get("final").canvas.cget("background") == FELT_COLOR


def test_export_writes_file_and_confirms(app, tmp_path, monkeypatch):
    from shuffle_solver.ui import app as app_module
    shown = []
    monkeypatch.setattr(app_module.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *a, **k: shown.append(a))
    path = tmp_path / "start.txt"
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", lambda **k: str(path))
    monkeypatch.setattr(app, "_ask_export_notes", lambda: "")
    app.load_preset()
    app.model.add_step(solver.Step(ops.OUT_FARO), 0)
    app.export_start()
    text = path.read_text(encoding="utf-8")
    assert "Shuffle sequence:\n 1. Out-Faro  (split " in text
    assert "A is the card you see on the bottom of the upper packet" in text
    assert "Notes:" not in text
    assert shown == [("Export", f"Saved to {path}")]

    shown.clear()
    monkeypatch.setattr(app, "_ask_export_notes", lambda: "Force the 7S.\nSecond line")
    app.export_start()
    assert path.read_text(encoding="utf-8").endswith("\nNotes:\nForce the 7S.\nSecond line\n")

    shown.clear()
    path.unlink()
    monkeypatch.setattr(app, "_ask_export_notes", lambda: None)  # cancelled
    app.export_start()
    assert not path.exists() and shown == []
    monkeypatch.setattr(app, "_ask_export_notes", lambda: "")

    shown.clear()
    bad = tmp_path / "no-such-dir" / "start.txt"
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", lambda **k: str(bad))
    app.export_start()
    assert shown[0][0] == "Export" and "Could not save" in shown[0][1]


def test_x_to_y_shows_best_so_far_and_keeps_it_on_cancel(app):
    tab = app.x_to_y
    tab.load_preset("start")
    tab.model.set_cards("end", random_order(7))
    tab.depth_var.set(7)
    tab._on_depth("7")
    tab.solve()
    end = time.monotonic() + 60
    while tab.model.outcome.status != "searching":
        assert tab.searching and time.monotonic() < end, "no best-so-far route shown"
        tab.frame.update()
        time.sleep(0.02)
    assert tab.badge.cget("text") == "SEARCHING"
    assert "Best so far" in tab.result_msg.cget("text")
    shown = tab._instructions()
    assert shown.startswith(" 1.")
    tab.cancel_search()
    wait_for_search(tab)
    assert tab.badge.cget("text") == "PASS"
    assert "cancelled" in tab.result_msg.cget("text")
    assert tab._instructions() == shown


# --- update check ---------------------------------------------------------------------

def newer_release():
    from shuffle_solver import updater
    return updater.Release("99.0.0", "https://example/releases/v99", "Notes",
                           "https://dl/CardApp-Setup-99.0.0.exe", "CardApp-Setup-99.0.0.exe",
                           "https://dl/CardApp-Setup-99.0.0.exe.sha256")


def update_checker(root, tmp_path, release, installed=False):
    from shuffle_solver.ui.update_dialog import UpdateChecker

    def fetch():
        if isinstance(release, Exception):
            raise release
        return release
    return UpdateChecker(root, tmp_path / "settings.json", fetch, lambda: installed)


def wait_for_check(checker, timeout=10):
    end = time.monotonic() + timeout
    while checker.checking:
        assert time.monotonic() < end, "update check did not finish"
        checker.root.update()
        time.sleep(0.02)


@pytest.fixture
def dialogs(monkeypatch):
    """Record message boxes instead of showing them."""
    from shuffle_solver.ui import update_dialog
    shown = []
    for name in ("showinfo", "showerror"):
        monkeypatch.setattr(update_dialog.messagebox, name,
                            lambda title, msg, name=name, **kw: shown.append((name, msg)))
    monkeypatch.setattr(update_dialog.messagebox, "askyesno",
                        lambda title, msg, **kw: shown.append(("askyesno", msg)) or False)
    return shown


def test_update_check_is_off_unless_asked_for(app):
    assert not app.updates.checking and app.updates.dialog is None


def test_manual_update_check_reports_up_to_date_and_errors(root, tmp_path, dialogs):
    from shuffle_solver import __version__, updater
    checker = update_checker(root, tmp_path, updater.Release(__version__, "u", ""))
    checker.check()
    wait_for_check(checker)
    assert dialogs == [("showinfo", f"You have the latest version ({__version__}).")]
    assert checker.dialog is None

    dialogs.clear()
    checker = update_checker(root, tmp_path, updater.UpdateError("offline"))
    checker.check(manual=False)
    wait_for_check(checker)
    assert dialogs == []  # startup checks fail quietly
    checker.check()
    wait_for_check(checker)
    assert dialogs == [("showerror", "offline")]


def test_newer_version_offers_update_and_can_be_skipped(root, tmp_path, dialogs):
    checker = update_checker(root, tmp_path, newer_release())
    checker.check(manual=False)
    wait_for_check(checker)
    dialog = checker.dialog
    assert dialog is not None and not dialog.will_install  # not the packaged app
    assert dialog.install_button.cget("text") == "Open release page"
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
    assert dialogs == []


def test_update_settings_keep_the_theme(root, tmp_path):
    checker = update_checker(root, tmp_path, newer_release())
    theme.ThemeChoice("nord", True).save(checker.settings_path)
    assert checker.check_on_startup
    checker.check_on_startup = False
    checker.skip("2.0.0")
    assert not checker.check_on_startup
    assert theme.ThemeChoice.load(checker.settings_path) == theme.ThemeChoice("nord", True)


def test_install_downloads_verifies_runs_installer_and_quits(root, tmp_path, dialogs,
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
    monkeypatch.setattr(root, "destroy", lambda: quit_.append(True))

    checker = update_checker(root, tmp_path, newer_release(), installed=True)
    checker.check()
    wait_for_check(checker)
    dialog = checker.dialog
    assert dialog.will_install and dialog.install_button.cget("text") == "Download and install"
    dialog.install()
    end = time.monotonic() + 10
    while not quit_:
        assert time.monotonic() < end, "install did not finish"
        root.update()
        time.sleep(0.02)
    assert ran == [str(tmp_path / "CardApp-Setup-99.0.0.exe")]
    assert dialogs == []
    dialog.window.destroy()


def test_damaged_download_is_deleted_and_not_run(root, tmp_path, dialogs, monkeypatch):
    from shuffle_solver import updater
    from shuffle_solver.ui import update_dialog
    monkeypatch.setattr(update_dialog.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater, "fetch_checksum", lambda url: "0" * 64)
    monkeypatch.setattr(updater, "download",
                        lambda url, dest, progress, cancelled: open(dest, "wb").close())
    ran = []
    monkeypatch.setattr(updater, "run_installer", ran.append)

    checker = update_checker(root, tmp_path, newer_release(), installed=True)
    checker.check()
    wait_for_check(checker)
    dialog = checker.dialog
    dialog.install()
    end = time.monotonic() + 10
    while dialog.worker is not None:
        assert time.monotonic() < end, "install did not finish"
        root.update()
        time.sleep(0.02)
    assert ran == [] and checker.dialog is None
    assert not (tmp_path / "CardApp-Setup-99.0.0.exe").exists()
    assert dialogs and dialogs[0][0] == "askyesno" and "damaged" in dialogs[0][1]


def test_add_and_edit_packet_run(app):
    app.load_preset()
    app.sequence.new_x_var.set("10")
    app.sequence.new_y_var.set("")
    app.sequence.add_step(ops.PACKET_RUN)
    app.sequence.new_y_var.set("3")
    app.sequence.add_step(ops.PACKET_RUN)
    assert [s for s, _see in steps_shown(app)] == ["1. Packet Run: reverse top 10",
                                                   "2. Packet Run: pick up 10, run 3"]
    assert app.badge.cget("text") == "PASS"
    app.sequence.select_step(0)
    assert str(app.sequence.edit_y.cget("state")) == "normal" and app.sequence.edit_y_var.get() == ""
    app.sequence.edit_y_var.set("4")
    app.sequence.commit_edit_y()
    assert app.model.steps[0] == solver.Step(ops.PACKET_RUN, 10, 4)
    app.sequence.edit_y_var.set("11")
    app.sequence.commit_edit_y()
    assert "Invalid Y" in app.sequence.seq_error.cget("text")
    app.sequence.new_y_var.set("12")
    app.sequence.add_step(ops.PACKET_RUN)
    assert "Can't add step" in app.sequence.seq_error.cget("text") and len(app.model.steps) == 2
    app.sequence.add_step(ops.CUT)  # Y is ignored for other shuffles; goes after the selected step
    assert app.model.steps[1] == solver.Step(ops.CUT, 10)
    app.sequence.select_step(1)
    assert str(app.sequence.edit_y.cget("state")) == "disabled"


def shown(tab, side):
    return tab.boxes[side].cget("text"), tab.views[side].get("1.0", "end-1c")


def test_tracker_shows_whole_run_or_one_step(app):
    tab = app.tracker
    assert "Enter a deck" in shown(tab, "before")[1]
    tab.preset_var.set("New deck order")
    tab.load_preset()
    tab.sequence.add_step(ops.OUT_FARO)
    tab.sequence.new_x_var.set("10")
    tab.sequence.add_step(ops.CUT)
    states = tab.model.states
    # A newly added step is selected, so the sides show its before and after.
    assert shown(tab, "before") == ("Before #2: Cut 10", format_table(states[1]))
    assert shown(tab, "after") == ("After #2: Cut 10", format_table(states[2]))
    tab.sequence.select_step(0)
    assert shown(tab, "before") == ("Before #1: Out-Faro", format_table(states[0]))
    assert tab.shorthand("after") == deck.format_cards(list(states[1].pile("A").cards))
    tab.show_whole_run()
    assert shown(tab, "before") == ("Starting order", format_table(states[0]))
    assert shown(tab, "after") == ("After all 2 steps", format_table(states[2]))
    cards = states[0].pile("A").cards
    see = f"{cards[25].pretty()} | {cards[26].pretty()}"  # the faro's split: both cards
    t = tab.sequence.step_list
    assert [t.set(row, "see") for row in t.get_children()][0] == see


def test_tracker_typed_deck_and_card_viewer(app):
    tab = app.tracker
    tab.deck_text.insert("1.0", "A-KH, A-KC, K-AD, K-AS")
    tab.frame.update()  # lets the box report the edit, starting the debounce
    tab.sequence.add_step(ops.OUT_FARO)
    tab.view_cards("after")  # applies the pending text first
    assert tab.model.cards == deck.PRESETS["New deck order"]
    assert tab._shown["after"] == tab.model.states[1]
    tab.show_whole_run()
    assert tab.viewers.get("after").win.title() == "After all 1 step"


def test_tracker_view_buttons_stay_visible_in_a_small_window(root):
    root.deiconify()
    root.geometry("1200x700")
    app = ShuffleSolverApp(root)
    app.notebook.select(app.tracker.frame)
    root.update()
    for side in ("before", "after"):
        frame = app.tracker.boxes[side]
        buttons = [w for row in frame.winfo_children() for w in row.winfo_children()
                   if isinstance(w, tb.Button)]
        assert [b.cget("text") for b in buttons] == ["Copy shorthand", "View cards"]
        for b in buttons:
            assert b.winfo_ismapped()
            assert b.winfo_rooty() + b.winfo_height() <= root.winfo_rooty() + root.winfo_height()


def test_tracker_aces_example_with_card_and_packet_steps(app):
    tab, seq = app.tracker, app.tracker.sequence
    tab.deck_text.insert("1.0", "AC, AH, AS, AD, 2-KC, 2-KH, 2-KS, 2-KD")
    tab.apply_text()
    tab.sizes_var.set("1,1,1,1, 12 12 12 12")
    assert tab.split()
    assert tab.model.piles_at(1) == list("ABCDEFGH")
    assert list(tab.place_pile_box["values"]) == list("ABCDEFGH")
    for pile, onto in zip("EFGH", "ABCD"):
        tab.place_pile_var.set(pile)
        tab.place_onto_var.set(onto)
        assert tab.place()
    tab.gather_var.set("a b c d")
    assert tab.gather()
    assert [t.split(". ", 1)[1] for t in (seq.step_list.set(r, "step")
                                           for r in seq.step_list.get_children())] == [
        "Split pile A into 1, 1, 1, 1, 12, 12, 12, 12", "Put pile E on top of pile A",
        "Put pile F on top of pile B", "Put pile G on top of pile C",
        "Put pile H on top of pile D", "Gather piles A, B, C, D"]
    assert tab.shorthand("after") == deck.format_cards(deck.parse_cards(
        "2-KC, AC, 2-KH, AH, 2-KS, AS, 2-KD, AD"))
    seq.select_step(0)
    assert shown(tab, "after")[1].count("Pile ") == 8
    assert len(tab._groups("after")) == 8
    tab.view_cards("after")  # the grouped popup draws without trouble
    assert "in 8 piles" in tab.viewers.get("after").summary.cget("text")


def test_tracker_card_steps_and_the_odd_pile_rule(app):
    tab, seq = app.tracker, app.tracker.sequence
    tab.load_preset()
    tab.cards_var.set("AS")
    assert tab.take_out("discard")  # 51 cards left
    assert "Odd number of cards (51): partial faros only." == seq.odd_note.cget("text")
    assert [str(b.cget("state")) for b in seq.faro_buttons] == ["disabled", "disabled"]
    assert tab.take_out("pile") is False  # they're gone now
    assert "not on the table" in seq.seq_error.cget("text")
    tab.add_pos_var.set("26")
    assert tab.add_cards()
    assert [str(b.cget("state")) for b in seq.faro_buttons] == ["normal", "normal"]
    assert tab.model.states[-1].pile("A").cards[25] == deck.parse_cards("AS")[0]
    seq.add_step(ops.OUT_FARO)
    assert len(tab.model.steps) == 3
    seq.select_step(0)  # now the faro is on 51 cards: refused, and the button is off
    assert str(seq.faro_buttons[0].cget("state")) == "disabled"
    seq.add_step(ops.OUT_FARO)
    assert len(tab.model.steps) == 3 and "full faro needs an even" in seq.seq_error.cget("text")
    seq.select_step(1)
    seq._delete_step()  # the faro after it is now on 51 cards and can't be done
    rows = [seq.step_list.set(r, "step") for r in seq.step_list.get_children()]
    assert rows[1].startswith("⚠ 2. Out-Faro")
    assert "Step 2 can't be done" in seq.seq_error.cget("text")
    tab.show_whole_run()
    assert shown(tab, "after")[1].startswith("Step 2 can't be done")


def test_tracker_names_x_cards(app):
    tab = app.tracker
    tab.model.set_from_text("AC, X3")
    tab.cards_var.set("KS")
    tab.name_pos_var.set("1")
    assert tab.name_cards() is False and "not an X card" in tab.sequence.seq_error.cget("text")
    tab.name_pos_var.set("3")
    assert tab.name_cards()
    assert [str(c) for c in tab.model.states[-1].pile("A").cards] == ["AC", "X", "KS", "X"]


def test_tracker_rearrange_dialog_adds_and_edits_a_step(app):
    tab = app.tracker
    tab.load_preset()
    dialog = tab.open_rearrange()
    assert dialog.text.get("1.0", "end-1c") == deck.format_cards(tab.model.cards)  # prefilled
    dialog.title_var.set("Card revelations")
    dialog.set_text("A-KH, A-KC | K-AD, K-AS`")
    assert "26 cards" not in dialog.status.cget("text")
    assert dialog.status.cget("text") == "✓ 52 cards in 2 piles"
    assert dialog.ok() and tab.dialog is None
    step = tab.model.steps[0]
    assert step.label() == "Rearrange: Card revelations (2 piles)"
    assert shown(tab, "after")[1].startswith("Pile A \u2014 26 cards")
    assert tab.shorthand("after") == "A: A-KH, A-KC |\nB: K-AD, K-AS`"
    dialog = tab.open_rearrange(0)  # edit it: prefilled with what was typed
    assert dialog.title_var.get() == "Card revelations"
    dialog.set_text("A-KH, A-KC, K-AD")  # 13 cards short
    assert "missing" in dialog.status.cget("text") and dialog.ok() is False
    dialog.set_text("A-KH, A-KC, K-AD, K-AS")  # back to one pile
    assert dialog.ok()
    assert len(tab.model.steps) == 1 and tab.model.states[1].names == ["A"]


def test_tracker_groups_steps_by_range(app):
    tab, seq = app.tracker, app.tracker.sequence
    tab.load_preset()
    for x in range(1, 6):
        seq.new_x_var.set(str(x))
        seq.add_step(ops.CUT)
    seq.select_step(None)
    assert tab.open_group_dialog() is None and "select the steps" in seq.seq_error.cget("text")
    seq.select_range(1, 3)
    assert seq.selected_range() == (1, 3) and seq.selected_step() is None
    assert shown(tab, "before")[0] == "Before #2\u2013#4"
    dialog = tab.open_group_dialog()
    dialog.title_var.set("Trick 1")
    dialog.color_var.set("Red")
    assert dialog.ok()
    t = seq.step_list
    assert t.get_children() == ("s0", "g1", "s4")
    assert t.get_children("g1") == ("s1", "s2", "s3")
    assert t.set("g1", "step") == "Trick 1   (#2\u2013#4)"
    assert str(t.tag_configure("g1", "background")) == theme.tint("Red", 0.55)
    t.selection_set(["g1"])
    tab.frame.update()
    assert seq.selected_range() == (1, 3)
    assert shown(tab, "after")[0] == "After Trick 1 (#2\u2013#4)"
    seq.new_x_var.set("7")
    seq.add_step(ops.CUT)  # goes after the group, outside it
    assert t.get_children("g1") == ("s1", "s2", "s3") and seq.selected_step() == 4
    t.item("g1", open=False)  # folded groups stay folded
    seq.select_step(0)
    seq.add_step(ops.OUT_FARO)  # before the group: its rows move down
    assert t.get_children("g1") == ("s2", "s3", "s4") and not t.item("g1", "open")
    t.selection_set(["g1"])
    dialog = tab.open_group_dialog()  # a selected group is edited, not regrouped
    assert dialog.title_var.get() == "Trick 1"
    dialog.ungroup()
    assert tab.model.groups == [] and t.get_children() == tuple(f"s{i}" for i in range(7))


def test_open_puts_each_kind_of_file_in_its_tab(app, tmp_path):
    tab = app.tracker
    tab.load_preset()
    tab.sequence.add_step(ops.OUT_FARO)
    tab.sequence.select_range(0, 0)
    tab.open_group_dialog().ok()
    project = tmp_path / "project.json"
    tab.model.save(project)
    app.model.load_preset("New deck order")
    setup = tmp_path / "setup.json"
    app.model.save(setup)

    fresh = ShuffleSolverApp(tk.Toplevel(app.root))
    fresh.open_path(str(project))
    assert fresh.notebook.select() == str(fresh.tracker.frame)
    assert fresh.tracker.model.steps == tab.model.steps
    assert fresh.tracker.sequence.step_list.get_children() == ("g1",)
    assert fresh.tracker.deck_text.get("1.0", "end-1c") == deck.format_cards(tab.model.cards)
    fresh.open_path(str(setup))
    assert fresh.notebook.index(fresh.notebook.select()) == 0
    assert fresh.model.slots == app.model.slots


def test_trainer_asks_checks_and_scores(app):
    tab = app.trainer
    assert tab.question_label.cget("text") == "No cards yet."
    assert str(tab.answer_entry.cget("state")) == "disabled"
    tab.deck_text.insert("1.0", "A-KH")
    tab.frame.update()
    tab.apply_text()
    assert tab.last_var.get() == "13" and tab.range_total.cget("text") == "of 13"
    tab.first_var.set("2")
    tab.last_var.set("5")
    assert tab.apply_range() and (tab.model.first, tab.model.last) == (2, 5)
    q = tab.model.question
    assert tab.question_label.cget("text") == q.prompt()
    tab.answer_var.set(str(q.answer) if q.kind == "position_of" else q.answer.pretty())
    assert tab.submit().correct
    assert tab.feedback.cget("text").startswith("✓") and tab.answer_var.get() == ""
    assert tab.give_up() is not None
    assert tab.feedback.cget("text").startswith("✗")
    assert tab.stats_label.cget("text").startswith("Session: 1 / 2 right (50%)")
    tab.answer_var.set("")
    assert tab.submit() is None and tab.model.asked == 2
    assert tab.feedback.cget("text").startswith("⚠")
    tab.answer_var.set("nonsense")
    assert not tab.submit().correct and tab.model.asked == 3
    assert tab.feedback.cget("text").startswith("✗ You said nonsense.")
    tab.first_var.set("9")
    assert not tab.apply_range() and tab.range_error.cget("text")
    tab.whole_deck()
    assert (tab.model.first, tab.model.last) == (1, 13) and not tab.range_error.cget("text")
    tab.model.reset_stats()
    assert tab.stats_label.cget("text") == "Session: no answers yet"



def test_stacking_tab_builds_a_stack_and_hands_it_on(app):
    tab = app.stacking
    tab.players_var.set("2")
    assert tab.apply_players()
    assert list(tab.hand_vars) == ["Player 1", "Player 2", "Flop", "Turn", "River"]
    tab.hand_vars["Player 2"].set("AS, AH")
    tab.hand_vars["Flop"].set("AD, AC, 2S")
    text = tab.stack_text.get("1.0", "end")
    assert " 2. A♠   Player 2 (dealer), card 1" in text
    assert " 6. A♦   Flop, card 1" in text

    tab.hand_vars["Turn"].set("AS")
    assert "Wanted twice" in tab.summary.cget("text")
    assert str(tab.final_button.cget("state")) == "disabled"
    tab.hand_vars["Turn"].set("")

    tab.model.set_game("five_card")
    assert list(tab.hand_vars) == ["Player 1", "Player 2"]
    assert tab.hand_vars["Player 2"].get() == "AS, AH"
    assert str(tab.burns_check.cget("state")) == "disabled"

    tab.send_to_final()
    assert app.notebook.index(app.notebook.select()) == 0
    assert app.model.slots[1].key == "AS" and app.model.slots[3].key == "AH"
    assert app.badge.cget("text") == "PASS"


def test_stacking_tab_rejects_bad_player_count(app):
    tab = app.stacking
    tab.players_var.set("11")
    assert not tab.apply_players()
    assert "2 to 10" in tab.players_error.cget("text")
    assert tab.model.players == 4
