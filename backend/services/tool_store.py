"""
tool_store.py — custom tools and their versions, shared by the UI routes (routers/custom_tools.py),
the public API (routers/v1_tools.py, the SDK's ``pipesets tool deploy``) and runs.

* Every save that changes the code, description, requirements or config keys is a new version
  (``custom_tool_versions``); the tool row holds the latest. Saving the same content again changes
  nothing (``changed: False``), which makes ``PUT /v1/tools/{name}`` an idempotent deploy.
* A rollback is a new version with an old version's content, so history only moves forward.
* A node can pin a version (``tool_version`` in its config); otherwise runs use the latest.
* The signature — entry point and parameter schema — is read from the code on save
  (services/tool_signature.py); code that can't be a tool is refused. ``@tool(secrets=…,
  requirements=…)`` add to the tool's config keys and requirements.
* Tools are looked up inside the tenant / project of the run or request, never by id alone.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from db import get_db_connection
from services.tool_signature import ToolSignature, analyze

SOURCES = ("ui", "sdk")


def _now() -> str:
    return datetime.utcnow().isoformat()


def checksum(code: str, description: str, requirements: List[str], config_keys: List[str]) -> str:
    blob = json.dumps({"code": code, "description": description, "requirements": sorted(requirements),
                       "config_keys": sorted(config_keys)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _signature(row: Dict[str, Any]) -> Dict[str, Any]:
    """The stored signature, read from the code for rows saved before signatures were."""
    if row.get("signature"):
        return json.loads(row["signature"])
    try:
        return analyze(row.get("code") or "").as_dict()
    except ValueError as e:
        return {"error": str(e)}


def _decode(row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["config_keys"] = json.loads(d.get("config_keys") or "[]")
    d["requirements"] = json.loads(d.get("requirements") or "[]")
    d["signature"] = _signature(d)
    return d


def get(tool_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM custom_tools WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (tool_id, tenant_id, project_id)).fetchone()
    finally:
        conn.close()
    return _decode(row) if row else None


def find_by_name(name: str, tenant_id: str, project_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM custom_tools WHERE name = ? AND tenant_id = ? AND project_id = ? "
                            "ORDER BY created_at", (name, tenant_id, project_id)).fetchall()
    finally:
        conn.close()
    return [_decode(r) for r in rows]


def list_tools(tenant_id: str, project_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM custom_tools WHERE tenant_id = ? AND project_id = ? ORDER BY created_at DESC",
                            (tenant_id, project_id)).fetchall()
    finally:
        conn.close()
    return [_decode(r) for r in rows]


def list_versions(tool_id: str, tenant_id: str, project_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT tool_id, version, name, description, source, checksum, note, created_at, created_by "
            "FROM custom_tool_versions WHERE tool_id = ? AND tenant_id = ? AND project_id = ? ORDER BY version DESC",
            (tool_id, tenant_id, project_id)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_version(tool_id: str, version: int, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM custom_tool_versions WHERE tool_id = ? AND version = ? AND tenant_id = ? "
                           "AND project_id = ?", (tool_id, version, tenant_id, project_id)).fetchone()
    finally:
        conn.close()
    return _decode(row) if row else None


def save(tenant_id: str, project_id: str, user_id: str, *, name: str, code: str, description: str = "",
         icon: str = "🔧", config_keys: Optional[List[str]] = None, requirements: Optional[List[str]] = None,
         source: str = "ui", note: Optional[str] = None, tool_id: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
    """Create a tool, or a new version of ``tool_id`` when its content changed.
    Returns (tool, changed). Raises ValueError (ToolCodeError) for code that can't be a tool."""
    from services import sandbox

    sig: ToolSignature = analyze(code)
    keys = list(dict.fromkeys([*(config_keys or []), *sig.secrets]))
    reqs = sandbox.normalize_requirements(list(dict.fromkeys([*(requirements or []), *sig.requirements])))
    desc = description or sig.description
    digest = checksum(code, desc, reqs, keys)
    now = _now()
    conn = get_db_connection()
    try:
        if tool_id is None:
            tool_id, version, changed = str(uuid.uuid4()), 1, True
            conn.execute(
                "INSERT INTO custom_tools (id, tenant_id, project_id, owner_user_id, name, icon, description, code, "
                "config_keys, requirements, version, source, signature, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (tool_id, tenant_id, project_id, user_id, name, icon, desc, code, json.dumps(keys), json.dumps(reqs),
                 source, json.dumps(sig.as_dict()), now, now))
        else:
            row = conn.execute("SELECT version FROM custom_tools WHERE id = ? AND tenant_id = ? AND project_id = ?",
                               (tool_id, tenant_id, project_id)).fetchone()
            if not row:
                raise LookupError(tool_id)
            latest = conn.execute("SELECT checksum FROM custom_tool_versions WHERE tool_id = ? AND version = ?",
                                  (tool_id, row["version"])).fetchone()
            changed = not latest or latest["checksum"] != digest
            version = row["version"] + (1 if changed else 0)
            conn.execute(
                "UPDATE custom_tools SET name = ?, icon = ?, description = ?, code = ?, config_keys = ?, requirements = ?, "
                "version = ?, source = ?, signature = ?, updated_at = ? WHERE id = ?",
                (name, icon, desc, code, json.dumps(keys), json.dumps(reqs), version, source,
                 json.dumps(sig.as_dict()), now, tool_id))
        if changed:
            conn.execute(
                "INSERT INTO custom_tool_versions (tool_id, version, tenant_id, project_id, name, description, code, "
                "signature, config_keys, requirements, source, checksum, note, created_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tool_id, version, tenant_id, project_id, name, desc, code, json.dumps(sig.as_dict()), json.dumps(keys),
                 json.dumps(reqs), source, digest, note, now, user_id))
        conn.commit()
    finally:
        conn.close()
    return get(tool_id, tenant_id, project_id), changed


def rollback(tool_id: str, to_version: int, tenant_id: str, project_id: str, user_id: str) -> Dict[str, Any]:
    """A new version with ``to_version``'s content. Raises LookupError for an unknown version."""
    old = get_version(tool_id, to_version, tenant_id, project_id)
    current = get(tool_id, tenant_id, project_id)
    if not old or not current:
        raise LookupError(f"{tool_id} v{to_version}")
    tool, _ = save(tenant_id, project_id, user_id, name=current["name"], code=old["code"],
                   description=old["description"], icon=current["icon"], config_keys=old["config_keys"],
                   requirements=old["requirements"], source=current["source"], note=f"Rollback to v{to_version}",
                   tool_id=tool_id)
    return tool


def for_run(tool_id: str, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The tool (pinned version, else latest) in the tenant / project of the run or request in
    progress; None outside one or when it isn't there."""
    from services.secret_store import current_scope_ids

    scope = current_scope_ids()
    if not scope:
        return None
    if version:
        found = get_version(tool_id, int(version), *scope)
        if found:
            found["id"] = tool_id
        return found
    return get(tool_id, *scope)


def run_signature(tool: Dict[str, Any]) -> Optional[ToolSignature]:
    sig = tool.get("signature") or {}
    return None if "error" in sig else ToolSignature.from_dict(sig)
