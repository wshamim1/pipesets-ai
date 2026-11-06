"""
Vector store backends for RAG collections.

A collection lives in exactly one backend, recorded in the `rag_collections`
registry (app SQLite DB) when it is written. Readers — the retrieval endpoint
and the LLM runner — only know the collection name, so they look the backend
up here instead of threading store config through every node.

Backends
--------
local     Chunks as JSON in the app DB's `rag_chunks` table; brute-force cosine
          in Python. Zero setup, fine up to a few thousand chunks.
          "chroma" is accepted as a legacy alias: earlier versions offered it in
          the UI but always wrote here.
pgvector  One Postgres table per collection with a fixed-dimension `vector`
          column and an HNSW cosine index. The DSN comes from the Vector Store
          node, falling back to the PGVECTOR_URL env var.

Every backend returns search hits as chunk dicts with `chunk_id`, `content`,
`embedding`, `source`, `metadata` and `_sim` (cosine similarity), best first.
"""

import hashlib
import json
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from db import get_db_connection, upsert as db_upsert

SUPPORTED_STORES = ("local", "pgvector")
_ALIASES = {"": "local", "chroma": "local"}

# pgvector's HNSW index supports up to 2000 dimensions for the `vector` type;
# bigger embeddings (e.g. text-embedding-3-large, 3072) fall back to exact scan.
_HNSW_MAX_DIM = 2000


class VectorStoreError(Exception):
    """Misconfiguration or backend failure, safe to show to the user."""


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def normalize_store_type(store_type: Optional[str]) -> str:
    st = (store_type or "").strip().lower()
    st = _ALIASES.get(st, st)
    if st not in SUPPORTED_STORES:
        raise VectorStoreError(
            f"Vector store '{store_type}' is not supported yet. Use one of: {', '.join(SUPPORTED_STORES)}."
        )
    return st


# ── Local (SQLite) ────────────────────────────────────────────────────────────

class LocalStore:
    name = "local"

    @staticmethod
    def _ensure_table(conn) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                chunk_id    TEXT PRIMARY KEY,
                collection  TEXT NOT NULL,
                content     TEXT NOT NULL,
                embedding   TEXT NOT NULL,
                source      TEXT NOT NULL DEFAULT '',
                metadata    TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_collection ON rag_chunks (collection)")

    def upsert(self, collection: str, chunks: List[Dict[str, Any]]) -> int:
        conn = get_db_connection()
        self._ensure_table(conn)
        db_upsert(
            conn, "rag_chunks",
            [
                {"chunk_id": ch["chunk_id"], "collection": collection, "content": ch["content"],
                 "embedding": json.dumps(ch["embedding"]), "source": ch.get("source", ""),
                 "metadata": json.dumps(ch.get("metadata", {}))}
                for ch in chunks
            ],
            key=("chunk_id",),
        )
        conn.commit()
        conn.close()
        return len(chunks)

    def search(self, collection: str, query_emb: List[float], k: int) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        self._ensure_table(conn)
        rows = conn.execute(
            "SELECT chunk_id, content, embedding, source, metadata FROM rag_chunks WHERE collection = ?",
            (collection,),
        ).fetchall()
        conn.close()
        hits = []
        for r in rows:
            emb = json.loads(r["embedding"])
            # A collection can hold chunks from different embedding models; cosine
            # across mismatched dimensions is meaningless, so skip them.
            if len(emb) != len(query_emb):
                continue
            hits.append({
                "chunk_id": r["chunk_id"],
                "content": r["content"],
                "embedding": emb,
                "source": r["source"],
                "metadata": json.loads(r["metadata"]),
                "_sim": cosine_similarity(query_emb, emb),
            })
        hits.sort(key=lambda h: h["_sim"], reverse=True)
        return hits[:k]

    def count(self, collection: str) -> int:
        conn = get_db_connection()
        self._ensure_table(conn)
        n = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE collection = ?", (collection,)).fetchone()[0]
        conn.close()
        return n

    def drop(self, collection: str) -> None:
        conn = get_db_connection()
        self._ensure_table(conn)
        conn.execute("DELETE FROM rag_chunks WHERE collection = ?", (collection,))
        conn.commit()
        conn.close()

    def collection_counts(self) -> Dict[str, int]:
        conn = get_db_connection()
        self._ensure_table(conn)
        rows = conn.execute("SELECT collection, COUNT(*) AS n FROM rag_chunks GROUP BY collection").fetchall()
        conn.close()
        return {r["collection"]: r["n"] for r in rows}


