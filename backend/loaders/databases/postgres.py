"""Postgres — document loader `postgres`."""

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

from loaders.base import Document, LoaderError, LoaderSpec, document
from loaders.databases._sql import _fetch_postgres_records

LOADER = LoaderSpec(
    type="postgres",
    label="Postgres",
    icon="🐘",
    category="Databases",
    desc="Query rows from a Postgres table as documents",
    source_label="Connection String",
    placeholder="postgresql://user:pass@localhost:5432/db",
    uses_connection=True,
    aliases=("postgresql", "pg"),
    order=10,
)


async def load(source: str, cfg: Dict[str, Any]) -> List[Document]:
    """One document per row; credentials from the linked Connection node (or a DSN in the source)."""
    conn = cfg.get("connection") or {}
    req = SimpleNamespace(
        connection_string=source if "://" in source else (conn.get("connection_string") or None),
        host=conn.get("host") or "localhost", port=conn.get("port") or None,
        database=conn.get("database") or conn.get("path") or (None),
        user=conn.get("user") or None, password=conn.get("password") or None,
        table=cfg.get("db_table") or None, query=cfg.get("db_query") or None,
        max_rows=int(cfg.get("max_rows", 1000)),
    )
    try:
        tables, texts = await asyncio.to_thread(_fetch_postgres_records, req)
    except Exception as e:
        raise LoaderError(f"Postgres error: {e}")
    if not texts:
        raise LoaderError("The query returned no rows.")
    return [document(t, source="Postgres", tables=", ".join(tables)) for t in texts]
