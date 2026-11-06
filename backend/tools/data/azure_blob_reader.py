"""Azure Blob Storage — built-in tool `azure_blob_reader` (Blob Storage REST API over HTTPS).

``list`` (blobs under a container / prefix, folder-style) or read one blob's text. Auth is a
Shared Access Signature in the node config (``sas_token``, starting with ``?``, signed for the
container or a blob) — plain REST + httpx, no SDK.
"""

import xml.etree.ElementTree as ElementTree
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from tools.base import ToolSpec, params

LABEL = "[Azure Blob]"


def _url(cfg: Dict[str, Any], path: str, extra: str) -> str:
    sas = (cfg.get("sas_token") or "").strip()
    sas = sas.lstrip("?")
    qs = (f"{extra}&{sas}" if extra else f"?{sas}") if sas else extra
    return f"{(cfg.get('account_url') or '').split('?')[0].rstrip('/')}/{path}{qs}"


def human(n_bytes: Any) -> str:
    n = int(n_bytes or 0)
    return f"{n/1024/1024:.1f} MB" if n >= 1024 * 1024 else f"{n/1024:.1f} KB" if n >= 1024 else f"{n} B"


def _tag(node: ElementTree.Element, name: str) -> str:
    """Text of the first child element with this tag, whichever XML namespace the answer used."""
    for child in node.iter():
        if child.tag.split("}")[-1] == name and child is not node:
            return (child.text or "").strip()
    return ""


def _blobs(xml_data: bytes) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(blobs, virtual directories) from a List Blobs XML response."""
    root = ElementTree.fromstring(xml_data or b"<Error/>")
    blobs, prefixes = [], []
    for child in root.iter():
        kind = child.tag.split("}")[-1]
        if kind == "Blob":
            blobs.append({"name": _tag(child, "Name"), "size": _tag(child, "Content-Length"),
                          "content_type": _tag(child, "Content-Type")})
        elif kind == "BlobPrefix":
            prefixes.append(_tag(child, "Name"))
    return blobs, prefixes


def _error(cfg: Dict[str, Any], resp: httpx.Response) -> str:
    if resp.status_code == 403:
        return (f"{LABEL} The SAS token doesn't allow this — check its permissions, expiry and the "
                "container it was signed for.")
    if resp.status_code == 404:
        return f"{LABEL} Blob not found (or the container doesn't exist)."
    try:
        root = ElementTree.fromstring(resp.content)
        message = _tag(root, "Message") or root.text or resp.text[:200]
    except Exception:
        message = resp.text[:200]
    return f"{LABEL} HTTP {resp.status_code}: {str(message or '')[:200]}"


TOOL = ToolSpec(
    id="azure_blob_reader",
    name="Azure Blob Storage Reader",
    icon="🟦",
    category="Data & Files",
    description=("Lists or reads blobs in Azure Storage via the Blob REST API: input is 'list' (or "
                 "a folder prefix ending in /) or one blob's path. Auth is a read Shared Access "
                 "Signature token in the node config."),
    default_config={"account_url": "", "container": "", "sas_token": ""},
    order=180,
    required=("account_url", "container", "sas_token"),
    parameters=params(
        {"blob_path": {"type": "string", "description": "Blob path to read, or 'list' / a folder prefix for listing"}},
    ),
    input_param="blob_path",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    for key in ("account_url", "container", "sas_token"):
        if not (cfg.get(key) or "").strip():
            return f"{LABEL} {key} is required in config — for a read-only account/container SAS token."
    container = str(cfg.get("container") or "").strip()
    raw_input = str(inp or "").strip().replace("\\", "/")
    target = raw_input.strip("/")
    listing = not target or target.lower() in ("list", "ls") or raw_input.endswith("/")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            if listing:
                prefix = "" if target.lower() in ("", "list", "ls") else target.rstrip("/")
                extra = (f"?restype=container&comp=list&maxresults=50"
                         + (f"&prefix={quote(prefix, safe='') + '/'}" if prefix else ""))
                resp = await client.get(_url(cfg, container, extra))
                if resp.status_code != 200:
                    return _error(cfg, resp)
                blobs, prefixes = _blobs(resp.content)
                if not blobs and not prefixes:
                    return (f"{LABEL} No blobs"
                            + (f" under '{prefix}'" if prefix else f" in container '{container}'") + ".")
                head = f"{LABEL} {len(blobs) + len(prefixes)} blob(s) / dir(s) in '{container}'" \
                       + (f" under '{prefix}'" if prefix else "")
                lines = [head, ""]
                lines += [f"  {p}/" for p in prefixes]
                lines += [f"  {b['name']}  ({human(b['size'])}, {b['content_type']})" for b in blobs]
                return "\n".join(lines)
            resp = await client.get(_url(cfg, f"{container}/{quote(target, safe='/+.')}", ""))
    except Exception as e:
        return f"{LABEL} Error: {e}"
    if resp.status_code != 200:
        return _error(cfg, resp)
    text = resp.content[:200000].decode("utf-8", "replace").replace("\x00", "")
    head = [f"{LABEL} '{target}' ({human(len(resp.content))}, {resp.headers.get('content-type', '?')})", ""]
    if text:
        head.append(text[:20000])
        if len(text) > 20000:
            head.append(f"\n… (truncated at 20000 characters — binary files read better elsewhere)")
    else:
        head.append("[empty blob]")
    return "\n".join(head)
