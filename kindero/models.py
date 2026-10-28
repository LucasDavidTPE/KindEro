"""Shared data types. This module is the contract between the other modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


class KinderoError(Exception):
    """Base class for errors shown to the user (no traceback)."""


class ConfigError(KinderoError):
    pass


class ZoteroError(KinderoError):
    pass


class SendError(KinderoError):
    pass


@dataclass
class Config:
    zotero_library_id: str = ""
    zotero_api_key: str = ""
    zotero_library_type: str = "user"  # "user" or "group"
    kindle_email: str = ""  # e.g. name_abc@kindle.com
    sender_email: str = ""  # must be approved in the Amazon account
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""  # overridden by KINDERO_SMTP_PASSWORD
    smtp_ssl: bool = False  # True for implicit TLS (port 465), else STARTTLS


@dataclass
class Collection:
    key: str
    name: str
    parent_key: str | None = None
    num_items: int = 0


@dataclass
class Item:
    key: str
    title: str
    creators: list[str] = field(default_factory=list)  # "Last, First" or name
    item_type: str = ""
    year: str = ""
    version: int = 0


@dataclass
class Attachment:
    key: str
    parent_key: str
    filename: str
    content_type: str
    link_mode: str  # imported_file, imported_url, linked_file, linked_url
    md5: str | None = None


@dataclass
class Note:
    key: str
    parent_key: str
    html: str
    version: int
    tags: list[str] = field(default_factory=list)


@dataclass
class Clipping:
    title: str
    author: str
    kind: str  # "highlight", "note" or "bookmark"
    text: str
    page: str | None = None
    location_start: int | None = None
    location_end: int | None = None
    added: datetime | None = None


@dataclass
class SyncResult:
    title: str
    author: str
    status: str  # "created", "updated", "unchanged", "not_found", "dry_run"
    item_key: str | None = None
    note_key: str | None = None
    count: int = 0
