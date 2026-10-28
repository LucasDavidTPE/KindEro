"""Prepare documents and send them to a Kindle by e-mail (Send to Kindle)."""

from __future__ import annotations

import io
import logging
import mimetypes
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import PurePath

from .models import Attachment, Config, Item, SendError

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".epub", ".doc", ".docx", ".txt", ".rtf", ".htm", ".html",
     ".png", ".jpg", ".jpeg", ".gif", ".bmp"}
)

# Amazon's limit for one e-mail.
MAX_EMAIL_BYTES = 50 * 1024 * 1024
# Attachments are base64-encoded (x4/3) in the message, so the raw bytes of
# one e-mail are kept under 3/4 of the limit.
_RAW_FRACTION = (3, 4)
MAX_FILENAME_LEN = 120
_SUBJECT = "KindEro"  # not "convert", which would trigger conversion

_CONTENT_TYPE_EXT = {
    "application/pdf": ".pdf",
    "application/epub+zip": ".epub",
    "text/plain": ".txt",
    "text/html": ".html",
    "application/rtf": ".rtf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def _clean(text: str) -> str:
    """Remove characters illegal in file names and collapse whitespace."""
    return re.sub(r"\s+", " ", _ILLEGAL.sub(" ", text)).strip()


def _extension(attachment: Attachment) -> str:
    ext = PurePath(attachment.filename or "").suffix.lower()
    if ext:
        return ext
    ctype = (attachment.content_type or "").split(";")[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(ctype, "")


def _last_name(creator: str) -> str:
    creator = creator.strip()
    if "," in creator:
        return creator.split(",", 1)[0].strip()
    return creator


def kindle_filename(item: Item, attachment: Attachment) -> str:
    """Build `Author year - Title.ext`, omitting missing parts."""
    ext = _extension(attachment)
    author = _clean(_last_name(item.creators[0])) if item.creators else ""
    head = " ".join(p for p in (author, _clean(item.year or "")) if p)
    title = _clean(item.title or "")
    budget = MAX_FILENAME_LEN - len(ext) - (len(head) + 3 if head and title else 0)
    title = title[: max(budget, 0)].rstrip()
    if head and title:
        stem = f"{head} - {title}"
    else:
        stem = head or title or "document"
    return stem[: MAX_FILENAME_LEN - len(ext)].rstrip() + ext


def _rewrite_pdf_metadata(item: Item, data: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("encrypted PDF")
    writer = PdfWriter(clone_from=reader)
    meta = {"/Title": item.title or ""}
    if item.creators:
        meta["/Author"] = "; ".join(item.creators)
    writer.add_metadata(meta)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def prepare_document(item: Item, attachment: Attachment, data: bytes) -> tuple[str, bytes]:
    """Return (filename, bytes) ready to send; PDFs get Title/Author metadata."""
    name = kindle_filename(item, attachment)
    ext = PurePath(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise SendError(
            f"Cannot send {attachment.filename or name!r} to a Kindle: unsupported format "
            f"{ext or '(unknown)'}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    if ext == ".pdf":
        try:
            data = _rewrite_pdf_metadata(item, data)
        except Exception as exc:  # pypdf raises many error types
            log.warning("Could not rewrite PDF metadata for %s: %s", name, exc)
    return name, data


def _batches(docs: list[tuple[str, bytes]], limit: int) -> list[list[tuple[str, bytes]]]:
    batches: list[list[tuple[str, bytes]]] = []
    current: list[tuple[str, bytes]] = []
    size = 0
    for doc in docs:
        if current and size + len(doc[1]) > limit:
            batches.append(current)
            current, size = [], 0
        current.append(doc)
        size += len(doc[1])
    if current:
        batches.append(current)
    return batches


def _message(batch: list[tuple[str, bytes]], sender: str, to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = _SUBJECT
    msg.set_content("Sent with KindEro.")
    for name, data in batch:
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg


def send_to_kindle(docs: list[tuple[str, bytes]], cfg: Config, smtp_factory=smtplib.SMTP) -> None:
    """E-mail documents to the Kindle address, split into batches under the size limit."""
    sender = cfg.sender_email or cfg.smtp_user
    if not cfg.kindle_email:
        raise SendError("No Kindle e-mail configured. Run `kindero init`.")
    if not sender:
        raise SendError("No sender e-mail configured (sender or smtp user). Run `kindero init`.")
    if not cfg.smtp_host:
        raise SendError("No SMTP host configured. Run `kindero init`.")
    if not docs:
        return

    limit = MAX_EMAIL_BYTES * _RAW_FRACTION[0] // _RAW_FRACTION[1]
    for name, data in docs:
        if len(data) > limit:
            raise SendError(
                f"{name!r} is too large to e-mail ({len(data) / 1e6:.1f} MB; "
                f"the limit is about {limit / 1e6:.0f} MB per file)."
            )
    messages = [_message(b, sender, cfg.kindle_email) for b in _batches(docs, limit)]

    hint = (
        f" Make sure {sender} is in your Amazon 'Approved Personal Document "
        "E-mail List' (Manage Your Content and Devices > Preferences)."
    )
    try:
        if cfg.smtp_ssl:
            if smtp_factory is smtplib.SMTP:  # default: switch to implicit TLS
                smtp = smtplib.SMTP_SSL(
                    cfg.smtp_host, cfg.smtp_port, context=ssl.create_default_context()
                )
            else:
                smtp = smtp_factory(cfg.smtp_host, cfg.smtp_port)
        else:
            smtp = smtp_factory(cfg.smtp_host, cfg.smtp_port)
        with smtp:
            if not cfg.smtp_ssl:
                smtp.starttls(context=ssl.create_default_context())
            if cfg.smtp_user:
                smtp.login(cfg.smtp_user, cfg.smtp_password)
            for msg in messages:
                smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise SendError(
            f"SMTP login failed ({exc.smtp_code}). Gmail and Outlook usually require an "
            "app password rather than your normal password."
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise SendError(f"The Kindle address was refused by the server: {exc}.{hint}") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise SendError(f"Sending failed: {exc}.{hint}") from exc
