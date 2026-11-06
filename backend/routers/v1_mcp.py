"""
v1_mcp.py — the public API as a remote MCP server (Streamable HTTP), for Claude Code, Claude
Desktop and other MCP clients.

POST /v1/mcp   — one JSON-RPC message (or a batch, for 2025-03-26 clients); requests get an
                 ``application/json`` response, notifications and responses get 202
GET / DELETE   — 405: the server is stateless, so there is no session and no server-to-client stream

Auth is the /v1 API key (``Authorization: Bearer <key>`` or ``X-API-Key``), checked and rate
limited on every request like the REST routes. ``tools/list`` shows only the tools the key's
scopes allow; each call checks its tool's scope again. The key acts as its creator, so ACLs,
budgets and middleware nodes apply as on ``POST /v1/apps/{id}/run``.

Tools
-----
  list_apps   (apps:read)  published apps the key can see
  get_app     (apps:read)  one published app's summary (never its flow: flows can hold keys)
  run_app     (apps:run)   run a published app once; returns its answer
  resume_run  (apps:run)   continue an interrupted or failed run
  cancel_run  (apps:run)   stop a running run (from another session: run_app blocks)
  list_drafts, get_flow, create_app, update_app   (apps:write)   build and edit drafts
  publish_app (apps:publish)  put a draft live

Write tools never touch what is live: ``update_app`` edits drafts only (a person starts a new draft
of a published app with Edit), and ``publish_app`` runs the app's eval gate with no override. They
call the same routes as the UI (plaintext credentials refused, ACLs of the key's owner) and each
write is recorded in the audit log under the owner, with the key in ``path``. ``get_flow`` refuses
flows that still hold plaintext credentials from before they were refused at save.

A run paused at a Human Gate is reported, not approvable here: the gate is there for a person,
so a reviewer decides it in the Pipesets UI (or ``POST /v1/runs/{id}/resume``), not the model.

Provider keys are never tool arguments (clients log those). Send them as headers instead —
``X-Provider-Key-Openai: sk-...`` — or rely on the project's default keys / the server's env.

Browsers: a request with an ``Origin`` header is refused unless that origin is listed in
MCP_ALLOWED_ORIGINS (comma-separated), per the MCP spec's DNS-rebinding rule.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from services.api_keys import ApiKeyPrincipal, authenticate

logger = logging.getLogger("pipesets-ai-backend")

router = APIRouter(prefix="/v1", tags=["v1"])

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")   # newest first
SERVER_INFO = {"name": "pipesets-ai", "title": "Pipesets AI", "version": "0.7.0"}
INSTRUCTIONS = ("Tools for Pipesets AI. Use list_apps to find published apps, then run_app to run one. "
                "run_app makes real LLM calls and can incur cost.")

# JSON-RPC error codes
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602


class ToolFailed(Exception):
    """Reported to the model as a tool result with isError, not as a protocol error."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@dataclass
class Tool:
    name: str
    scope: str
    description: str
    schema: Dict[str, Any]
    annotations: Dict[str, Any]
    fn: Callable[[Dict[str, Any], ApiKeyPrincipal, Request], Awaitable[Dict[str, Any]]]

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.schema,
                "annotations": self.annotations}


READ = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
RUN = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
PUBLISH = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}


def _schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _provider_key_headers(request: Request) -> Dict[str, str]:
    prefix = "x-provider-key-"
    return {k[len(prefix):]: v for k, v in request.headers.items() if k.startswith(prefix) and v}


def _http_error(e: HTTPException) -> ToolFailed:
    detail = e.detail.get("message", e.detail) if isinstance(e.detail, dict) else e.detail
    return ToolFailed(str(detail))


async def _list_apps(args, p, request):
    from routers.v1 import v1_list_apps
    return {"apps": v1_list_apps(p)["data"]}


async def _get_app(args, p, request):
    from routers.v1 import v1_get_app
    try:
        return v1_get_app(args["app_id"], p)
    except HTTPException as e:
        raise _http_error(e)


def _run_outcome(res: Dict[str, Any]) -> Dict[str, Any]:
    if res["status"] == "failed":
        raise ToolFailed(res.get("error") or "Run failed")
    return res


async def _run_app(args, p, request):
    from routers.v1 import V1RunRequest, v1_run_app
    try:
        body = V1RunRequest(prompt=args["prompt"], session_id=args.get("session_id"), user=args.get("user"), stream=False,
                            timeout_ms=args.get("timeout_ms", 120000), provider_keys=_provider_key_headers(request))
    except ValueError as e:
        raise ToolFailed(f"Invalid arguments: {e}")
    try:
        return _run_outcome(await v1_run_app(args["app_id"], body, p))
    except HTTPException as e:
        raise _http_error(e)


