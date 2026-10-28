"""Command-line interface: `kindero <command>`."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

from . import __version__
from .clippings import dedupe, read_clippings_file
from .config import config_path, load_config, save_config
from .devices import find_kindle_clippings
from .kindle import SUPPORTED_EXTENSIONS, prepare_document, send_to_kindle
from .models import Attachment, Config, Item, KinderoError
from .sync import sync_clippings
from .zotero import ZoteroClient

# Preferred attachment types when an item has several files.
_PREFERRED_TYPES = ("application/pdf", "application/epub+zip")


def _client(cfg: Config) -> ZoteroClient:
    return ZoteroClient(cfg.zotero_library_id, cfg.zotero_api_key, cfg.zotero_library_type)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def cmd_init(args: argparse.Namespace) -> int:
    try:
        cfg = load_config()
    except KinderoError:
        cfg = Config()
    print("Zotero: create an API key at https://www.zotero.org/settings/keys")
    print("        (allow library access and write access, for the highlight notes).")
    cfg.zotero_library_id = _ask("Zotero library ID (your userID)", cfg.zotero_library_id)
    cfg.zotero_library_type = _ask("Library type (user/group)", cfg.zotero_library_type)
    cfg.zotero_api_key = _ask("Zotero API key", cfg.zotero_api_key)
    print("\nKindle: Amazon > Manage Your Content and Devices > Preferences >")
    print("        Personal Document Settings. Add your sending address to the")
    print("        Approved Personal Document E-mail List.")
    cfg.kindle_email = _ask("Kindle e-mail address", cfg.kindle_email)
    cfg.smtp_host = _ask("SMTP server (e.g. smtp.gmail.com)", cfg.smtp_host)
    cfg.smtp_port = int(_ask("SMTP port (587 STARTTLS, 465 SSL)", str(cfg.smtp_port)))
    cfg.smtp_ssl = cfg.smtp_port == 465
    cfg.smtp_user = _ask("SMTP user", cfg.smtp_user)
    cfg.sender_email = _ask("Sender address", cfg.sender_email or cfg.smtp_user)
    password = getpass.getpass(
        "SMTP password (leave empty to use KINDERO_SMTP_PASSWORD instead): "
    )
    if password:
        cfg.smtp_password = password
    path = save_config(cfg)
    print(f"\nSaved to {path}")
    return 0


def _find_collection_key(client: ZoteroClient, name: str) -> str:
    matches = [c for c in client.collections() if c.name.casefold() == name.casefold()]
    if not matches:
        raise KinderoError(f"No collection named {name!r}. See `kindero collections`.")
    if len(matches) > 1:
        raise KinderoError(f"Several collections are named {name!r}; rename one in Zotero.")
    return matches[0].key


def _authors(item: Item) -> str:
    names = [c.split(",")[0] for c in item.creators]
    if len(names) > 2:
        return f"{names[0]} et al."
    return " & ".join(names)


def cmd_collections(args: argparse.Namespace) -> int:
    collections = _client(load_config()).collections()
    children: dict[str | None, list] = {}
    for c in collections:
        children.setdefault(c.parent_key, []).append(c)

    def show(parent: str | None, depth: int) -> None:
        for c in sorted(children.get(parent, []), key=lambda c: c.name.casefold()):
            print(f"{'  ' * depth}{c.name}  ({c.num_items})")
            show(c.key, depth + 1)

    show(None, 0)
    return 0


def cmd_items(args: argparse.Namespace) -> int:
    client = _client(load_config())
    key = _find_collection_key(client, args.collection) if args.collection else None
    for item in client.items(collection_key=key, query=args.search, limit=args.limit):
        year = f" ({item.year})" if item.year else ""
        print(f"{item.key}  {_authors(item)}{year} - {item.title}")
    return 0


def _pick_attachment(attachments: list[Attachment]) -> Attachment | None:
    stored = [a for a in attachments if a.link_mode in ("imported_file", "imported_url")]
    for content_type in _PREFERRED_TYPES:
        for a in stored:
            if a.content_type == content_type:
                return a
    for a in stored:
        if Path(a.filename).suffix.lower() in SUPPORTED_EXTENSIONS:
            return a
    return None


def cmd_send(args: argparse.Namespace) -> int:
    cfg = load_config()
    client = _client(cfg)
    if args.collection:
        items = client.items(collection_key=_find_collection_key(client, args.collection))
    elif args.keys:
        items = [client.item(k) for k in args.keys]
    else:
        raise KinderoError("Give item keys or --collection NAME (see `kindero items`).")

    docs: list[tuple[str, bytes]] = []
    for item in items:
        attachment = _pick_attachment(client.attachments(item.key))
        if attachment is None:
            print(f"skip  {item.title}: no file stored in Zotero")
            continue
        if args.dry_run:
            print(f"would send  {item.title}  ({attachment.filename})")
            continue
        name, data = prepare_document(item, attachment, client.download(attachment))
        docs.append((name, data))
        print(f"ready  {name}  ({len(data) // 1024} KB)")

    if args.dry_run or not docs:
        return 0
    send_to_kindle(docs, cfg)
    print(f"Sent {len(docs)} document(s) to {cfg.kindle_email}.")
    return 0


def cmd_import_clippings(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else find_kindle_clippings()
    if path is None:
        raise KinderoError(
            "No Kindle found. Plug it in via USB or give the path to My Clippings.txt."
        )
    if not path.is_file():
        raise KinderoError(f"{path} does not exist.")
    clips = dedupe(read_clippings_file(path))
    print(f"Read {len(clips)} clipping(s) from {path}")
    results = sync_clippings(clips, _client(load_config()), dry_run=args.dry_run)
    for r in results:
        print(f"{r.status:<10} {r.title}  ({r.count})")
    missing = sum(r.status == "not_found" for r in results)
    if missing:
        print(f"\n{missing} book(s) not matched to a Zotero item (title too different).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kindero", description="Zotero <-> Kindle, without jailbreak."
    )
    parser.add_argument("--version", action="version", version=f"kindero {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logs")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="interactive setup")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("collections", help="list Zotero collections")
    p.set_defaults(func=cmd_collections)

    p = sub.add_parser("items", help="list Zotero items with their keys")
    p.add_argument("--collection", metavar="NAME")
    p.add_argument("--search", metavar="TEXT")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_items)

    p = sub.add_parser("send", help="send items to the Kindle")
    p.add_argument("keys", nargs="*", metavar="ITEM_KEY")
    p.add_argument("--collection", metavar="NAME")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("import-clippings", help="import Kindle highlights into Zotero")
    p.add_argument("path", nargs="?", help="path to My Clippings.txt (default: auto-detect)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_import_clippings)

    p = sub.add_parser("where", help="print the config file location")
    p.set_defaults(func=lambda a: print(config_path()) or 0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    try:
        return args.func(args)
    except KinderoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
