"""Airtable — built-in tool `airtable` (Airtable Web API v0 with a personal access token).

Actions: ``search`` (records in a table, matched by a formula on one field, by text across every
field, or all of them) and ``create`` (one record from a JSON object of fields). Token scopes:
data.records:read, plus data.records:write to create.
"""

import json
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Airtable]"
API = "https://api.airtable.com/v0"

TOOL = ToolSpec(
    id="airtable",
    name="Airtable",
    icon="🗂️",
    category="Productivity",
    description="Searches records in an Airtable table or creates one. Input: the text to search for (search), or a JSON object of fields (create).",
    default_config={"api_token": "", "base_id": "", "table": "", "action": "search", "search_field": "",
                    "view": "", "max_results": 10},
    order=60,
    required=("api_token", "base_id", "table"),
    selects={"action": Select("Action", (("search", "Search records"), ("create", "Create a record")))},
    parameters=params(
        {"request": {"type": "string", "description": "Text to search for (empty = the first records), or a JSON object of field values to create"}},
        {
            "action": enum(["search", "create"], "search = find records, create = add one"),
            "search_field": {"type": "string", "description": "Search only this field (default: every field)"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Records to return (search)"},
        },
    ),
    input_param="request",
)


def _error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error")
    except ValueError:
        err = None
    msg = (err.get("message") or err.get("type")) if isinstance(err, dict) else (err or resp.text[:200])
    if resp.status_code == 401:
        return f"{LABEL} The api_token is invalid."
    if resp.status_code == 403:
        return f"{LABEL} The token can't access this base — check its scopes and that the base is added to it."
    if resp.status_code == 404:
        return f"{LABEL} Base or table not found — check base_id (app…) and the table name."
    return f"{LABEL} HTTP {resp.status_code}: {msg}"


def _formula_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _record(r: Dict[str, Any]) -> str:
    fields = r.get("fields") or {}
    shown = ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v}"
                      for k, v in list(fields.items())[:12])
    return f"- {r.get('id')}  {shown[:600]}"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    for key in ("api_token", "base_id", "table"):
        if not str(cfg.get(key) or "").strip():
            return f"{LABEL} {key} is required in config."
    action = (cfg.get("action") or "search").strip().lower()
    if action not in ("search", "create"):
        return f'{LABEL} Action is "search" or "create" — got "{action}".'
    url = f"{API}/{cfg['base_id'].strip()}/{quote(str(cfg['table']).strip(), safe='')}"
    headers = {"Authorization": f"Bearer {cfg['api_token'].strip()}"}
    text = inp.strip()

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        if action == "create":
            try:
                fields = json.loads(text)
            except ValueError:
                fields = None
            if not isinstance(fields, dict) or not fields:
                return f'{LABEL} To create a record, give a JSON object of fields, e.g. {{"Name": "Ada", "Status": "Todo"}}.'
            resp = await client.post(url, json={"records": [{"fields": fields}], "typecast": True})
            if resp.status_code != 200:
                return _error(resp)
            rec = (resp.json().get("records") or [{}])[0]
            return f"{LABEL} Created record {rec.get('id')}\n{_record(rec)}"

        limit = max(1, min(int(cfg.get("max_results") or 10), 100))
        q: Dict[str, Any] = {"pageSize": 100}
        if cfg.get("view"):
            q["view"] = cfg["view"]
        field = str(cfg.get("search_field") or "").strip()
        if text and field:
            name = field.replace("}", "")
            q["filterByFormula"] = f"SEARCH(LOWER({_formula_string(text)}), LOWER({{{name}}} & \"\"))"
            q["maxRecords"] = limit
        elif not text:
            q["maxRecords"] = limit
        # without a field, every field is matched here, over the first 500 records
        found, offset = [], None
        for _ in range(5):
            if offset:
                q["offset"] = offset
            resp = await client.get(url, params=q)
            if resp.status_code != 200:
                return _error(resp)
            body = resp.json()
            for r in body.get("records", []):
                if text and not field and text.lower() not in json.dumps(r.get("fields") or {}, ensure_ascii=False).lower():
                    continue
                found.append(r)
            offset = body.get("offset")
            if len(found) >= limit or not offset:
                break
        found = found[:limit]
        if not found:
            return f"{LABEL} No records match '{text}'." if text else f"{LABEL} The table is empty."
        head = f"matching '{text}'" if text else "in the table"
        return f"{LABEL} {len(found)} record(s) {head}\n\n" + "\n".join(_record(r) for r in found)
