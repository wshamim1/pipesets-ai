import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import APIRouter

from db import get_db_connection, upsert

router = APIRouter(prefix="/api/cache", tags=["cache"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_cache_key(prompt: str, cfg, scope: str) -> str:
    """Stable hash key: scope + prompt + optional model/config fields."""
    base = prompt.strip()
    if scope == "strict":
        base += f"|{cfg.model}|{cfg.temperature}|{cfg.top_p}|{cfg.max_tokens}"
    elif scope == "model":
        base += f"|{cfg.model}"
    return hashlib.sha256(f"{scope}:{base}".encode()).hexdigest()


def cache_get(conn, cache_key: str) -> Optional[Dict[str, Any]]:
    now = datetime.utcnow().isoformat()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT output, model, provider, hit_count FROM cache_entries WHERE cache_key = ? AND expires_at > ?",
        (cache_key, now),
    )
    row = cursor.fetchone()
    if row:
        conn.execute(
            "UPDATE cache_entries SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (cache_key,),
        )
        conn.commit()
        return {
            "output": row["output"],
            "model": row["model"],
            "provider": row["provider"],
            "hit_count": row["hit_count"] + 1,
        }
    return None


def cache_set(conn, cache_key: str, scope: str, prompt: str, output: str, cfg, ttl_seconds: int) -> None:
    now = datetime.utcnow()
    expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
    prompt_hash = hashlib.sha256(prompt.strip().encode()).hexdigest()[:16]
    upsert(conn, "cache_entries", {
        "cache_key": cache_key, "scope": scope, "prompt_hash": prompt_hash, "output": output, "model": cfg.model,
        "provider": cfg.provider, "hit_count": 0, "created_at": now.isoformat(), "expires_at": expires_at,
    }, key=("cache_key",))
    conn.commit()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_cache_entries(limit: int = 50):
    conn = get_db_connection()
    now = datetime.utcnow().isoformat()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT cache_key, scope, model, provider, hit_count, created_at, expires_at,
                  substr(output, 1, 120) as output_preview
           FROM cache_entries WHERE expires_at > ?
           ORDER BY hit_count DESC, created_at DESC LIMIT ?""",
        (now, limit),
    )
    rows = cursor.fetchall()
    cursor.execute(
        "SELECT COUNT(*) as total, SUM(hit_count) as total_hits FROM cache_entries WHERE expires_at > ?",
        (now,),
    )
    stats = cursor.fetchone()
    conn.close()
    return {
        "entries": [dict(r) for r in rows],
        "stats": {"active_entries": stats["total"] or 0, "total_hits": stats["total_hits"] or 0},
    }


@router.delete("")
def clear_all_cache():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cache_entries")
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": True, "deleted": deleted}


@router.post("/evict_expired")
def evict_expired_cache():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cache_entries WHERE expires_at <= ?", (datetime.utcnow().isoformat(),))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": True, "evicted": deleted}


@router.delete("/{cache_key}")
def delete_cache_entry(cache_key: str):
    conn = get_db_connection()
    conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
    conn.commit()
    conn.close()
    return {"success": True, "cache_key": cache_key}
