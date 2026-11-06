"""Google Drive Reader — built-in tool `google_drive` (Drive REST API v3, read-only).

Actions: ``search`` (Drive query syntax e.g. "name contains 'report' fullText contains 'q3'"),
``list`` (files, newest first), ``read`` (one file's text content). Google Docs/Sheets are
exported as plain text/CSV; stored text files are downloaded directly. Auth is an OAuth
access token with the https://www.googleapis.com/auth/drive.readonly scope (+ refresh token /
client id / secret when present) in the node config, resolved from a ``secret://`` ref.
"""

from typing import Any, Dict, List, Optional, Tuple

from tools.base import MAX_RESULTS, ToolSpec, enum, params
from tools.productivity._google_auth import call as google_call
from tools.productivity._google_auth import http_error

LABEL = "[Google Drive]"
DRIVE_API = "https://www.googleapis.com/drive/v3"
MAX_BYTES = 20000

# Google Docs types and the mime to export them as text
EXPORT = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.note": "text/plain",
}

_FILE_FIELDS = "files(id, name, mimeType, size, modifiedTime, webViewLink)"


def _human(n: int) -> str:
    return f"{n/1024/1024:.1f} MB" if n >= 1024 * 1024 else f"{n/1024:.1f} KB" if n >= 1024 else f"{n} B"


async def _meta(cfg: Dict[str, Any], file_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    resp = await google_call(cfg, "GET", f"{DRIVE_API}/files/{file_id}", query={
        "fields": "id, name, mimeType, size, modifiedTime, webViewLink"})
    if resp.status_code != 200:
        return None, http_error(LABEL, resp)
    return resp.json(), ""


TOOL = ToolSpec(
    id="google_drive",
    name="Google Drive Reader",
    icon="🗂️",
    category="Productivity",
    description="Searches, lists and reads files in the user's Google Drive (docs, sheets and stored text files) via the Drive API.",
    default_config={"access_token": "", "query": "", "page_size": 15},
    order=30,
    required=("access_token",),
    parameters=params(
        {"action": enum(["search", "list", "read"], "search = files matching a Drive query, list = recent files, read = one file's text")},
        {
            "query": {"type": "string", "description": "Drive query syntax, e.g. \"name contains 'q3'\" (search)"},
            "max_results": MAX_RESULTS,
            "file_id": {"type": "string", "description": "The file id to read (from search / list) (read)"},
        },
    ),
    input_param="action",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide an OAuth access token (or a secret:// ref) "
                "with the drive.readonly scope.")
    action = str(inp or "").strip().lower()
    if action not in ("search", "list", "read"):
        return f'{LABEL} Action is "search", "list" or "read" — got "{inp}".'

    if action == "read":
        file_id = str(cfg.get("file_id") or "").strip()
        if not file_id:
            return f"{LABEL} read needs a file_id — pass the id of a file from search or list."
        return await _read(cfg, file_id)

    page_size = min(max(int(cfg.get("page_size", 15) or 15), 1), 20)
    query = str(cfg.get("query") or "").strip()
    listing: Dict[str, Any] = {"pageSize": page_size, "fields": _FILE_FIELDS}
    if action == "search":
        listing["q"] = query or "name != ''"
        listing["orderBy"] = "relevance desc"
    else:                      # list: recent files
        listing["orderBy"] = "modifiedTime desc"
    resp = await google_call(cfg, "GET", f"{DRIVE_API}/files", query=listing)
    if resp.status_code != 200:
        return http_error(LABEL, resp)
    files: List[Dict[str, Any]] = resp.json().get("files") or []
    if not files:
        return f'{LABEL} No files{" match the query" if query else " in this Drive"}.'
    suffix = (f' for "{query}"' if action == "search" and query
              else (", newest first" if action == "list" else ""))
    lines = [f"{LABEL} {len(files)} file(s)" + suffix, ""]
    for f in files:
        size = f"  {_human(int(f['size']))}" if str(f.get("size") or "").isdigit() else ""
        modified = f'  modified {str(f.get("modifiedTime") or "")[:10]}' if f.get("modifiedTime") else ""
        lines.append(f'  #{f.get("id")}\n    {str(f.get("name") or "(unnamed)")}\n'
                     f'    {str(f.get("mimeType") or "?")}{size}{modified}')
        if f.get("webViewLink"):
            lines.append(f"    {f['webViewLink']}")
    return "\n".join(lines) + "\n\nTo read one as text: google_drive read with its file_id."


async def _read(cfg: Dict[str, Any], file_id: str) -> str:
    meta, error = await _meta(cfg, file_id)
    if error:
        return error
    name, mime = str(meta.get("name") or "?"), str(meta.get("mimeType") or "")

    if mime in EXPORT:  # Google Docs / Sheets / Slides → export as text
        resp = await google_call(cfg, "GET", f"{DRIVE_API}/files/{file_id}/export",
                                 query={"mimeType": EXPORT[mime]})
        note = f" ({EXPORT[mime]})"
    elif mime.startswith("text/") or mime in ("application/json", "text/plain"):
        resp = await google_call(cfg, "GET", f"{DRIVE_API}/files/{file_id}", query={"alt": "media"})
        note = f" ({mime})"
    else:
        return (f"{LABEL} {name} is not readable as text ({mime}).\n"
                f"Open it in Drive instead: {meta.get('webViewLink') or '(no link)'}")
    if resp.status_code != 200:
        return http_error(LABEL, resp)
    text = resp.text
    if not text.strip():
        return f"{LABEL} {name} is empty (or has no text content)."
    out = f"{LABEL} {name}{note}\n"
    out += "\n" + text[:MAX_BYTES]
    if len(text) > MAX_BYTES:
        out += f"\n\n… (truncated at {MAX_BYTES} of {len(text)} characters)"
    return out
