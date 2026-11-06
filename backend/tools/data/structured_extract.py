"""Structured Extract — built-in tool `structured_extract` (services/extraction.py).

Loads a document with any document loader (PDF with OCR fallback, Docling, email, Yardi export, …),
asks the model for the node's fields with the page and exact quote each came from, checks every
quote against its page, and (by default) files the fields in the review queue
(services/extraction_reviews.py) for a person to approve or correct.
"""

import json
from types import SimpleNamespace
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, params

LABEL = "[Structured Extract]"

EXAMPLE_FIELDS = """lease_start: Lease commencement date
lease_end: Lease expiration date
monthly_base_rent: Monthly base rent in the first lease year
annual_escalation: Annual rent increase (percent or fixed amount)
tenant_entity: Legal name of the tenant / operator
guarantor: Who guarantees the lease, if anyone
license_requirement: What license the tenant must keep, and the clause that says so
renewal_options: Number and length of renewal options"""

TOOL = ToolSpec(
    id="structured_extract",
    name="Structured Extract",
    icon="🧾",
    category="Data & Files",
    description="Extracts the fields you list from a document, each with the page and exact quote it came from "
                "(checked against the page), and sends them to the review queue for approval. Documents longer "
                "than max_chars are split into parts and the results merged.",
    default_config={
        "loader": "pdf",
        "ocr_engine": "auto",
        "ocr_language": "eng",
        "fields": EXAMPLE_FIELDS,
        "instructions": "",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "api_key": "",
        "base_url": "",
        "review": "queue",
        "batch": "",
        "max_chars": 150000,
    },
    order=6,
    is_new=True,
    selects={
        "loader": Select("Read the document with", [
            ("pdf", "PDF (OCR fallback for scanned pages)"), ("docling", "Docling (OCR, layout, tables)"),
            ("docx", "Word (DOCX)"), ("email", "Email (EML/MSG) with attachments"),
            ("yardi_export", "Yardi report export"), ("image", "Scanned image (OCR)"), ("excel", "Excel"),
            ("text", "Text")]),
        "ocr_engine": Select("OCR for scanned pages", [
            ("auto", "Auto (first installed: OCRmyPDF, Tesseract, Docling)"), ("tesseract", "Tesseract"),
            ("ocrmypdf", "OCRmyPDF"), ("docling", "Docling"), ("vision", "Vision model (this node's model)"),
            ("off", "Off")], "Vision sends page images to the model's provider and is billed per page"),
        "review": Select("Review", [("queue", "Send every field to the review queue"), ("off", "Return only")],
                         "Queued fields wait in Evaluate → Review queue for a person to approve or correct"),
    },
    parameters=params({"source": {"type": "string", "description": "Path of the document to extract from"}}),
    input_param="source",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import asyncio

    import loaders
    from loaders.base import LoaderError
    from services import extraction, extraction_reviews
    from services.long_term_memory import current

    source = inp.strip()
    if source.startswith("{"):
        try:
            source = str(json.loads(source).get("source") or "")
        except (json.JSONDecodeError, AttributeError):
            pass
    if not source:
        return f"{LABEL} Give the path of the document to extract from."
    try:
        fields = extraction.parse_fields(cfg.get("fields"))
        llm_cfg = SimpleNamespace(provider=str(cfg.get("provider") or "openai"), model=str(cfg.get("model") or ""),
                                  api_key=cfg.get("api_key") or "", base_url=cfg.get("base_url") or None)
        # Vision OCR uses the node's own model unless ocr_provider / ocr_model name another
        loader_cfg = {"ocr_provider": llm_cfg.provider, "ocr_model": llm_cfg.model, "ocr_api_key": llm_cfg.api_key,
                      "ocr_base_url": llm_cfg.base_url, **{k: v for k, v in cfg.items() if v not in (None, "")}}
        docs = await loaders.load_documents(str(cfg.get("loader") or "pdf"), source, loader_cfg)
        instructions = str(cfg.get("instructions") or "")
        results, parts = await extraction.extract(docs, fields, llm_cfg, instructions,
                                                  int(cfg.get("max_chars") or extraction.DEFAULT_MAX_CHARS))
    except (LoaderError, extraction.ExtractionError) as e:
        return f"{LABEL} {e}"

    version = extraction.prompt_version(fields, instructions)
    out: Dict[str, Any] = {"source": source, "fields": results, "parts": parts, "prompt_version": version,
                           "unverified": [r["name"] for r in results if r["value"] is not None and not r["verified"]],
                           "not_found": [r["name"] for r in results if r["value"] is None],
                           "conflicts": [r["name"] for r in results if r["conflict"]]}
    if cfg.get("review", "queue") == "queue":
        from services.pipeline_runner import current_scope

        who = current()
        scope = current_scope.get()
        # The node's own batch name, else the batch run this run is a row of (services/batches.py)
        batch = str(cfg.get("batch") or (scope.batch if scope else "") or "")
        if who.tenant_id:
            ids = await asyncio.to_thread(extraction_reviews.add, who.tenant_id, who.project_id, source, results,
                                          batch, who.user, f"{llm_cfg.provider}/{llm_cfg.model}",
                                          version, extraction.pages_of(docs))
            out["review"] = {"queued": len(ids), "where": "Evaluate → Review queue"}
        else:
            out["review"] = {"queued": 0, "why": "not in a project run"}
    return json.dumps(out, ensure_ascii=False)
