"""Google Cloud Storage — built-in tool `gcs_reader` (GCS JSON API, read-only).

``list`` (objects under a bucket / prefix) or read one object's text. Auth is a Google OAuth access
token (+ refresh token / client id / secret when present) in the node config, resolved from a
``secret://`` ref like the other Google tools — with an authorized user or a service account JWT
bearing the ``https://www.googleapis.com/auth/devstorage.read_only`` scope
(env GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET).
"""

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from tools.base import ToolSpec, params
from tools.productivity._google_auth import call as google_call
from tools.productivity._google_auth import http_error

LABEL = "[GCS]"
API = "https://storage.googleapis.com/storage/v1/b"


def human(n_bytes: Any) -> str:
    n = int(n_bytes or 0)
    return f"{n/1024/1024:.1f} MB" if n >= 1024 * 1024 else f"{n/1024:.1f} KB" if n >= 1024 else f"{n} B"


def _line(item: Dict[str, Any]) -> str:
    size = human(item.get("size"))
    kind = str(item.get("contentType") or "").replace("application/", "")
    return f"  {item.get('name') or '?'}  ({size}, {kind})"


TOOL = ToolSpec(
    id="gcs_reader",
    name="Google Cloud Storage Reader",
    icon="🪣",
    category="Data & Files",
    description=("Lists or reads objects in a Google Cloud Storage bucket via the GCS JSON API: "
                 "input is 'list' (or a folder-like prefix ending in /) or one object's name. "
                 "OAuth access token with the devstorage.read_only scope."),
    default_config={"bucket": "", "prefix": "", "access_token": ""},
    order=170,
    required=("access_token",),
    parameters=params(
        {"object_path": {"type": "string", "description": "Object name to read, or 'list' / a folder-like prefix for listing"}},
        {"prefix": {"type": "string", "description": "List objects under this prefix"},
         "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Most objects per page"}},
    ),
    input_param="object_path",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide a Google OAuth access token (or a "
                "secret:// ref) with the devstorage.read_only scope.")
    bucket = str(cfg.get("bucket") or "").strip()
    if not bucket:
        return f"{LABEL} bucket is required in config."
    target = str(inp or "").strip()
    listing = not target or target.lower() in ("list", "ls") or target.endswith("/")

    if listing:
        prefix = (target.rstrip("/") if target.lower() not in ("list", "ls") else "") or (cfg.get("prefix") or "")
        resp = await google_call(cfg, "GET", f"{API}/{quote(bucket, safe='')}/o", query={
            "maxResults": min(max(int(cfg.get("max_results", 50) or 50), 1), 50),
            **({"prefix": prefix} if prefix else {}),
            "delimiter": "/"})
        if resp.status_code != 200:
            return http_error(LABEL, resp)
        items: List[Dict[str, Any]] = resp.json().get("items") or []
        prefixes = [p for p in resp.json().get("prefixes") or []]
        if not items and not prefixes:
            return f"{LABEL} No objects{' under ' + prefix if prefix else ''} in bucket '{bucket}'."
        lines = [f"{LABEL} {len(items) + len(prefixes)} object(s) / folder(s) in '{bucket}'"
                 + (f" under '{prefix}'" if prefix else ""), ""]
        lines += [f"  {p} (folder)" for p in prefixes]
        lines += [_line(i) for i in items]
        next_page = resp.json().get("nextPageToken")
        if next_page:
            lines.append(f"\nMore pages exist — narrow the prefix. (nextPageToken {next_page[:20]}…)")
        return "\n".join(lines).rstrip()

    resp = await google_call(cfg, "GET", f"{API}/{quote(bucket, safe='')}/o/{quote(target, safe='')}",
                             query={"alt": "media"})
    if resp.status_code != 200:
        return http_error(LABEL, resp)
    text = resp.content[:200000].decode("utf-8", "replace").replace("\x00", "")
    head = [f"{LABEL} gs://{bucket}/{target} ({human(len(resp.content))}, "
            f"{resp.headers.get('content-type', '?')})", ""]
    if text:
        head.append(text[:20000])
        if len(text) > 20000:
            head.append(f"\n… (truncated at 20000 characters — binary files read better elsewhere)")
    else:
        head.append("[empty object]")
    return "\n".join(head)
