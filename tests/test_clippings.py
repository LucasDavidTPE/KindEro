from datetime import datetime

from kindero.clippings import (
    dedupe,
    group_by_book,
    parse_clippings,
    read_clippings_file,
)
from kindero.devices import find_kindle_clippings
from kindero.models import Clipping

SEP = "=========="


def entry(header: str, meta: str, text: str = "") -> str:
    return f"{header}\n{meta}\n\n{text}\n{SEP}\n"


def one(header: str, meta: str, text: str = "x") -> Clipping:
    clips = parse_clippings(entry(header, meta, text))
    assert len(clips) == 1
    return clips[0]


def test_en_highlight_with_page_and_24h_date():
    c = one(
        "Deep Work (Cal Newport)",
        "- Your Highlight on page 12 | Location 180-182 | Added on Monday, 3 March 2025 14:05:12",
        "Hello",
    )
    assert (c.title, c.author, c.kind, c.text) == ("Deep Work", "Cal Newport", "highlight", "Hello")
    assert (c.page, c.location_start, c.location_end) == ("12", 180, 182)
    assert c.added == datetime(2025, 3, 3, 14, 5, 12)


def test_en_us_date_pm_no_page():
    c = one(
        "Deep Work (Cal Newport)",
        "- Your Highlight on Location 180-182 | Added on Monday, March 3, 2025 2:05:12 PM",
    )
    assert c.page is None
    assert c.added == datetime(2025, 3, 3, 14, 5, 12)


def test_en_note_and_bookmark():
    n = one("B (A)", "- Your Note on page 12 | Location 182 | Added on Monday, 3 March 2025 14:05:12", "my note")
    assert (n.kind, n.location_start, n.location_end) == ("note", 182, 182)
    b = one("B (A)", "- Your Bookmark on page 5 | Location 70 | Added on Monday, 3 March 2025 14:05:12", "")
    assert (b.kind, b.page, b.text) == ("bookmark", "5", "")


def test_roman_page():
    c = one("B (A)", "- Your Highlight on page xiv | Location 10-11 | Added on Monday, 3 March 2025 1:00:00 AM")
    assert c.page == "xiv"
    assert c.added == datetime(2025, 3, 3, 1, 0, 0)


def test_french_variants():
    c = one(
        "Le Livre (Jean Dupont)",
        "- Votre surlignement sur la page 12 | emplacement 180-182 | Ajouté le lundi 3 mars 2025 14:05:12",
    )
    assert (c.kind, c.page, c.location_start, c.location_end) == ("highlight", "12", 180, 182)
    assert c.added == datetime(2025, 3, 3, 14, 5, 12)
    assert one("L (A)", "- Votre note sur la page 12 | emplacement 182 | Ajouté le lundi 3 mars 2025 14:05:12").kind == "note"
    assert one("L (A)", "- Votre signet sur la page 5 | emplacement 70 | Ajouté le lundi 3 mars 2025 14:05:12").kind == "bookmark"
    old = one("L (A)", "- Votre surlignement Emplacement 180-182 | Ajouté le mardi 4 février 2025 09:00:00")
    assert (old.page, old.location_start, old.location_end) == (None, 180, 182)
    assert old.added == datetime(2025, 2, 4, 9, 0, 0)


def test_french_accented_month():
    c = one("L (A)", "- Votre note sur la page 1 | emplacement 2 | Ajouté le samedi 2 août 2025 10:00:00")
    assert c.added == datetime(2025, 8, 2, 10, 0, 0)


def test_german():
    c = one("Buch (Autor)", "- Ihre Markierung auf Seite 12 | Position 180-182 | Hinzugefügt am Montag, 3. März 2025 14:05:12")
    assert (c.kind, c.page, c.location_start, c.location_end) == ("highlight", "12", 180, 182)
    assert c.added == datetime(2025, 3, 3, 14, 5, 12)
    assert one("B (A)", "- Ihre Notiz auf Seite 12 | Position 182 | Hinzugefügt am Montag, 3. März 2025 14:05:12").kind == "note"
    assert one("B (A)", "- Ihr Lesezeichen auf Seite 5 | Position 70 | Hinzugefügt am Montag, 3. März 2025 14:05:12").kind == "bookmark"


def test_spanish():
    c = one("Libro (Autor)", "- La subrayado en la página 12 | posición 180-182 | Añadido el lunes, 3 de marzo de 2025 14:05:12")
    assert (c.kind, c.page, c.location_start, c.location_end) == ("highlight", "12", 180, 182)
    assert c.added == datetime(2025, 3, 3, 14, 5, 12)
    assert one("L (A)", "- Tu nota en la página 12 | posición 182 | Añadido el lunes, 3 de marzo de 2025 14:05:12").kind == "note"
    assert one("L (A)", "- Tu marcador en la página 5 | posición 70 | Añadido el lunes, 3 de marzo de 2025 14:05:12").kind == "bookmark"


def test_unparsable_date_is_none():
    c = one("B (A)", "- Your Highlight on page 1 | Location 5-6 | Added on someday")
    assert c.added is None
    c = one("B (A)", "- Your Highlight on page 1 | Location 5-6 | Added on Monday, 32 March 2025 14:05:12")
    assert c.added is None


