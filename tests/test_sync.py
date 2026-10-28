"""Tests for kindero.sync (no network, fake Zotero client)."""

from __future__ import annotations

from kindero.models import Clipping, Item, Note
from kindero.sync import (
    book_marker,
    match_book,
    normalize_title,
    render_note,
    sync_clippings,
)


class FakeClient:
    """Implements the ZoteroClient methods used by sync_clippings."""

    def __init__(self, items: list[Item], notes: dict[str, list[Note]] | None = None):
        self._items = items
        self._notes = notes or {}
        self.items_calls = 0
        self.created: list[tuple[str, str, list[str]]] = []
        self.updated: list[tuple[Note, str]] = []

    def items(self, collection_key=None, query=None, limit=None) -> list[Item]:
        self.items_calls += 1
        return list(self._items)

    def notes(self, item_key: str) -> list[Note]:
        return list(self._notes.get(item_key, []))

    def create_note(self, parent_key: str, html: str, tags: list[str]) -> str:
        self.created.append((parent_key, html, tags))
        key = f"NOTE{len(self.created)}"
        self._notes.setdefault(parent_key, []).append(Note(key, parent_key, html, 1, tags))
        return key

    def update_note(self, note: Note, html: str) -> None:
        self.updated.append((note, html))
        note.html = html


def hl(text, title="Deep Learning", author="Smith, John", start=None, end=None, page=None):
    return Clipping(title, author, "highlight", text, page, start, end)


def nt(text, title="Deep Learning", author="Smith, John", start=None):
    return Clipping(title, author, "note", text, None, start, start)


def bm(title="Deep Learning", author="Smith, John", start=None):
    return Clipping(title, author, "bookmark", "", None, start, None)


# --- normalize_title -------------------------------------------------------

def test_normalize_accents_and_punctuation():
    assert normalize_title("  Étude   des Réseaux: une ÉCOLE!  ") == "etude des reseaux une ecole"


def test_normalize_strips_extension():
    assert normalize_title("My Paper.pdf") == "my paper"
    assert normalize_title("My Paper.EPUB") == "my paper"


def test_normalize_strips_author_suffix():
    assert normalize_title("Deep Learning (Goodfellow, Ian)") == "deep learning"


def test_normalize_filename_form_keeps_prefix():
    # The prefix is handled by match_book, not by normalize_title.
    assert normalize_title("Smith 2021 - Deep learning for X.pdf") == "smith 2021 deep learning for x"


# --- match_book ------------------------------------------------------------

ITEMS = [
    Item("A1", "Attention Is All You Need", ["Vaswani, Ashish"], year="2017"),
    Item("B2", "Deep learning for protein structure prediction", ["Smith, John"], year="2021"),
    Item("C3", "A survey of graph neural networks", ["Wu, Zonghan"], year="2020"),
]


def test_match_exact():
    assert match_book("Attention Is All You Need", "Unknown", ITEMS).key == "A1"


def test_match_fuzzy():
    assert match_book("Attention is all you need!", "", ITEMS).key == "A1"
    assert match_book("A Survey on Graph Neural Networks", "", ITEMS).key == "C3"


def test_match_truncated_title():
    assert match_book("Deep learning for protein struc", "", ITEMS).key == "B2"


def test_match_filename_prefix():
    item = match_book("Smith 2021 - Deep learning for protein structure prediction", "", ITEMS)
    assert item.key == "B2"


def test_author_bonus_lifts_score_over_threshold():
    items = [Item("X", "Graph neural networks in practice", ["Doe, Jane"])]
    title = "Graph neural models in practice"  # ratio 0.84, just below 0.85
    assert match_book(title, "", items) is None
    assert match_book(title, "Jane Doe", items).key == "X"


def test_below_threshold_returns_none():
    assert match_book("Cooking with grandma", "Anon", ITEMS) is None
    assert match_book("", "", ITEMS) is None


def test_tie_returns_first_item():
    items = [Item("first", "Same title"), Item("second", "Same title")]
    assert match_book("Same title", "", items).key == "first"


# --- render_note -----------------------------------------------------------

def test_render_escapes_and_marker_first():
    html = render_note("A <b> & c", [hl('x < y & "z"', title="A <b> & c", author="Me")])
    assert html.startswith(book_marker("A <b> & c", "Me"))
    assert "<h1>Kindle highlights — A &lt;b&gt; &amp; c</h1>" in html
    assert "x &lt; y &amp; &quot;z&quot;" in html
    assert "<b>" not in html
    assert html.endswith("<p><em>Imported by KindEro</em></p>")


