"""Long documents and the faster review queue (plan.md P1): splitting a document into parts at section
headings, merging the parts' answers (verified quote wins, disagreements kept as alternatives and
flagged), the cited page shown with each review, bulk approval and the per-field accuracy report.
Steps of one scenario, in order; the model is stubbed."""
import asyncio
import json
import re
from types import SimpleNamespace

import pytest

from db import get_db_connection
from helpers import hdr
from services import extraction

ADMIN = hdr()
BATCH = "long-leases"
FIELDS = "tenant_entity: Legal name of the tenant\nmonthly_base_rent: rent per month\nguarantor: who guarantees it"


def _page(no: int, text: str) -> dict:
    return {"text": (text + " " + "x" * 300)[:300], "metadata": {"source": "long.pdf", "page": no}}


# 8 pages of 300 characters; page 6 opens Article 9 and page 7 is an amendment that changes the rent
DOCS = [_page(1, "LEASE AGREEMENT between Maple Grove Owner LLC and Sunrise Care LLC (Tenant)."),
        _page(2, "ARTICLE 4 Rent. Tenant shall pay monthly base rent of $185,000.00."),
        _page(3, "4.2 Late charges."), _page(4, "4.3 Taxes."), _page(5, "4.4 Insurance."),
        _page(6, "ARTICLE 9 Licensure. Tenant keeps its license."),
        _page(7, "First Amendment: monthly base rent of $190,000.00 from 2027."), _page(8, "Signatures.")]
ANSWERS = {
    1: [{"name": "tenant_entity", "value": "Sunrise Care LLC", "page": 1, "quote": "Sunrise Care LLC (Tenant)",
         "confidence": 0.95},
        {"name": "monthly_base_rent", "value": 185000, "page": 2, "quote": "monthly base rent of $185,000.00",
         "confidence": 0.9},
        {"name": "guarantor", "value": None, "page": None, "quote": None, "confidence": 0.9}],
    2: [{"name": "tenant_entity", "value": "Sunrise Care, LLC", "page": 6, "quote": "Sunrise Care LLC signs here",
         "confidence": 0.6},                                    # same value, unverified: no alternative
        {"name": "monthly_base_rent", "value": 190000.0, "page": 7, "quote": "monthly base rent of $190,000.00",
         "confidence": 0.8},
        {"name": "guarantor", "value": None, "page": None, "quote": None, "confidence": 0.9}],
}
state = {}


def test_split_parts_at_section_headings():
    pages = extraction.pages_of([dict(d) for d in DOCS])
    parts = extraction.split_parts(pages, max_chars=2000)
    assert [[p["page"] for p in part] for part in parts] == [[1, 2, 3, 4, 5], [6, 7, 8]], \
        "page 6 would fit, but the part is two-thirds full and page 6 opens Article 9"
    assert len(extraction.split_parts(pages)) == 1, "a short document stays one call"

    long_page = [{"page": 3, "label": None, "text": "\n\n".join(["para " + "y" * 900] * 6)}]
    pieces = extraction.split_parts(long_page, max_chars=2000)
    assert len(pieces) > 1 and all(len(part[0]["text"]) <= 2000 for part in pieces)
    assert {part[0]["page"] for part in pieces} == {3}, "pieces of one page keep its page number"
    assert all(part[0]["text"].startswith("para") for part in pieces), "cut at paragraph breaks"

    many = [{"page": i, "label": None, "text": "z" * 1900} for i in range(1, 22)]
    with pytest.raises(extraction.ExtractionError, match="needs 21 parts"):
        extraction.split_parts(many, max_chars=2000)


def test_prompt_version():
    fields = extraction.parse_fields(FIELDS)
    v = extraction.prompt_version(fields)
    assert re.fullmatch(r"pv_[0-9a-f]{10}", v) and v == extraction.prompt_version(fields, "  ")
    assert v != extraction.prompt_version(fields, "Use the amended rent.")
    assert v != extraction.prompt_version(fields[:2])


def _fake_model(monkeypatch, fail_part=None):
    import llm

    prompts = []

    async def fake_complete(req):
        system = req.messages[0]["content"]
        prompts.append(system)
        no = int(re.search(r"This is part (\d) of 2", system).group(1))
        if no == fail_part:
            raise RuntimeError("rate limited")
        return SimpleNamespace(text=json.dumps({"fields": ANSWERS[no]}))

    monkeypatch.setattr(llm, "complete", fake_complete)
    return prompts


def test_parts_are_merged(monkeypatch):
    prompts = _fake_model(monkeypatch)
    cfg = SimpleNamespace(provider="openai", model="gpt-4o-mini", api_key="", base_url=None)
    results, parts = asyncio.run(extraction.extract([dict(d) for d in DOCS], extraction.parse_fields(FIELDS), cfg,
                                                    max_chars=2000))
    assert parts == 2 and len(prompts) == 2
    assert any("part 2 of 2 of a longer document (pages 6–8)" in p for p in prompts)
    by = {r["name"]: r for r in results}
    tenant, rent, guarantor = by["tenant_entity"], by["monthly_base_rent"], by["guarantor"]
    assert tenant["value"] == "Sunrise Care LLC" and tenant["verified"] and tenant["confidence"] == 0.95
    assert tenant["alternatives"] == [] and not tenant["conflict"], "'Sunrise Care, LLC' is the same value"
    assert rent["value"] == 185000 and rent["page"] == 2, "both verified: the higher confidence wins"
    assert rent["conflict"] and rent["confidence"] == extraction.CONFLICT_CAP
    assert [(a["value"], a["page"], a["verified"]) for a in rent["alternatives"]] == [(190000.0, 7, True)]
    assert guarantor["value"] is None and guarantor["alternatives"] == []

    _fake_model(monkeypatch, fail_part=2)
    with pytest.raises(extraction.ExtractionError, match=r"failed \(part 2 of 2\): rate limited"):
        asyncio.run(extraction.extract([dict(d) for d in DOCS], extraction.parse_fields(FIELDS), cfg, max_chars=2000))


