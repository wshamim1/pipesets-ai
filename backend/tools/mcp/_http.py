"""Client for remote MCP servers — Streamable HTTP (spec 2025-03-26+) and the legacy HTTP+SSE
transport (2024-11-05).

``transport="http"`` POSTs JSON-RPC to the server's one endpoint. Replies come back as JSON or as
an SSE stream, and the ``Mcp-Session-Id`` the server returns on ``initialize`` goes with every
later request. A server that turns the ``initialize`` POST away (400 / 404 / 405) is retried
over the legacy transport, as the spec's backwards-compatibility section describes.

``transport="sse"`` is the legacy transport: GET opens an event stream whose first ``endpoint``
event names the URL to POST messages to, and replies arrive as ``message`` events on that stream.

URLs go through the outbound SSRF guard (``services.external_agent.validate_endpoint``), and
redirects are not followed. A 401 raises ``MCPAuthRequired``. With an ``auth`` callback (OAuth,
``services/mcp_oauth.py``) its token goes in the Authorization header, and a 401 asks it once more
with ``force=True`` (refresh) before giving up.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from services.external_agent import validate_endpoint
from tools.mcp._stdio import CALL_TIMEOUT, call_result_text, missing_key, tool_listing

PROTOCOL_VERSION = "2025-06-18"
LEGACY_PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "pipesets-ai", "version": "1.0.0"}

RemotePrepare = Callable[[Dict[str, Any], str, Dict[str, Any]], Tuple[str, Dict[str, str], str, Dict[str, Any]]]
Auth = Optional[Callable[[bool], Awaitable[Optional[str]]]]   # force refresh → bearer token or None


class MCPRemoteError(RuntimeError):
    """The server couldn't be reached or answered with an error; the message says why."""


class MCPAuthRequired(MCPRemoteError):
    """The server answered 401. ``www_authenticate`` carries its challenge (OAuth metadata hint)."""

    def __init__(self, url: str, www_authenticate: str = ""):
        super().__init__(f"{url} requires authorization (401). Add an Authorization header, "
                         f"or connect the server with OAuth.")
        self.www_authenticate = www_authenticate


class _NotStreamable(Exception):
    """The endpoint refused the Streamable HTTP initialize — try the legacy SSE transport."""


async def _sse_events(response: httpx.Response) -> AsyncIterator[Tuple[str, str]]:
    """(event, data) pairs from a text/event-stream response."""
    event, data = "message", []
    async for line in response.aiter_lines():
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
    if data:
        yield event, "\n".join(data)


def _reply_to(payload: Any, msg_id: Any) -> Optional[Dict[str, Any]]:
    """The response to request ``msg_id`` in one JSON-RPC message or batch, if it's there."""
    for m in payload if isinstance(payload, list) else [payload]:
        if isinstance(m, dict) and m.get("id") == msg_id and ("result" in m or "error" in m):
            return m
    return None


def _check(url: str, r: httpx.Response) -> None:
    if r.status_code == 401:
        raise MCPAuthRequired(url, r.headers.get("www-authenticate", ""))
    if r.status_code >= 400:
        raise MCPRemoteError(f"{url} answered HTTP {r.status_code}")


class _StreamableSession:
    def __init__(self, client: httpx.AsyncClient, url: str, headers: Dict[str, str]):
        self.client, self.url, self.headers = client, url, headers
        self.session_id: Optional[str] = None
        self.protocol_version: Optional[str] = None

    def _request_headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **self.headers}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            h["MCP-Protocol-Version"] = self.protocol_version
        return h

    async def send(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        async with self.client.stream("POST", self.url, json=message, headers=self._request_headers()) as r:
            if message.get("method") == "initialize" and r.status_code in (400, 404, 405):
                raise _NotStreamable()
            _check(self.url, r)
            self.session_id = r.headers.get("mcp-session-id") or self.session_id
            if "id" not in message:
                return None
            if r.headers.get("content-type", "").startswith("text/event-stream"):
                async for _, data in _sse_events(r):
                    try:
                        reply = _reply_to(json.loads(data), message["id"])
                    except json.JSONDecodeError:
                        continue
                    if reply:
                        return reply
                return None
            body = await r.aread()
        try:
            return _reply_to(json.loads(body), message["id"])
        except json.JSONDecodeError:
            raise MCPRemoteError(f"{self.url} didn't answer with JSON-RPC")

    async def open(self) -> None:
        init = await self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO}})
        if not init or "result" not in init:
            raise MCPRemoteError(f"initialize failed: {(init or {}).get('error', 'no answer')}")
        self.protocol_version = init["result"].get("protocolVersion") or PROTOCOL_VERSION
        await self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def close(self) -> None:
        if self.session_id:
            try:
                await self.client.delete(self.url, headers=self._request_headers())
            except httpx.HTTPError:
                pass


