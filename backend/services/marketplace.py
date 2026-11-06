"""
marketplace.py — turn a tenant's published pipeline into a shareable listing, and back.

Publishing snapshots the app's flow and makes it safe to hand to another tenant:

* **Secrets are stripped.** Any string field whose name looks like a credential
  (api_key, password, token, auth_header, connection_string, …), at any depth of a
  node's data, is blanked. Connection nodes lose their whole config.
* **Tenant-private references are cut.** Knowledge bases, vector collections, document
  sources, DB connections and child pipelines point at the publisher's data, so they
  are cleared — otherwise an importer's run would read the publisher's documents.
* **Custom tool code is bundled.** Custom tools are referenced by id, so the code is
  copied into the listing (shown to importers before they import) and recreated in the
  importer's project on import.
* Custom MCP servers can't be published yet (their server config is tenant-private).

Everything the importer has to supply is recorded as a ``requirement`` so the UI can
show a checklist before and after import.
"""

import copy
import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from services import sandbox

# Field names that hold credentials. Only non-empty *string* values are blanked, so
# numeric settings like max_tokens / token_budget are untouched.
_SECRET_FIELD_RE = re.compile(
    r"(api_?key|secret|password|passwd|token$|^token|auth_header|authorization|bearer|"
    r"connection_string|dsn|webhook|credential|private_key|access_key)",
    re.IGNORECASE,
)
_SAFE_FIELDS = {"max_tokens", "token_budget", "max_tokens_per_run"}

# Providers that run without a key
_KEYLESS_PROVIDERS = {"", "local", "ollama", "llamacpp", "jan", "mock", "huggingface_local", "sentence_transformers"}

MODEL_NODE_TYPES = {"llm", "master_agent", "child_agent", "embedding", "reranker"}
DATA_NODE_FIELDS = {
    "knowledge_base": ("kb_id", "chunk_count"),
    "retriever": ("collection_name",),
    "vector_store": ("collection_name",),
    "doc_loader": ("source", "db_table", "db_query"),
}

CATEGORIES = ("general", "rag", "agents", "customer_support", "data", "content", "dev_tools", "research")


def _strip_secrets(value: Any, path: str, found: List[str]) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            sub = f"{path}.{k}" if path else k
            if (isinstance(v, str) and v.strip() and k not in _SAFE_FIELDS
                    and _SECRET_FIELD_RE.search(k)):
                out[k] = ""
                found.append(sub)
            else:
                out[k] = _strip_secrets(v, sub, found)
        return out
    if isinstance(value, list):
        return [_strip_secrets(v, f"{path}[{i}]", found) for i, v in enumerate(value)]
    return value


def _custom_tool_ids(data: Dict[str, Any]) -> List[str]:
    """Custom tool ids referenced by a tool/toolkit node (toolId 'custom_<id>')."""
    ids = []
    for tid in [data.get("toolId")] + [st.get("toolId") for st in data.get("subTools") or [] if isinstance(st, dict)]:
        if isinstance(tid, str) and tid.startswith("custom_") and not tid.startswith("custom_mcp_"):
            ids.append(tid[len("custom_"):])
    return ids


def _uses_custom_mcp(data: Dict[str, Any]) -> bool:
    tids = [data.get("toolId")] + [st.get("toolId") for st in data.get("subTools") or [] if isinstance(st, dict)]
    return any(isinstance(t, str) and t.startswith("custom_mcp_") for t in tids)


