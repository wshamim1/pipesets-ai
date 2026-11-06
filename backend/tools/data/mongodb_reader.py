"""MongoDB — built-in tool `mongodb_reader` (pymongo, read-only).

Finds documents in one collection: the input is a MongoDB filter as JSON, optionally extended with
``$sort`` / ``$skip`` / ``$limit`` / ``$project``; or a JSON array to run as an aggregation
pipeline. The driver is optional — install ``pymongo``. Auth is the connection URI
(mongodb:// or mongodb+srv://, credentials or SRV host included) in the node config, resolved from a
``secret://`` ref like any other credential.
"""

import asyncio
import json as _json
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

LABEL = "[MongoDB]"
HINTS = ("$sort", "$skip", "$limit", "$project")


def _parse(inp: str) -> Any:
    try:
        return _json.loads(inp)
    except _json.JSONDecodeError as e:
        raise ValueError(f"the query must be valid JSON ({e.msg} at position {e.pos})")


def _split_filter_body(query: Dict[str, Any]) -> tuple:
    """(plain filter, hints) — the $-prefixed keys come out of the find filter."""
    body: Dict[str, Any] = {}
    hints: Dict[str, Any] = {}
    for key, value in (query or {}).items():
        if key in HINTS:
            hints[key] = value
        else:
            body[key] = value
    return body, hints


def _fetch(uri: str, database: str, collection: str, query: Any, limit: int) -> tuple:
    """(docs, did-find-use-a-projection) — sync, run in a thread; MongoClient is blocking."""
    import pymongo
    from pymongo import MongoClient

    with MongoClient(uri, serverSelectionTimeoutMS=8000) as client:
        coll = client[database][collection]
        if isinstance(query, list):
            docs = list(coll.aggregate(query))
            projected = any("$project" in stage for stage in query if isinstance(stage, dict))
        else:
            body, hints = _split_filter_body(query)
            cursor = coll.find(body, projection=hints.get("$project"))
            if "$sort" in hints:
                cursor = cursor.sort(list((hints["$sort"] or {}).items()))
            cursor = cursor.skip(int(hints.get("$skip") or 0)).limit(int(hints.get("$limit") or limit))
            docs = list(cursor)
            projected = (hints.get("$project") or {}) != {}
        docs = docs[:limit]   # never return more than the configured cap, either path
        return docs, projected


def _present(docs: list, projected: bool) -> str:
    items = []
    for doc in docs:
        doc = dict(doc)
        if "_id" in doc and not projected:
            doc["_id"] = str(doc["_id"])
        items.append(doc)
    text = _json.dumps(items if len(items) > 1 else (items[0] if items else []), indent=2, default=str,
                       ensure_ascii=False)
    return f"{LABEL} {len(docs)} document(s)\n{text}"


TOOL = ToolSpec(
    id="mongodb_reader",
    name="MongoDB Reader",
    icon="🍃",
    category="Data & Files",
    description=("Reads documents from a MongoDB collection: pass a filter as JSON, e.g. "
                 "{\"status\": \"active\"} (optionally with $sort / $skip / $limit / $project), or "
                 "an aggregation pipeline as a JSON array. Needs the pymongo package."),
    default_config={"uri": "mongodb://user:pass@localhost:27017", "database": "", "collection": "",
                    "max_results": 20},
    order=210,
    required=("uri",),
    parameters=params(
        {"query": {"type": "string", "description": "JSON filter object for find, or a JSON array for aggregate"}},
        {"database": {"type": "string", "description": "The database name"},
         "collection": {"type": "string", "description": "The collection name"},
         "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Most documents (find)"}},
    ),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    uri = (cfg.get("uri") or "").strip()
    if not uri or uri.split("://")[0] not in ("mongodb", "mongodb+srv"):
        return f"{LABEL} A mongodb:// or mongodb+srv:// uri is required in config."
    database = str(cfg.get("database") or "").strip()
    collection = str(cfg.get("collection") or "").strip()
    if not (database and collection):
        return f"{LABEL} database and collection are required in config."
    raw = str(inp or "").strip()
    if not raw:
        return (f'{LABEL} Pass a JSON filter — e.g. {{"status": "active"}} — or a JSON array '
                "to run as an aggregation pipeline.")
    try:
        query = _parse(raw)
    except ValueError as e:
        return f"{LABEL} {e}"
    limit = min(max(int(cfg.get("max_results", 20) or 20), 1), 100)

    try:
        docs, projected = await asyncio.to_thread(_fetch, uri, database, collection, query, limit)
    except ModuleNotFoundError:
        return f"{LABEL} pymongo is not installed — pip install pymongo"
    except Exception as e:
        msg = str(e)
        if "authentication" in msg.lower() or "invalid credentials" in msg.lower():
            return f"{LABEL} Authentication failed — check the uri credentials."
        if "timed out" in msg.lower():
            return f"{LABEL} Could not reach the server in time: {msg[:200]}"
        return f"{LABEL} {msg[:200]}"
    if not docs:
        return f"{LABEL} No documents match the filter."
    return _present(docs, projected)
