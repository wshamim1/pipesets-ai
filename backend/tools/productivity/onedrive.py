"""OneDrive — built-in tool `onedrive` (Microsoft Graph drive items, read-only).

Actions: ``search`` (items matching free text), ``list`` (recent items, newest first) and
``read`` (one item: a text file's content, or the children of a folder). Auth is a delegated
Microsoft OAuth access token (+ refresh token / client id / secret when present) in the node
config, resolved from a ``secret://`` ref. Delegate scopes: ``offline_access Files.Read.All``.
Workbooks (.xlsx) go through the ``excel_workbook`` tool instead.
"""

from typing import Any, Dict, List, Optional

from tools.base import MAX_RESULTS, ToolSpec, enum, params
from tools.productivity._ms_auth import GRAPH, call as ms_call
from tools.productivity._ms_auth import ms_error

LABEL = "[OneDrive]"
ITEM_FIELDS = "id,name,size,file,folder,webUrl,lastModifiedDateTime"
MAX_READ_BYTES = 40000


def human(n: int) -> str:
    return f"{n/1024/1024:.1f} MB" if n >= 1024 * 1024 else f"{n/1024:.1f} KB" if n >= 1024 else f"{n} B"


def _kind(item: Dict[str, Any]) -> str:
    if (item.get("folder") or {}).get("childCount") is not None or item.get("folder"):
        return "folder"
    return str((item.get("file") or {}).get("mimeType") or "file")


def _line(item: Dict[str, Any]) -> list:
    kind = _kind(item)
    folder = kind == "folder"
    size = "folder" if folder else human(int(item.get("size") or 0))
    out = [f"  #{item.get('id')} · {item.get('name') or '?'} · {size}"
           + ("" if folder else f" · {kind}")]
    if folder:
        count = (item.get("folder") or {}).get("childCount")
        if count is not None:
            out[0] += f" · {count} child(ren)"
    elif item.get("lastModifiedDateTime"):
        out[0] += f" · modified {str(item['lastModifiedDateTime'])[:10]}"
    return out


def _search_query(query: str) -> str:
    """Free text into the /search(q=…) path fragment."""
    return query.replace("'", r"\'")


TOOL = ToolSpec(
    id="onedrive",
    name="OneDrive Reader",
    icon="📁",
    category="Productivity",
    description=("Searches, lists and reads files in the signed-in user's OneDrive via Microsoft "
                 "Graph (read: a text file's content, or a folder's children; .xlsx is read with "
                 "excel_workbook). Delegated Graph scopes: Files.Read.All."),
    default_config={"access_token": "", "action": "list", "query": "", "max_results": 15},
    order=80,
    required=("access_token",),
    parameters=params(
        {"action": enum(["search", "list", "read"], "search = items matching free text, list = recent files, read = one item")},
        {
            "query": {"type": "string", "description": "Free text to match against file names and content (search)"},
            "max_results": MAX_RESULTS,
            "file_id": {"type": "string", "description": "The drive item id to read (from search / list) (read)"},
            "path": {"type": "string", "description": "Or read by OneDrive path, e.g. Documents/notes.md (read)"},
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 100000,
                          "description": "Most characters to return (read)"},
        },
    ),
    input_param="action",
)


async def _resolve(cfg: Dict[str, Any]) -> Any:
    """The item id to read (file_id, or the id found at the given path), or an error string."""
    file_id = str(cfg.get("file_id") or "").strip()
    if file_id:
        return file_id
    path = str(cfg.get("path") or "").strip().strip("/")
    if not path:
        return ""
    resp = await ms_call(cfg, "GET", f"{GRAPH}/me/drive/root:/{path}", query={"$select": "id,name"})
    if resp.status_code != 200:
        return ms_error(LABEL, resp)
    return resp.json().get("id") or ""


async def _read(item_id: str, cfg: Dict[str, Any]) -> str:
    meta = await ms_call(cfg, "GET", f"{GRAPH}/me/drive/items/{item_id}", query={"$select": ITEM_FIELDS})
    if meta.status_code != 200:
        return ms_error(LABEL, meta)
    item = meta.json() or {}
    name = str(item.get("name") or item_id)
    max_chars = min(max(int(cfg.get("max_chars", MAX_READ_BYTES) or MAX_READ_BYTES), 200), 100000)

    if _kind(item) == "folder":
        resp = await ms_call(cfg, "GET", f"{GRAPH}/me/drive/items/{item_id}/children", query={
            "$select": ITEM_FIELDS, "$top": 20})
        if resp.status_code != 200:
            return ms_error(LABEL, resp)
        children = resp.json().get("value") or []
        if not children:
            return f"{LABEL} Folder '{name}' is empty."
        lines = [f"{LABEL} Folder '{name}' — {len(children)} child(ren)", ""]
        for child in children:
            lines += _line(child)
        return "\n".join(lines).rstrip()

    size = int(item.get("size") or 0)
    if size > 50 * 1024 * 1024:
        return f"{LABEL} '{name}' is {human(size)} — too large to read."

    content = await ms_call(cfg, "GET", f"{GRAPH}/me/drive/items/{item_id}/content")
    if content.status_code != 200:
        return ms_error(LABEL, content)
    text = content.content[:200000].decode("utf-8", "replace").replace("\x00", "")
    kind = _kind(item)
    head = [f"{LABEL} '{name}' · {human(size)} · {kind}",
            f"Web link: {item.get('webUrl') or '—'}", ""]
    if text:
        head.append(text[:max_chars])
        if len(text) > max_chars:
            head.append(f"\n… (truncated at {max_chars} of {len(text)} characters)")
    else:
        head.append("[empty file]")
    return "\n".join(head)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide a Microsoft OAuth access token "
                "(or a secret:// ref) with the Files.Read.All delegated scope.")
    action = str(inp or cfg.get("action") or "").strip().lower() or "list"
    if action not in ("search", "list", "read"):
        return f'{LABEL} Action is "search", "list" or "read" — got "{inp}".'

    if action == "read":
        target = await _resolve(cfg)
        if not target:
            return f"{LABEL} read needs a file_id (from search / list) or a path — pass one."
        return await _read(target, cfg)

    top = min(max(int(cfg.get("max_results", 15) or 15), 1), 20)
    query = str(cfg.get("query") or "").strip()
    if action == "search":
        if not query:
            return f"{LABEL} search needs a query — pass text to look for in names and content."
        resp = await ms_call(cfg, "GET", f"{GRAPH}/me/drive/root/search(q='{_search_query(query)}')",
                             query={"$top": top})
    else:
        resp = await ms_call(cfg, "GET", f"{GRAPH}/me/drive/recent", query={"$top": top})
    if resp.status_code != 200:
        return ms_error(LABEL, resp)
    items: List[Dict[str, Any]] = resp.json().get("value") or []
    if not items:
        return f'{LABEL} No drive items match "{query}".' if action == "search" \
            else f"{LABEL} The drive has no recent items."
    title = f"{len(items)} drive item(s) matching \"{query}\"" if action == "search" \
        else f"{len(items)} recent drive item(s)"
    lines = [f"{LABEL} {title}", ""]
    for item in items:
        lines += _line(item)
    lines.append("")
    return "\n".join(lines).rstrip() + "\n\nTo read one: onedrive read with its file_id."
