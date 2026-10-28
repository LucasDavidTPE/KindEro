"""Match Kindle clippings to Zotero items and write them as child notes.

Deduplication of extended highlights (``clippings.dedupe``) is the caller's
job (the CLI): this module takes the clippings as given, so it stays
independent from the parser.
"""

from __future__ import annotations

import difflib
import hashlib
import html
import re
import unicodedata
from typing import TYPE_CHECKING

from .models import Clipping, Item, Note, SyncResult

if TYPE_CHECKING:  # avoid a hard dependency on zotero.py (and requests)
    from .zotero import ZoteroClient

MARKER = "<!-- kindero:book={} -->"
NOTE_TAG = "kindero"
AUTHOR_BONUS = 0.05
PREFIX_SCORE = 0.9  # minimum score when one title is a prefix of the other
PREFIX_MIN_CHARS = 20

_EXTENSION_RE = re.compile(
    r"\.(pdf|epub|mobi|azw3?|kfx|docx?|txt|rtf|html?)\s*$", re.IGNORECASE
)
_TRAILING_PAREN_RE = re.compile(r"\s*\([^()]*\)\s*$")
_PUNCT_RE = re.compile(r"[\W_]+")
# "Smith 2021 - Title" or "Van der Berg 2019 - Title" (see kindle.kindle_filename)
_FILENAME_PREFIX_RE = re.compile(
    r"^\s*(?P<name>[^\W\d][^\d]*?)\s+(?P<year>\d{4})\s+[-–—]\s+(?P<rest>.+)$"
)


