"""
shared_state.py — state every replica must agree on: sliding-window counters (rate limits, login
lockouts) and expiring flags (cancel signals).

Backends (PIPESETS_SHARED_STATE)
--------------------------------
  memory     this process only. Right for one process (one-box installs, the desktop app); with
             several replicas each counts on its own, so N replicas allow N times a limit.
  database   rows in the app DB (``shared_hits``, ``shared_flags``; migration 0016). Needs nothing
             new beyond a shared DATABASE_URL. A few small writes per request.
  redis      REDIS_URL. Sorted sets per window and keys with a TTL; a limit check is one atomic
             script, so it never lets more through than the limit.
  auto       (default) redis when REDIS_URL is set, else memory.

Windows
-------
``add(key, window_s, limit)`` records a hit and returns the window's count. With ``limit`` > 0 a
hit that would go past it is refused and not recorded (``Window.allowed`` False, ``retry_after``
set). ``peek`` counts without recording; ``reset`` forgets a key. On the database backend two
replicas checking at the same instant can both pass the last free slot; redis and memory can't.

Flags
-----
``set_flag(name, ttl_s)`` / ``has_flag(name)`` / ``clear_flag(name)``: a name that exists until it
expires, e.g. ``cancel:job:<id>`` while a cancel is pending.

Old database rows are purged by a periodic loop (``shared_state.purge``, hourly).
"""

import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional

from db import IntegrityError, get_db_connection
from services import jobs

logger = logging.getLogger("pipesets-ai-backend")

MAX_WINDOW_SECONDS = 24 * 3600   # longest window any caller uses; older database rows are purged
MEMORY_KEYS_MAX = 10_000         # a flood of fresh keys (session ids, emails) can't grow memory past this


@dataclass
class Window:
    allowed: bool
    count: int                    # hits in the window, including this one when it was recorded
    retry_after: Optional[int]    # seconds until a slot frees, when at or over the limit


def _window(count: int, oldest: Optional[float], window_s: float, limit: int, allowed: bool, now: float) -> Window:
    full = limit > 0 and count >= limit
    retry = max(1, int((oldest or now) + window_s - now) + 1) if (full or not allowed) else None
    return Window(allowed=allowed, count=count, retry_after=retry)


# ── Memory ────────────────────────────────────────────────────────────────────