def test_title_with_parentheses_and_missing_author():
    c = one("Title (Part 1) (Jane Doe)", "- Your Highlight on Location 1-2 | Added on Monday, 3 March 2025 14:05:12")
    assert (c.title, c.author) == ("Title (Part 1)", "Jane Doe")
    c = one("No Author Book", "- Your Highlight on Location 1-2 | Added on Monday, 3 March 2025 14:05:12")
    assert (c.title, c.author) == ("No Author Book", "")


def test_crlf_bom_and_multiline_text():
    meta = "- Your Highlight on Location 1-2 | Added on Monday, 3 March 2025 14:05:12"
    raw = (
        f"﻿A (X)\r\n{meta}\r\n\r\nline1\r\nline2\r\n{SEP}\r\n"
        f"﻿B (Y)\r\n{meta}\r\n\r\nother\r\n{SEP}\r\n"
    )
    clips = parse_clippings(raw)
    assert [(c.title, c.author, c.text) for c in clips] == [
        ("A", "X", "line1\nline2"),
        ("B", "Y", "other"),
    ]


def test_garbled_entries_skipped():
    meta = "- Your Highlight on Location 1-2 | Added on Monday, 3 March 2025 14:05:12"
    raw = f"garbage\n{SEP}\nOnly title\n{SEP}\nT (A)\n- Your Mystery on Location 1\n\nx\n{SEP}\n" + entry("Ok (A)", meta, "fine")
    assert [c.title for c in parse_clippings(raw)] == ["Ok"]
    assert parse_clippings("") == []


def test_read_file_with_bom(tmp_path):
    p = tmp_path / "My Clippings.txt"
    meta = "- Your Highlight on Location 1-2 | Added on Monday, 3 March 2025 14:05:12"
    p.write_bytes(("﻿" + entry("Ünï (Ä)", meta, "t")).encode("utf-8"))
    clips = read_clippings_file(p)
    assert (clips[0].title, clips[0].author) == ("Ünï", "Ä")


def hl(title, start, end, text, kind="highlight", author="A"):
    return Clipping(title, author, kind, text, location_start=start, location_end=end)


def test_group_by_book_preserves_order():
    clips = [hl("B", 1, 2, "a"), hl("A", 1, 2, "b"), hl("B", 5, 6, "c")]
    groups = group_by_book(clips)
    assert list(groups) == [("B", "A"), ("A", "A")]
    assert [c.text for c in groups[("B", "A")]] == ["a", "c"]


def test_dedupe_extended_highlight_keeps_later():
    a = hl("B", 180, 182, "The quick brown")
    b = hl("B", 180, 184, "The quick brown fox jumps")
    c = hl("B", 300, 301, "unrelated")
    assert dedupe([a, b, c]) == [b, c]


def test_dedupe_extended_at_start_and_same_start_differing_text():
    a = hl("B", 10, 12, "brown fox")
    b = hl("B", 8, 12, "the quick brown fox")
    assert dedupe([a, b]) == [b]
    d = hl("B", 20, 22, "typo text")
    e = hl("B", 20, 23, "fixed text now")
    assert dedupe([d, e]) == [e]


def test_dedupe_overlap_without_text_relation_kept():
    a = hl("B", 10, 12, "alpha")
    b = hl("B", 11, 14, "beta")
    assert dedupe([a, b]) == [a, b]


def test_dedupe_other_book_and_chain():
    a = hl("B", 1, 2, "one")
    other = hl("Z", 1, 2, "one one", author="Q")
    b = hl("B", 1, 3, "one two")
    c = hl("B", 1, 4, "one two three")
    assert dedupe([a, other, b, c]) == [other, c]


def test_dedupe_notes_and_bookmarks():
    n1 = hl("B", 5, 5, "note", kind="note")
    n2 = hl("B", 5, 5, "note", kind="note")
    n3 = hl("B", 6, 6, "other note", kind="note")
    b1 = hl("B", 7, 7, "", kind="bookmark")
    b2 = hl("B", 7, 7, "", kind="bookmark")
    assert dedupe([n1, n3, n2, b1, b2]) == [n3, n2, b1, b2]


def make_kindle(root, name):
    p = root / name / "documents"
    p.mkdir(parents=True)
    f = p / "My Clippings.txt"
    f.write_text("x")
    return f


def test_device_found_and_none(tmp_path):
    assert find_kindle_clippings(roots=[tmp_path / "missing", tmp_path]) is None
    f = make_kindle(tmp_path, "Whatever")
    assert find_kindle_clippings(roots=[tmp_path / "nope", tmp_path / "Whatever"]) == f


def test_device_prefers_kindle_volume(tmp_path):
    make_kindle(tmp_path, "USBSTICK")
    k = make_kindle(tmp_path, "Kindle")
    roots = [tmp_path / "USBSTICK", tmp_path / "Kindle"]
    assert find_kindle_clippings(roots) == k


def test_device_zero_arg_call_works():
    result = find_kindle_clippings()
    assert result is None or result.name == "My Clippings.txt"
