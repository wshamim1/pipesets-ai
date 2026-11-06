"""Elasticsearch — built-in tool `elasticsearch_search` (Elasticsearch REST, read-only).

Searches one index: the input is free text / a Lucene query string (run as a ``query_string``)
or a JSON body (POST _search with a query DSL object). Auth is HTTP basic auth, an ApiKey
header, or none.
"""

import json as _json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[Elasticsearch]"
MAX_CHARS = 300


def _auth(cfg: Dict[str, Any]) -> Dict[str, str]:
    api_key = (cfg.get("api_key") or "").strip()
    if api_key:
        return {"Authorization": f"ApiKey {api_key}"}
    return {}


def _body(inp: str) -> Optional[Dict[str, Any]]:
    """Posted body for a JSON input; a query string becomes multi_match."""
    raw = str(inp or "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            body = _json.loads(raw)
            if not isinstance(body, dict):
                return {"query": body}
            return body
        except _json.JSONDecodeError:
            pass
    return {"query": {"query_string": {"query": raw, "lenient": True}}}


def _source_line(hit: Dict[str, Any]) -> list:
    out = [f"  [{hit.get('_index', '?')}/{hit.get('_id', '?')}] score {hit.get('_score', 0):.2f}"]
    src = hit.get("_source") or {}
    bits = []
    for k, v in list(src.items())[:8]:
        text = v if isinstance(v, (str, int, float, bool)) else _json.dumps(v, ensure_ascii=False, default=str)
        bits.append(f"{k}: {str(text)[:MAX_CHARS]}")
    if bits:
        out.append("    " + " · ".join(bits))
    return out


TOOL = ToolSpec(
    id="elasticsearch_search",
    name="Elasticsearch Search",
    icon="🧱",
    category="Data & Files",
    description=("Searches an Elasticsearch index (read-only): pass query text (free text or Lucene "
                 "syntax) or a query-DSL body as JSON. Auth by ApiKey or basic auth in the node config."),
    default_config={"base_url": "http://localhost:9200", "index": "", "api_key": "", "username": "",
                    "password": "", "max_results": 10},
    order=200,
    required=("base_url",),
    parameters=params(
        {"query": {"type": "string", "description": "Query text or Lucene string, or a JSON query-DSL body"}},
        {"index": {"type": "string", "description": "The index (or pattern) to search"},
         "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Most hits"}},
    ),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base:
        return f"{LABEL} base_url is required in config."
    index = (cfg.get("index") or "").strip()
    if not index:
        return f"{LABEL} index is required in config (accepts a pattern like logs-*)."
    raw = str(inp or "").strip()
    if not raw:
        return f'{LABEL} Pass the query text, or a JSON body like {{"query": {{"match_all": {{}}}}}}.'
    limit = min(max(int(cfg.get("max_results", 10) or 10), 1), 50)
    body = _body(raw)
    auth = _auth(cfg)
    basic = (cfg.get("username") or "")
    kwargs: Dict[str, Any] = {"headers": {**auth, "Accept": "application/json"}, "timeout": 20.0}
    if basic:
        kwargs["auth"] = (basic, cfg.get("password") or "")

    url = f"{base}/{index}/_search"
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            if body:
                resp = await client.post(url, json={**body, "size": limit})
            else:
                resp = await client.get(url, params={"q": raw, "size": limit})
    except Exception as e:
        return f"{LABEL} Could not reach {base}: {e}"
    if resp.status_code != 200:
        try:
            reason = resp.json().get("error", {}).get("reason", "")[:200]
        except Exception:
            reason = resp.text[:200]
        if resp.status_code == 401:
            return f"{LABEL} Authentication failed — check api_key / username / password. {reason}"
        if resp.status_code == 404:
            return f"{LABEL} Index '{index}' not found."
        return f"{LABEL} HTTP {resp.status_code}: {reason}"

    data = resp.json()
    hits = (data.get("hits") or {}).get("hits") or []
    total = (data.get("hits") or {}).get("total", {})
    total_txt = (total.get("value") if isinstance(total, dict) else total) or len(hits)
    if not hits:
        return f"{LABEL} No hits match '{raw[:120]}' (index '{index}')."
    head = f"{total_txt} hit(s)" if total_txt <= len(hits) else f"{len(hits)} of {total_txt} hit(s)"
    out = [f"{LABEL} {head} in '{index}'", ""]
    for hit in hits:
        out += _source_line(hit)
    out.append("")
    return "\n".join(out).rstrip() + "\n\nTip: pass a JSON body for exact query DSL (e.g. term, range, bool)."