def test_render_is_deterministic_and_skips_bookmarks():
    clips = [hl("one", start=180, end=182, page="12"), bm(start=200), hl("two", start=300)]
    a, b = render_note("Deep Learning", clips), render_note("Deep Learning", clips)
    assert a == b
    assert a.count("<blockquote>") == 2
    assert "p. 12 · loc. 180–182" in a
    assert "loc. 300<" in a
    assert "bookmark" not in a.lower()


def test_render_places_note_after_its_highlight():
    clips = [nt("my thought", start=182), hl("first", start=180, end=182), hl("second", start=400)]
    html = render_note("Deep Learning", clips)
    first, note, second = html.index("first"), html.index("my thought"), html.index("second")
    assert first < note < second
    assert html.count("<strong>Note:</strong>") == 1


def test_render_loose_note_keeps_order():
    clips = [hl("first", start=10, end=12), nt("loose", start=50), hl("second", start=100)]
    html = render_note("Deep Learning", clips)
    assert html.index("first") < html.index("loose") < html.index("second")


def test_marker_format():
    marker = book_marker("Deep Learning", "Smith")
    assert marker.startswith("<!-- kindero:book=") and marker.endswith(" -->")
    assert len(marker) == len("<!-- kindero:book= -->") + 12
    assert book_marker("Deep Learning.pdf", "SMITH") == marker


# --- sync_clippings --------------------------------------------------------

LIB = [Item("K1", "Deep Learning", ["Smith, John"])]


def test_sync_creates_note():
    client = FakeClient(LIB)
    clips = [hl("a", start=1), nt("n", start=1), bm()]
    [res] = sync_clippings(clips, client)
    assert (res.status, res.item_key, res.note_key, res.count) == ("created", "K1", "NOTE1", 2)
    parent, html, tags = client.created[0]
    assert parent == "K1" and tags == ["kindero"]
    assert book_marker("Deep Learning", "Smith, John") in html
    assert client.items_calls == 1


def test_sync_unchanged_then_updated():
    client = FakeClient(LIB)
    clips = [hl("a", start=1)]
    sync_clippings(clips, client)
    [res] = sync_clippings(clips, client)
    assert res.status == "unchanged" and res.note_key == "NOTE1"
    assert client.updated == [] and len(client.created) == 1

    [res] = sync_clippings(clips + [hl("b", start=5)], client)
    assert res.status == "updated" and res.note_key == "NOTE1"
    assert len(client.updated) == 1 and "b</p>" in client.updated[0][1]
    assert len(client.created) == 1


def test_sync_ignores_unrelated_notes():
    other = Note("N0", "K1", "<p>My own note</p>", 3)
    client = FakeClient(LIB, {"K1": [other]})
    [res] = sync_clippings([hl("a")], client)
    assert res.status == "created" and client.updated == []


def test_sync_not_found_and_skips_bookmark_only_books():
    client = FakeClient(LIB)
    clips = [hl("x", title="Unknown Novel", author="Nobody"), bm(title="Only Bookmarks")]
    results = sync_clippings(clips, client)
    assert [(r.title, r.status, r.item_key, r.count) for r in results] == [
        ("Unknown Novel", "not_found", None, 1)
    ]
    assert client.created == [] and client.updated == []


def test_sync_dry_run_writes_nothing():
    client = FakeClient(LIB)
    [res] = sync_clippings([hl("a")], client, dry_run=True)
    assert res.status == "dry_run" and res.item_key == "K1" and res.note_key is None
    assert client.created == [] and client.updated == []


def test_sync_groups_books_in_order():
    lib = LIB + [Item("K2", "Attention Is All You Need", ["Vaswani, Ashish"])]
    client = FakeClient(lib)
    clips = [
        hl("a"),
        hl("b", title="Attention Is All You Need", author="Vaswani"),
        hl("c"),
    ]
    results = sync_clippings(clips, client)
    assert [(r.item_key, r.count) for r in results] == [("K1", 2), ("K2", 1)]
    assert client.items_calls == 1


def test_sync_empty_input_makes_no_calls():
    client = FakeClient(LIB)
    assert sync_clippings([], client) == []
    assert client.items_calls == 0
