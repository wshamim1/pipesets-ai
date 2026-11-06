"""
chat_links.py — public chat links for published pipelines (see services/chat_links.py).

GET    /api/chat-links              — links in the caller's tenant/project (?app_id= filters)
POST   /api/chat-links              — create one for a published pipeline
PATCH  /api/chat-links/{link_id}    — change name / title / greeting / limits
POST   /api/chat-links/{link_id}/rotate — a new URL for the link; the old one stops working
DELETE /api/chat-links/{link_id}    — revoke (immediate; the URL stops working on the next message)

POST   /v1/chat/{token}/session     — public: start (or check) a visitor's session; title, greeting,
                                      starter prompts and (when the link shows them) pipeline details
POST   /v1/chat/{token}/message     — public: send a message, streamed back as SSE
POST   /v1/chat/{token}/feedback    — public: 👍 / 👎 on an answer, with the token its ``done`` event carried

The public routes need no login: the token in the URL is the credential, and it can only chat with
its one pipeline. Visitors only ever see the answer (``token``, ``error`` and ``done`` events),
never traces, costs or run ids: ``done`` carries ``feedback``, a sealed token naming the run that only
this visitor's session on this link can use to rate it (services/feedback.py).
"""

from dataclasses import replace
from typing import Annotated, Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from db import get_db_connection
from routers.v1 import V1RunRequest, _provider_keys, _run_events, _sse
from services import chat_links, feedback as ratings
from services.acl import require_access
from services.pipeline_runner import RunScope, _load_published_app
from services.request_context import get_request_context

router = APIRouter(prefix="/api/chat-links", tags=["chat-links"])
public_router = APIRouter(prefix="/v1/chat", tags=["v1"])


class Limits(BaseModel):
    rate_limit_per_min: Optional[int] = Field(default=None, ge=0, le=1000, description="per visitor IP; 0 = unlimited")
    max_turns: Optional[int] = Field(default=None, ge=0, le=10000, description="messages per conversation; 0 = unlimited")
    max_message_chars: Optional[int] = Field(default=None, ge=1, le=100000)
    daily_message_cap: Optional[int] = Field(default=None, ge=0, le=1000000, description="all visitors, 24 h; 0 = unlimited")


Prompts = List[Annotated[str, Field(max_length=500)]]


class ChatLinkCreate(Limits):
    app_id: str = Field(..., min_length=1)
    name: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200, description="heading on the chat page; default: the pipeline's name")
    greeting: str = Field(default="", max_length=2000, description="first message visitors see")
    show_details: bool = Field(default=True, description="show the pipeline's description, models, tools and agents")
    starter_prompts: Prompts = Field(default_factory=list, max_length=chat_links.MAX_STARTERS)


class ChatLinkUpdate(Limits):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    title: Optional[str] = Field(default=None, max_length=200)
    greeting: Optional[str] = Field(default=None, max_length=2000)
    show_details: Optional[bool] = None
    starter_prompts: Optional[Prompts] = Field(default=None, max_length=chat_links.MAX_STARTERS)


# ── Builder side ──────────────────────────────────────────────────────────────

@router.get("")
def list_chat_links(request: Request, app_id: str = "") -> List[Dict[str, Any]]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    return chat_links.list_links(ctx.tenant_id, ctx.project_id, app_id)


