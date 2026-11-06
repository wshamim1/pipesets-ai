"""
custom_mcp.py — User-defined Model Context Protocol (MCP) servers.

Supports:
- stdio transport: launching local MCP processes (npx, uvx, python, docker)
- http transport: remote Streamable HTTP endpoints (falls back to legacy SSE)
- sse transport: remote legacy HTTP+SSE endpoints
- tool discovery via MCP JSON-RPC handshake
- tool execution

Endpoints
---------
GET    /api/custom-mcp              — list all custom MCP servers
POST   /api/custom-mcp              — create custom MCP server
PUT    /api/custom-mcp/{id}         — update server configuration
DELETE /api/custom-mcp/{id}         — delete server
POST   /api/custom-mcp/test         — test connection & discover tools (before saving)
POST   /api/custom-mcp/{id}/discover— refresh discovered tools for saved server
POST   /api/custom-mcp/{id}/execute — execute tool on saved server
POST   /api/custom-mcp/{id}/oauth/start — begin OAuth sign-in; returns the authorization URL
DELETE /api/custom-mcp/{id}/oauth   — forget the server's OAuth tokens
GET    /api/custom-mcp/oauth/callback — public: where the authorization server sends the browser back

A server's OAuth tokens (services/mcp_oauth.py) are never returned; records carry ``oauth_status``
("none" | "connected" | "expired") instead.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from db import get_db_connection
from services import mcp_oauth, secret_store
from services.acl import require_access
from services.request_context import get_request_context
from tools.mcp._http import MCPAuthRequired, MCPRemoteError, call_remote, discover_remote
from tools.mcp._stdio import CALL_TIMEOUT, discover_stdio, execute_stdio

logger = logging.getLogger("pipesets-ai-backend")

router = APIRouter(prefix="/api/custom-mcp", tags=["custom-mcp"])
public_router = APIRouter(prefix="/api/custom-mcp", tags=["custom-mcp"])   # the OAuth callback only


# ── Models ────────────────────────────────────────────────────────────────────

class CustomMcpCreate(BaseModel):
    name: str
    icon: str = "🔌"
    description: str = ""
    transport: str = "stdio"  # "stdio" | "sse" | "http"
    command: str = ""        # e.g. "npx" or "uvx" or "python"
    args: List[str] = Field(default_factory=list) # e.g. ["-y", "@modelcontextprotocol/server-postgres", "postgresql://..."]
    env_vars: Dict[str, str] = Field(default_factory=dict)
    url: str = ""            # e.g. "http://localhost:3000/sse"
    headers: Dict[str, str] = Field(default_factory=dict)
    tools_cache: List[Dict[str, Any]] = Field(default_factory=list)


class CustomMcpUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    transport: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env_vars: Optional[Dict[str, str]] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    tools_cache: Optional[List[Dict[str, Any]]] = None


class McpTestRequest(BaseModel):
    transport: str = "stdio"
    command: str = ""
    args: List[str] = Field(default_factory=list)
    env_vars: Dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)


class McpOAuthStart(BaseModel):
    client_id: str = ""        # for servers without dynamic client registration (e.g. GitHub)
    client_secret: str = ""
    scope: Optional[str] = None  # default: what the server advertises


class McpExecuteRequest(BaseModel):
    tool_name: str = ""
    arguments: Dict[str, Any] = Field(default_factory=dict)
    input_text: str = ""


# ── DB Helpers ────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    for field in ("args", "tools_cache"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = []
    for field in ("env_vars", "headers"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = {}
    d["oauth_status"] = mcp_oauth.status(mcp_oauth.from_column(d.pop("oauth", "") or ""))
    return d


def _get_server(server_id: str, tenant_id: Optional[str] = None, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    if tenant_id and project_id:
        row = conn.execute(
            "SELECT * FROM custom_mcp_servers WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (server_id, tenant_id, project_id),
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM custom_mcp_servers WHERE id = ?", (server_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


# ── MCP Protocol Handlers ─────────────────────────────────────────────────────

def _stdio_launch(command: str, args: List[str], env_vars: Dict[str, str], default_tool: str):
    """Launch defaults and prepare() for the shared stdio runner (tools/mcp/_stdio.py)."""
    defaults = {"command": command, "args": list(args), "default_tool": default_tool}

    def prepare(config, input_text, launch_args, env, defaults):
        env.update(env_vars or {})
        tool_name = config.get("tool_name") or defaults["default_tool"]
        return launch_args, tool_name, config.get("arguments") or {"input": input_text, "query": input_text}

    return defaults, prepare


def _oauth(server_id: str):
    """The remote client's auth callback for a saved server: its OAuth token, if it has one."""
    if not server_id:
        return None

    async def auth(force: bool) -> Optional[str]:
        try:
            return await mcp_oauth.bearer(server_id, force)
        except mcp_oauth.OAuthError as e:
            raise MCPRemoteError(f"{e}. Reconnect the server with OAuth.")
    return auth