class MemoryStore:
    name = "memory"

    def __init__(self):
        self._hits: "OrderedDict[str, List[float]]" = OrderedDict()   # least recently used first
        self._flags: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _live(self, key: str, cutoff: float) -> List[float]:
        hits = [t for t in self._hits.pop(key, []) if t > cutoff]
        self._hits[key] = hits
        while len(self._hits) > MEMORY_KEYS_MAX:
            self._hits.popitem(last=False)
        return hits

    def add(self, key: str, window_s: float, limit: int = 0) -> Window:
        now = time.time()
        with self._lock:
            hits = self._live(key, now - window_s)
            if limit > 0 and len(hits) >= limit:
                return _window(len(hits), hits[0], window_s, limit, False, now)
            hits.append(now)
            return _window(len(hits), hits[0], window_s, limit, True, now)

    def peek(self, key: str, window_s: float, limit: int = 0) -> Window:
        now = time.time()
        with self._lock:
            hits = self._live(key, now - window_s)
            return _window(len(hits), hits[0] if hits else None, window_s, limit, True, now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def set_flag(self, name: str, ttl_s: float) -> None:
        with self._lock:
            self._flags[name] = time.time() + ttl_s

    def has_flag(self, name: str) -> bool:
        with self._lock:
            expires = self._flags.get(name)
            if expires is not None and expires <= time.time():
                del self._flags[name]
                return False
            return expires is not None

    def clear_flag(self, name: str) -> None:
        with self._lock:
            self._flags.pop(name, None)

    def purge(self) -> None:
        now = time.time()
        with self._lock:
            for name in [n for n, exp in self._flags.items() if exp <= now]:
                del self._flags[name]

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
            self._flags.clear()


# ── Database ──────────────────────────────────────────────────────────────────

class DatabaseStore:
    name = "database"

    def _count(self, conn, key: str, cutoff: float):
        row = conn.execute("SELECT COUNT(*) AS n, MIN(at) AS oldest FROM shared_hits WHERE bucket = ? AND at > ?",
                           (key, cutoff)).fetchone()
        return int(row["n"]), row["oldest"]

    def add(self, key: str, window_s: float, limit: int = 0) -> Window:
        now = time.time()
        conn = get_db_connection()
        try:
            n, oldest = self._count(conn, key, now - window_s)
            if limit > 0 and n >= limit:
                return _window(n, oldest, window_s, limit, False, now)
            conn.execute("INSERT INTO shared_hits (bucket, at) VALUES (?, ?)", (key, now))
            conn.commit()
            return _window(n + 1, oldest or now, window_s, limit, True, now)
        finally:
            conn.close()

    def peek(self, key: str, window_s: float, limit: int = 0) -> Window:
        now = time.time()
        conn = get_db_connection()
        try:
            n, oldest = self._count(conn, key, now - window_s)
        finally:
            conn.close()
        return _window(n, oldest, window_s, limit, True, now)

    def reset(self, key: str) -> None:
        self._exec("DELETE FROM shared_hits WHERE bucket = ?", (key,))

    def set_flag(self, name: str, ttl_s: float) -> None:
        expires = time.time() + ttl_s
        conn = get_db_connection()
        try:
            if conn.execute("UPDATE shared_flags SET expires_at = ? WHERE name = ?", (expires, name)).rowcount == 0:
                try:
                    conn.execute("INSERT INTO shared_flags (name, expires_at) VALUES (?, ?)", (name, expires))
                except IntegrityError:   # set by another process meanwhile
                    conn.rollback()
                    conn.execute("UPDATE shared_flags SET expires_at = ? WHERE name = ?", (expires, name))
            conn.commit()
        finally:
            conn.close()

    def has_flag(self, name: str) -> bool:
        conn = get_db_connection()
        try:
            return conn.execute("SELECT 1 FROM shared_flags WHERE name = ? AND expires_at > ?",
                                (name, time.time())).fetchone() is not None
        finally:
            conn.close()

    def clear_flag(self, name: str) -> None:
        self._exec("DELETE FROM shared_flags WHERE name = ?", (name,))

    def purge(self) -> None:
        now = time.time()
        self._exec("DELETE FROM shared_hits WHERE at < ?", (now - MAX_WINDOW_SECONDS,))
        self._exec("DELETE FROM shared_flags WHERE expires_at < ?", (now,))

    def clear(self) -> None:
        self._exec("DELETE FROM shared_hits", ())
        self._exec("DELETE FROM shared_flags", ())

    @staticmethod
    def _exec(sql: str, params: tuple) -> None:
        conn = get_db_connection()
        try:
            conn.execute(sql, params)
            conn.commit()
        finally:
            conn.close()


# ── Redis ─────────────────────────────────────────────────────────────────────

# KEYS[1] window key. ARGV: now, window_s, limit (0 = none), member, record (1/0).
# Returns {count, oldest score, allowed}.
_ADD_SCRIPT = """
local now, window, limit = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local n = redis.call('ZCARD', KEYS[1])
local allowed = 1
if ARGV[5] == '1' then
  if limit > 0 and n >= limit then
    allowed = 0
  else
    redis.call('ZADD', KEYS[1], now, ARGV[4])
    redis.call('PEXPIRE', KEYS[1], math.ceil(window * 1000))
    n = n + 1
  end
end
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
return {n, oldest[2] or false, allowed}
"""


class RedisStore:
    name = "redis"

    def __init__(self, url: str, prefix: str = "pipesets:"):
        import redis   # only needed with this backend
        self._r = redis.Redis.from_url(url, socket_timeout=5, socket_connect_timeout=5)
        self._add = self._r.register_script(_ADD_SCRIPT)
        self._prefix = prefix

    def _k(self, key: str) -> str:
        return self._prefix + key

    def _run(self, key: str, window_s: float, limit: int, record: bool) -> Window:
        now = time.time()
        n, oldest, allowed = self._add(keys=[self._k(f"w:{key}")],
                                       args=[now, window_s, limit, f"{now}:{uuid.uuid4().hex[:8]}", int(record)])
        return _window(int(n), float(oldest) if oldest else None, window_s, limit, bool(allowed), now)

    def add(self, key: str, window_s: float, limit: int = 0) -> Window:
        return self._run(key, window_s, limit, True)

    def peek(self, key: str, window_s: float, limit: int = 0) -> Window:
        return self._run(key, window_s, limit, False)

    def reset(self, key: str) -> None:
        self._r.delete(self._k(f"w:{key}"))

    def set_flag(self, name: str, ttl_s: float) -> None:
        self._r.set(self._k(f"f:{name}"), "1", px=max(1, int(ttl_s * 1000)))

    def has_flag(self, name: str) -> bool:
        return bool(self._r.exists(self._k(f"f:{name}")))

    def clear_flag(self, name: str) -> None:
        self._r.delete(self._k(f"f:{name}"))

    def purge(self) -> None:
        pass   # keys expire on their own

    def clear(self) -> None:
        for k in self._r.scan_iter(match=self._prefix + "*"):
            self._r.delete(k)


# ── Selection ─────────────────────────────────────────────────────────────────

_store = None
_store_lock = threading.Lock()


def backend_name() -> str:
    mode = os.getenv("PIPESETS_SHARED_STATE", "auto").strip().lower()
    if mode == "auto":
        return "redis" if os.getenv("REDIS_URL") else "memory"
    if mode not in ("memory", "database", "redis"):
        raise ValueError(f"PIPESETS_SHARED_STATE={mode!r}: use auto, memory, database or redis")
    return mode


def store():
    """The configured store, created on first use."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                name = backend_name()
                if name == "redis":
                    url = os.getenv("REDIS_URL")
                    if not url:
                        raise ValueError("PIPESETS_SHARED_STATE=redis needs REDIS_URL")
                    _store = RedisStore(url)
                else:
                    _store = DatabaseStore() if name == "database" else MemoryStore()
                logger.info(f"Shared state: {name}")
    return _store


def use(new_store) -> None:
    """Swap the store (tests); None goes back to the configured one on next use."""
    global _store
    _store = new_store


def add(key: str, window_s: float, limit: int = 0) -> Window:
    return store().add(key, window_s, limit)


def peek(key: str, window_s: float, limit: int = 0) -> Window:
    return store().peek(key, window_s, limit)


def reset(key: str) -> None:
    store().reset(key)


def set_flag(name: str, ttl_s: float) -> None:
    store().set_flag(name, ttl_s)


def has_flag(name: str) -> bool:
    return store().has_flag(name)


def clear_flag(name: str) -> None:
    store().clear_flag(name)


@jobs.periodic("shared_state.purge", 3600)
async def _purge() -> None:
    import asyncio
    await asyncio.to_thread(store().purge)
