"""Check GitHub Releases for a newer version, and fetch its installer on request.

Nothing here runs by itself: ``fetch_latest_release`` only reads the release's
metadata, and the installer is downloaded only when the UI calls ``download``
after the user agreed. Releases are tagged ``v<version>`` and carry two
assets, ``CardApp-Setup-<version>.exe`` and ``<that name>.sha256``, both made
by ``.github/workflows/release.yml``.
"""

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

REPO = "bigthebenck/CardApp"
API_URL = "https://api.github.com/repos/{repo}/releases/latest"
INSTALLER_PREFIX = "CardApp-Setup-"
CHUNK = 64 * 1024


class UpdateError(Exception):
    """The check or download failed; the message is fit to show the user."""


class DownloadCancelled(Exception):
    pass


def parse_version(text):
    """``"v1.2.3"`` or ``"1.2.3"`` -> ``(1, 2, 3)``; None if it isn't a version."""
    parts = text.strip().removeprefix("v").split(".")
    if not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def is_newer(latest, current=__version__):
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))  # so 1.2 == 1.2.0
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def is_installed():
    """True in the packaged app, where running a newer installer updates this copy."""
    return getattr(sys, "frozen", False)


@dataclass
class Release:
    version: str  # without the "v"
    page_url: str
    notes: str
    installer_url: str | None = None
    installer_name: str | None = None
    checksum_url: str | None = None

    @property
    def can_install(self):
        return self.installer_url is not None and self.checksum_url is not None


def parse_release(data):
    """A ``Release`` from the GitHub API's JSON for one release."""
    try:
        version = data["tag_name"].strip().removeprefix("v")
        release = Release(version, data["html_url"], data.get("body") or "")
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    except (KeyError, TypeError, AttributeError) as exc:
        raise UpdateError("GitHub sent a release description this app can't read.") from exc
    for name, url in assets.items():
        if name.startswith(INSTALLER_PREFIX) and name.endswith(".exe"):
            release.installer_url, release.installer_name = url, name
            release.checksum_url = assets.get(name + ".sha256")
            break
    return release


def _open(url, timeout):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"CardApp/{__version__}",
    })
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_latest_release(repo=REPO, timeout=5, opener=_open):
    """The newest published release (drafts and pre-releases are skipped by GitHub)."""
    try:
        with opener(API_URL.format(repo=repo), timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No releases have been published yet.") from exc
        raise UpdateError(f"GitHub answered with an error ({exc.code}).") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError("Could not reach GitHub. Check your internet connection.") from exc
    except ValueError as exc:
        raise UpdateError("GitHub sent a reply this app can't read.") from exc
    return parse_release(data)


def download(url, dest, progress=None, cancelled=lambda: False, timeout=30, opener=_open):
    """Save ``url`` to ``dest``, calling ``progress(done_bytes, total_bytes_or_None)``."""
    try:
        with opener(url, timeout) as response, open(dest, "wb") as out:
            total = response.headers.get("Content-Length")
            total = int(total) if total and total.isdigit() else None
            done = 0
            while chunk := response.read(CHUNK):
                if cancelled():
                    raise DownloadCancelled
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"The download failed: {exc}") from exc


def fetch_checksum(url, timeout=10, opener=_open):
    """The hex SHA-256 in a ``.sha256`` file (``"<hash>  <name>"`` or just the hash)."""
    try:
        with opener(url, timeout) as response:
            text = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"Could not fetch the installer's checksum: {exc}") from exc
    digest = text.split()[0].lower() if text.split() else ""
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise UpdateError("The release's checksum file is malformed.")
    return digest


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def run_installer(path):
    """Start the installer in silent mode; it closes this app, upgrades it and restarts it."""
    subprocess.Popen([str(path), "/SILENT", "/NORESTART"], close_fds=True)
