"""Client for the Zotero Web API v3 (https://www.zotero.org/support/dev/web_api/v3/basics)."""

from __future__ import annotations

import time
from typing import Any

import requests

from .models import Attachment, Collection, Item, Note, ZoteroError

PAGE_SIZE = 100
MAX_RETRIES = 3
KEYS_URL = "https://www.zotero.org/settings/keys"
_NON_REGULAR_TYPES = ("attachment", "note")


def _sleep(seconds: float) -> None:
    """Indirection so tests can monkeypatch the wait."""
    time.sleep(seconds)


class ZoteroClient:
    """Thin client over the Zotero Web API (read items, read/write child notes)."""

    def __init__(self, library_id: str, api_key: str, library_type: str = "user",
                 session: requests.Session | None = None,
                 base_url: str = "https://api.zotero.org") -> None:
        if library_type not in ("user", "group"):
            raise ZoteroError(f"Unknown library type {library_type!r} (use 'user' or 'group').")
        self.library_id = library_id
        self.api_key = api_key
        self.library_type = library_type
        self.session = session or requests.Session()
        self.base = f"{base_url.rstrip('/')}/{library_type}s/{library_id}"
        self.sleep = _sleep

    # -- low-level HTTP -------------------------------------------------

    def _request(self, method: str, path: str, *, params: dict | None = None,
                 json: Any = None, headers: dict | None = None,
                 write: bool = False) -> requests.Response:
        """Send a request, retrying on 429/503, and turn failures into ZoteroError."""
        hdrs = {"Zotero-API-Key": self.api_key, "Zotero-API-Version": "3"}
        hdrs.update(headers or {})
        url = f"{self.base}{path}"
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self.session.request(method, url, params=params, json=json,
                                            headers=hdrs, allow_redirects=True, timeout=60)
            except requests.RequestException as exc:
                raise ZoteroError(f"Network error talking to Zotero: {exc}") from exc
            if resp.status_code in (429, 503) and attempt < MAX_RETRIES:
                self.sleep(self._wait_seconds(resp))
                continue
            self._check(resp, write)
            return resp
        raise ZoteroError("Zotero API is busy; retries exhausted.")  # pragma: no cover

    @staticmethod
    def _wait_seconds(resp: requests.Response) -> float:
        for name in ("Retry-After", "Backoff"):
            try:
                return max(0.0, float(resp.headers.get(name, "")))
            except (TypeError, ValueError):
                continue
        return 1.0

    @staticmethod
    def _check(resp: requests.Response, write: bool) -> None:
        code = resp.status_code
        if 200 <= code < 300:
            return
        if code == 403:
            need = "read and write" if write else "read"
            raise ZoteroError(
                f"Zotero refused access (403). The API key must have {need} access "
                f"to this library. Create or edit a key at {KEYS_URL}.")
        if code == 404:
            raise ZoteroError("Not found on Zotero (404): check the library id, library type and item key.")
        if code == 412:
            raise ZoteroError("The Zotero item was modified meanwhile (412); rerun to get the latest version.")
        snippet = (resp.text or "")[:200]
        raise ZoteroError(f"Zotero API error {code}: {snippet}")

    def _get_json(self, path: str, params: dict | None = None) -> Any:
        params = {"format": "json", **(params or {})}
        try:
            return self._request("GET", path, params=params).json()
        except ValueError as exc:
            raise ZoteroError(f"Invalid JSON from Zotero: {exc}") from exc

    def _paginate(self, path: str, params: dict | None = None,
                  limit: int | None = None) -> list[dict]:
        """Collect pages of 100 until exhausted (or `limit` reached)."""
        out: list[dict] = []
        start = 0
        while limit is None or len(out) < limit:
            size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(out))
            page_params = {**(params or {}), "format": "json", "limit": size, "start": start}
            resp = self._request("GET", path, params=page_params)
            try:
                page = resp.json()
            except ValueError as exc:
                raise ZoteroError(f"Invalid JSON from Zotero: {exc}") from exc
            out.extend(page)
            start += len(page)
            total = resp.headers.get("Total-Results")
            if len(page) < size or (total is not None and total.isdigit() and start >= int(total)):
                break
        return out if limit is None else out[:limit]

    # -- mapping --------------------------------------------------------

    @staticmethod
    def _to_item(raw: dict) -> Item:
        data = raw.get("data", {})
        creators = []
        for c in data.get("creators", []):
            last, first = c.get("lastName", ""), c.get("firstName", "")
            if last and first:
                creators.append(f"{last}, {first}")
            else:
                creators.append(last or first or c.get("name", ""))
        parsed = raw.get("meta", {}).get("parsedDate", "")
        return Item(key=data.get("key", raw.get("key", "")), title=data.get("title", ""),
                    creators=[c for c in creators if c], item_type=data.get("itemType", ""),
                    year=parsed[:4] if parsed else "", version=int(data.get("version", 0)))

    @staticmethod
    def _to_attachment(raw: dict) -> Attachment:
        data = raw.get("data", {})
        return Attachment(key=data.get("key", ""), parent_key=data.get("parentItem", ""),
                          filename=data.get("filename") or data.get("title", ""),
                          content_type=data.get("contentType", ""),
                          link_mode=data.get("linkMode", ""), md5=data.get("md5"))

    @staticmethod
    def _to_note(raw: dict) -> Note:
        data = raw.get("data", {})
        return Note(key=data.get("key", ""), parent_key=data.get("parentItem", ""),
                    html=data.get("note", ""), version=int(data.get("version", 0)),
                    tags=[t["tag"] for t in data.get("tags", []) if "tag" in t])

    # -- public API -----------------------------------------------------

    def collections(self) -> list[Collection]:
        """All collections of the library."""
        result = []
        for raw in self._paginate("/collections"):
            data = raw.get("data", {})
            result.append(Collection(key=data["key"], name=data.get("name", ""),
                                     parent_key=data.get("parentCollection") or None,
                                     num_items=int(raw.get("meta", {}).get("numItems", 0))))
        return result

    def items(self, collection_key: str | None = None, query: str | None = None,
              limit: int | None = None) -> list[Item]:
        """Top-level regular items (no attachments or standalone notes)."""
        path = f"/collections/{collection_key}/items/top" if collection_key else "/items/top"
        params = {"q": query} if query else {}
        raws = self._paginate(path, params, limit)
        return [self._to_item(r) for r in raws
                if r.get("data", {}).get("itemType") not in _NON_REGULAR_TYPES]

    def item(self, key: str) -> Item:
        """One item by key."""
        return self._to_item(self._get_json(f"/items/{key}"))

    def _children(self, item_key: str, item_type: str) -> list[dict]:
        raws = self._paginate(f"/items/{item_key}/children")
        return [r for r in raws if r.get("data", {}).get("itemType") == item_type]

    def attachments(self, item_key: str) -> list[Attachment]:
        """File attachments of an item."""
        return [self._to_attachment(r) for r in self._children(item_key, "attachment")]

    def download(self, attachment: Attachment) -> bytes:
        """Download a stored file from Zotero cloud storage."""
        if attachment.link_mode in ("linked_file", "linked_url"):
            raise ZoteroError(
                f"{attachment.filename or attachment.key} is a linked file/URL: it is not stored "
                "in Zotero cloud storage, so it cannot be downloaded through the API.")
        return self._request("GET", f"/items/{attachment.key}/file").content

    def notes(self, item_key: str) -> list[Note]:
        """Child notes of an item."""
        return [self._to_note(r) for r in self._children(item_key, "note")]

    def create_note(self, parent_key: str, html: str, tags: list[str]) -> str:
        """Create a child note and return its key."""
        payload = [{"itemType": "note", "parentItem": parent_key, "note": html,
                    "tags": [{"tag": t} for t in tags]}]
        resp = self._request("POST", "/items", json=payload, write=True)
        try:
            body = resp.json()
        except ValueError as exc:
            raise ZoteroError(f"Invalid JSON from Zotero: {exc}") from exc
        failed = body.get("failed") or {}
        if failed:
            first = next(iter(failed.values()))
            msg = first.get("message", first) if isinstance(first, dict) else first
            raise ZoteroError(f"Zotero could not create the note: {msg}")
        created = (body.get("successful") or {}).get("0")
        if isinstance(created, dict):
            created = created.get("key") or created.get("data", {}).get("key")
        created = created or (body.get("success") or {}).get("0")
        if not created:
            raise ZoteroError("Zotero did not return the new note key.")
        return created

    def update_note(self, note: Note, html: str) -> None:
        """Replace a note's HTML, guarded by its version."""
        self._request("PATCH", f"/items/{note.key}", json={"note": html},
                      headers={"If-Unmodified-Since-Version": str(note.version)}, write=True)
