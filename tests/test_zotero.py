"""Tests for the Zotero client; HTTP is faked, no network access."""

import json

import pytest
import requests

from kindero.models import Attachment, Note, ZoteroError
from kindero.zotero import ZoteroClient


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, content=b""):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = content
        self.text = json.dumps(body) if body is not None else content.decode("utf-8", "ignore")

    def json(self):
        return self._body


class FakeSession:
    """Replays queued responses and records requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(*responses, library_type="user"):
    session = FakeSession(*responses)
    client = ZoteroClient("42", "KEY", library_type, session=session)
    client.sleep = lambda s: None
    return client, session


def raw_item(key, title="T", item_type="journalArticle", creators=(), parsed="", version=3):
    return {"key": key, "version": version, "meta": {"parsedDate": parsed} if parsed else {},
            "data": {"key": key, "title": title, "itemType": item_type,
                     "creators": list(creators), "version": version}}


def test_headers_and_group_path():
    client, s = make(FakeResponse(body=[]), library_type="group")
    client.items()
    call = s.calls[0]
    assert call["url"] == "https://api.zotero.org/groups/42/items/top"
    assert call["headers"]["Zotero-API-Key"] == "KEY"
    assert call["headers"]["Zotero-API-Version"] == "3"
    assert call["params"]["format"] == "json"


def test_pagination_follows_full_pages():
    page1 = [raw_item(f"A{i}") for i in range(100)]
    page2 = [raw_item(f"B{i}") for i in range(30)]
    client, s = make(FakeResponse(body=page1, headers={"Total-Results": "130"}),
                     FakeResponse(body=page2, headers={"Total-Results": "130"}))
    items = client.items()
    assert len(items) == 130
    assert [c["params"]["start"] for c in s.calls] == [0, 100]
    assert all(c["params"]["limit"] == 100 for c in s.calls)


def test_pagination_stops_on_total_results():
    page = [raw_item(f"A{i}") for i in range(100)]
    client, s = make(FakeResponse(body=page, headers={"Total-Results": "100"}))
    assert len(client.items()) == 100
    assert len(s.calls) == 1


def test_items_limit_respected():
    page = [raw_item(f"A{i}") for i in range(5)]
    client, s = make(FakeResponse(body=page))
    assert len(client.items(limit=5)) == 5
    assert s.calls[0]["params"]["limit"] == 5


def test_items_collection_query_and_exclusion():
    raws = [raw_item("K1"), raw_item("K2", item_type="attachment"), raw_item("K3", item_type="note")]
    client, s = make(FakeResponse(body=raws))
    items = client.items(collection_key="COL", query="deep")
    assert [i.key for i in items] == ["K1"]
    assert s.calls[0]["url"].endswith("/collections/COL/items/top")
    assert s.calls[0]["params"]["q"] == "deep"


def test_creator_and_year_mapping():
    creators = [{"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"},
                {"creatorType": "author", "name": "ACME Lab"}]
    client, _ = make(FakeResponse(body=raw_item("K1", "Engines", creators=creators,
                                                parsed="1843-01-01", version=7)))
    item = client.item("K1")
    assert item.creators == ["Lovelace, Ada", "ACME Lab"]
    assert item.year == "1843"
    assert item.version == 7
    assert item.title == "Engines"


def test_collections_mapping():
    raws = [{"key": "C1", "data": {"key": "C1", "name": "Root", "parentCollection": False},
             "meta": {"numItems": 4}},
            {"key": "C2", "data": {"key": "C2", "name": "Sub", "parentCollection": "C1"},
             "meta": {"numItems": 1}}]
    client, _ = make(FakeResponse(body=raws))
    cols = client.collections()
    assert cols[0].parent_key is None and cols[0].num_items == 4
    assert cols[1].parent_key == "C1"


def children():
    return [
        {"data": {"key": "AT1", "parentItem": "P", "itemType": "attachment", "linkMode": "imported_file",
                  "contentType": "application/pdf", "filename": "a.pdf", "md5": "abc", "title": "A"}},
        {"data": {"key": "AT2", "parentItem": "P", "itemType": "attachment", "linkMode": "linked_url",
                  "contentType": "text/html", "title": "Web page"}},
        {"data": {"key": "N1", "parentItem": "P", "itemType": "note", "note": "<p>x</p>",
                  "version": 9, "tags": [{"tag": "kindero"}, {"tag": "x"}]}},
    ]


def test_attachments_filtering_and_mapping():
    client, s = make(FakeResponse(body=children()))
    atts = client.attachments("P")
    assert [a.key for a in atts] == ["AT1", "AT2"]
    assert atts[0].filename == "a.pdf" and atts[0].md5 == "abc"
    assert atts[1].filename == "Web page" and atts[1].md5 is None
    assert s.calls[0]["url"].endswith("/items/P/children")


def test_notes_mapping():
    client, _ = make(FakeResponse(body=children()))
    notes = client.notes("P")
    assert len(notes) == 1
    assert notes[0] == Note(key="N1", parent_key="P", html="<p>x</p>", version=9, tags=["kindero", "x"])


def test_download_returns_bytes():
    client, s = make(FakeResponse(content=b"%PDF"))
    att = Attachment("AT1", "P", "a.pdf", "application/pdf", "imported_file")
    assert client.download(att) == b"%PDF"
    assert s.calls[0]["url"].endswith("/items/AT1/file")
    assert s.calls[0]["allow_redirects"] is True


@pytest.mark.parametrize("mode", ["linked_file", "linked_url"])
def test_download_linked_file_raises(mode):
    client, s = make()
    att = Attachment("AT1", "P", "a.pdf", "application/pdf", mode)
    with pytest.raises(ZoteroError, match="cloud storage"):
        client.download(att)
    assert s.calls == []


def test_create_note_new_response_shape():
    client, s = make(FakeResponse(body={"successful": {"0": {"key": "NEW1", "data": {}}},
                                        "success": {"0": "NEW1"}, "failed": {}}))
    key = client.create_note("P", "<p>hi</p>", ["kindero"])
    assert key == "NEW1"
    call = s.calls[0]
    assert call["method"] == "POST" and call["url"].endswith("/items")
    assert call["json"] == [{"itemType": "note", "parentItem": "P", "note": "<p>hi</p>",
                             "tags": [{"tag": "kindero"}]}]


def test_create_note_old_response_shape():
    client, _ = make(FakeResponse(body={"success": {"0": "OLD1"}, "failed": {}}))
    assert client.create_note("P", "<p>hi</p>", []) == "OLD1"


def test_create_note_failure():
    client, _ = make(FakeResponse(body={"successful": {}, "failed": {"0": {"code": 400, "message": "bad parent"}}}))
    with pytest.raises(ZoteroError, match="bad parent"):
        client.create_note("P", "x", [])


def test_update_note_sends_version_header():
    client, s = make(FakeResponse(status=204))
    client.update_note(Note("N1", "P", "old", 9), "<p>new</p>")
    call = s.calls[0]
    assert call["method"] == "PATCH" and call["url"].endswith("/items/N1")
    assert call["json"] == {"note": "<p>new</p>"}
    assert call["headers"]["If-Unmodified-Since-Version"] == "9"


def test_update_note_412():
    client, _ = make(FakeResponse(status=412, body={}))
    with pytest.raises(ZoteroError, match="modified meanwhile"):
        client.update_note(Note("N1", "P", "old", 9), "new")


def test_403_message_mentions_key_settings():
    client, _ = make(FakeResponse(status=403, body={}))
    with pytest.raises(ZoteroError) as exc:
        client.items()
    assert "read" in str(exc.value) and "https://www.zotero.org/settings/keys" in str(exc.value)


def test_403_on_write_mentions_write():
    client, _ = make(FakeResponse(status=403, body={}))
    with pytest.raises(ZoteroError, match="write"):
        client.create_note("P", "x", [])


def test_404_message():
    client, _ = make(FakeResponse(status=404, body={}))
    with pytest.raises(ZoteroError, match="Not found"):
        client.item("NOPE")


def test_other_error_includes_status_and_body():
    client, _ = make(FakeResponse(status=500, content=b"boom"))
    with pytest.raises(ZoteroError, match="500.*boom"):
        client.item("K")


def test_retry_on_429_then_success():
    client, s = make(FakeResponse(status=429, headers={"Retry-After": "2"}),
                     FakeResponse(body=raw_item("K1")))
    waits = []
    client.sleep = waits.append
    assert client.item("K1").key == "K1"
    assert waits == [2.0] and len(s.calls) == 2


def test_retry_gives_up_after_three_retries():
    client, s = make(*[FakeResponse(status=503, headers={"Backoff": "1"}, content=b"busy")
                       for _ in range(4)])
    waits = []
    client.sleep = waits.append
    with pytest.raises(ZoteroError, match="503"):
        client.item("K1")
    assert len(waits) == 3 and len(s.calls) == 4


def test_network_error_wrapped():
    client, _ = make(requests.ConnectionError("down"))
    with pytest.raises(ZoteroError, match="Network error"):
        client.item("K1")
