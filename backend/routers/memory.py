from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from models import MemoryMessage, MemorySessionResponse
from services import kv_store
from services import long_term_memory as ltm
from services.acl import has_access, require_access
from services.request_context import RequestContext, get_request_context

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def rough_token_count(text: str) -> int:
    """Rough estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


def trim_to_budget(messages: List[dict], token_budget: int, strategy: str) -> List[dict]:
    """Apply windowing strategy to keep messages within token_budget."""
    total = sum(m["token_count"] for m in messages)
    if total <= token_budget:
        return messages

    if strategy == "sliding_window":
        trimmed = [m for m in messages if m["role"] == "system"]
        non_system = [m for m in messages if m["role"] != "system"]
        for msg in reversed(non_system):
            if sum(m["token_count"] for m in trimmed) + msg["token_count"] <= token_budget:
                trimmed.insert(len([m for m in trimmed if m["role"] == "system"]), msg)
        return sorted(trimmed, key=lambda m: m["created_at"])

    elif strategy == "summarize":
        system_msgs = [m for m in messages if m["role"] == "system"]
        non_system = [m for m in messages if m["role"] != "system"]
        return system_msgs + non_system[-4:]

    else:  # last_k
        return messages[-8:]


# ── Routes ────────────────────────────────────────────────────────────────────
# Everything is scoped to the caller's tenant / project (services/long_term_memory.py). Reading
# needs apps:read; changing or deleting needs apps:write; the long-term opt-in is the tenant's
# (memory:admin — tenant owners have it).

def _who(request: Request) -> ltm.Who:
    ctx = get_request_context(request)
    return ltm.Who(ctx.tenant_id, ctx.project_id, ctx.user_id)


def _require(request: Request, action: str) -> RequestContext:
    ctx = get_request_context(request)
    require_access(ctx, "apps", action)
    return ctx


# ── Long-term memory (defined first: "/long-term/..." must not match "/{session_id}") ─

class LongTermSettings(BaseModel):
    enabled: bool


class FactCreate(BaseModel):
    user: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=ltm.MAX_FACT_CHARS)


@router.get("/long-term/settings")
def get_long_term_settings(request: Request):
    ctx = _require(request, "read")
    return {"enabled": ltm.enabled(ctx.tenant_id), "can_change": has_access(ctx, "memory", "admin")}


@router.put("/long-term/settings")
def put_long_term_settings(body: LongTermSettings, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "memory", "admin")
    ltm.set_enabled(ctx.tenant_id, body.enabled, ctx.user_id)
    return {"enabled": body.enabled, "can_change": True}


@router.get("/long-term/users")
def list_long_term_users(request: Request):
    ctx = _require(request, "read")
    return {"users": ltm.list_subjects(ctx.tenant_id, ctx.project_id)}


@router.get("/long-term/facts")
def list_long_term_facts(request: Request, user: Optional[str] = None):
    ctx = _require(request, "read")
    return {"facts": ltm.list_facts(ctx.tenant_id, ctx.project_id, user)}


@router.post("/long-term/facts", status_code=201)
def add_long_term_fact(body: FactCreate, request: Request):
    ctx = _require(request, "write")
    stored = ltm.add_facts(ltm.Who(ctx.tenant_id, ctx.project_id, body.user.strip()), [body.content], source="manual")
    if not stored:
        raise HTTPException(status_code=409, detail="Already remembered")
    return {"stored": stored}


@router.delete("/long-term/facts/{fact_id}")
def delete_long_term_fact(fact_id: str, request: Request):
    ctx = _require(request, "write")
    if not ltm.delete_fact(fact_id, ctx.tenant_id, ctx.project_id):
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"deleted": fact_id}


@router.delete("/long-term/users/{user}")
def forget_long_term_user(user: str, request: Request):
    """Forget everything remembered about one end user, and their key-value store entries."""
    ctx = _require(request, "write")
    return {"user": user, "deleted": ltm.forget(ctx.tenant_id, ctx.project_id, user),
            "store_entries_deleted": kv_store.forget(ctx.tenant_id, ctx.project_id, user)}


# ── Key-value store (services/kv_store.py): subject "" = entries shared across the project ─

class StoreEntryPut(BaseModel):
    subject: str = Field("", max_length=255)
    namespace: str = Field(..., min_length=1, max_length=128)
    key: str = Field(..., min_length=1, max_length=kv_store.MAX_KEY_CHARS)
    value: Any = None
    ttl_seconds: Optional[int] = Field(None, ge=1, le=kv_store.MAX_TTL_SECONDS)


@router.get("/store/subjects")
def list_store_subjects(request: Request):
    ctx = _require(request, "read")
    return {"subjects": kv_store.list_subjects(ctx.tenant_id, ctx.project_id)}


@router.get("/store/entries")
def list_store_entries(request: Request, subject: str = "", namespace: Optional[str] = None):
    ctx = _require(request, "read")
    return {"entries": kv_store.list_entries(ctx.tenant_id, ctx.project_id, subject, namespace)}


@router.put("/store/entries")
def put_store_entry(body: StoreEntryPut, request: Request):
    """Add or edit an entry. An edited entry keeps its expiry unless ``ttl_seconds`` is given."""
    ctx = _require(request, "write")
    try:
        expires = kv_store.put(ctx.tenant_id, ctx.project_id, body.namespace.strip(), body.subject.strip(),
                               body.key, body.value, body.ttl_seconds, keep_expiry=True)
    except kv_store.StoreError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"key": body.key, "stored": True, "expires_at": expires}


@router.delete("/store/entries")
def delete_store_entry(request: Request, namespace: str, key: str, subject: str = ""):
    ctx = _require(request, "write")
    if not kv_store.delete(ctx.tenant_id, ctx.project_id, namespace, subject, key):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"deleted": key}


# ── Conversation sessions ─────────────────────────────────────────────────────

@router.get("")
def list_memory_sessions(request: Request):
    _require(request, "read")
    return {"sessions": ltm.list_sessions(_who(request))}


@router.get("/{session_id}", response_model=MemorySessionResponse)
def get_memory_session(session_id: str, request: Request, strategy: str = "sliding_window", token_budget: int = 4096):
    _require(request, "read")
    messages = ltm.load_messages(_who(request), session_id)
    active = trim_to_budget(messages, token_budget, strategy)
    return MemorySessionResponse(
        session_id=session_id,
        messages=[MemoryMessage(role=m["role"], content=m["content"], token_count=m["token_count"],
                                created_at=m["created_at"]) for m in active],
        total_tokens=sum(m["token_count"] for m in active),
        strategy=strategy,
        token_budget=token_budget,
    )


@router.post("/{session_id}/add")
def add_memory_message(session_id: str, msg: MemoryMessage, request: Request):
    _require(request, "write")
    who = _who(request)
    ltm.append_messages(who, session_id, [(msg.role, msg.content, msg.token_count or rough_token_count(msg.content))])
    total = sum(m["token_count"] for m in ltm.load_messages(who, session_id))
    return {"success": True, "session_id": session_id, "total_tokens": total}


@router.delete("/{session_id}")
def clear_memory_session(session_id: str, request: Request):
    _require(request, "write")
    ltm.clear_session(_who(request), session_id)
    return {"success": True, "session_id": session_id, "cleared": True}


@router.delete("/{session_id}/messages/{message_idx}")
def delete_session_message(session_id: str, message_idx: int, request: Request):
    """Delete a specific message from a session by its 0-based order index."""
    _require(request, "write")
    ltm.delete_message(_who(request), session_id, message_idx)
    return {"success": True, "session_id": session_id, "deleted_index": message_idx}
