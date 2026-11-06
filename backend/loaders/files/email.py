"""Email (EML/MSG) — document loader `email`.

One document for the message (headers + body) and, with ``attachments`` on (the default), the
documents of every attachment a file loader can read (PDF pages, DOCX, XLSX sheets, …), each tagged
with the message it came from. ``.msg`` needs the optional ``extract-msg`` package.
"""

import asyncio
import email
import os
from email import policy
from typing import Any, Dict, List, Optional, Tuple

from loaders._common import read_file, decode
from loaders.base import Document, LoaderError, LoaderSpec, document

LOADER = LoaderSpec(
    type="email",
    label="Email (EML/MSG)",
    icon="📧",
    category="Files",
    desc="Load .eml and Outlook .msg messages, with their attachments",
    source_label="File Path",
    placeholder="/path/to/message.eml",
    file_based=True,
    aliases=("eml", "msg", "outlook", "outlookmessage", "outlookmessageloader", "unstructuredemail"),
    order=180,
)
EXTENSIONS = (".eml", ".msg")

HEADERS = ("from", "to", "cc", "date", "subject")
Attachment = Tuple[str, bytes]


def _html_text(html: str) -> str:
    from tools.data.html_to_markdown import html_to_markdown
    return html_to_markdown(html, include_links=False, main_content_only=False)[1] or ""


def _read_eml(data: bytes) -> Tuple[Dict[str, str], str, List[Attachment]]:
    msg = email.message_from_bytes(data, policy=policy.default)
    headers = {h: str(msg.get(h, "") or "") for h in HEADERS}
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        content = body_part.get_content()
        body = _html_text(content) if body_part.get_content_type() == "text/html" else content
    attachments = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True)
        if part.get_filename() and payload:
            attachments.append((part.get_filename(), payload))
    return headers, body, attachments


def _read_msg(name: str, data: bytes) -> Tuple[Dict[str, str], str, List[Attachment]]:
    try:
        import extract_msg
    except ImportError:
        raise LoaderError(f"Reading Outlook .msg files needs the extract-msg package (pip install extract-msg); "
                          f"save {os.path.basename(name)} as .eml instead.")
    msg = extract_msg.Message(data)
    try:
        headers = {"from": msg.sender or "", "to": msg.to or "", "cc": msg.cc or "",
                   "date": str(msg.date or ""), "subject": msg.subject or ""}
        body = msg.body or (_html_text(decode(msg.htmlBody)) if msg.htmlBody else "")
        attachments = [(a.longFilename or a.shortFilename, a.data) for a in msg.attachments
                       if (a.longFilename or a.shortFilename) and isinstance(a.data, bytes)]
    finally:
        msg.close()
    return headers, body, attachments


def _attachment_docs(message: str, attachments: List[Attachment], cfg: Dict[str, Any]) -> Tuple[List[Document], List[str]]:
    import loaders

    docs: List[Document] = []
    skipped: List[str] = []
    for fname, payload in attachments:
        parser = loaders.parser_for(fname)
        if parser is None or os.path.splitext(fname)[1].lower() in EXTENSIONS:   # unknown type, or a forwarded message
            skipped.append(fname)
            continue
        try:
            parsed = parser(fname, payload, cfg)
        except Exception as e:  # noqa: BLE001 — one bad attachment shouldn't lose the message
            skipped.append(f"{fname} ({e})")
            continue
        for d in parsed:
            d["metadata"].update(source=message, attachment=fname)
            docs.append(d)
    return docs, skipped


def parse(name: str, data: bytes, cfg: Dict[str, Any]) -> List[Document]:
    if name.lower().endswith(".msg"):
        headers, body, attachments = _read_msg(name, data)
    else:
        headers, body, attachments = _read_eml(data)
    lines = [f"{h.capitalize()}: {v}" for h, v in headers.items() if v]
    text = "\n".join(lines) + ("\n\n" + body.strip() if body.strip() else "")
    docs: List[Document] = []
    skipped: List[str] = []
    if cfg.get("attachments", True):
        docs, skipped = _attachment_docs(name, attachments, cfg)
    names: Optional[str] = ", ".join(a for a, _ in attachments) or None
    message = document(text, source=name, subject=headers["subject"], sender=headers["from"],
                       date=headers["date"], attachments=names,
                       skipped_attachments="; ".join(skipped) or None)
    if not text.strip() and not docs:
        raise LoaderError(f"{name} has no readable content.")
    return [message] + docs


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    name, data = read_file(source)
    return await asyncio.to_thread(parse, name, data, cfg)
