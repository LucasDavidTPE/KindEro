import io
import smtplib

import pytest
from pypdf import PdfReader, PdfWriter

from kindero import kindle
from kindero.models import Attachment, Config, Item, SendError


def att(filename="paper.pdf", ctype="application/pdf"):
    return Attachment("A1", "I1", filename, ctype, "imported_file")


def item(**kw):
    base = dict(key="I1", title="Deep Learning", creators=["LeCun, Yann", "Bengio, Yoshua"], year="2015")
    base.update(kw)
    return Item(**base)


def make_pdf() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


# --- filenames ---

def test_filename_basic():
    assert kindle.kindle_filename(item(), att()) == "LeCun 2015 - Deep Learning.pdf"


def test_filename_missing_parts():
    assert kindle.kindle_filename(item(creators=[], year=""), att()) == "Deep Learning.pdf"
    assert kindle.kindle_filename(item(year=""), att()) == "LeCun - Deep Learning.pdf"
    assert kindle.kindle_filename(item(title=""), att()) == "LeCun 2015.pdf"


def test_filename_single_field_author():
    assert kindle.kindle_filename(item(creators=["WHO"]), att()).startswith("WHO 2015")


def test_filename_sanitised():
    name = kindle.kindle_filename(item(title='A: b/c  "d"?\x01  e*'), att())
    assert name == "LeCun 2015 - A b c d e.pdf"


def test_filename_truncated_keeps_extension():
    name = kindle.kindle_filename(item(title="x" * 500), att())
    assert len(name) <= 120
    assert name.endswith(".pdf")
    assert name.startswith("LeCun 2015 - xxx")


def test_filename_ext_from_content_type():
    assert kindle.kindle_filename(item(), att("", "application/epub+zip")).endswith(".epub")
    assert kindle.kindle_filename(item(), att("noext", "application/pdf")).endswith(".pdf")


# --- prepare_document ---

def test_prepare_pdf_sets_metadata():
    name, data = kindle.prepare_document(item(), att(), make_pdf())
    assert name == "LeCun 2015 - Deep Learning.pdf"
    meta = PdfReader(io.BytesIO(data)).metadata
    assert meta.title == "Deep Learning"
    assert "LeCun, Yann" in meta.author


def test_prepare_pdf_garbage_falls_back(caplog):
    with caplog.at_level("WARNING"):
        name, data = kindle.prepare_document(item(), att(), b"not a pdf")
    assert data == b"not a pdf"
    assert name.endswith(".pdf")
    assert caplog.records


def test_prepare_epub_untouched():
    name, data = kindle.prepare_document(item(), att("b.epub", "application/epub+zip"), b"zip")
    assert name.endswith(".epub") and data == b"zip"


def test_prepare_unsupported():
    with pytest.raises(SendError, match="Supported"):
        kindle.prepare_document(item(), att("data.zip", "application/zip"), b"x")


# --- send_to_kindle ---

class FakeSMTP:
    instances: list = []
    fail_login = False

    def __init__(self, host, port, **kw):
        self.host, self.port, self.calls, self.messages = host, port, [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, **kw):
        self.calls.append("starttls")

    def login(self, user, pw):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad creds")
        self.calls.append(("login", user, pw))

    def send_message(self, msg):
        self.messages.append(msg)


@pytest.fixture(autouse=True)
def reset_fake():
    FakeSMTP.instances = []
    FakeSMTP.fail_login = False


def cfg(**kw):
    base = dict(kindle_email="me_x@kindle.com", sender_email="me@example.com",
                smtp_host="smtp.example.com", smtp_port=587, smtp_user="me", smtp_password="pw")
    base.update(kw)
    return Config(**base)


def test_send_starttls_login_and_message():
    docs = [("É article.pdf", b"%PDF-1"), ("b.epub", b"zip")]
    kindle.send_to_kindle(docs, cfg(), smtp_factory=FakeSMTP)
    smtp = FakeSMTP.instances[0]
    assert smtp.calls == ["starttls", ("login", "me", "pw")]
    assert len(smtp.messages) == 1
    msg = smtp.messages[0]
    assert msg["To"] == "me_x@kindle.com" and msg["From"] == "me@example.com"
    assert msg["Subject"] == "KindEro"
    atts = list(msg.iter_attachments())
    assert [a.get_filename() for a in atts] == ["É article.pdf", "b.epub"]
    assert atts[0].get_content_type() == "application/pdf"
    assert atts[0].get_content() == b"%PDF-1"


def test_no_login_without_user():
    kindle.send_to_kindle([("a.txt", b"x")], cfg(smtp_user=""), smtp_factory=FakeSMTP)
    assert FakeSMTP.instances[0].calls == ["starttls"]


def test_send_requires_sender():
    with pytest.raises(SendError):
        kindle.send_to_kindle([("a.txt", b"x")], cfg(sender_email="", smtp_user=""), smtp_factory=FakeSMTP)


def test_send_sender_fallback_to_smtp_user():
    kindle.send_to_kindle([("a.txt", b"x")], cfg(sender_email="", smtp_user="u@x.org"), smtp_factory=FakeSMTP)
    assert FakeSMTP.instances[0].messages[0]["From"] == "u@x.org"


def test_send_ssl_skips_starttls():
    kindle.send_to_kindle([("a.txt", b"x")], cfg(smtp_ssl=True, smtp_port=465), smtp_factory=FakeSMTP)
    assert "starttls" not in FakeSMTP.instances[0].calls


def test_send_validates_config():
    for bad in (cfg(kindle_email=""), cfg(smtp_host="")):
        with pytest.raises(SendError):
            kindle.send_to_kindle([("a.txt", b"x")], bad, smtp_factory=FakeSMTP)


def test_batching(monkeypatch):
    monkeypatch.setattr(kindle, "MAX_EMAIL_BYTES", 400)  # raw limit 300
    docs = [("a.txt", b"a" * 200), ("b.txt", b"b" * 200), ("c.txt", b"c" * 50), ("d.txt", b"d" * 50)]
    kindle.send_to_kindle(docs, cfg(), smtp_factory=FakeSMTP)
    smtp = FakeSMTP.instances[0]
    names = [[a.get_filename() for a in m.iter_attachments()] for m in smtp.messages]
    assert names == [["a.txt"], ["b.txt", "c.txt", "d.txt"]]


def test_single_doc_too_large(monkeypatch):
    monkeypatch.setattr(kindle, "MAX_EMAIL_BYTES", 400)
    with pytest.raises(SendError, match="too large"):
        kindle.send_to_kindle([("big.pdf", b"x" * 301)], cfg(), smtp_factory=FakeSMTP)
    assert FakeSMTP.instances == []


def test_auth_error_mapped():
    FakeSMTP.fail_login = True
    with pytest.raises(SendError, match="app password"):
        kindle.send_to_kindle([("a.txt", b"x")], cfg(), smtp_factory=FakeSMTP)


def test_connection_error_mentions_approved_list():
    def boom(host, port, **kw):
        raise OSError("unreachable")

    with pytest.raises(SendError, match="Approved Personal Document"):
        kindle.send_to_kindle([("a.txt", b"x")], cfg(), smtp_factory=boom)
