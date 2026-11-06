"""
long_term_memory.py — conversation memory and long-term memory, both scoped to tenant / project.

Conversation memory (the Memory node's session history)
-------------------------------------------------------
``memory_messages`` rows keyed by (tenant, project, session_id). Two tenants using the same session
id never see each other's history. The scope comes from the run (``current_scope``: published / API
/ scheduled runs) or the request (``request_scope``: the canvas).

Long-term memory (facts about an end user, across sessions)
------------------------------------------------------------
With "Long-term memory" on in a Memory node and the feature enabled for the tenant (off by default;
Settings → Memory), a run:

1. recalls the end user's remembered facts into its context — all of them up to ``recall_k``, else
   the ``recall_k`` that share the most words with the prompt, then the most recent;
2. after answering, queues a ``memory.extract`` job that reads the turn and stores new durable facts
   (preferences, profile, goals) about the user. The run's model does the reading when a key is
   available on the server (a ``secret://`` / sealed node key, the project's default key, or the
   server's env key); otherwise — and for the mock and local models — simple rules pick up plain
   statements ("I prefer …", "call me …", "I'm vegetarian"). Keys typed into the browser are never
   put in the job.

Every fact goes through the PII redactor before it is stored. The end user is the signed-in user on
the canvas and the ``user`` field on /v1 and MCP runs; runs with no person (schedules, webhooks)
have no long-term memory. The inspector (Monitor → Sessions → Long-term) lists, deletes and forgets
facts; forgetting a user deletes everything remembered about them.

Facts are ranked by shared words, not embeddings: a user typically has a handful, and all of them up
to ``recall_k`` are recalled anyway.
"""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from db import IntegrityError, get_db_connection
from services import jobs

logger = logging.getLogger("pipesets-ai-backend")

FEATURE = "long_term_memory"
JOB_KIND = "memory.extract"
MAX_FACTS_PER_USER = 200      # past this, the least recently used go
MAX_FACT_CHARS = 300
DEFAULT_RECALL_K = 8


@dataclass
class Who:
    tenant_id: str
    project_id: str
    user: str = ""            # the end user long-term memory is about; "" = none


def current() -> Who:
    """The tenant / project / end user of the run or request in progress."""
    from services.pipeline_runner import current_scope
    from services.request_context import request_user
    from services.secret_store import request_scope

    scope = current_scope.get()
    if scope:
        return Who(scope.tenant_id, scope.project_id, scope.end_user or "")
    rs = request_scope.get()
    if rs:
        return Who(rs[0], rs[1], request_user.get() or "")
    return Who("", "", "")


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Conversation memory ───────────────────────────────────────────────────────

def session_ttl_hours(memory_config: Optional[Dict[str, Any]]) -> Optional[float]:
    """The Memory node's Session TTL, or None when unset / not a positive number (keep everything)."""
    try:
        hours = float((memory_config or {}).get("session_ttl_hours") or 0)
    except (TypeError, ValueError):
        return None
    return hours if hours > 0 else None