async def discover_mcp_tools(
    transport: str,
    command: str,
    args: List[str],
    env_vars: Dict[str, str],
    url: str,
    headers: Dict[str, str],
    server_id: str = "",
) -> List[Dict[str, Any]]:
    """
    Connects to an MCP server (stdio, Streamable HTTP or legacy SSE) and runs tools/list.
    ``server_id`` (a saved server) adds its OAuth token.
    """
    if transport == "stdio":
        if not command:
            raise ValueError("Command is required for stdio transport (e.g. npx, uvx, python).")
        defaults, prepare = _stdio_launch(command, args, env_vars, "")
        return await discover_stdio(command, {}, defaults, prepare)
    if transport in ("sse", "http"):
        if not url:
            raise ValueError("URL is required for HTTP/SSE transport.")
        return await discover_remote(url, secret_store.resolve_refs(headers or {}), transport,
                                     auth=_oauth(server_id))
    raise ValueError(f"Unknown transport: {transport}")


async def execute_custom_mcp(server_id: str, input_text: str, config: Dict[str, Any]) -> str:
    """
    Executes a tool on a saved custom MCP server — one in the tenant / project of the run or
    request in progress (never looked up by id alone).
    """
    scope = secret_store.current_scope_ids()
    server = _get_server(server_id, *scope) if scope else None
    if not server:
        return f"[Error: Custom MCP server {server_id} not found]"

    cached = server.get("tools_cache") or []
    tool_name = config.get("tool_name") or (cached[0].get("name") if cached else "") or "query"
    label = f"MCP {server['name']}"
    transport = server.get("transport", "stdio")

    if transport == "stdio":
        defaults, prepare = _stdio_launch(server.get("command", ""), server.get("args", []),
                                          server.get("env_vars", {}), tool_name)
        return await execute_stdio(label, input_text, config, defaults, prepare)
    if transport in ("sse", "http"):
        args = config.get("arguments") or {"input": input_text, "query": input_text}
        try:
            headers = secret_store.resolve_refs(server.get("headers") or {})
        except secret_store.SecretError as e:
            return f"[{label}] {e}"
        timeout = float(config.get("call_timeout") or CALL_TIMEOUT)
        return await call_remote(label, server.get("url", ""), headers, transport, tool_name, args, timeout,
                                 auth=_oauth(server_id))
    return f"[Error: Unknown transport {transport}]"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
def list_custom_mcp_servers(request: Request):
    """List all registered custom MCP servers."""
    ctx = get_request_context(request)
    require_access(ctx, "mcp", "read")
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM custom_mcp_servers WHERE tenant_id = ? AND project_id = ? ORDER BY created_at ASC",
        (ctx.tenant_id, ctx.project_id),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