def prepare_snapshot(conn, flow: Dict[str, Any], tenant_id: str, project_id: str
                     ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(sanitised flow, requirements, bundled custom tools) for a publisher's flow."""
    nodes_in = flow.get("nodes") or []
    edges = [{k: e[k] for k in ("id", "source", "target", "sourceHandle", "targetHandle", "type", "label") if k in e}
             for e in flow.get("edges") or []]

    requirements: List[Dict[str, Any]] = []
    providers: Dict[str, List[str]] = {}
    bundled: Dict[str, Dict[str, Any]] = {}
    nodes_out = []

    for node in nodes_in:
        ntype = node.get("type", "")
        label = (node.get("data") or {}).get("label") or ntype
        data = copy.deepcopy(node.get("data") or {})
        for ui_key in ("isSelected", "onDelete", "onDropTool"):
            data.pop(ui_key, None)

        if _uses_custom_mcp(data):
            raise HTTPException(status_code=400, detail=(
                f"Node '{label}' uses a custom MCP server. Pipelines with custom MCP servers "
                "can't be published to the marketplace yet."))

        # Providers whose keys the importer must bring
        if ntype in MODEL_NODE_TYPES and data.get("kind", "llm") == "llm":
            for field in ("provider", "fallback_provider"):
                p = str(data.get(field) or "").lower()
                if p not in _KEYLESS_PROVIDERS:
                    providers.setdefault(p, []).append(label)
        if ntype == "retriever":
            p = str(data.get("embedding_provider") or "").lower()
            if p not in _KEYLESS_PROVIDERS:
                providers.setdefault(p, []).append(label)

        if ntype == "connection":
            requirements.append({"kind": "connection", "node_id": node.get("id"), "label": label,
                                 "detail": f"Configure a {data.get('connection_type') or 'database'} connection"})
            data.update({"config": {}, "connection_id": "", "status": "untested", "status_msg": ""})

        if ntype in DATA_NODE_FIELDS:
            cleared = [f for f in DATA_NODE_FIELDS[ntype] if data.get(f)]
            for f in DATA_NODE_FIELDS[ntype]:
                if f in data:
                    data[f] = 0 if f == "chunk_count" else ""
            if cleared or ntype == "knowledge_base":
                requirements.append({"kind": "data_source", "node_id": node.get("id"), "label": label,
                                     "detail": "Point this at your own documents / collection"})

        if ntype == "memory":
            data["session_id"] = ""  # never share the publisher's conversation history

        if ntype == "child_agent" and data.get("kind") == "pipeline":
            requirements.append({"kind": "child_pipeline", "node_id": node.get("id"), "label": label,
                                 "detail": f"Link one of your own pipelines (was: {data.get('app_name') or 'a private pipeline'})"})
            data.update({"app_id": "", "app_name": "", "app_version": 0})

        for tool_id in _custom_tool_ids(data):
            if tool_id in bundled:
                continue
            row = conn.execute(
                "SELECT id, name, icon, description, code, config_keys, requirements FROM custom_tools "
                "WHERE id = ? AND tenant_id = ? AND project_id = ?",
                (tool_id, tenant_id, project_id),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=400, detail=f"Node '{label}' uses custom tool '{tool_id}', which no longer exists.")
            bundled[tool_id] = {
                "ref": tool_id, "name": row["name"], "icon": row["icon"], "description": row["description"],
                "code": row["code"], "config_keys": json.loads(row["config_keys"] or "[]"),
                "requirements": json.loads(row["requirements"] or "[]"),
            }

        stripped: List[str] = []
        data = _strip_secrets(data, "", stripped)
        # Model keys are covered by the provider_key requirement; anything else is listed per node
        other_secrets = [f for f in stripped if f not in ("api_key", "fallback_api_key", "embedding_api_key")]
        if other_secrets:
            requirements.append({"kind": "secret", "node_id": node.get("id"), "label": label,
                                 "detail": "Re-enter: " + ", ".join(sorted(set(other_secrets)))})
        if ntype == "child_agent" and data.get("kind") == "external" and data.get("auth_type", "none") != "none":
            requirements.append({"kind": "secret", "node_id": node.get("id"), "label": label,
                                 "detail": f"Credentials for external agent {data.get('endpoint_url') or ''}".strip()})

        nodes_out.append({k: node[k] for k in ("id", "type", "position", "width", "height", "parentId") if k in node}
                         | {"data": data})

    for p, labels in sorted(providers.items()):
        requirements.insert(0, {"kind": "provider_key", "provider": p, "label": ", ".join(sorted(set(labels))),
                                "detail": f"A {p} API key (from your key store or the server)"})
    for tool in bundled.values():
        if tool["config_keys"]:
            requirements.append({"kind": "tool_config", "label": tool["name"],
                                 "detail": "Set tool settings: " + ", ".join(map(str, tool["config_keys"]))})

    return {"nodes": nodes_out, "edges": edges}, requirements, list(bundled.values())


def can_try(requirements: List[Dict[str, Any]], bundled_tools: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """A listing can run un-imported unless it needs custom code, data or wiring of your own.
    Missing secrets (e.g. a tool's webhook) only make that tool fail during the trial."""
    if bundled_tools:
        return False, "It runs custom tool code — import it to review and run that code in your project."
    blocking = [r for r in requirements if r["kind"] in ("data_source", "connection", "child_pipeline")]
    if blocking:
        return False, "It needs setup first (" + ", ".join(sorted({r["kind"].replace("_", " ") for r in blocking})) + ")."
    return True, ""


def materialize_import(conn, flow: Dict[str, Any], bundled_tools: List[Dict[str, Any]],
                       tenant_id: str, project_id: str, user_id: str) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Copy bundled tools into the importer's project and rewire the flow to them.
    Returns (flow ready to save, created tools)."""
    now = datetime.utcnow().isoformat()
    remap: Dict[str, str] = {}
    created = []
    for tool in bundled_tools:
        new_id = str(uuid.uuid4())  # same id format as routers/custom_tools.py
        try:   # listings published before requirements existed have none; re-check what a listing carries
            requirements = sandbox.normalize_requirements(tool.get("requirements") or [])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Bundled tool '{tool['name']}': {e}") from None
        conn.execute(
            "INSERT INTO custom_tools (id, tenant_id, project_id, owner_user_id, name, icon, description, code, "
            "config_keys, requirements, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, tenant_id, project_id, user_id, tool["name"], tool.get("icon") or "🔧",
             tool.get("description") or "", tool["code"], json.dumps(tool.get("config_keys") or []),
             json.dumps(requirements), now, now),
        )
        remap[f"custom_{tool['ref']}"] = f"custom_{new_id}"
        created.append({"id": new_id, "name": tool["name"]})

    flow = copy.deepcopy(flow)
    for node in flow.get("nodes", []):
        data = node.get("data") or {}
        if data.get("toolId") in remap:
            data["toolId"] = remap[data["toolId"]]
        for st in data.get("subTools") or []:
            if isinstance(st, dict) and st.get("toolId") in remap:
                st["toolId"] = remap[st["toolId"]]
        if node.get("type") == "memory":
            data["session_id"] = f"session-{uuid.uuid4().hex[:8]}"
    return flow, created


def fresh_session_ids(flow: Dict[str, Any]) -> Dict[str, Any]:
    """A per-run memory session for un-imported trial runs."""
    flow = copy.deepcopy(flow)
    for node in flow.get("nodes", []):
        if node.get("type") == "memory":
            node.setdefault("data", {})["session_id"] = f"try-{uuid.uuid4().hex[:8]}"
    return flow


def node_summary(flow: Dict[str, Any]) -> Dict[str, Any]:
    types = [n.get("type") for n in flow.get("nodes", [])]
    counts: Dict[str, int] = {}
    for t in types:
        counts[t] = counts.get(t, 0) + 1
    return {
        "node_count": len(types),
        "node_types": counts,
        "uses_agents": "master_agent" in types,
        "uses_rag": "retriever" in types or "knowledge_base" in types,
        "runnable": "llm" in types or "master_agent" in types,
    }


def parse_tags(tags: Optional[List[str]]) -> List[str]:
    out = []
    for t in tags or []:
        t = re.sub(r"[^a-z0-9\-]+", "-", str(t).strip().lower()).strip("-")[:30]
        if t and t not in out:
            out.append(t)
    return out[:10]