def load_messages(who: Who, session_id: str, max_age_hours: Optional[float] = None) -> List[Dict[str, Any]]:
    """A session's messages, oldest first; with ``max_age_hours``, only those newer than that
    (the Memory node's Session TTL — older turns stay stored and visible in the inspector)."""
    sql = ("SELECT id, role, content, token_count, created_at FROM memory_messages "
           "WHERE tenant_id = ? AND project_id = ? AND session_id = ?")
    args: List[Any] = [who.tenant_id, who.project_id, session_id]
    if max_age_hours:
        sql += " AND created_at >= ?"
        args.append((datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat())
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + " ORDER BY id", tuple(args)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def append_messages(who: Who, session_id: str, messages: List[Tuple[str, str, int]]) -> None:
    """Append (role, content, token_count) rows to a session."""
    now = _now()
    conn = get_db_connection()
    try:
        for role, content, tokens in messages:
            conn.execute(
                "INSERT INTO memory_messages (tenant_id, project_id, session_id, role, content, token_count, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", (who.tenant_id, who.project_id, session_id, role, content, tokens, now))
        conn.commit()
    finally:
        conn.close()


def clear_session(who: Who, session_id: str) -> int:
    conn = get_db_connection()
    try:
        n = conn.execute("DELETE FROM memory_messages WHERE tenant_id = ? AND project_id = ? AND session_id = ?",
                         (who.tenant_id, who.project_id, session_id)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def delete_message(who: Who, session_id: str, index: int) -> bool:
    """Delete a session's message by its 0-based position."""
    messages = load_messages(who, session_id)
    if not 0 <= index < len(messages):
        return False
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM memory_messages WHERE id = ?", (messages[index]["id"],))
        conn.commit()
    finally:
        conn.close()
    return True


def list_sessions(who: Who) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT session_id, COUNT(*) AS message_count, SUM(token_count) AS total_tokens, "
            "MAX(created_at) AS last_updated, MIN(id) AS first_id FROM memory_messages "
            "WHERE tenant_id = ? AND project_id = ? GROUP BY session_id ORDER BY last_updated DESC",
            (who.tenant_id, who.project_id),
        ).fetchall()
        out = []
        for r in rows:
            first = conn.execute("SELECT content FROM memory_messages WHERE id = ?", (r["first_id"],)).fetchone()
            out.append({"session_id": r["session_id"], "message_count": r["message_count"],
                        "total_tokens": r["total_tokens"] or 0, "last_updated": r["last_updated"],
                        "first_prompt": first["content"] if first else None})
        return out
    finally:
        conn.close()


# ── Per-tenant opt-in ─────────────────────────────────────────────────────────

def enabled(tenant_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT enabled FROM tenant_features WHERE tenant_id = ? AND feature = ?",
                           (tenant_id, FEATURE)).fetchone()
    finally:
        conn.close()
    return bool(row and row["enabled"])


def set_enabled(tenant_id: str, on: bool, user_id: str) -> None:
    now = _now()
    conn = get_db_connection()
    try:
        if conn.execute("UPDATE tenant_features SET enabled = ?, updated_at = ?, updated_by = ? "
                        "WHERE tenant_id = ? AND feature = ?", (int(on), now, user_id, tenant_id, FEATURE)).rowcount == 0:
            try:
                conn.execute("INSERT INTO tenant_features (tenant_id, feature, enabled, updated_at, updated_by) "
                             "VALUES (?, ?, ?, ?, ?)", (tenant_id, FEATURE, int(on), now, user_id))
            except IntegrityError:
                conn.rollback()
                conn.execute("UPDATE tenant_features SET enabled = ?, updated_at = ?, updated_by = ? "
                             "WHERE tenant_id = ? AND feature = ?", (int(on), now, user_id, tenant_id, FEATURE))
        conn.commit()
    finally:
        conn.close()


def active(memory_config: Optional[Dict[str, Any]], who: Who) -> bool:
    """Long-term memory applies to this run."""
    return bool(memory_config and memory_config.get("long_term") and who.user and who.tenant_id
                and enabled(who.tenant_id))


# ── Facts ─────────────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def list_facts(tenant_id: str, project_id: str, subject: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM memories WHERE tenant_id = ? AND project_id = ?"
    params: List[Any] = [tenant_id, project_id]
    if subject is not None:
        sql += " AND subject = ?"
        params.append(subject)
    conn = get_db_connection()
    try:
        rows = conn.execute(sql + " ORDER BY updated_at DESC LIMIT ?", (*params, limit)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def list_subjects(tenant_id: str, project_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT subject, COUNT(*) AS facts, MAX(updated_at) AS last_updated FROM memories "
                            "WHERE tenant_id = ? AND project_id = ? GROUP BY subject ORDER BY last_updated DESC",
                            (tenant_id, project_id)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def add_facts(who: Who, facts: List[str], app_id: Optional[str] = None, source: str = "extracted") -> List[str]:
    """Store facts about ``who.user`` (PII redacted, duplicates skipped — by a unique index, so two
    extraction jobs at once can't both add one); returns what was stored."""
    from routers.middleware import redact_pii

    stored: List[str] = []
    now = _now()
    conn = get_db_connection()
    try:
        for fact in facts:
            text = redact_pii(" ".join(str(fact).split()))[:MAX_FACT_CHARS].strip()
            key = _norm(text)[:255]
            if not key:
                continue
            try:
                conn.execute("INSERT INTO memories (id, tenant_id, project_id, subject, content, fact_key, source, "
                             "app_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (f"mem_{uuid.uuid4().hex[:16]}", who.tenant_id, who.project_id, who.user, text, key,
                              source, app_id, now, now))
                conn.commit()
            except IntegrityError:   # already remembered
                conn.rollback()
                continue
            stored.append(text)
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM memories WHERE tenant_id = ? AND project_id = ? AND subject = ? "
            "ORDER BY COALESCE(last_used_at, updated_at) DESC", (who.tenant_id, who.project_id, who.user)).fetchall()]
        for old in ids[MAX_FACTS_PER_USER:]:
            conn.execute("DELETE FROM memories WHERE id = ?", (old,))
        conn.commit()
    finally:
        conn.close()
    return stored