@router.post("")
async def create_custom_mcp_server(req: CustomMcpCreate, request: Request):
    """Create a new custom MCP server and discover its tools."""
    ctx = get_request_context(request)
    require_access(ctx, "mcp", "write")

    server_id = f"custom_mcp_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    # Discover tools if possible
    tools = req.tools_cache
    if not tools and (req.command or req.url):
        try:
            tools = await discover_mcp_tools(
                req.transport, req.command, req.args, req.env_vars, req.url, req.headers
            )
        except Exception as e:
            logger.warning("Could not auto-discover tools during MCP create: %s", e)

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO custom_mcp_servers
        (id, tenant_id, project_id, owner_user_id, name, icon, description, transport, command, args, env_vars, url, headers, tools_cache, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            server_id,
            ctx.tenant_id,
            ctx.project_id,
            ctx.user_id,
            req.name,
            req.icon,
            req.description,
            req.transport,
            req.command,
            json.dumps(req.args),
            json.dumps(req.env_vars),
            req.url,
            json.dumps(req.headers),
            json.dumps(tools),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    return _get_server(server_id, ctx.tenant_id, ctx.project_id)


@router.put("/{server_id}")
async def update_custom_mcp_server(server_id: str, req: CustomMcpUpdate, request: Request):
    """Update a custom MCP server."""
    ctx = get_request_context(request)
    require_access(ctx, "mcp", "write")
    existing = _get_server(server_id, ctx.tenant_id, ctx.project_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Custom MCP server not found")

    name = req.name if req.name is not None else existing["name"]
    icon = req.icon if req.icon is not None else existing["icon"]
    description = req.description if req.description is not None else existing["description"]
    transport = req.transport if req.transport is not None else existing["transport"]
    command = req.command if req.command is not None else existing["command"]
    args = req.args if req.args is not None else existing["args"]
    env_vars = req.env_vars if req.env_vars is not None else existing["env_vars"]
    url = req.url if req.url is not None else existing["url"]
    headers = req.headers if req.headers is not None else existing["headers"]
    tools_cache = req.tools_cache if req.tools_cache is not None else existing["tools_cache"]
    now = datetime.utcnow().isoformat()
    if url != existing["url"] or transport != existing["transport"]:
        mcp_oauth.disconnect(server_id)   # tokens are for the old server; never send them to the new URL

    conn = get_db_connection()
    conn.execute(
        """
        UPDATE custom_mcp_servers
        SET name = ?, icon = ?, description = ?, transport = ?, command = ?, args = ?,
            env_vars = ?, url = ?, headers = ?, tools_cache = ?, updated_at = ?
        WHERE id = ? AND tenant_id = ? AND project_id = ?
        """,
        (
            name,
            icon,
            description,
            transport,
            command,
            json.dumps(args),
            json.dumps(env_vars),
            url,
            json.dumps(headers),
            json.dumps(tools_cache),
            now,
            server_id,
            ctx.tenant_id,
            ctx.project_id,
        ),
    )
    conn.commit()
    conn.close()

    return _get_server(server_id, ctx.tenant_id, ctx.project_id)


@router.delete("/{server_id}")
def delete_custom_mcp_server(server_id: str, request: Request):
    """Delete a custom MCP server."""
    ctx = get_request_context(request)
    require_access(ctx, "mcp", "delete")
    conn = get_db_connection()
    cur = conn.execute(
        "DELETE FROM custom_mcp_servers WHERE id = ? AND tenant_id = ? AND project_id = ?",
        (server_id, ctx.tenant_id, ctx.project_id),
    )
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Custom MCP server not found")
    return {"deleted": True, "id": server_id}


@router.post("/test")
async def test_mcp_connection(req: McpTestRequest, request: Request):
    """Test connection and discover tools without saving."""
    require_access(get_request_context(request), "mcp", "write")   # it launches the given command
    try:
        tools = await discover_mcp_tools(
            req.transport, req.command, req.args, req.env_vars, req.url, req.headers
        )
        return {"success": True, "tools": tools, "tool_count": len(tools)}
    except MCPAuthRequired as e:
        return {"success": False, "error": str(e), "tools": [], "auth_required": True}
    except Exception as e:
        return {"success": False, "error": str(e), "tools": []}


@router.post("/{server_id}/discover")
async def discover_saved_mcp_tools(server_id: str, request: Request):
    """Refresh tool discovery for a saved MCP server and update database."""
    ctx = get_request_context(request)
    require_access(ctx, "mcp", "execute")
    server = _get_server(server_id, ctx.tenant_id, ctx.project_id)
    if not server:
        raise HTTPException(status_code=404, detail="Custom MCP server not found")

    try:
        tools = await discover_mcp_tools(
            server["transport"],
            server["command"],
            server["args"],
            server["env_vars"],
            server["url"],
            server["headers"],
            server_id,
        )
        now = datetime.utcnow().isoformat()
        conn = get_db_connection()
        conn.execute(
            "UPDATE custom_mcp_servers SET tools_cache = ?, updated_at = ? WHERE id = ? AND tenant_id = ? AND project_id = ?",
            (json.dumps(tools), now, server_id, ctx.tenant_id, ctx.project_id),
        )
        conn.commit()
        conn.close()
        return {"success": True, "tools": tools, "tool_count": len(tools)}
    except Exception as e:
        return {"success": False, "error": str(e), "tools": server.get("tools_cache", [])}


@router.post("/{server_id}/execute")
async def execute_saved_mcp_server(server_id: str, req: McpExecuteRequest, request: Request):
    """Execute a tool call against a saved MCP server."""
    ctx = get_request_context(request)
    require_access(ctx, "mcp", "execute")
    server = _get_server(server_id, ctx.tenant_id, ctx.project_id)
    if not server:
        raise HTTPException(status_code=404, detail="Custom MCP server not found")
    output = await execute_custom_mcp(
        server_id, req.input_text, {"tool_name": req.tool_name, "arguments": req.arguments}
    )
    return {"success": not output.startswith("[Error"), "output": output, "server_id": server_id}


# ── OAuth ─────────────────────────────────────────────────────────────────────

@router.post("/{server_id}/oauth/start")
async def start_mcp_oauth(server_id: str, req: McpOAuthStart, request: Request):
    """Begin signing in to a remote server; open the returned URL in a browser window."""
    ctx = get_request_context(request)
    require_access(ctx, "mcp", "write")
    server = _get_server(server_id, ctx.tenant_id, ctx.project_id)
    if not server:
        raise HTTPException(status_code=404, detail="Custom MCP server not found")
    if server["transport"] not in ("http", "sse"):
        raise HTTPException(status_code=400, detail="OAuth is for remote (HTTP / SSE) servers")
    try:
        url = await mcp_oauth.start(server, mcp_oauth.redirect_uri(str(request.base_url)),
                                    req.client_id.strip(), req.client_secret.strip(), req.scope)
    except mcp_oauth.OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"authorization_url": url}


@router.delete("/{server_id}/oauth")
def disconnect_mcp_oauth(server_id: str, request: Request):
    """Forget the server's OAuth client and tokens."""
    ctx = get_request_context(request)
    require_access(ctx, "mcp", "write")
    if not _get_server(server_id, ctx.tenant_id, ctx.project_id):
        raise HTTPException(status_code=404, detail="Custom MCP server not found")
    mcp_oauth.disconnect(server_id)
    return {"disconnected": True, "id": server_id}


_CALLBACK_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>MCP sign-in</title></head>
<body style="font-family:system-ui;padding:2rem"><p>{text}</p></body></html>"""


@public_router.get("/oauth/callback", response_class=HTMLResponse)
async def mcp_oauth_callback(state: str = "", code: str = "", error: str = "", error_description: str = ""):
    """Public — the single-use ``state`` is the credential. A plain page: the app polls the
    server's ``oauth_status`` rather than talking to this window (COOP severs the opener)."""
    import html

    if error:
        ok, message = False, f"Sign-in failed: {error_description or error}"
    elif not code:
        ok, message = False, "The authorization server sent no code."
    else:
        try:
            await mcp_oauth.finish(state, code)
            ok, message = True, "Connected. You can close this window and return to Pipesets."
        except mcp_oauth.OAuthError as e:
            ok, message = False, str(e)
    return HTMLResponse(_CALLBACK_PAGE.format(text=html.escape(message, quote=False)), status_code=200 if ok else 400)