def test_tool_queues_merged_fields_with_pages(monkeypatch):
    import loaders
    from services.secret_store import request_scope
    from tools.data import structured_extract

    async def fake_load(loader_type, source, cfg):
        return [dict(d) for d in DOCS]

    monkeypatch.setattr(loaders, "load_documents", fake_load)
    _fake_model(monkeypatch)
    cfg = {**structured_extract.TOOL.default_config, "fields": FIELDS, "batch": BATCH, "max_chars": 2000}
    token = request_scope.set(("tenant_demo", "proj_research"))
    try:
        out = json.loads(asyncio.run(structured_extract.run("/data/leases/long.pdf", cfg, "structured_extract")))
    finally:
        request_scope.reset(token)
    assert out["parts"] == 2 and out["conflicts"] == ["monthly_base_rent"]
    assert out["prompt_version"] == extraction.prompt_version(extraction.parse_fields(FIELDS))
    assert out["review"]["queued"] == 3
    state["version"] = out["prompt_version"]


def test_review_shows_cited_page_and_alternatives(client):
    items = client.get("/api/reviews", params={"batch": BATCH}, headers=ADMIN).json()["items"]
    by = {i["field"]: i for i in items}
    state.update({f: i["id"] for f, i in by.items()})
    rent = by["monthly_base_rent"]
    assert rent["conflict"] and rent["alternatives"][0]["page"] == 7 and rent["prompt_version"] == state["version"]

    r = client.get(f"/api/reviews/{state['monthly_base_rent']}/page", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["page"] == 2 and "monthly base rent of $185,000.00" in r.json()["text"]
    alt = client.get(f"/api/reviews/{state['monthly_base_rent']}/page", params={"page": 7}, headers=ADMIN).json()
    assert "$190,000.00" in alt["text"], "an alternative's page can be opened too"
    assert client.get(f"/api/reviews/{state['monthly_base_rent']}/page", params={"page": 3},
                      headers=ADMIN).status_code == 400, "only pages the review cites"
    assert client.get("/api/reviews/rv_nope/page", headers=ADMIN).status_code == 404
    assert client.get(f"/api/reviews/{state['monthly_base_rent']}/page",
                      headers=hdr(project="proj_other")).status_code in (403, 404)

    conn = get_db_connection()
    try:
        kept = sorted(r[0] for r in conn.execute("SELECT page FROM extraction_review_pages WHERE batch = ?", (BATCH,)))
    finally:
        conn.close()
    assert kept == [1, 2, 7], "only cited pages are kept"


def test_bulk_approve(client):
    preview = client.get("/api/reviews/bulk-approve", params={"min_confidence": 0.9, "batch": BATCH}, headers=ADMIN)
    assert preview.status_code == 200 and preview.json()["matching"] == 1 and preview.json()["approved"] == 0
    assert preview.json()["ids"] == [state["tenant_entity"]], "conflicting and not-found fields are left out"
    assert client.post("/api/reviews/bulk-approve", json={"min_confidence": 0.4}, headers=ADMIN).status_code == 400
    r = client.post("/api/reviews/bulk-approve", json={"min_confidence": 0.9, "batch": BATCH}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["approved"] == 1
    tenant = client.get(f"/api/reviews/{state['tenant_entity']}", headers=ADMIN).json()
    assert tenant["status"] == "approved" and tenant["bulk"] and tenant["final_value"] == "Sunrise Care LLC"
    assert tenant["note"].startswith("Bulk approved")


def test_accuracy_report(client):
    def decide(field, **body):
        assert client.post(f"/api/reviews/{state[field]}/decision", json=body, headers=ADMIN).status_code == 200

    decide("monthly_base_rent", decision="correct", value=190000, note="amendment on page 7")
    decide("guarantor", decision="reject")
    group = client.get("/api/reviews/report", params={"batch": BATCH}, headers=ADMIN).json()["groups"][0]
    assert (group["model"], group["prompt_version"]) == ("openai/gpt-4o-mini", state["version"])
    assert (group["right"], group["wrong"], group["bulk"], group["checked"], group["accuracy"]) == (1, 1, 1, 2, 0.5)
    fields = {f["field"]: f for f in group["fields"]}
    assert fields["guarantor"]["accuracy"] == 1.0, "'not found' rejected = the model was right"
    assert fields["monthly_base_rent"]["accuracy"] == 0.0
    assert fields["tenant_entity"]["accuracy"] is None and fields["tenant_entity"]["bulk"] == 1, "bulk isn't scored"

    decide("tenant_entity", decision="approve")
    group = client.get("/api/reviews/report", params={"batch": BATCH}, headers=ADMIN).json()["groups"][0]
    assert (group["right"], group["bulk"], group["accuracy"]) == (2, 0, 0.6667), "a person's look clears bulk"


def test_bulk_approve_is_audited():
    conn = get_db_connection()
    try:
        actions = [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE action LIKE 'review.%'")]
    finally:
        conn.close()
    assert actions.count("review.bulk_approve") == 1, "the preview (GET) isn't audited, the failed POST isn't either"
