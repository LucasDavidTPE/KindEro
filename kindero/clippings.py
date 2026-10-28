"""Parser for the Kindle ``My Clippings.txt`` file (EN, FR, DE, ES)."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .models import Clipping

_SEPARATOR = re.compile(r"^=+[ \t]*$", re.MULTILINE)
_TITLE = re.compile(r"^(?P<title>.*?)\s*\((?P<author>[^()]*)\)\s*$")

# Keyword (lowercase) found in the first metadata segment -> clipping kind.
_KINDS = (
    (("highlight", "surlignement", "markierung", "subrayado"), "highlight"),
    (("bookmark", "signet", "lesezeichen", "marcador"), "bookmark"),
    (("note", "notiz", "nota"), "note"),
)
_PAGE = re.compile(
    r"(?:page|seite|p[aá]gina)\s+(\d+|[ivxlcdm]+)\b", re.IGNORECASE
)
_LOCATION = re.compile(
    r"(?:location|emplacement|position|posici[oó]n|ubicaci[oó]n)\s*(\d+)(?:\s*-\s*(\d+))?",
    re.IGNORECASE,
)
_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp][Mm])?")
_YEAR = re.compile(r"\b(\d{4})\b")
_DAY = re.compile(r"\b(\d{1,2})\b")

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            "january janvier januar enero",
            "february fevrier februar febrero",
            "march mars marz maerz marzo",
            "april avril abril",
            "may mai mayo",
            "june juin juni junio",
            "july juillet juli julio",
            "august aout agosto",
            "september septembre septiembre setiembre",
            "october octobre oktober octubre",
            "november novembre noviembre",
            "december decembre dezember diciembre",
        ),
        start=1,
    )
    for name in names.split()
}


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _parse_kind(segment: str) -> str | None:
    words = set(re.findall(r"[^\W\d_]+", segment.lower()))
    for keywords, kind in _KINDS:
        if words.intersection(keywords):
            return kind
    return None


def _parse_date(meta: str) -> datetime | None:
    """Best-effort date parsing; returns None rather than raising."""
    try:
        time_match = _TIME.search(meta)
        rest = _TIME.sub(" ", meta, count=1)
        year_match = _YEAR.search(rest)
        if not year_match:
            return None
        rest = rest[: year_match.start()] + " " + rest[year_match.end():]
        month = next(
            (
                _MONTHS[w]
                for w in re.findall(r"[a-z]+", _strip_accents(rest).lower())
                if w in _MONTHS
            ),
            None,
        )
        day_match = _DAY.search(rest)
        if month is None or not day_match:
            return None
        hour = minute = second = 0
        if time_match:
            hour, minute = int(time_match[1]), int(time_match[2])
            second = int(time_match[3] or 0)
            meridian = (time_match[4] or "").lower()
            if meridian == "pm" and hour < 12:
                hour += 12
            elif meridian == "am" and hour == 12:
                hour = 0
        return datetime(
            int(year_match[1]), month, int(day_match[1]), hour, minute, second
        )
    except (ValueError, TypeError):
        return None


def _parse_entry(chunk: str) -> Clipping | None:
    lines = [line.replace("﻿", "").rstrip() for line in chunk.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if len(lines) < 2 or not lines[1].lstrip().startswith("-"):
        return None
    header, meta = lines[0].strip(), lines[1].strip()
    kind = _parse_kind(meta.split("|")[0])
    if not header or kind is None:
        return None
    match = _TITLE.match(header)
    title, author = (
        (match["title"].strip(), match["author"].strip()) if match else (header, "")
    )
    page = _PAGE.search(meta)
    loc = _LOCATION.search(meta)
    start = int(loc[1]) if loc else None
    end = int(loc[2]) if loc and loc[2] else start
    return Clipping(
        title=title or header,
        author=author,
        kind=kind,
        text="\n".join(lines[2:]).strip(),
        page=page[1] if page else None,
        location_start=start,
        location_end=end,
        added=_parse_date(meta.split("|")[-1]),
    )


def parse_clippings(text: str) -> list[Clipping]:
    """Parse the content of ``My Clippings.txt``; garbled entries are skipped."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    clips = (_parse_entry(chunk) for chunk in _SEPARATOR.split(text))
    return [clip for clip in clips if clip is not None]


def read_clippings_file(path: Path) -> list[Clipping]:
    """Read and parse a clippings file (UTF-8, with or without BOM)."""
    return parse_clippings(Path(path).read_text(encoding="utf-8-sig", errors="replace"))


def group_by_book(clips: list[Clipping]) -> dict[tuple[str, str], list[Clipping]]:
    """Group clippings by (title, author), preserving file order."""
    books: dict[tuple[str, str], list[Clipping]] = {}
    for clip in clips:
        books.setdefault((clip.title, clip.author), []).append(clip)
    return books


def _range(clip: Clipping) -> tuple[int, int] | None:
    if clip.location_start is None:
        return None
    end = clip.location_end if clip.location_end is not None else clip.location_start
    return clip.location_start, max(end, clip.location_start)


def _supersedes(later: Clipping, earlier: Clipping) -> bool:
    """True if ``later`` is an extended/edited version of ``earlier``."""
    a, b = _range(earlier), _range(later)
    if a is None or b is None:
        return False
    if a[0] > b[1] or b[0] > a[1]:  # no overlap
        return False
    t1, t2 = earlier.text.casefold().strip(), later.text.casefold().strip()
    return a[0] == b[0] or t1 in t2 or t2 in t1


def dedupe(clips: list[Clipping]) -> list[Clipping]:
    """Drop highlights superseded by a later one and duplicate notes."""
    drop: set[int] = set()
    for i, clip in enumerate(clips):
        for j in range(i + 1, len(clips)):
            other = clips[j]
            if (other.title, other.author) != (clip.title, clip.author):
                continue
            if clip.kind == "highlight" and other.kind == "highlight":
                if _supersedes(other, clip):
                    drop.add(i)
                    break
            elif clip.kind == "note" and other.kind == "note":
                if (clip.text, clip.location_start, clip.location_end) == (
                    other.text,
                    other.location_start,
                    other.location_end,
                ):
                    drop.add(i)
                    break
    return [clip for i, clip in enumerate(clips) if i not in drop]
