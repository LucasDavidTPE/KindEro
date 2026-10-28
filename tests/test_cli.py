from kindero import cli
from kindero.models import Attachment, Collection, Config, Item, SyncResult


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.downloaded = []

    def collections(self):
        return [Collection("C1", "Thèse", None, 2), Collection("C2", "Chapitre 1", "C1", 1)]

    def items(self, collection_key=None, query=None, limit=None):
        return [Item("I1", "Deep learning", ["Smith, John"], "journalArticle", "2021")]

    def item(self, key):
        return Item(key, "Paper " + key, ["Doe, Jane"], "journalArticle", "2020")

    def attachments(self, item_key):
        return [
            Attachment("L1", item_key, "linked.pdf", "application/pdf", "linked_file"),
            Attachment("A1", item_key, "paper.pdf", "application/pdf", "imported_file"),
        ]

    def download(self, attachment):
        self.downloaded.append(attachment.key)
        return b"%PDF-fake"


def setup(monkeypatch, sent):
    monkeypatch.setattr(cli, "load_config", lambda: Config(kindle_email="me@kindle.com"))
    monkeypatch.setattr(cli, "ZoteroClient", FakeClient)
    monkeypatch.setattr(cli, "prepare_document", lambda item, att, data: (f"{item.title}.pdf", data))
    monkeypatch.setattr(cli, "send_to_kindle", lambda docs, cfg: sent.extend(docs))


def test_collections_tree(monkeypatch, capsys):
    setup(monkeypatch, [])
    assert cli.main(["collections"]) == 0
    assert capsys.readouterr().out.splitlines() == ["Thèse  (2)", "  Chapitre 1  (1)"]


def test_send_by_key_picks_stored_pdf(monkeypatch, capsys):
    sent = []
    setup(monkeypatch, sent)
    assert cli.main(["send", "K1"]) == 0
    assert sent == [("Paper K1.pdf", b"%PDF-fake")]


def test_send_dry_run_sends_nothing(monkeypatch, capsys):
    sent = []
    setup(monkeypatch, sent)
    assert cli.main(["send", "--collection", "thèse", "--dry-run"]) == 0
    assert sent == []
    assert "would send" in capsys.readouterr().out


def test_unknown_collection_is_a_clean_error(monkeypatch, capsys):
    setup(monkeypatch, [])
    assert cli.main(["send", "--collection", "nope"]) == 1
    assert "No collection named" in capsys.readouterr().err


def test_import_clippings(monkeypatch, tmp_path, capsys):
    setup(monkeypatch, [])
    f = tmp_path / "My Clippings.txt"
    f.write_text(
        "Deep learning (Smith, John)\n"
        "- Your Highlight on page 3 | Location 10-12 | Added on Monday, 3 March 2025 14:05:12\n"
        "\nSome text\n==========\n",
        encoding="utf-8",
    )
    seen = {}

    def fake_sync(clips, client, dry_run=False):
        seen["clips"], seen["dry_run"] = clips, dry_run
        return [SyncResult("Deep learning", "Smith, John", "dry_run", "I1", None, 1)]

    monkeypatch.setattr(cli, "sync_clippings", fake_sync)
    assert cli.main(["import-clippings", str(f), "--dry-run"]) == 0
    assert seen["dry_run"] is True
    assert [c.text for c in seen["clips"]] == ["Some text"]
    assert "dry_run" in capsys.readouterr().out


def test_import_clippings_without_kindle(monkeypatch, capsys):
    setup(monkeypatch, [])
    monkeypatch.setattr(cli, "find_kindle_clippings", lambda: None)
    assert cli.main(["import-clippings"]) == 1
    assert "No Kindle found" in capsys.readouterr().err
