"""Ask GitHub for a newer version and, only if the user agrees, install it.

``UpdateChecker.check`` reads the latest release on a worker thread (the Tk
side polls it, as the X to Y search does). When a newer version exists it
shows ``UpdateDialog``; nothing is downloaded unless the user presses its
install button. The packaged app then downloads the installer, checks its
SHA-256, runs it and quits; a copy run from source opens the release page.
"""

import os
import tempfile
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox

import ttkbootstrap as tb

from .. import __version__, updater
from . import theme

POLL_MS = 100
TITLE = "Check for updates"


class _Worker:
    """Runs ``task(report)`` on a thread; the Tk side polls ``done``."""

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
        self.progress = (done, total)  # a single assignment, read by the Tk thread


def _poll(widget, worker, finish, tick=None):
    """Call ``tick()`` until ``worker`` is done, then ``finish()``, on the Tk thread."""
    if not worker.done.is_set():
        if tick:
            tick()
        widget.after(POLL_MS, lambda: _poll(widget, worker, finish, tick))
        return
    finish()


class UpdateChecker:
    def __init__(self, root, settings_path, fetch=updater.fetch_latest_release,
                 installed=updater.is_installed):
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
                messagebox.showerror(TITLE, str(worker.error), parent=self.root)
            return
        release = worker.result
        if not updater.is_newer(release.version, __version__):
            if manual:
                messagebox.showinfo(TITLE, f"You have the latest version ({__version__}).",
                                    parent=self.root)
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

        win = self.window = tb.Toplevel(self.root)
        win.title("Update available")
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", self.not_now)
        body = tb.Frame(win, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        tb.Label(body, text=f"Version {release.version} is available. You have {__version__}.",
                 font=("TkDefaultFont", 11, "bold")).pack(anchor=tk.W)
        notes = tk.Text(body, width=64, height=12, wrap=tk.WORD)
        notes.insert("1.0", release.notes.strip() or "(No release notes.)")
        notes.config(state=tk.DISABLED)
        notes.pack(fill=tk.BOTH, expand=True, pady=8)

        self.status = tb.Label(body, style="Muted.TLabel", text=(
            "The installer will download, then close and update this app."
            if self.will_install else "This opens the release page, where you can download it."))
        self.status.pack(anchor=tk.W)
        self.progress = tb.Progressbar(body, mode="determinate", maximum=1.0)

        buttons = tb.Frame(body)
        buttons.pack(fill=tk.X, pady=(8, 0))
        self.install_button = tb.Button(
            buttons, bootstyle="success", command=self.install,
            text="Download and install" if self.will_install else "Open release page")
        self.install_button.pack(side=tk.RIGHT)
        self.later_button = tb.Button(buttons, text="Not now", bootstyle="secondary",
                                      command=self.not_now)
        self.later_button.pack(side=tk.RIGHT, padx=6)
        self.skip_button = tb.Button(buttons, text="Skip this version", bootstyle="link",
                                     command=self.skip)
        self.skip_button.pack(side=tk.LEFT)

    def close(self):
        if self.worker is not None:
            self.worker.cancel.set()
        if self.checker.dialog is self:
            self.checker.dialog = None
        self.window.destroy()

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
        self.install_button.config(state=tk.DISABLED)
        self.skip_button.config(state=tk.DISABLED)
        self.later_button.config(text="Cancel")
        self.progress.pack(fill=tk.X, pady=(6, 0), before=self.install_button.master)
        self.status.config(text="Downloading…")
        self.worker = _Worker(self._download)
        # Polled from the root: Cancel closes this window while the worker winds down.
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
        if total and not self.worker.cancel.is_set():
            self.progress.config(value=done / total)
            self.status.config(text=f"Downloading… {done // 1024:,} of {total // 1024:,} KB")

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
            if messagebox.askyesno(TITLE, f"{worker.error}\n\nOpen the release page instead?",
                                   parent=self.root):
                webbrowser.open(self.release.page_url)
            return
        try:
            updater.run_installer(self.installer_path)
        except OSError as exc:
            self.close()
            messagebox.showerror(TITLE, f"Could not start the installer:\n{exc}",
                                 parent=self.root)
            return
        self.root.destroy()  # the installer replaces our files and starts the new version
