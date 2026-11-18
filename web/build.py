"""Build the phone web app into build/web (and optionally serve it).

    python web/build.py            # build
    python web/build.py --serve    # build, then serve on http://<this PC>:8000

The page runs the same ``shuffle_solver`` code as the desktop app, in the
browser through Pyodide. This script zips the Qt-free part of the package
(plus ``webbridge.py``) into ``py/solver.zip`` next to the web files, and
stamps the app version into the service worker so each release gets a fresh
offline cache. Upload the contents of build/web to any static host (GitHub
Pages works); it must be served over HTTPS for "Add to Home Screen" and
offline use.
"""

import argparse
import http.server
import shutil
import socket
import sys
import zipfile
from functools import partial
from pathlib import Path

WEB = Path(__file__).resolve().parent
ROOT = WEB.parent
OUT = ROOT / "build" / "web"

# The package files the web app needs: everything except the Qt window and the
# desktop updater. ui/model.py is the window's Qt-free state layer.
PACKAGE_FILES = [
    "__init__.py", "deck.py", "shuffle_ops.py", "solver.py", "path_finder.py",
    "stacking.py", "tracking.py", "ui/__init__.py", "ui/model.py",
]
STATIC = ["index.html", "app.css", "app.js", "tracker.js", "worker.js", "sw.js", "manifest.webmanifest",
          "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png",
          "icons/apple-touch-icon.png"]


def version():
    sys.path.insert(0, str(ROOT))
    try:
        from shuffle_solver import __version__
    finally:
        sys.path.pop(0)
    return __version__


def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "py").mkdir(parents=True)
    ver = version()
    for name in STATIC:
        src, dest = WEB / name, OUT / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if name == "sw.js":
            dest.write_text(src.read_text(encoding="utf-8").replace("__VERSION__", ver),
                            encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(src, dest)
    with zipfile.ZipFile(OUT / "py" / "solver.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for rel in PACKAGE_FILES:
            z.write(ROOT / "shuffle_solver" / rel, f"shuffle_solver/{rel}")
        z.write(WEB / "webbridge.py", "webbridge.py")
    print(f"Built version {ver} into {OUT}")


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; picks the LAN interface
            return s.getsockname()[0]
    except OSError:
        return "localhost"


def serve(port):
    class Handler(http.server.SimpleHTTPRequestHandler):
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                          ".webmanifest": "application/manifest+json",
                          ".wasm": "application/wasm", ".js": "text/javascript"}

        def end_headers(self):
            self.send_header("Cache-Control", "no-cache")  # always pick up a rebuild
            super().end_headers()

    handler = partial(Handler, directory=str(OUT))
    with http.server.ThreadingHTTPServer(("0.0.0.0", port), handler) as httpd:
        print(f"Serving on http://localhost:{port}  (on your phone: http://{lan_address()}:{port})", flush=True)
        print("Offline mode and Add to Home Screen need HTTPS, so they only work from a real "
              "host or localhost; everything else works over the LAN. Ctrl+C stops.", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", action="store_true", help="serve build/web after building")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    build()
    if args.serve:
        serve(args.port)
