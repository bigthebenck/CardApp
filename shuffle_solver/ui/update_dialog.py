"""Ask GitHub for a newer version and, only if the user agrees, install it.

``UpdateChecker.check`` reads the latest release on a worker thread (the Qt
side polls it, as the X to Y search does). When a newer version exists it
shows ``UpdateDialog``; nothing is downloaded unless the user presses its
install button. The packaged app then downloads the installer, checks its
SHA-256, runs it and quits; a copy run from source opens the release page.
"""

import os
import tempfile
import threading
import webbrowser

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

from .. import __version__, updater
from . import dialogs, theme
from .widgets import button, label, row, text_box

POLL_MS = 100
TITLE = "Check for updates"


class _Worker:
    """Runs ``task(report)`` on a thread; the Qt side polls ``done``."""

    def __init__(self, task):
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.progress = (0, None)
        self.result = None
        self.error = None
        threading.Thread(target=self._run, args=(task,), daemon=True).start()

    def _run(self, task):
        try:
            self.result = task(self)
        except updater.DownloadCancelled:
            pass
        except Exception as exc:  # shown to the user instead of dying silently
            self.error = exc
        finally:
            self.done.set()

    def report(self, done, total):
        self.progress = (done, total)  # a single assignment, read by the Qt thread


def _poll(owner, worker, finish, tick=None):
    """Call ``tick()`` until ``worker`` is done, then ``finish()``, on the Qt thread."""
    if not worker.done.is_set():
        if tick:
            tick()
        QTimer.singleShot(POLL_MS, owner, lambda: _poll(owner, worker, finish, tick))
        return
    finish()


class UpdateChecker:
    def __init__(self, root, settings_path, fetch=updater.fetch_latest_release,
                 installed=updater.is_installed):
        """``root``: the main window, which the dialogs sit over and which an
        install closes."""
        self.root = root
        self.settings_path = settings_path
        self.fetch = fetch
        self.installed = installed
        self.dialog = None
        self._worker = None

    @property
    def check_on_startup(self):
        return theme.read_settings(self.settings_path).get("check_updates", True) is not False

    @check_on_startup.setter
    def check_on_startup(self, value):
        theme.write_settings(self.settings_path, check_updates=bool(value))

    @property
    def checking(self):
        return self._worker is not None

    def check(self, manual=True):
        """Look for a newer release; ``manual`` also reports "up to date" and errors."""
        if self._worker is not None:
            return
        worker = self._worker = _Worker(lambda _w: self.fetch())
        _poll(self.root, worker, lambda: self._finish(worker, manual))

    def _finish(self, worker, manual):
        self._worker = None
        if worker.error is not None:
            if manual:
                dialogs.error(self.root, TITLE, str(worker.error))
            return
        release = worker.result
        if not updater.is_newer(release.version, __version__):
            if manual:
                dialogs.info(self.root, TITLE, f"You have the latest version ({__version__}).")
            return
        skipped = theme.read_settings(self.settings_path).get("skip_version")
        if not manual and skipped == release.version:
            return
        if self.dialog is not None:
            self.dialog.close()
        self.dialog = UpdateDialog(self, release)

    def skip(self, version):
        theme.write_settings(self.settings_path, skip_version=version)


class UpdateDialog:
    """"Version X is available" with its notes: Install / Not now / Skip this version."""

    def __init__(self, checker, release):
        self.checker = checker
        self.root = checker.root
        self.release = release
        self.worker = None
        self.installer_path = None
        self.will_install = checker.installed() and release.can_install

        win = self.window = QDialog(self.root)
        win.setWindowTitle("Update available")
        win.rejected.connect(self.not_now)
        layout = QVBoxLayout(win)
        layout.setContentsMargins(16, 16, 16, 16)
        heading = QLabel(f"Version {release.version} is available. You have {__version__}.")
        heading.setStyleSheet("font-weight: 700; font-size: 11pt;")
        layout.addWidget(heading)
        notes = text_box(mono=False, read_only=True)
        notes.setPlainText(release.notes.strip() or "(No release notes.)")
        notes.setMinimumSize(520, 220)
        layout.addWidget(notes, 1)

        self.status = label("The installer will download, then close and update this app."
                            if self.will_install else
                            "This opens the release page, where you can download it.",
                            tone="muted", wrap=True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.install_button = button(
            "Download and install" if self.will_install else "Open release page",
            self.install, kind="primary")
        self.later_button = button("Not now", self.not_now)
        self.skip_button = button("Skip this version", self.skip, kind="link")
        layout.addWidget(row(self.skip_button, None, self.later_button, self.install_button))
        win.show()

    def close(self):
        if self.worker is not None:
            self.worker.cancel.set()
        if self.checker.dialog is self:
            self.checker.dialog = None
        if self.window is not None:
            win, self.window = self.window, None
            win.hide()
            win.deleteLater()

    def not_now(self):
        self.close()

    def skip(self):
        self.checker.skip(self.release.version)
        self.close()

    def install(self):
        if not self.will_install:
            webbrowser.open(self.release.page_url)
            self.close()
            return
        if self.worker is not None:
            return
        self.installer_path = os.path.join(tempfile.gettempdir(), self.release.installer_name)
        self.install_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.later_button.setText("Cancel")
        self.progress.show()
        self.status.setText("Downloading…")
        self.worker = _Worker(self._download)
        # Polled from the main window: Cancel closes this one while the worker winds down.
        _poll(self.root, self.worker, self._downloaded, self._show_progress)

    def _download(self, worker):
        """On the worker thread: fetch the checksum, then the installer, and compare."""
        expected = updater.fetch_checksum(self.release.checksum_url)
        updater.download(self.release.installer_url, self.installer_path, worker.report,
                         worker.cancel.is_set)
        if updater.sha256_of(self.installer_path) != expected:
            raise updater.UpdateError("The downloaded installer is damaged (its checksum "
                                      "doesn't match). Nothing was installed.")

    def _show_progress(self):
        done, total = self.worker.progress
        if total and not self.worker.cancel.is_set() and self.window is not None:
            self.progress.setValue(round(done / total * 1000))
            self.status.setText(f"Downloading… {done // 1024:,} of {total // 1024:,} KB")

    def _downloaded(self):
        worker, self.worker = self.worker, None
        if worker.cancel.is_set() or worker.error is not None:
            try:
                os.remove(self.installer_path)
            except OSError:
                pass
        if worker.cancel.is_set():
            return  # the window is already closed
        if worker.error is not None:
            self.close()
            if dialogs.ask_yes_no(self.root, TITLE,
                                  f"{worker.error}\n\nOpen the release page instead?"):
                webbrowser.open(self.release.page_url)
            return
        try:
            updater.run_installer(self.installer_path)
        except OSError as exc:
            self.close()
            dialogs.error(self.root, TITLE, f"Could not start the installer:\n{exc}")
            return
        self.close()
        self.root.close()  # the installer replaces our files and starts the new version