def delete_fact(fact_id: str, tenant_id: str, project_id: str) -> bool:
    conn = get_db_connection()
    try:
        n = conn.execute("DELETE FROM memories WHERE id = ? AND tenant_id = ? AND project_id = ?",
                         (fact_id, tenant_id, project_id)).rowcount
        conn.commit()
        return n == 1
    finally:
        conn.close()


def forget(tenant_id: str, project_id: str, subject: str) -> int:
    """Delete everything remembered about one end user."""
    conn = get_db_connection()
    try:
        n = conn.execute("DELETE FROM memories WHERE tenant_id = ? AND project_id = ? AND subject = ?",
                         (tenant_id, project_id, subject)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


_STOP = set("a an and are as at be but by do does for from has have how i if in is it its me my of on or "
            "so that the their them they this to us was we what when where which who why will with you your".split())


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP and len(w) > 1}


def recall(who: Who, query: str, k: int = DEFAULT_RECALL_K) -> List[str]:
    facts = list_facts(who.tenant_id, who.project_id, who.user)
    if len(facts) > k:
        q = _words(query)
        facts = sorted(facts, key=lambda f: (len(q & _words(f["content"])), f["updated_at"]), reverse=True)[:k]
    if facts:
        conn = get_db_connection()
        try:
            conn.execute(f"UPDATE memories SET last_used_at = ? WHERE id IN ({', '.join('?' for _ in facts)})",
                         (_now(), *[f["id"] for f in facts]))
            conn.commit()
        finally:
            conn.close()
    return [f["content"] for f in facts]


def context_block(facts: List[str]) -> str:
    return ("What you remember about this user from earlier conversations (it may be out of date; what they "
            "say now wins):\n" + "\n".join(f"- {f}" for f in facts))


# ── Extraction ────────────────────────────────────────────────────────────────

_RULES = [
    (r"\bmy name is ([A-Z][\w'-]*(?: [A-Z][\w'-]*)?)", "Their name is {}"),
    (r"\bcall me ([A-Z][\w'-]*)", "Prefers to be called {}"),
    (r"\bi (?:really )?(?:prefer|like|love|enjoy) ([^.,;!?\n]{2,80})", "Likes {}"),
    (r"\bi (?:really )?(?:dislike|hate|can't stand|don't like) ([^.,;!?\n]{2,80})", "Dislikes {}"),
    (r"\bi(?:'m| am) (?:a |an )?(vegetarian|vegan|pescatarian|allergic to [^.,;!?\n]{2,40}|"
     r"lactose intolerant|gluten[- ]free)", "Is {}"),
    (r"\bi (?:live|am based) in ([A-Z][^.,;!?\n]{1,60})", "Lives in {}"),
    (r"\bi work (?:at|for) ([A-Z][^.,;!?\n]{1,60})", "Works at {}"),
    (r"\bi(?:'m| am) an? ([a-z][a-z -]{2,40}(?:er|or|ist|ian|ant|ent|eer|ect|ager|signer))\b", "Is a {}"),
    (r"\b(?:please )?(?:always|never) ([^.;!?\n]{4,100})", "Asked: {}"),
    (r"\bi want (?:you )?to ([^.,;!?\n]{4,80})", "Wants to {}"),
]


def rule_facts(user_text: str) -> List[str]:
    """Plain statements about the user, without a model."""
    out: List[str] = []
    for pattern, template in _RULES:
        for m in re.finditer(pattern, user_text, flags=re.IGNORECASE):
            value = m.group(0) if template.startswith("Asked") else m.group(1)
            # "I work at Acme and I hate cilantro": one fact per clause
            value = re.split(r"\s+(?:and|but|so|because|although)\s+(?:i|i'm|my)\b", value, flags=re.IGNORECASE)[0]
            out.append(template.format(value.strip().rstrip(" .")))
    return out