# ── pgvector ──────────────────────────────────────────────────────────────────

def _vec_literal(emb: List[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in emb) + "]"


class PgVectorStore:
    name = "pgvector"

    def __init__(self, dsn: str = ""):
        self.dsn = dsn or os.environ.get("PGVECTOR_URL", "")
        if not self.dsn:
            raise VectorStoreError(
                "pgvector needs a Postgres connection string — set it on the Vector Store node "
                "or in the PGVECTOR_URL environment variable."
            )

    @staticmethod
    def _table(collection: str) -> str:
        # Collection names are free text; hash them into a safe identifier.
        return "pipesets_rag_" + hashlib.sha1(collection.encode()).hexdigest()[:20]

    def _run(self, fn):
        """Open a connection, ensure the schema, run fn(cursor) in one transaction."""
        try:
            import psycopg2
        except ImportError:
            raise VectorStoreError("psycopg2 is not installed. Run: pip install psycopg2-binary")
        try:
            conn = psycopg2.connect(self.dsn, connect_timeout=10)
        except psycopg2.Error as e:
            raise VectorStoreError(f"Could not connect to pgvector database: {str(e).strip()}")
        try:
            with conn, conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS pipesets_rag_collections (
                        collection  TEXT PRIMARY KEY,
                        table_name  TEXT NOT NULL,
                        dim         INTEGER NOT NULL
                    )
                """)
                return fn(cur)
        except psycopg2.Error as e:
            raise VectorStoreError(f"pgvector error: {str(e).strip()}")
        finally:
            conn.close()

    @staticmethod
    def _dim(cur, collection: str) -> Optional[int]:
        cur.execute("SELECT dim FROM pipesets_rag_collections WHERE collection = %s", (collection,))
        row = cur.fetchone()
        return row[0] if row else None

    def upsert(self, collection: str, chunks: List[Dict[str, Any]]) -> int:
        if not chunks:
            return 0
        dim = len(chunks[0]["embedding"])
        if any(len(ch["embedding"]) != dim for ch in chunks):
            raise VectorStoreError("All chunks in one ingest must have the same embedding dimension.")
        table = self._table(collection)

        def op(cur):
            from psycopg2.extras import Json, execute_values
            existing = self._dim(cur, collection)
            if existing is not None and existing != dim:
                raise VectorStoreError(
                    f"Collection '{collection}' holds {existing}-dimension vectors but these are {dim}-dimension "
                    "(a different embedding model). Drop the collection and re-ingest."
                )
            if existing is None:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        chunk_id   TEXT PRIMARY KEY,
                        content    TEXT NOT NULL,
                        embedding  vector({dim}) NOT NULL,
                        source     TEXT NOT NULL DEFAULT '',
                        metadata   JSONB NOT NULL DEFAULT '{{}}'
                    )
                """)
                if dim <= _HNSW_MAX_DIM:
                    cur.execute(f"CREATE INDEX IF NOT EXISTS {table}_hnsw ON {table} USING hnsw (embedding vector_cosine_ops)")
                cur.execute(
                    "INSERT INTO pipesets_rag_collections (collection, table_name, dim) VALUES (%s, %s, %s)",
                    (collection, table, dim),
                )
            execute_values(
                cur,
                f"INSERT INTO {table} (chunk_id, content, embedding, source, metadata) VALUES %s "
                "ON CONFLICT (chunk_id) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding, "
                "source = EXCLUDED.source, metadata = EXCLUDED.metadata",
                [
                    (ch["chunk_id"], ch["content"], _vec_literal(ch["embedding"]),
                     ch.get("source", ""), Json(ch.get("metadata", {})))
                    for ch in chunks
                ],
                template="(%s, %s, %s::vector, %s, %s)",
            )
            return len(chunks)

        return self._run(op)

    def search(self, collection: str, query_emb: List[float], k: int) -> List[Dict[str, Any]]:
        table = self._table(collection)

        def op(cur):
            if self._dim(cur, collection) != len(query_emb):
                return []  # missing collection, or a different embedding model
            # HNSW returns at most ef_search rows; raise it so large k still fills.
            cur.execute(f"SET LOCAL hnsw.ef_search = {min(max(int(k), 40), 1000)}")
            q = _vec_literal(query_emb)
            cur.execute(
                f"SELECT chunk_id, content, embedding::text, source, metadata, 1 - (embedding <=> %s::vector) "
                f"FROM {table} ORDER BY embedding <=> %s::vector LIMIT %s",
                (q, q, int(k)),
            )
            return [
                {
                    "chunk_id": r[0],
                    "content": r[1],
                    "embedding": json.loads(r[2]),
                    "source": r[3],
                    "metadata": r[4] or {},
                    "_sim": float(r[5]),
                }
                for r in cur.fetchall()
            ]

        return self._run(op)

    def count(self, collection: str) -> int:
        def op(cur):
            if self._dim(cur, collection) is None:
                return 0
            cur.execute(f"SELECT COUNT(*) FROM {self._table(collection)}")
            return cur.fetchone()[0]

        return self._run(op)

    def drop(self, collection: str) -> None:
        def op(cur):
            cur.execute(f"DROP TABLE IF EXISTS {self._table(collection)}")
            cur.execute("DELETE FROM pipesets_rag_collections WHERE collection = %s", (collection,))

        self._run(op)


