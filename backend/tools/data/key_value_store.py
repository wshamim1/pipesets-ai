"""Key-value store — built-in tool `key_value_store` (services/kv_store.py).

The agent gets, sets, deletes and lists JSON values under keys in the node's namespace. Per end user
by default, so each user of a published app has their own entries; "project" shares them across
every run in the project.
"""

import json
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, json_input, params

LABEL = "[Key-Value Store]"

TOOL = ToolSpec(
    id="key_value_store",
    name="Key-Value Store",
    icon="🗄️",
    category="Data & Files",
    description="Lets the agent remember JSON values under keys across runs — per end user or shared "
                "across the project, optionally expiring.",
    default_config={"namespace": "default", "scope": "user", "default_ttl_seconds": "", "access": "read_write"},
    order=5,
    selects={
        "scope": Select("Scope", [("user", "Per end user"), ("project", "Shared across the project")],
                        "Runs with no end user (schedules, webhooks) can only use shared entries"),
        "access": Select("Access", [("read_write", "Read and write"), ("read_only", "Read only")]),
    },
    parameters=params(
        {"action": enum(["get", "set", "delete", "list"], "What to do")},
        {
            "key": {"type": "string", "description": "The key (get, set, delete)"},
            "value": {"description": "Any JSON value to store under the key (set)"},
            "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 365 * 86400,
                            "description": "Forget the entry after this many seconds (set); default: the node's"},
            "prefix": {"type": "string", "description": "Only list keys starting with this (list)"},
        },
    ),
    to_input=json_input,
)


def _ttl(raw: Any) -> Optional[float]:
    try:
        ttl = float(raw)
    except (TypeError, ValueError):
        return None
    return ttl if ttl > 0 else None


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    import asyncio
    from services import kv_store
    from services.long_term_memory import current

    try:
        req = json.loads(inp) if inp else {}
    except json.JSONDecodeError:
        req = None
    if not isinstance(req, dict) or req.get("action") not in ("get", "set", "delete", "list"):
        return (f'{LABEL} Expected a JSON object like {{"action": "get", "key": "k"}}; '
                "action is get, set, delete or list.")

    who = current()
    if not who.tenant_id:
        return f"{LABEL} Not available outside a project run."
    per_user = cfg.get("scope", "user") != "project"
    if per_user and not who.user:
        return (f"{LABEL} This run has no end user, so per-user entries can't be used. "
                "Pass `user` when calling the app, or set the node's scope to shared.")
    namespace = str(cfg.get("namespace") or "default").strip()[:128] or "default"
    where = (who.tenant_id, who.project_id, namespace, who.user if per_user else "")
    action = req["action"]
    if action in ("set", "delete") and cfg.get("access") == "read_only":
        return f"{LABEL} This store is read only."

    try:
        if action == "get":
            found, value = await asyncio.to_thread(kv_store.get, *where, str(req.get("key") or ""))
            return json.dumps({"key": req.get("key"), "found": found, "value": value}, ensure_ascii=False)
        if action == "set":
            if "value" not in req:
                return f"{LABEL} set needs a value."
            ttl = _ttl(req.get("ttl_seconds")) or _ttl(cfg.get("default_ttl_seconds"))
            expires = await asyncio.to_thread(kv_store.put, *where, str(req.get("key") or ""), req["value"], ttl)
            return json.dumps({"key": req.get("key"), "stored": True, "expires_at": expires})
        if action == "delete":
            deleted = await asyncio.to_thread(kv_store.delete, *where, str(req.get("key") or ""))
            return json.dumps({"key": req.get("key"), "deleted": deleted})
        keys = await asyncio.to_thread(kv_store.list_keys, *where, str(req.get("prefix") or ""))
        return json.dumps({"keys": keys, "truncated": len(keys) >= kv_store.MAX_LIST})
    except kv_store.StoreError as e:
        return f"{LABEL} {e}"