async def _resume_run(args, p, request):
    from routers.v1 import V1ResumeRequest, v1_resume_run
    try:
        body = V1ResumeRequest(timeout_ms=args.get("timeout_ms", 120000), provider_keys=_provider_key_headers(request))
    except ValueError as e:
        raise ToolFailed(f"Invalid arguments: {e}")
    try:
        return _run_outcome(await v1_resume_run(args["run_id"], body, p))
    except HTTPException as e:
        if e.status_code == 400 and "waiting for review" in str(e.detail):
            raise ToolFailed(f"{e.detail}. A person decides Human Gates: approve or reject it in the Pipesets UI "
                             f"(or POST /v1/runs/{args['run_id']}/resume with a gate_decision).")
        raise _http_error(e)


# ── Write tools (apps:write / apps:publish) ───────────────────────────────────

def _as_user(p: ApiKeyPrincipal, request: Request) -> Request:
    """Let the app routes run as the key's owner: they read the caller from request.state.ctx."""
    from services.secret_store import request_scope
    request.state.ctx = p.ctx
    request_scope.set((p.ctx.tenant_id, p.ctx.project_id))
    return request


def _audit(p: ApiKeyPrincipal, request: Request, action: str, target: str, tool: str, outcome: str = "success",
           status: int = 200) -> None:
    from services import audit
    audit.record(tenant_id=p.ctx.tenant_id, project_id=p.ctx.project_id, actor=p.ctx.user_id, action=action,
                 target_id=target, outcome=outcome, status=status, method="MCP",
                 path=f"/v1/mcp {tool} · key {p.name} ({p.key_id})",
                 ip=request.client.host if request.client else "")


def _summary(app) -> Dict[str, Any]:
    nodes = (app.flow_data or {}).get("nodes", [])
    return {"id": app.id, "name": app.name, "description": app.description, "status": app.status,
            "version": app.version, "node_count": len(nodes), "updated_at": app.updated_at}


async def _list_drafts(args, p, request):
    from routers.apps import list_apps
    return {"apps": [_summary(a) for a in list_apps(_as_user(p, request)) if a.status != "published"]}


async def _get_flow(args, p, request):
    from routers.apps import get_app
    from services.secret_store import plaintext_credentials
    try:
        app = get_app(args["app_id"], _as_user(p, request))
    except HTTPException as e:
        raise _http_error(e)
    if plaintext_credentials(app.flow_data):
        raise ToolFailed("This app's flow holds credentials in plain text (saved before they were refused), so it "
                         "isn't shown. Move them to Secrets in Pipesets first.")
    return {**_summary(app), "flow_data": app.flow_data}