def _strip_accents(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_title(s: str) -> str:
    """Lowercase, accent-free, punctuation-free title for fuzzy comparison."""
    s = _strip_accents(s).lower().strip()
    s = _EXTENSION_RE.sub("", s)
    s = _TRAILING_PAREN_RE.sub("", s)
    s = _PUNCT_RE.sub(" ", s)
    return " ".join(s.split())


def _split_filename_prefix(title: str) -> tuple[str, str, str] | None:
    """Split a ``"Name 2021 - Title"`` file name into (name, year, title)."""
    m = _FILENAME_PREFIX_RE.match(title)
    if not m:
        return None
    return m.group("name"), m.group("year"), m.group("rest")


def _last_name(creator: str) -> str:
    """Normalized last name from ``"Last, First"`` or ``"First Last"``."""
    if "," in creator:
        return normalize_title(creator.split(",", 1)[0])
    words = normalize_title(creator).split()
    return words[-1] if words else ""


def _title_score(a: str, b: str) -> float:
    """SequenceMatcher ratio, raised when one title is a prefix of the other."""
    if not a or not b:
        return 0.0
    score = difflib.SequenceMatcher(None, a, b).ratio()
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= PREFIX_MIN_CHARS and longer.startswith(shorter):
        score = max(score, PREFIX_SCORE)
    return score


def _has_author_bonus(item: Item, author_text: str, year: str | None) -> bool:
    """True if a creator last name appears in the author text, or years match."""
    padded = f" {normalize_title(author_text)} "
    for creator in item.creators:
        last = _last_name(creator)
        if last and f" {last} " in padded:
            return True
    return bool(year and item.year and item.year.startswith(year))


def match_book(
    title: str, author: str, items: list[Item], threshold: float = 0.85
) -> Item | None:
    """Return the item whose title best matches the Kindle book, or None."""
    variants = [normalize_title(title)]
    author_text, year = author, None
    prefix = _split_filename_prefix(title)
    if prefix:
        name, year, rest = prefix
        variants.append(normalize_title(rest))
        author_text = f"{author} {name}"

    best, best_score = None, 0.0
    for item in items:
        target = normalize_title(item.title)
        score = max(_title_score(v, target) for v in variants)
        if score > 0 and _has_author_bonus(item, author_text, year):
            score = min(1.0, score + AUTHOR_BONUS)
        if score > best_score:  # strict: ties keep the first item
            best, best_score = item, score
    return best if best_score >= threshold else None


def book_marker(title: str, author: str) -> str:
    """Stable HTML comment identifying the note of one Kindle book."""
    key = f"{normalize_title(title)}|{author.lower()}"
    return MARKER.format(hashlib.sha1(key.encode("utf-8")).hexdigest()[:12])


def _position(clip: Clipping) -> str:
    """Human-readable position, e.g. ``p. 12 · loc. 180–182``."""
    parts = []
    if clip.page:
        parts.append(f"p. {clip.page}")
    if clip.location_start is not None:
        loc = str(clip.location_start)
        if clip.location_end is not None and clip.location_end != clip.location_start:
            loc += f"–{clip.location_end}"
        parts.append(f"loc. {loc}")
    return " · ".join(parts)


def _owner(note: Clipping, highlights: list[Clipping]) -> Clipping | None:
    """Last highlight whose location range contains the note's location."""
    loc = note.location_start
    if loc is None:
        return None
    owner = None
    for h in highlights:
        if h.location_start is None:
            continue
        end = h.location_end if h.location_end is not None else h.location_start
        if h.location_start <= loc <= end:
            owner = h
    return owner


def render_note(title: str, clips: list[Clipping]) -> str:
    """Deterministic HTML for the Zotero note (marker first, bookmarks skipped).

    A note is placed right after the highlight whose location range contains
    it; a note with no such highlight stays at its place in the sequence.
    The marker's author is taken from the first clip (all clips share it).
    """
    author = clips[0].author if clips else ""
    highlights = [c for c in clips if c.kind == "highlight"]
    attached: dict[int, list[Clipping]] = {}
    for c in clips:
        if c.kind == "note":
            h = _owner(c, highlights)
            if h is not None:
                attached.setdefault(id(h), []).append(c)
    attached_ids = {id(n) for notes in attached.values() for n in notes}

    def note_html(n: Clipping) -> str:
        return f"<p><strong>Note:</strong> {html.escape(n.text)}</p>"

    parts = [
        book_marker(title, author),
        f"<h1>Kindle highlights — {html.escape(title)}</h1>",
    ]
    for c in clips:
        if c.kind == "highlight":
            parts.append(f"<blockquote><p>{html.escape(c.text)}</p></blockquote>")
            pos = _position(c)
            if pos:
                parts.append(f"<p><small>{html.escape(pos)}</small></p>")
            parts.extend(note_html(n) for n in attached.get(id(c), []))
        elif c.kind == "note" and id(c) not in attached_ids:
            parts.append(note_html(c))
    parts.append("<p><em>Imported by KindEro</em></p>")
    return "\n".join(parts)


def _group(clips: list[Clipping]) -> dict[tuple[str, str], list[Clipping]]:
    groups: dict[tuple[str, str], list[Clipping]] = {}
    for c in clips:
        groups.setdefault((c.title, c.author), []).append(c)
    return groups


def _find_note(notes: list[Note], marker: str) -> Note | None:
    return next((n for n in notes if marker in n.html), None)


def sync_clippings(
    clips: list[Clipping], client: ZoteroClient, dry_run: bool = False
) -> list[SyncResult]:
    """Create or update one Zotero child note per Kindle book.

    Clippings should already be deduplicated by the caller. Books with no
    highlight or note (bookmarks only) are skipped.
    """
    books = []
    for (title, author), group in _group(clips).items():
        count = sum(1 for c in group if c.kind in ("highlight", "note"))
        if count:
            books.append((title, author, group, count))
    if not books:
        return []

    # Whole library, fetched once. Fine for v0.1; very large libraries could
    # narrow the candidates with client.items(query=...) per book instead.
    items = client.items()
    results = []
    for title, author, group, count in books:
        result = SyncResult(title=title, author=author, status="not_found", count=count)
        results.append(result)
        item = match_book(title, author, items)
        if item is None:
            continue
        result.item_key = item.key
        html_text = render_note(title, group)
        existing = _find_note(client.notes(item.key), book_marker(title, author))
        if existing is not None:
            result.note_key = existing.key
        if dry_run:
            result.status = "dry_run"
        elif existing is None:
            result.note_key = client.create_note(item.key, html_text, [NOTE_TAG])
            result.status = "created"
        elif existing.html == html_text:
            result.status = "unchanged"
        else:
            client.update_note(existing, html_text)
            result.status = "updated"
    return results