class _LegacySseSession:
    def __init__(self, client: httpx.AsyncClient, url: str, headers: Dict[str, str]):
        self.client, self.url, self.headers = client, url, headers
        self.post_url = ""
        self._stream = None
        self._events: Optional[AsyncIterator[Tuple[str, str]]] = None

    async def open(self) -> None:
        self._stream = self.client.stream("GET", self.url, headers={"Accept": "text/event-stream", **self.headers})
        r = await self._stream.__aenter__()
        _check(self.url, r)
        self._events = _sse_events(r)
        async for event, data in self._events:
            if event == "endpoint":
                self.post_url = urljoin(self.url, data.strip())
                break
        if not self.post_url:
            raise MCPRemoteError(f"{self.url} didn't send an endpoint event")
        a, b = urlparse(self.url), urlparse(self.post_url)
        if (a.scheme, a.netloc) != (b.scheme, b.netloc):
            raise MCPRemoteError(f"{self.url} named a message endpoint on another origin")
        init = await self.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": LEGACY_PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO}})
        if not init or "result" not in init:
            raise MCPRemoteError(f"initialize failed: {(init or {}).get('error', 'no answer')}")
        await self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def send(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        r = await self.client.post(self.post_url, json=message,
                                   headers={"Content-Type": "application/json", **self.headers})
        _check(self.post_url, r)
        if "id" not in message:
            return None
        async for event, data in self._events:
            if event != "message":
                continue
            try:
                reply = _reply_to(json.loads(data), message["id"])
            except json.JSONDecodeError:
                continue
            if reply:
                return reply
        raise MCPRemoteError(f"{self.url} closed the event stream before answering")

    async def close(self) -> None:
        if self._stream is not None:
            await self._stream.__aexit__(None, None, None)


@asynccontextmanager
async def remote_session(url: str, headers: Optional[Dict[str, str]] = None, transport: str = "http",
                         timeout: float = CALL_TIMEOUT):
    """An initialized session; ``await session.send(message)`` returns the reply to a request."""
    if not url:
        raise MCPRemoteError("A URL is required for a remote MCP server")
    try:
        await validate_endpoint(url)
    except ValueError as e:
        raise MCPRemoteError(str(e))
    headers = dict(headers or {})
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=False) as client:
        session: Any = None
        try:
            if transport != "sse":
                session = _StreamableSession(client, url, headers)
                try:
                    await asyncio.wait_for(session.open(), timeout)
                except _NotStreamable:
                    session = None
            if session is None:
                session = _LegacySseSession(client, url, headers)
                await asyncio.wait_for(session.open(), timeout)
            yield session
        except asyncio.TimeoutError:
            raise MCPRemoteError(f"{url} didn't answer within {timeout:g}s")
        except httpx.HTTPError as e:
            raise MCPRemoteError(f"Couldn't reach {url}: {e}")
        finally:
            if session is not None:
                await session.close()


async def _with_session(url: str, headers: Optional[Dict[str, str]], transport: str, timeout: float,
                        auth: Auth, use: Callable[[Any], Awaitable[Any]]) -> Any:
    """``use(session)`` with the auth callback's token; a 401 refreshes the token and retries once."""
    for attempt in (0, 1):
        h = dict(headers or {})
        token = await auth(attempt == 1) if auth else None
        if token:
            h["Authorization"] = f"Bearer {token}"
        try:
            async with remote_session(url, h, transport, timeout) as s:
                return await use(s)
        except MCPAuthRequired:
            if attempt or not token:
                raise


async def discover_remote(url: str, headers: Optional[Dict[str, str]] = None, transport: str = "http",
                          timeout: float = CALL_TIMEOUT, auth: Auth = None) -> List[Dict[str, Any]]:
    """The server's tools — [{name, description, inputSchema}]. Raises MCPRemoteError."""
    async def use(s):
        tools: List[Dict[str, Any]] = []
        cursor = None
        for i in range(20):   # follow nextCursor pages, bounded
            params = {"cursor": cursor} if cursor else {}
            res = await asyncio.wait_for(s.send({"jsonrpc": "2.0", "id": 2 + i, "method": "tools/list",
                                                 "params": params}), timeout)
            if not res or "result" not in res:
                raise MCPRemoteError(f"tools/list failed: {(res or {}).get('error', 'no answer')}")
            tools += tool_listing(res["result"])
            cursor = res["result"].get("nextCursor")
            if not cursor:
                break
        return tools
    return await _with_session(url, headers, transport, timeout, auth, use)


async def call_remote(label: str, url: str, headers: Optional[Dict[str, str]], transport: str, tool_name: str,
                      arguments: Dict[str, Any], timeout: float = CALL_TIMEOUT, auth: Auth = None) -> str:
    """Call one tool and return its text output, or a ``[label] ...`` error line."""
    async def use(s):
        return await asyncio.wait_for(s.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                              "params": {"name": tool_name, "arguments": arguments}}), timeout)
    try:
        res = await _with_session(url, headers, transport, timeout, auth, use)
    except MCPRemoteError as e:
        return f"[{label}] {e}"
    return call_result_text(label, res)


def remote_server(label: str, default_tool: str, prepare: RemotePrepare, required: Sequence[str] = ()):
    """A registry ``run`` (with ``discover``) for a built-in server reached over Streamable HTTP — the
    remote counterpart of ``_stdio.stdio_server``. ``prepare(config, input_text, defaults)`` returns
    (url, headers, tool name, call arguments); a missing ``required`` key is named before any request."""
    defaults = {"default_tool": default_tool}

    async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> str:
        missing = missing_key(cfg, required)
        if missing:
            return f"[{label}] Set {missing} in the node's Parameters & Auth first."
        url, headers, tool_name, arguments = prepare(cfg, inp, defaults)
        return await call_remote(label, url, headers, "http", tool_name, arguments,
                                 float(cfg.get("call_timeout") or CALL_TIMEOUT))

    async def discover(cfg: Dict[str, Any], tool_type: str = "") -> List[Dict[str, Any]]:
        missing = missing_key(cfg, required)
        if missing:
            raise RuntimeError(f"[{label}] Set {missing} to list this server's tools.")
        url, headers, _, _ = prepare(cfg, "", defaults)
        return await discover_remote(url, headers, "http", float(cfg.get("call_timeout") or CALL_TIMEOUT))

    run.discover = discover
    return run
