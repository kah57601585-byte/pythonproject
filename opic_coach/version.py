"""App version, so you can see whether the code you are running is the latest.

RELEASE is a human-readable label bumped with each change. BUILD is a short hash of the
files the server and browser load, so a stale copy or a stale browser cache is detectable.
"""

import hashlib
from pathlib import Path

RELEASE = "2026-11-26.2"

_BASE = Path(__file__).resolve().parent
_FILES = [
    "server.py", "coach.py", "questions.py", "version.py",
    "static/index.html", "static/app.js", "static/style.css", "static/sw.js",
]


def _build_hash() -> str:
    h = hashlib.sha1()
    for name in _FILES:
        path = _BASE / name
        if path.exists():
            # Normalize line endings so Windows (CRLF) and Linux checkouts get the same hash.
            h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:8]


BUILD = _build_hash()
APP_VERSION = f"{RELEASE}+{BUILD}"
