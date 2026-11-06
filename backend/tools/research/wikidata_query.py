"""Wikidata — built-in tool `wikidata_query` (Wikidata API and SPARQL endpoint; free, no key).

A SPARQL ``SELECT`` / ``ASK`` query runs on query.wikidata.org and comes back as a table. An item
id (Q42) returns its label, description, aliases and Wikipedia link. Anything else searches items
by name. Wikimedia asks automated clients for a descriptive User-Agent, which is sent.
"""

import re
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, markdown_table, params

LABEL = "[Wikidata]"
API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
UA = "pipesets-ai/1.0 (workflow tool; https://www.wikidata.org/wiki/Wikidata:Data_access)"
_QID = re.compile(r"^[QP]\d+$", re.I)
_SPARQL = re.compile(r"^\s*(PREFIX\s[^\n]*\n\s*)*(SELECT|ASK)\b", re.I)
MAX_ROWS = 50

TOOL = ToolSpec(
    id="wikidata_query",
    name="Wikidata",
    icon="🗃️",
    category="Research & Knowledge",
    description="Looks up structured facts on Wikidata: search items by name, read an item (Q42), or run a SPARQL SELECT query. Free, no key.",
    default_config={"language": "en", "max_results": 10},
    order=160,
    parameters=params({"query": {"type": "string", "description": "An item name to search, an item id like Q42, or a SPARQL SELECT query"}}),
    input_param="query",
)


def _cell(binding: Dict[str, Any]) -> str:
    value = binding.get("value", "")
    return value.rsplit("/", 1)[-1] if value.startswith("http://www.wikidata.org/entity/") else value


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text = inp.strip()
    if not text:
        return f"{LABEL} Provide an item name, an id like Q42, or a SPARQL SELECT query."
    lang = (cfg.get("language") or "en").strip()
    try:
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": UA}) as client:
            if _SPARQL.match(text):
                resp = await client.get(SPARQL, params={"query": text, "format": "json"})
                if resp.status_code == 400:
                    return f"{LABEL} The query was rejected: {resp.text.strip().splitlines()[0][:300] if resp.text.strip() else 'bad query'}"
                if resp.status_code != 200:
                    return f"{LABEL} HTTP {resp.status_code} from the query service (timeouts are 60s)."
                body = resp.json()
                if "boolean" in body:
                    return f"{LABEL} {body['boolean']}"
                cols = body.get("head", {}).get("vars", [])
                rows = body.get("results", {}).get("bindings", [])
                if not rows:
                    return f"{LABEL} The query returned no rows."
                table = markdown_table(cols, [[_cell(r.get(c, {})) for c in cols] for r in rows[:MAX_ROWS]])
                more = f"\n({len(rows) - MAX_ROWS} more rows not shown — add a LIMIT)" if len(rows) > MAX_ROWS else ""
                return f"{LABEL} {len(rows)} row(s)\n\n{table}{more}"

            if _QID.match(text):
                resp = await client.get(API, params={"action": "wbgetentities", "ids": text.upper(), "format": "json",
                                                     "props": "labels|descriptions|aliases|sitelinks/urls",
                                                     "languages": f"{lang}|mul", "sitefilter": f"{lang}wiki"})
                resp.raise_for_status()
                entity = (resp.json().get("entities") or {}).get(text.upper()) or {}
                if "missing" in entity or not entity:
                    return f"{LABEL} No item {text.upper()}."
                # "mul" holds the label shared by every language (Wikidata's default since 2024)
                pick = lambda field: entity.get(field, {}).get(lang) or entity.get(field, {}).get("mul")  # noqa: E731
                label = (pick("labels") or {}).get("value", "(no label)")
                desc = (pick("descriptions") or {}).get("value", "")
                aliases = ", ".join(a["value"] for a in (pick("aliases") or [])[:10])
                wiki = (entity.get("sitelinks", {}).get(f"{lang}wiki") or {}).get("url", "")
                return "\n".join(filter(None, [f"{LABEL} {text.upper()}: {label}", desc and f"  {desc}",
                                               aliases and f"  Also known as: {aliases}", wiki and f"  {wiki}",
                                               f"  https://www.wikidata.org/wiki/{text.upper()}"]))

            limit = max(1, min(int(cfg.get("max_results") or 10), 50))
            resp = await client.get(API, params={"action": "wbsearchentities", "search": text, "language": lang,
                                                 "uselang": lang, "type": "item", "limit": limit, "format": "json"})
            resp.raise_for_status()
            hits = resp.json().get("search") or []
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach Wikidata: {e}"
    except ValueError:
        return f"{LABEL} Wikidata returned an unexpected response."
    if not hits:
        return f"{LABEL} No items match '{text}'."
    return f"{LABEL} {len(hits)} item(s) for '{text}'\n" + "\n".join(
        f"- {h['id']}: {h.get('label', '')}" + (f" — {h['description']}" if h.get("description") else "") for h in hits)