_EXTRACT_PROMPT = """You maintain long-term memory about a user of an assistant. From the conversation turn below, list
facts about THE USER worth remembering in future conversations: stable preferences, profile, constraints, goals,
how they like answers. Not: the question itself, one-off details, anything about the assistant, secrets, passwords,
payment details or other sensitive data. Each fact one short third-person sentence ("Prefers metric units").
Skip facts already known. Answer with a JSON array of strings only; [] when there is nothing new.

Already known:
{known}

User: {user}
Assistant: {assistant}"""


def _parse_facts(raw: str) -> Optional[List[str]]:
    m = re.search(r"\[.*\]", raw or "", flags=re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return [str(x) for x in data if isinstance(x, (str, int, float)) and str(x).strip()][:10] \
        if isinstance(data, list) else None


async def model_facts(cfg: Any, user_text: str, assistant_text: str, known: List[str]) -> Optional[List[str]]:
    """Facts read by a model, or None when it can't be asked (no key) or answers nonsense."""
    import llm
    try:
        completion = await llm.complete(llm.request_from_config(
            cfg, [{"role": "user", "content": _EXTRACT_PROMPT.format(
                known="\n".join(f"- {k}" for k in known) or "(nothing yet)",
                user=user_text[:4000], assistant=assistant_text[:2000])}],
            temperature=0.0, max_tokens=400, timeout_s=max(1, int(cfg.timeout_ms or 45000)) / 1000.0))
    except Exception as e:  # noqa: BLE001 — any failure falls back to the rules
        logger.warning(f"Long-term memory extraction with {cfg.provider}/{cfg.model} failed: {e}")
        return None
    return _parse_facts(completion.text)


def _storable_key(key: Optional[str]) -> Optional[str]:
    """Only references and sealed values go into a job row; never a key typed in the browser."""
    from services import secret_store
    return key if key and (secret_store.is_ref(key) or secret_store.is_sealed(key)) else None


def queue_extraction(who: Who, cfg: Any, app_id: Optional[str], user_text: str, assistant_text: str,
                     node_api_key: Optional[str] = None) -> Optional[str]:
    """Queue the memory.extract job for one finished turn. Never raises."""
    try:
        return jobs.enqueue(JOB_KIND, {
            "tenant_id": who.tenant_id, "project_id": who.project_id, "user": who.user, "app_id": app_id,
            "user_text": user_text[:4000], "assistant_text": assistant_text[:2000],
            "provider": cfg.provider, "model": cfg.model, "base_url": getattr(cfg, "base_url", None),
            "api_key": _storable_key(node_api_key),
        }, tenant_id=who.tenant_id, project_id=who.project_id, max_attempts=2)
    except Exception:
        logger.exception("Queueing long-term memory extraction failed")
        return None


@jobs.handler(JOB_KIND)
async def _extract_job(payload: Dict[str, Any], job: jobs.Job) -> None:
    from models import LLMConfig
    from routers.v1 import _provider_keys
    from services.pipeline_runner import RunScope, current_scope

    who = Who(payload["tenant_id"], payload["project_id"], payload["user"])
    if not who.user or not enabled(who.tenant_id):
        return   # turned off since
    known = [f["content"] for f in list_facts(who.tenant_id, who.project_id, who.user)]
    facts: Optional[List[str]] = None
    provider = payload.get("provider") or "mock"
    if provider != "mock":
        scope = RunScope(tenant_id=who.tenant_id, project_id=who.project_id, user_id="system",
                         provider_keys=_provider_keys({}, (who.tenant_id, who.project_id)))
        token = current_scope.set(scope)
        try:
            key = payload.get("api_key") or (scope.provider_keys or {}).get(provider.lower(), "")
            cfg = LLMConfig(provider=provider, model=payload.get("model") or "", api_key=key,
                            base_url=payload.get("base_url"), temperature=0.0, max_tokens=400)
            facts = await model_facts(cfg, payload["user_text"], payload["assistant_text"], known)
        finally:
            current_scope.reset(token)
    if facts is None:
        facts = rule_facts(payload["user_text"])
    stored = await asyncio.to_thread(add_facts, who, facts, payload.get("app_id"))
    if stored:
        logger.info(f"Long-term memory: {len(stored)} new fact(s) for a user in {who.tenant_id}/{who.project_id}")