@router.post("", status_code=201)
def create_chat_link(body: ChatLinkCreate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    conn = get_db_connection()
    try:
        app = conn.execute("SELECT name, status FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (body.app_id, ctx.tenant_id, ctx.project_id)).fetchone()
    finally:
        conn.close()
    if not app:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if app["status"] != "published":
        raise HTTPException(status_code=409, detail="Publish the pipeline before sharing a chat link")
    limits = body.model_dump(include=set(Limits.model_fields))
    return chat_links.create(ctx.tenant_id, ctx.project_id, ctx.user_id, body.app_id,
                             body.name.strip() or f"{app['name']} chat", body.title.strip(), body.greeting.strip(),
                             body.show_details, body.starter_prompts, **limits)


@router.patch("/{link_id}")
def update_chat_link(link_id: str, body: ChatLinkUpdate, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    link = chat_links.update(link_id, ctx.tenant_id, ctx.project_id, ctx.user_id, **body.model_dump())
    if not link:
        raise HTTPException(status_code=404, detail="Chat link not found or revoked")
    return link


@router.post("/{link_id}/rotate")
def rotate_chat_link(link_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    link = chat_links.rotate(link_id, ctx.tenant_id, ctx.project_id, ctx.user_id)
    if not link:
        raise HTTPException(status_code=404, detail="Chat link not found or revoked")
    return link


@router.delete("/{link_id}")
def revoke_chat_link(link_id: str, request: Request) -> Dict[str, Any]:
    ctx = get_request_context(request)
    require_access(ctx, "apps", "write")
    if not chat_links.revoke(link_id, ctx.tenant_id, ctx.project_id):
        raise HTTPException(status_code=404, detail="Chat link not found or already revoked")
    return {"revoked": True, "id": link_id}


# ── Public side ───────────────────────────────────────────────────────────────

class SessionRequest(BaseModel):
    session: str = Field(default="", max_length=1000, description="a session from an earlier visit, to continue it")


class MessageRequest(BaseModel):
    session: str = Field(..., min_length=1, max_length=1000)
    message: str = Field(..., min_length=1, max_length=100000)


class FeedbackRequest(BaseModel):
    session: str = Field(..., min_length=1, max_length=1000)
    feedback: str = Field(..., min_length=1, max_length=2000, description="the token from the answer's done event")
    rating: int = Field(..., description="1 = 👍, -1 = 👎")
    comment: str = Field(default="", max_length=ratings.MAX_COMMENT)


_UNAVAILABLE = "This chat link doesn't exist or has been turned off"


def _link(token: str) -> Dict[str, Any]:
    link = chat_links.find_by_token(token)
    if not link:
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    return link


def _scope(link: Dict[str, Any]) -> RunScope:
    scope = (link["tenant_id"], link["project_id"])
    return RunScope(tenant_id=link["tenant_id"], project_id=link["project_id"], user_id=link["created_by"],
                    provider_keys=_provider_keys({}, scope), caller=f"link:{link['id']}")


def _app(link: Dict[str, Any], scope: RunScope) -> Dict[str, Any]:
    """The pipeline the link runs; 404 / 503 in visitor terms when it can't."""
    try:
        app = _load_published_app(link["app_id"], scope)
    except LookupError:
        raise HTTPException(status_code=404, detail=_UNAVAILABLE)
    except (PermissionError, ValueError):   # owner lost access, or the pipeline was unpublished
        raise HTTPException(status_code=503, detail="This chat is unavailable right now")
    if not {n.get("type") for n in app["flow"].get("nodes", [])} & {"llm", "master_agent"}:
        raise HTTPException(status_code=503, detail="This chat is unavailable right now")
    return app


@public_router.post("/{token}/session")
def start_session(token: str, body: SessionRequest) -> Dict[str, Any]:
    link = _link(token)
    app = _app(link, _scope(link))
    session = body.session if body.session and chat_links.open_session(link, body.session) else chat_links.new_session(link)
    return {
        "session": session,
        "resumed": session == body.session,
        "title": link["title"] or app["name"],
        "greeting": link["greeting"],
        "starter_prompts": chat_links.parse_prompts(link["starter_prompts"]),
        "about": chat_links.about(app, _description(link)) if link["show_details"] else None,
        "max_message_chars": link["max_message_chars"],
    }


def _description(link: Dict[str, Any]) -> str:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT description FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (link["app_id"], link["tenant_id"], link["project_id"])).fetchone()
    finally:
        conn.close()
    return (row["description"] if row else "") or ""


async def _visitor_events(events: AsyncIterator[Dict[str, Any]], link: Optional[Dict[str, Any]] = None,
                          sid: str = "") -> AsyncIterator[str]:
    """Only what a visitor should see: the answer text, a readable error, the end — with a sealed
    token to rate the answer when there is a run to rate."""
    run_id = None
    async for ev in events:
        kind = ev.get("type")
        run_id = run_id or ev.get("run_id")
        if kind == "token":
            yield _sse({"type": "token", "text": ev.get("text", "")})
        elif kind == "error":
            yield _sse({"type": "error", "message": ev.get("message") or "Something went wrong",
                        "retract": bool(ev.get("retract"))})
        elif kind == "paused":
            yield _sse({"type": "error", "message": "This answer is waiting for a review — try again later"})
        elif kind == "done":
            done: Dict[str, Any] = {"type": "done"}
            if run_id and link:
                done["feedback"] = ratings.chat_token(link["id"], sid, run_id)
            yield _sse(done)


@public_router.post("/{token}/message")
async def send_message(token: str, body: MessageRequest, request: Request):
    link = _link(token)
    sid = chat_links.open_session(link, body.session)
    if not sid:
        raise HTTPException(status_code=401, detail="Your chat session has expired — reload the page")
    scope = _scope(link)
    app = _app(link, scope)
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Type a message first")
    try:
        chat_links.check_message(link, sid, request.client.host if request.client else "", message)
    except chat_links.LimitExceeded as e:
        headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
        raise HTTPException(status_code=e.status, detail=str(e), headers=headers)

    run = V1RunRequest(prompt=message, session_id=chat_links.memory_session(link, sid))
    events = _run_events(app, run, replace(scope), default_memory=chat_links.DEFAULT_MEMORY)
    return StreamingResponse(
        _visitor_events(events, link, sid),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@public_router.post("/{token}/feedback")
def rate_answer(token: str, body: FeedbackRequest) -> Dict[str, Any]:
    link = _link(token)
    sid = chat_links.open_session(link, body.session)
    if not sid:
        raise HTTPException(status_code=401, detail="Your chat session has expired — reload the page")
    run_id = ratings.open_chat_token(body.feedback, link["id"], sid)
    if not run_id:
        raise HTTPException(status_code=404, detail="That answer can't be rated")
    try:
        ratings.rate(link["tenant_id"], link["project_id"], run_id, "chat_link", f"link:{link['id']}:{sid}",
                      body.rating, body.comment)
    except ratings.FeedbackError as e:
        raise HTTPException(status_code=e.status, detail="That answer can't be rated" if e.status == 404 else str(e))
    return {"ok": True, "rating": body.rating}
