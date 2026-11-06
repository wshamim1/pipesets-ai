"""The document loader registry: catalog, the file / directory / database loaders on generated
fixtures, error messages, and POST /api/retrieval/ingest/loader end to end. Offline — fake
embeddings; web loaders are not exercised here."""
import asyncio
import io
import json
import os
import sqlite3

import pytest

import loaders
from helpers import hdr
from loaders.base import LoaderError

RUNNABLE = ["pdf", "text", "markdown", "csv", "json", "docx", "html", "directory", "excel", "web_url", "sitemap",
            "rss", "wikipedia", "arxiv", "s3", "postgres", "mysql", "sql_database", "docling", "email", "yardi_export",
            "image"]
CATALOG_SIZE = 115


def load(loader_type, source, cfg=None):
    return asyncio.run(loaders.load_documents(loader_type, source, cfg or {}))


def load_error(loader_type, source, cfg=None):
    with pytest.raises(LoaderError) as e:
        load(loader_type, source, cfg)
    return str(e.value)


@pytest.fixture(scope="module")
def F(tmp_path_factory):
    """A folder of generated documents in every supported format (plus files to skip)."""
    import docx
    import openpyxl
    from reportlab.pdfgen import canvas

    root = tmp_path_factory.mktemp("docs")
    F = str(root)
    os.makedirs(os.path.join(F, "nested"))
    c = canvas.Canvas(os.path.join(F, "report.pdf"))
    c.drawString(72, 720, "Revenue grew 12% in Q3")
    c.showPage()
    c.drawString(72, 720, "Risks: supply chain")
    c.save()
    d = docx.Document()
    d.add_heading("Policy", 1)
    d.add_paragraph("Refunds within 30 days.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text, t.cell(1, 0).text, t.cell(1, 1).text = "Plan", "Price", "Pro", "$20"
    d.save(os.path.join(F, "policy.docx"))
    wb = openpyxl.Workbook()
    wb.active.title = "Q3"
    wb.active.append(["Region", "Revenue"])
    wb.active.append(["EMEA", 120])
    wb.create_sheet("Empty")
    wb.save(os.path.join(F, "sales.xlsx"))
    files = {
        "people.csv": "name;city\nAna;Lisbon\nRaj;Pune\n",
        "items.json": json.dumps([{"id": 1, "tags": ["a"]}, {"id": 2}]),
        "nested/events.jsonl": '{"e": "signup"}\n{"e": "upgrade"}\n',
        "page.html": "<html><title>Docs</title><body><h1>Intro</h1><p>Hello <b>world</b></p><script>x()</script></body></html>",
        "nested/notes.md": "# Notes\nShip it.",
        ".hidden.txt": "secret",
    }
    for name, text in files.items():
        with open(os.path.join(F, name), "w") as f:
            f.write(text)
    with open(os.path.join(F, "image.bin"), "wb") as f:
        f.write(b"\x00\x01")
    return F


@pytest.fixture(scope="module")
def shop_db(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("db") / "shop.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE products (name TEXT, price REAL)")
    con.executemany("INSERT INTO products VALUES (?, ?)", [("Mug", 9.5), ("Hat", 15.0)])
    con.commit()
    con.close()
    return path


def test_catalog():
    cat = loaders.catalog()
    by_type = {e["type"]: e for e in cat}
    assert len(cat) == CATALOG_SIZE
    assert sorted(e["type"] for e in cat if e["available"]) == sorted(RUNNABLE)
    assert all(e["category"] in loaders.CATEGORY_ORDER for e in cat)
    assert [e["category"] for e in cat] == sorted((e["category"] for e in cat), key=loaders.CATEGORY_ORDER.index)
    assert by_type["pdf"].get("fileBased") and by_type["excel"].get("fileBased")
    assert by_type["postgres"].get("usesConnection") and not by_type["web_url"].get("usesConnection")
    assert [loaders.resolve(a) for a in ("PyPDFLoader", "WebBaseLoader", "sqlite", "onedrive", "Docx2txtLoader")] \
        == ["pdf", "web_url", "sql_database", "onedrive", "docx"], "importer aliases resolve"
    assert "isn't available yet" in load_error("youtube", "https://youtu.be/x")
    assert "Unknown document loader" in load_error("nope", "x")
    assert "Set the File Path" in load_error("pdf", "  ")


def test_file_loaders(F):
    docs = load("pdf", os.path.join(F, "report.pdf"))
    assert [x["metadata"]["page"] for x in docs] == [1, 2] and "Revenue grew 12%" in docs[0]["text"]
    docs = load("docx", os.path.join(F, "policy.docx"))
    assert "# Policy" in docs[0]["text"] and "| Pro | $20 |" in docs[0]["text"]
    docs = load("excel", os.path.join(F, "sales.xlsx"))
    assert len(docs) == 1 and "Sheet: Q3" in docs[0]["text"] and "| EMEA | 120 |" in docs[0]["text"]
    docs = load("csv", os.path.join(F, "people.csv"))
    assert [x["text"] for x in docs] == ["name: Ana\ncity: Lisbon", "name: Raj\ncity: Pune"], "delimiter sniffed"
    docs = load("json", os.path.join(F, "items.json"))
    assert len(docs) == 2 and 'tags: ["a"]' in docs[0]["text"]
    assert len(load("json", os.path.join(F, "nested", "events.jsonl"))) == 2
    docs = load("html", os.path.join(F, "page.html"))
    assert "# Intro" in docs[0]["text"] and "**world**" in docs[0]["text"] and "x()" not in docs[0]["text"]
    assert docs[0]["metadata"]["title"] == "Docs"
    assert load("markdown", os.path.join(F, "nested", "notes.md"))[0]["text"] == "# Notes\nShip it."
    assert "File not found" in load_error("pdf", os.path.join(F, "nope.pdf"))
    assert "Directory loader" in load_error("text", F)
    assert "isn't valid JSON" in load_error("json", os.path.join(F, "people.csv"))


def test_directory(F):
    sources = sorted({x["metadata"]["source"] for x in load("directory", F)})
    assert sources == sorted(["report.pdf", "policy.docx", "sales.xlsx", "people.csv", "items.json", "page.html",
                              os.path.join("nested", "events.jsonl"), os.path.join("nested", "notes.md")]), \
        "every supported file, recursively; hidden / unsupported skipped"
    assert not any(x["metadata"]["source"].startswith("nested") for x in load("directory", F, {"recursive": "false"}))
    assert "Folder not found" in load_error("directory", os.path.join(F, "nope"))


def test_databases(shop_db):
    docs = load("sql_database", shop_db)
    assert len(docs) == 2 and "name: Mug" in docs[0]["text"] and docs[0]["metadata"]["tables"] == "products"
    docs = load("sql_database", f"sqlite:///{shop_db}", {"db_query": "SELECT name FROM products WHERE price > 10"})
    assert len(docs) == 1 and "Hat" in docs[0]["text"]
    assert "Postgres error" in load_error("postgres", "", {"connection": {"host": "127.0.0.1", "port": 1, "user": "x"}})
    assert "s3://bucket/prefix" in load_error("s3", "my-bucket/docs")


def test_ingest_endpoint(client, F, shop_db, monkeypatch):
    from routers import retrieval
    from services.vector_store import store_for

    async def fake_embed(texts, provider, model, api_key):
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(retrieval, "embed_texts", fake_embed)
    r = client.get("/api/retrieval/loaders", headers=hdr())
    assert r.status_code == 200 and len(r.json()["loaders"]) == CATALOG_SIZE
    r = client.post("/api/retrieval/ingest/loader", headers=hdr(), json={
        "loader_type": "PyPDFLoader", "source": os.path.join(F, "report.pdf"), "collection": "chk_pdf"})
    assert r.status_code == 200, r.text
    assert r.json()["loader_type"] == "pdf" and r.json()["documents_loaded"] == 2 and r.json()["chunks_ingested"] >= 2
    stored = store_for("chk_pdf").search("chk_pdf", [1.0, 0.0, 0.0], 10)
    assert sorted(c["metadata"].get("page") for c in stored) == [1, 2]
    assert all(c["metadata"]["loader_type"] == "pdf" for c in stored)
    r = client.post("/api/retrieval/ingest/loader", headers=hdr(),
                    json={"loader_type": "youtube", "source": "x", "collection": "c"})
    assert r.status_code == 400 and "isn't available yet" in r.text
    r = client.post("/api/retrieval/ingest/loader", headers=hdr(), json={
        "loader_type": "sql_database", "source": "", "collection": "chk_db", "connection": {"path": shop_db}})
    assert r.status_code == 200 and r.json()["documents_loaded"] == 2, r.text


# ── Document extraction loaders (plan.md P1): Docling / OCR fallback, email, Yardi export ──────────

def _pdf(path, pages):
    """A PDF with one page per entry; None = a page with no text layer (like a scan)."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path)
    for text in pages:
        if text:
            c.drawString(72, 720, text)
        else:
            c.rect(72, 600, 200, 100)
        c.showPage()
    c.save()
    return path


def _scan(path, lines, fmt="PDF"):
    """A real scan: text drawn into an image, saved as an image-only PDF (no text layer) or image."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1700, 400), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=48)
    for i, line in enumerate(lines):
        draw.text((60, 60 + i * 90), line, fill="black", font=font)
    img.save(path, fmt, resolution=200)
    return path


def _only(monkeypatch, *engines):
    from loaders import _ocr
    monkeypatch.setattr(_ocr, "available", lambda e: e in engines)


def test_pdf_ocr_engines(tmp_path, monkeypatch):
    from loaders import _docling

    path = _pdf(str(tmp_path / "lease.pdf"), ["Lease between Landlord and Operator", None])
    calls = []

    def fake_convert(name, data, cfg):
        calls.append(cfg.get("ocr"))
        return [(1, "OCR copy of page 1"), (2, "Exhibit B: licensed beds 120")]

    monkeypatch.setattr(_docling, "convert_pages", fake_convert)
    _only(monkeypatch, "docling")
    docs = load("pdf", path)
    assert [(d["metadata"]["page"], d["text"]) for d in docs] == [
        (1, "Lease between Landlord and Operator"), (2, "Exhibit B: licensed beds 120")], \
        "only the page without a text layer comes from OCR"
    assert calls == [True] and docs[1]["metadata"]["parser"] == "ocr:docling" and "parser" not in docs[0]["metadata"]

    calls.clear()
    assert len(load("pdf", path, {"ocr_engine": "off"})) == 1 and calls == []
    assert len(load("pdf", path, {"ocr_fallback": False})) == 1 and calls == [], "the old setting still turns it off"

    _only(monkeypatch, "tesseract", "docling")
    import loaders._ocr as ocr
    monkeypatch.setattr(ocr, "_tesseract", lambda png, lang: f"tesseract {lang} {png[:4] == bytes([137, 80, 78, 71])}")
    docs = load("pdf", path, {"ocr_language": "eng+spa"})
    assert docs[1]["text"] == "tesseract eng+spa True" and docs[1]["metadata"]["parser"] == "ocr:tesseract", \
        "auto prefers Tesseract over Docling; pages rendered to PNG"

    _only(monkeypatch)
    scan = _pdf(str(tmp_path / "scan.pdf"), [None])
    assert "No OCR engine is installed" in load_error("pdf", scan)
    assert "Tesseract isn't installed" in load_error("pdf", scan, {"ocr_engine": "tesseract"})
    assert "Unknown OCR engine" in load_error("pdf", scan, {"ocr_engine": "magic"})
    docs = load("pdf", path)
    assert len(docs) == 1 and docs[0]["metadata"]["pages_without_text"] == "2", \
        "a page OCR couldn't read is reported, not silently dropped"
    assert "No OCR engine" in docs[0]["metadata"]["ocr_error"]


def test_vision_ocr(tmp_path, monkeypatch):
    import llm

    seen = []

    async def fake_complete(req):
        part = req.messages[0]["content"][1]
        seen.append((req.provider, req.model, req.temperature, part["image_url"]["url"][:22]))
        return type("R", (), {"text": "  4.1 Term ends December 31, 2034  "})()

    monkeypatch.setattr(llm, "complete", fake_complete)
    path = _pdf(str(tmp_path / "lease.pdf"), [None, "Typed page", None])
    vision = {"ocr_engine": "vision", "ocr_provider": "openai", "ocr_model": "gpt-4o-mini"}
    docs = load("pdf", path, vision)
    assert [(d["metadata"]["page"], d["text"]) for d in docs] == [
        (1, "4.1 Term ends December 31, 2034"), (2, "Typed page"), (3, "4.1 Term ends December 31, 2034")]
    assert seen == [("openai", "gpt-4o-mini", 0.0, "data:image/png;base64,")] * 2, "one call per scanned page"
    scan = _pdf(str(tmp_path / "scan.pdf"), [None, None])
    assert "needs a model" in load_error("pdf", scan, {"ocr_engine": "vision"})
    assert "OCR is limited to 1" in load_error("pdf", scan, {**vision, "ocr_max_pages": 1})
    assert "needs a model" in load("pdf", path, {"ocr_engine": "vision"})[0]["metadata"]["ocr_error"]

    folder = tmp_path / "scans"
    folder.mkdir()
    _scan(str(folder / "page.png"), ["x"], "PNG")
    seen.clear()
    docs = load("directory", str(folder), vision)
    assert docs[0]["text"] == "4.1 Term ends December 31, 2034" and len(seen) == 1, \
        "works when called from inside a running event loop (Directory)"


@pytest.mark.skipif(not __import__("shutil").which("tesseract"), reason="tesseract not installed")
def test_tesseract_reads_a_real_scan(tmp_path):
    pdf = _scan(str(tmp_path / "scan.pdf"), ["LEASE AGREEMENT", "Monthly base rent 185000"])
    docs = load("pdf", pdf, {"ocr_engine": "tesseract"})
    assert docs[0]["metadata"]["parser"] == "ocr:tesseract"
    assert "LEASE AGREEMENT" in docs[0]["text"] and "185000" in docs[0]["text"]
    img = _scan(str(tmp_path / "scan.png"), ["Skilled nursing license SNF 1042"], "PNG")
    docs = load("image", img, {"ocr_engine": "tesseract"})
    assert "SNF 1042" in docs[0]["text"] and docs[0]["metadata"]["parser"] == "ocr:tesseract"


def test_image_loader_errors(tmp_path, monkeypatch):
    img = _scan(str(tmp_path / "scan.png"), ["x"], "PNG")
    assert "OCRmyPDF reads PDFs only" in load_error("image", img, {"ocr_engine": "ocrmypdf"})
    assert "OCR is off" in load_error("image", img, {"ocr_engine": "off"})
    _only(monkeypatch)
    assert "No OCR engine is installed" in load_error("image", img)
    assert loaders.resolve("ocr") == "image" and loaders.parser_for("x.TIFF") is not None


def test_docling_loader(tmp_path, monkeypatch):
    from loaders import _docling

    with pytest.raises(LoaderError, match="Docling can't read notes.txt"):
        _docling.convert_pages("notes.txt", b"x", {})
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(_docling, "convert_pages", lambda name, data, cfg: [(1, "Page one"), (3, "Page three")])
    docs = load("docling", str(path))
    assert [(d["metadata"]["page"], d["metadata"]["pages"], d["metadata"]["parser"]) for d in docs] == \
        [(1, 3, "docling"), (3, 3, "docling")]
    assert loaders.parser_for("x.pdf").__module__ == "loaders.files.pdf", "PDF loader stays the default for .pdf"


def test_email_loader(tmp_path):
    from email.message import EmailMessage
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.append(["Operator", "License"])
    wb.active.append(["Sunrise Care LLC", "SNF-1042"])
    xlsx = io.BytesIO()
    wb.save(xlsx)
    pdf = _pdf(str(tmp_path / "license.pdf"), ["State license SNF-1042 expires 2027-03-31"])

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "ops@sunrise.example", "compliance@owner.example", "Renewed license"
    msg["Date"] = "Mon, 02 Nov 2026 09:00:00 -0500"
    msg.set_content("Attached is the renewed license.")
    msg.add_alternative("<p>Attached is the <b>renewed</b> license.</p>", subtype="html")
    msg.add_attachment(open(pdf, "rb").read(), maintype="application", subtype="pdf", filename="license.pdf")
    msg.add_attachment(xlsx.getvalue(), maintype="application",
                       subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="roster.xlsx")
    msg.add_attachment(b"\x00", maintype="application", subtype="octet-stream", filename="logo.bin")
    eml = tmp_path / "renewal.eml"
    eml.write_bytes(bytes(msg))

    docs = load("eml", str(eml))
    head = docs[0]
    assert head["text"].startswith("From: ops@sunrise.example\nTo: compliance@owner.example")
    assert "Subject: Renewed license" in head["text"] and "Attached is the renewed license." in head["text"]
    assert head["metadata"]["attachments"] == "license.pdf, roster.xlsx, logo.bin"
    assert head["metadata"]["skipped_attachments"] == "logo.bin"
    pdf_doc, sheet = docs[1], docs[2]
    assert "SNF-1042 expires" in pdf_doc["text"] and pdf_doc["metadata"]["page"] == 1
    assert pdf_doc["metadata"]["source"] == str(eml) and pdf_doc["metadata"]["attachment"] == "license.pdf"
    assert "| Sunrise Care LLC | SNF-1042 |" in sheet["text"] and sheet["metadata"]["attachment"] == "roster.xlsx"
    assert len(load("email", str(eml), {"attachments": False})) == 1
    assert loaders.parser_for("x.eml") is not None, "Directory and S3 pick up .eml files"

    msg_file = tmp_path / "x.msg"
    msg_file.write_bytes(b"\xd0\xcf\x11\xe0")
    try:
        import extract_msg  # noqa: F401
    except ImportError:
        assert "extract-msg" in load_error("email", str(msg_file))


YARDI_ROWS = [
    ["Rent Roll", "", "", "", "", "", ""],
    ["Healthcare Portfolio (all)", "", "", "", "", "", ""],
    ["As of 10/31/2026", "", "", "", "", "", ""],
    [],
    ["Unit", "Tenant", "Lease From", "Lease To", "Sq Ft", "Monthly Rent", "Security Deposit"],
    ["Maple Grove SNF (mg01)", "", "", "", "", "", ""],
    ["100", "Sunrise Care LLC", "01/01/2020", "12/31/2034", "52000", "185000.00", "370000.00"],
    ["Total Maple Grove SNF", "", "", "", "52000", "185000.00", ""],
    ["Oak Ridge ALF (or02)", "", "", "", "", "", ""],
    ["Unit", "Tenant", "Lease From", "Lease To", "Sq Ft", "Monthly Rent", "Security Deposit"],
    ["A", "Harbor Senior Living", "06/01/2021", "05/31/2031", "38000", "121500.00", ""],
    ["Grand Total", "", "", "", "90000", "306500.00", ""],
]


def test_yardi_export(tmp_path):
    import csv as _csv
    import openpyxl

    path = tmp_path / "rent_roll.csv"
    with open(path, "w", newline="") as f:
        _csv.writer(f).writerows(YARDI_ROWS)
    docs = load("yardi", str(path))
    meta = [d["metadata"] for d in docs]
    assert [(m["property"], m["unit"], m["tenant"], m["lease_to"], m["monthly_rent"]) for m in meta] == [
        ("Maple Grove SNF (mg01)", "100", "Sunrise Care LLC", "12/31/2034", "185000.00"),
        ("Oak Ridge ALF (or02)", "A", "Harbor Senior Living", "05/31/2031", "121500.00")], \
        "property from group headings; totals and repeated headers skipped"
    assert meta[0]["row"] == 7 and meta[0]["report"] == "Rent Roll · Healthcare Portfolio (all) · As of 10/31/2026"
    assert docs[0]["text"].startswith("Property: Maple Grove SNF (mg01)\nUnit: 100\nTenant: Sunrise Care LLC")
    assert "security_deposit" not in meta[1], "empty cells aren't copied"

    wb = openpyxl.Workbook()
    for r in YARDI_ROWS:
        wb.active.append(r)
    wb.active.cell(row=7, column=4).value = __import__("datetime").datetime(2034, 12, 31)
    xlsx = tmp_path / "rent_roll.xlsx"
    wb.save(xlsx)
    docs = load("yardi_export", str(xlsx))
    assert len(docs) == 2 and docs[0]["metadata"]["lease_to"] == "2034-12-31", "Excel dates as ISO dates"

    bad = tmp_path / "plain.csv"
    bad.write_text("a,b\n1,2\n")
    assert "Couldn't find the header row" in load_error("yardi_export", str(bad))
    assert "no tenant rows" in load_error("yardi_export", str(bad), {"header_row": 1})
