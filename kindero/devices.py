"""Detection of a mounted Kindle."""

from __future__ import annotations

import glob
import string
import sys
from pathlib import Path
from typing import Iterable

CLIPPINGS_RELPATH = Path("documents") / "My Clippings.txt"


def default_roots() -> list[Path]:
    """Candidate volume mount points for the current platform."""
    if sys.platform.startswith("win"):
        return [Path(f"{letter}:\\") for letter in string.ascii_uppercase[3:]]
    patterns = ("/Volumes/*", "/media/*/*", "/run/media/*/*", "/mnt/*")
    return [Path(p) for pattern in patterns for p in sorted(glob.glob(pattern))]


def find_kindle_clippings(roots: Iterable[Path] | None = None) -> Path | None:
    """Return the path of ``My Clippings.txt`` on a mounted Kindle, if any.

    ``roots`` overrides the candidate volumes (used by tests). Volumes named
    "Kindle" are preferred over other volumes that happen to hold the file.
    """
    candidates = [
        root / CLIPPINGS_RELPATH
        for root in (default_roots() if roots is None else [Path(r) for r in roots])
    ]
    found = []
    for path in candidates:
        try:
            if path.is_file():
                found.append(path)
        except OSError:
            continue
    found.sort(key=lambda p: "kindle" not in p.parents[1].name.lower())
    return found[0] if found else None
