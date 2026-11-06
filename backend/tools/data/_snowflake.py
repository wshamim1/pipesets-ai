"""REST plumbing shared by the Snowflake built-in tools: the account URL and token headers from the
node config, one authenticated request to the REST APIs (``/api/v2/...``), SQL through the SQL API
(``/api/v2/statements``, polling statements that run long) and the ``[Label]`` + JSON report every
tool returns. No driver needed — unlike ``snowflake_reader``, which uses snowflake-connector-python.
Not a tool itself (the registry skips ``_`` modules).

Auth is a bearer token: a programmatic access token (default), an OAuth access token, or a
key-pair JWT the caller generated, picked by ``token_type``.
"""

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from tools.base import Select

TOKEN_TYPES = {"pat": "PROGRAMMATIC_ACCESS_TOKEN", "oauth": "OAUTH", "keypair_jwt": "KEYPAIR_JWT"}
TOKEN_SELECT = Select("Token type", [("pat", "Programmatic access token"), ("oauth", "OAuth"),
                                     ("keypair_jwt", "Key-pair JWT")])
DEFAULT_CONFIG = {"account": "", "token": "", "token_type": "pat", "warehouse": "", "database": "", "schema": "",
                  "role": ""}
REQUIRED = ("account", "token")

# One identifier: plain (letters, digits, _ and $) or double-quoted
_PART = r'(?:[A-Za-z_][\w$]*|"[^"]+")'


def account_url(cfg: Dict[str, Any]) -> str:
    """``https://<account>.snowflakecomputing.com``, or the URL as given when it already is one."""
    account = (cfg.get("account") or "").strip().rstrip("/")
    if not account or account.startswith(("http://", "https://")):
        return account
    account = account.removesuffix(".snowflakecomputing.com")
    return f"https://{account.lower()}.snowflakecomputing.com"


def missing(label: str, **values: Any) -> Optional[str]:
    """The standard error line naming every empty value, or None when all are set."""
    empty = [name for name, value in values.items() if value in (None, "")]
    return f"[{label}] Missing required config: {', '.join(empty)}" if empty else None


def credentials_missing(label: str, cfg: Dict[str, Any]) -> Optional[str]:
    return missing(label, account=account_url(cfg), token=(cfg.get("token") or "").strip())


def name_parts(name: str, count: int) -> Optional[List[str]]:
    """``db.schema.object`` split into ``count`` identifiers (quotes kept), or None when it isn't one.
    The check keeps names safe to put in SQL text and URL paths."""
    if not re.fullmatch(r"\s*%s(?:\.%s){%d}\s*" % (_PART, _PART, count - 1), name or ""):
        return None
    return re.findall(_PART, name.strip())


def url_part(identifier: str) -> str:
    """One identifier for a REST path: quoted names keep their quotes, as the REST API expects."""
    return quote(identifier, safe="")


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    kind = TOKEN_TYPES.get(str(cfg.get("token_type") or "pat").lower(), TOKEN_TYPES["pat"])
    return {"Authorization": f"Bearer {(cfg.get('token') or '').strip()}",
            "X-Snowflake-Authorization-Token-Type": kind,
            "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "pipesets-ai/1.0"}


def _error(label: str, resp: httpx.Response) -> str:
    detail = resp.text[:500]
    try:
        detail = resp.json().get("message") or detail
    except Exception:
        pass
    return f"[{label}] HTTP {resp.status_code}: {detail}"


async def _send(label: str, cfg: Dict[str, Any], method: str, path: str, params: Optional[Dict[str, Any]],
                body: Any, timeout: float) -> Tuple[Optional[httpx.Response], Optional[str]]:
    problem = credentials_missing(label, cfg)
    if problem:
        return None, problem
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.request(method, f"{account_url(cfg)}{path}", params=params, json=body,
                                        headers=_headers(cfg)), None
    except Exception as exc:
        return None, f"[{label}] Error: {exc}"


async def request(label: str, cfg: Dict[str, Any], method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                  body: Any = None, timeout: float = 30.0) -> Tuple[Any, Optional[str]]:
    """(parsed JSON or text, None) on success, or (None, ``[label] ...`` error line)."""
    resp, error = await _send(label, cfg, method, path, params, body, timeout)
    if error:
        return None, error
    if resp.status_code >= 400:
        return None, _error(label, resp)
    if not resp.content:
        return {}, None
    try:
        return resp.json(), None
    except ValueError:
        return resp.text, None


async def statement(label: str, cfg: Dict[str, Any], sql: str, *, timeout: int = 60,
                    max_rows: int = 100) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Run one SQL statement through the SQL API → (rows as dicts, None) or (None, error line).
    A statement still running after the first reply (HTTP 202) is polled until ``timeout``."""
    body: Dict[str, Any] = {"statement": sql, "timeout": timeout}
    for key in ("warehouse", "database", "schema", "role"):
        if (cfg.get(key) or "").strip():
            body[key] = cfg[key].strip()
    resp, error = await _send(label, cfg, "POST", "/api/v2/statements", None, body, 30.0)
    deadline = time.monotonic() + timeout
    while not error and resp.status_code == 202:
        if time.monotonic() > deadline:
            return None, f"[{label}] The statement didn't finish within {timeout}s"
        await asyncio.sleep(1)
        handle = resp.json().get("statementHandle")
        resp, error = await _send(label, cfg, "GET", f"/api/v2/statements/{handle}", None, None, 30.0)
    if error:
        return None, error
    if resp.status_code >= 400:
        return None, _error(label, resp)
    result = resp.json()
    names = [c.get("name") for c in (result.get("resultSetMetaData") or {}).get("rowType") or []]
    return [dict(zip(names, row)) for row in (result.get("data") or [])[:max_rows]], None


def report(label: str, data: Any) -> str:
    return f"[{label}]\n{json.dumps(data, indent=2, sort_keys=True, default=str)}"
