"""REST plumbing shared by the Databricks built-in tools: workspace credentials from the node config,
one authenticated request, and the ``[Label]`` + JSON report every tool returns. Not a tool itself
(the registry skips ``_`` modules)."""

import json
from typing import Any, Dict, Optional, Tuple

import httpx


def credentials(cfg: Dict[str, Any]) -> Tuple[str, str]:
    """(host, token). The host gets ``https://`` when the user pasted a bare hostname."""
    host = (cfg.get("host") or "").strip().rstrip("/")
    if host and not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host, (cfg.get("token") or "").strip()


def missing(label: str, **values: Any) -> Optional[str]:
    """The standard error line naming every empty value, or None when all are set."""
    empty = [name for name, value in values.items() if value in (None, "")]
    return f"[{label}] Missing required config: {', '.join(empty)}" if empty else None


async def request(label: str, cfg: Dict[str, Any], method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                  body: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Tuple[Any, Optional[str]]:
    """(parsed JSON or text, None) on success, or (None, ``[label] ...`` error line)."""
    host, token = credentials(cfg)
    problem = missing(label, host=host, token=token)
    if problem:
        return None, problem
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, f"{host}{path}", params=params, json=body, headers=headers)
    except Exception as exc:
        return None, f"[{label}] Error: {exc}"
    if resp.status_code >= 400:
        detail = resp.text[:500]
        try:
            detail = resp.json().get("message") or detail
        except Exception:
            pass
        return None, f"[{label}] HTTP {resp.status_code}: {detail}"
    if not resp.content:
        return {}, None
    try:
        return resp.json(), None
    except ValueError:
        return resp.text, None


def report(label: str, data: Any) -> str:
    return f"[{label}]\n{json.dumps(data, indent=2, sort_keys=True, default=str)}"
