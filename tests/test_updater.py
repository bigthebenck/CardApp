"""The update checker's GitHub parsing, version compare and download, with no network."""

import hashlib
import io
import json
import urllib.error

import pytest

from shuffle_solver import updater


class FakeResponse(io.BytesIO):
    def __init__(self, data, length=True):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))} if length else {}


def opener_for(pages):
    """An ``opener`` serving ``pages[url]`` (bytes, or an exception to raise)."""
    def opener(url, timeout):
        page = pages[url]
        if isinstance(page, Exception):
            raise page
        return FakeResponse(page)
    return opener


LATEST = updater.API_URL.format(repo=updater.REPO)


def release_json(tag="v1.2.0", assets=("CardApp-Setup-1.2.0.exe", "CardApp-Setup-1.2.0.exe.sha256")):
    return json.dumps({
        "tag_name": tag,
        "html_url": f"https://github.com/{updater.REPO}/releases/tag/{tag}",
        "body": "Faster search.",
        "assets": [{"name": n, "browser_download_url": f"https://dl/{n}"} for n in assets],
    }).encode()


@pytest.mark.parametrize("latest,current,newer", [
    ("v1.0.1", "1.0.0", True),
    ("1.10.0", "1.9.9", True),  # numeric, not string, compare
    ("v2.0", "1.9.9", True),
    ("v1.0.0", "1.0.0", False),
    ("v1.0", "1.0.0", False),
    ("v0.9.0", "1.0.0", False),
    ("nightly", "1.0.0", False),
    ("v1.0.0-beta", "0.1.0", False),
])
def test_is_newer(latest, current, newer):
    assert updater.is_newer(latest, current) is newer


def test_fetch_latest_release_finds_installer_and_checksum():
    release = updater.fetch_latest_release(opener=opener_for({LATEST: release_json()}))
    assert release.version == "1.2.0"
    assert release.notes == "Faster search."
    assert release.page_url.endswith("/releases/tag/v1.2.0")
    assert release.installer_url == "https://dl/CardApp-Setup-1.2.0.exe"
    assert release.installer_name == "CardApp-Setup-1.2.0.exe"
    assert release.checksum_url == "https://dl/CardApp-Setup-1.2.0.exe.sha256"
    assert release.can_install


def test_release_without_checksum_cannot_install():
    data = release_json(assets=("CardApp-Setup-1.2.0.exe", "source.zip"))
    release = updater.fetch_latest_release(opener=opener_for({LATEST: data}))
    assert release.installer_url and not release.can_install


@pytest.mark.parametrize("failure,message", [
    (urllib.error.HTTPError(LATEST, 404, "Not Found", {}, None), "No releases"),
    (urllib.error.HTTPError(LATEST, 403, "rate limited", {}, None), "(403)"),
    (urllib.error.URLError("no route"), "Could not reach GitHub"),
    (TimeoutError(), "Could not reach GitHub"),
])
def test_fetch_errors_become_readable_update_errors(failure, message):
    with pytest.raises(updater.UpdateError, match=message):
        updater.fetch_latest_release(opener=opener_for({LATEST: failure}))


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"tag_name": "v1.0.0"}'])
def test_fetch_rejects_unreadable_replies(body):
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest_release(opener=opener_for({LATEST: body}))


def test_download_reports_progress_and_checksum_matches(tmp_path):
    data = bytes(range(256)) * 1000
    seen = []
    dest = tmp_path / "setup.exe"
    updater.download("u", dest, lambda done, total: seen.append((done, total)),
                     opener=opener_for({"u": data}))
    assert dest.read_bytes() == data
    assert seen[-1] == (len(data), len(data)) and len(seen) > 1
    assert updater.sha256_of(dest) == hashlib.sha256(data).hexdigest()


def test_download_can_be_cancelled(tmp_path):
    with pytest.raises(updater.DownloadCancelled):
        updater.download("u", tmp_path / "x", cancelled=lambda: True,
                         opener=opener_for({"u": b"x" * 200_000}))


def test_fetch_checksum_accepts_sha256sum_format():
    digest = "ab" * 32
    opener = opener_for({"a": f"{digest.upper()}  CardApp-Setup-1.2.0.exe\n".encode(),
                         "b": digest.encode(), "c": b"nope", "d": b""})
    assert updater.fetch_checksum("a", opener=opener) == digest
    assert updater.fetch_checksum("b", opener=opener) == digest
    for bad in "cd":
        with pytest.raises(updater.UpdateError):
            updater.fetch_checksum(bad, opener=opener)