# ── Registry ──────────────────────────────────────────────────────────────────

def _ensure_registry(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_collections (
            collection  TEXT PRIMARY KEY,
            store_type  TEXT NOT NULL,
            dsn         TEXT NOT NULL DEFAULT '',
            updated_at  TEXT NOT NULL
        )
    """)


def _lookup(collection: str) -> Tuple[str, str]:
    conn = get_db_connection()
    _ensure_registry(conn)
    row = conn.execute(
        "SELECT store_type, dsn FROM rag_collections WHERE collection = ?", (collection,)
    ).fetchone()
    conn.close()
    return (row["store_type"], row["dsn"]) if row else ("local", "")


def _register(collection: str, store_type: str, dsn: str) -> None:
    conn = get_db_connection()
    _ensure_registry(conn)
    db_upsert(conn, "rag_collections", {"collection": collection, "store_type": store_type, "dsn": dsn,
                                        "updated_at": datetime.utcnow().isoformat()}, key=("collection",))
    conn.commit()
    conn.close()


def _unregister(collection: str) -> None:
    conn = get_db_connection()
    _ensure_registry(conn)
    conn.execute("DELETE FROM rag_collections WHERE collection = ?", (collection,))
    conn.commit()
    conn.close()


def get_store(store_type: str, dsn: str = ""):
    st = normalize_store_type(store_type)
    return PgVectorStore(dsn) if st == "pgvector" else LocalStore()


def store_for(collection: str):
    """The backend a collection was written to (local if it was never registered)."""
    return get_store(*_lookup(collection))


def write_chunks(collection: str, chunks: List[Dict[str, Any]], store_type: str = "local", dsn: str = "") -> int:
    """Store chunks in the given backend and record it as the collection's home."""
    st = normalize_store_type(store_type)
    target = get_store(st, dsn)
    prev_type, prev_dsn = _lookup(collection)
    if (prev_type, prev_dsn) != (st, dsn):
        # Switching backends: the old copy would be unreachable, so remove it.
        try:
            get_store(prev_type, prev_dsn).drop(collection)
        except VectorStoreError:
            pass
    n = target.upsert(collection, chunks)
    _register(collection, st, dsn)
    return n


def drop_collection(collection: str) -> None:
    store_for(collection).drop(collection)
    _unregister(collection)


def list_collections() -> List[Dict[str, Any]]:
    out = {name: {"collection": name, "chunk_count": n, "store_type": "local"}
           for name, n in LocalStore().collection_counts().items()}
    conn = get_db_connection()
    _ensure_registry(conn)
    rows = conn.execute("SELECT collection, store_type, dsn FROM rag_collections WHERE store_type != 'local'").fetchall()
    conn.close()
    for r in rows:
        try:
            n: Optional[int] = get_store(r["store_type"], r["dsn"]).count(r["collection"])
        except VectorStoreError:
            n = None  # backend unreachable — still list it
        out[r["collection"]] = {"collection": r["collection"], "chunk_count": n, "store_type": r["store_type"]}
    return sorted(out.values(), key=lambda c: c["collection"])
