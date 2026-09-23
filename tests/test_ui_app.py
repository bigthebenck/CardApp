"""Smoke tests for the Tk window. Skipped when Tk or a display is unavailable."""

import time

import pytest

tk = pytest.importorskip("tkinter")
tb = pytest.importorskip("ttkbootstrap")

from shuffle_solver import deck, solver  # noqa: E402
from shuffle_solver import shuffle_ops as ops  # noqa: E402
from shuffle_solver.ui import theme  # noqa: E402
from shuffle_solver.ui.app import ShuffleSolverApp  # noqa: E402


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
    t = app.step_list
    return [tuple(t.set(row, col) for col in ("step", "see")) for row in t.get_children()]


def test_preset_add_steps_and_result(app):
    app.load_preset()
    assert app.badge.cget("text") == "PASS"
    app.new_x_var.set("7")
    app._add_step(ops.OUT_FARO)
    app._add_step(ops.OVERHAND_RUN)
    see = app.model.result.start[25].pretty()  # bottom card of the upper half
    assert steps_shown(app) == [("1. Out-Faro", see), ("2. Overhand Run of 7", "")]
    assert app.badge.cget("text") == "PASS"
    assert start_text(app).splitlines()[0].startswith("1.")


def test_reorder_in_ui_changes_result(app):
    app.load_preset()
    app._add_step(ops.OUT_FARO)
    app._add_step(ops.CUT)
    before = start_text(app)
    app._select_step(1)
    app._move_step(-1)
    assert steps_shown(app)[0] == ("1. Cut 5", "")
    assert app._selected_step() == 0  # the moved step stays selected
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


def test_faro_splits_shown_under_step_list(app):
    app._add_step(ops.OUT_FARO)
    assert app.split_label.cget("text") == ""  # no deck yet, so nothing to split
    app.load_preset()
    app._add_step(ops.CUT)
    start = app.model.result.start
    lines = app.split_label.cget("text").splitlines()
    assert lines[0].startswith("Where to split")
    assert lines[1:] == [f"#1  {start[25].pretty():>4} | {start[26].pretty()}"]  # not the cut
    assert steps_shown(app) == [("1. Out-Faro", start[25].pretty()), ("2. Cut 5", "")]


def test_partial_faro_direction_picker(app):
    app.new_x_var.set("9")
    app._add_step(app._partial_kind(True))
    app.partial_dir_var.set("bottom into top")
    app._add_step(app._partial_kind(False))
    assert [step for step, _see in steps_shown(app)] == [
        "1. Partial Out-Faro of top 9 into top", "2. Partial In-Faro of bottom 9 into top"]


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


def test_tabs_present(app):
    tabs = [app.notebook.tab(t, "text") for t in app.notebook.tabs()]
    assert tabs == ["Starting Order", "X to Y"]


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
    app._add_step(ops.OUT_FARO)
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


def test_x_to_y_depth_slider_warns_above_five(app):
    tab = app.x_to_y
    assert tab.depth_var.get() == 5 and "⚠" not in tab.depth_note.cget("text")
    tab.depth_var.set(6)
    tab._on_depth("6")
    assert tab.model.depth == 6
    assert "⚠" in tab.depth_note.cget("text") and "minutes" in tab.depth_note.cget("text")


def test_x_to_y_cancel_long_search(app):
    tab = app.x_to_y
    tab.load_preset("start")
    tab.model.set_cards("end", random_order(5))
    tab.depth_var.set(6)
    tab._on_depth("6")
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
    tab.depth_var.set(6)
    tab._on_depth("6")
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
    tab.depth_var.set(6)
    tab._on_depth("6")
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