def _flow_arg(args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    flow = args.get("flow_data")
    if flow is not None and not (isinstance(flow, dict) and isinstance(flow.get("nodes", []), list)
                                 and isinstance(flow.get("edges", []), list)):
        raise ToolFailed("flow_data must be an object with 'nodes' and 'edges' lists")
    return flow


async def _create_app(args, p, request):
    from models import AppCreateRequest
    from routers.apps import create_app
    flow = _flow_arg(args)
    try:
        app = create_app(AppCreateRequest(name=args["name"], description=args.get("description") or "",
                                          flow_data=flow or {"nodes": [], "edges": []}), _as_user(p, request))
    except HTTPException as e:
        raise _http_error(e)
    _audit(p, request, "app.create", app.id, "create_app")
    return _summary(app)


async def _update_app(args, p, request):
    from models import AppUpdateRequest
    from routers.apps import update_app
    flow = _flow_arg(args)
    try:
        app = update_app(args["app_id"], AppUpdateRequest(name=args.get("name"), description=args.get("description"),
                                                          flow_data=flow), _as_user(p, request))
    except HTTPException as e:
        if e.status_code == 409:
            raise ToolFailed("This app is published, and update_app never changes what is live. A person starts a "
                             "new draft of it with Edit in Pipesets; or create_app a new app from its flow.")
        raise _http_error(e)
    _audit(p, request, "app.update", app.id, "update_app")
    return _summary(app)


async def _publish_app(args, p, request):
    from routers.apps import PublishRequest, get_app, publish_app
    from routers.v1 import _provider_keys
    try:
        if get_app(args["app_id"], _as_user(p, request)).status == "published":
            raise ToolFailed("This app is already published; there is no draft to publish.")
    except HTTPException as e:
        raise _http_error(e)
    body = PublishRequest(force=False, provider_keys=_provider_keys(_provider_key_headers(request),
                                                                    (p.ctx.tenant_id, p.ctx.project_id)))
    try:
        app = await publish_app(args["app_id"], _as_user(p, request), body)
    except HTTPException as e:
        if e.status_code in (403, 409):
            _audit(p, request, "app.publish", args["app_id"], "publish_app", "denied", e.status_code)
        raise _http_error(e)
    _audit(p, request, "app.publish", app.id, "publish_app")
    return {**_summary(app), "publish_gate": app.publish_gate}


FLOW = {"type": "object", "description": (
    "React Flow graph: {\"nodes\": [...], \"edges\": [...]}. A node is {\"id\", \"type\", \"data\"}, e.g. "
    "{\"id\": \"llm1\", \"type\": \"llm\", \"data\": {\"label\": \"Answer\", \"provider\": \"openai\", "
    "\"model\": \"gpt-4o-mini\", \"system_prompt\": \"...\"}}; an edge is {\"id\", \"source\", \"target\"}. "
    "Copy the shapes of an existing app with get_flow. Credentials only as \"secret://<name>\" references.")}


async def _cancel_run(args, p, request):
    from routers.v1 import v1_cancel_run
    try:
        return v1_cancel_run(args["run_id"], p)
    except HTTPException as e:
        raise _http_error(e)


TIMEOUT = {"type": "integer", "minimum": 1000, "maximum": 600000, "default": 120000,
           "description": "Give up after this many milliseconds"}

TOOLS: Dict[str, Tool] = {t.name: t for t in (
    Tool("list_apps", "apps:read",
         "List the published apps this key can run: id, name, description, version, and whether each uses "
         "agents or RAG. Only published apps can be run.",
         _schema({}, []), READ, _list_apps),
    Tool("get_app", "apps:read", "Get one published app's summary.",
         _schema({"app_id": {"type": "string", "description": "From list_apps"}}, ["app_id"]), READ, _get_app),
    Tool("run_app", "apps:run",
         "Run a published app once with a prompt and return its answer. Makes real LLM calls and may incur cost. "
         "A Master Agent app can stop at a Human Gate: the result then has status 'paused', a run_id and the "
         "output waiting for review, and a person approves it in Pipesets.",
         _schema({"app_id": {"type": "string", "description": "From list_apps"},
                  "prompt": {"type": "string", "minLength": 1},
                  "session_id": {"type": "string", "maxLength": 200,
                                 "description": "Conversation id for apps with memory; one per end user"},
                  "user": {"type": "string", "maxLength": 255,
                           "description": "End user id, for apps with long-term memory"},
                  "timeout_ms": TIMEOUT}, ["app_id", "prompt"]), RUN, _run_app),
    Tool("resume_run", "apps:run",
         "Continue a run that was interrupted or failed, reusing its finished model and tool calls. Runs paused at "
         "a Human Gate can't be approved here.",
         _schema({"run_id": {"type": "string"}, "timeout_ms": TIMEOUT}, ["run_id"]), RUN, _resume_run),
    Tool("cancel_run", "apps:run",
         "Stop a running run (it stops within seconds), or close a paused / interrupted / failed "
         "one so it can't resume. The run_id comes from run_app's result or from Pipesets.",
         _schema({"run_id": {"type": "string"}}, ["run_id"]), RUN, _cancel_run),
    Tool("list_drafts", "apps:write", "List apps that are drafts (not published), which update_app can edit.",
         _schema({}, []), READ, _list_drafts),
    Tool("get_flow", "apps:write", "Get an app's flow (nodes and edges), draft or published, to edit or copy it.",
         _schema({"app_id": {"type": "string"}}, ["app_id"]), READ, _get_flow),
    Tool("create_app", "apps:write", "Create a new app as a draft. It can't run until it is published.",
         _schema({"name": {"type": "string", "minLength": 1}, "description": {"type": "string"}, "flow_data": FLOW},
                 ["name"]), WRITE, _create_app),
    Tool("update_app", "apps:write",
         "Change a draft app's name, description or flow. Omitted fields stay as they are; flow_data replaces the "
         "whole flow. Published apps can't be changed here.",
         _schema({"app_id": {"type": "string"}, "name": {"type": "string", "minLength": 1},
                  "description": {"type": "string"}, "flow_data": FLOW}, ["app_id"]), WRITE, _update_app),
    Tool("publish_app", "apps:publish",
         "Publish a draft as its next version, making it runnable through the API and MCP. If the app has an eval "
         "gate, the draft must pass it; there is no override.",
         _schema({"app_id": {"type": "string"}}, ["app_id"]), PUBLISH, _publish_app),
)}


def _text(result: Dict[str, Any]) -> str:
    """What the model reads: a run's answer, else the JSON."""
    if result.get("status") == "completed" and "output" in result:
        return result["output"]
    if result.get("status") == "paused":
        gate = result.get("pending_gate") or {}
        return (f"Paused for human review at '{gate.get('agent', 'a Human Gate')}' (run_id {result.get('run_id')}). "
                f"A reviewer approves or rejects it in Pipesets; the output waiting for review:\n\n{gate.get('output', '')}")
    return json.dumps(result, indent=2, default=str)


async def _call_tool(params: Dict[str, Any], p: ApiKeyPrincipal, request: Request) -> Dict[str, Any]:
    name, args = params.get("name"), params.get("arguments") or {}
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if tool is None or tool.scope not in p.scopes:
        raise RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
    if not isinstance(args, dict):
        raise RpcError(INVALID_PARAMS, "arguments must be an object")
    missing = [k for k in tool.schema["required"] if not args.get(k)]
    if missing:
        return _tool_error(f"Missing argument(s): {', '.join(missing)}")
    try:
        result = await tool.fn(args, p, request)
    except ToolFailed as e:
        return _tool_error(str(e))
    return {"content": [{"type": "text", "text": _text(result)}], "structuredContent": result, "isError": False}


def _tool_error(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


# ── JSON-RPC ──────────────────────────────────────────────────────────────────

class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _negotiate(requested: Any) -> str:
    return requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]


async def _dispatch(method: str, params: Dict[str, Any], p: ApiKeyPrincipal, request: Request) -> Dict[str, Any]:
    if method == "initialize":
        return {"protocolVersion": _negotiate(params.get("protocolVersion")),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [t.describe() for t in TOOLS.values() if t.scope in p.scopes]}
    if method == "tools/call":
        return await _call_tool(params, p, request)
    raise RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")


async def _handle(msg: Any, p: ApiKeyPrincipal, request: Request) -> Optional[Dict[str, Any]]:
    """The response to one message, or None for notifications and client responses."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _rpc_error(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message")
    if "method" not in msg:
        return None   # a response to a server request; this server sends none
    if "id" not in msg:
        return None   # notification (notifications/initialized, cancelled, ...)
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(msg["id"], INVALID_PARAMS, "params must be an object")
    try:
        return {"jsonrpc": "2.0", "id": msg["id"], "result": await _dispatch(msg["method"], params, p, request)}
    except RpcError as e:
        return _rpc_error(msg["id"], e.code, str(e))
    except Exception:
        logger.exception(f"MCP {msg['method']} failed")
        return _rpc_error(msg["id"], -32603, "Internal error")


def _rpc_error(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _origin_allowed(origin: Optional[str]) -> bool:
    if not origin:
        return True   # not a browser
    allowed = {o.strip().rstrip("/") for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()}
    return origin.rstrip("/") in allowed


@router.post("/mcp")
async def mcp_post(request: Request):
    if not _origin_allowed(request.headers.get("origin")):
        return JSONResponse(_rpc_error(None, INVALID_REQUEST, "Origin not allowed"), status_code=403)
    version = request.headers.get("mcp-protocol-version")
    if version and version not in PROTOCOL_VERSIONS:
        return JSONResponse(_rpc_error(None, INVALID_REQUEST, f"Unsupported MCP-Protocol-Version: {version}"),
                            status_code=400)
    p = authenticate(request, None)   # 401 / 403 / 429 like every /v1 route
    try:
        body = json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(_rpc_error(None, PARSE_ERROR, "Parse error"), status_code=400)

    if isinstance(body, list):   # batch (2025-03-26)
        if not body:
            return JSONResponse(_rpc_error(None, INVALID_REQUEST, "Empty batch"), status_code=400)
        replies = [r for r in [await _handle(m, p, request) for m in body] if r is not None]
        return JSONResponse(replies) if replies else Response(status_code=202)
    reply = await _handle(body, p, request)
    return JSONResponse(reply) if reply is not None else Response(status_code=202)


@router.get("/mcp")
@router.delete("/mcp")
def mcp_no_session():
    return Response(status_code=405, headers={"Allow": "POST"})
