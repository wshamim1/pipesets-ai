"""
knowledge_base.py — Unified Knowledge Base management.

Provides:
- Create Knowledge Base from raw text, file upload, or web URL
- Automatic chunking (recursive splitter) and embedding generation
- Querying knowledge bases via semantic similarity search
- Knowledge Base list, detail, and delete operations

Endpoints:
- GET    /api/knowledge-bases          — List all knowledge bases with chunk counts
- POST   /api/knowledge-bases          — Create and index knowledge base from text/URL
- POST   /api/knowledge-bases/upload   — Create and index knowledge base from uploaded file
- GET    /api/knowledge-bases/{id}     — Get details of a single knowledge base
- DELETE /api/knowledge-bases/{id}     — Delete knowledge base and its indexed chunks
- POST   /api/knowledge-bases/{id}/query — Query specific knowledge base
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from db import get_db_connection
from routers.retrieval import (
    embed_texts,
    ensure_table,
    query as query_rag_endpoint,
    save_chunks,
    split_text,
    QueryRequest,
)

logger = logging.getLogger("pipesets-ai-backend")

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-base"])


# ── Models ────────────────────────────────────────────────────────────────────

class KnowledgeBaseCreate(BaseModel):
    name: str
    icon: str = "📚"
    description: str = ""
    source_type: str = "text"  # text | web_url
    content: str = ""
    url: str = ""
    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    api_key: str = ""
    chunk_size: int = 500
    chunk_overlap: int = 50


class KnowledgeBaseQueryRequest(BaseModel):
    query: str
    top_k: int = 4
    score_threshold: float = 0.0
    api_key: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> Dict[str, Any]:
    return dict(row)


def _get_kb(kb_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
def list_knowledge_bases():
    """List all knowledge bases."""
    ensure_table()
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM knowledge_bases ORDER BY created_at DESC").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


@router.post("")
async def create_knowledge_base(req: KnowledgeBaseCreate):
    """Create a knowledge base from text or URL."""
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()

    raw_text = req.content
    source_detail = "Raw text"

    if req.source_type == "web_url":
        source_detail = req.url
        if not req.url:
            raise HTTPException(status_code=400, detail="URL is required for web_url source.")
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(req.url, headers={"User-Agent": "Mozilla/5.0"})
                raw_text = resp.text
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {e}")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="No content provided to index.")

    # 1. Split into chunks
    text_chunks = split_text(raw_text, "recursive_character", req.chunk_size, req.chunk_overlap)
    if not text_chunks:
        raise HTTPException(status_code=400, detail="Could not extract chunks from content.")

    # 2. Generate embeddings
    embeddings = await embed_texts(
        text_chunks,
        provider=req.embedding_provider,
        model=req.embedding_model,
        api_key=req.api_key,
    )

    # 3. Store in vector index (rag_chunks)
    chunk_records = [
        {
            "chunk_id": f"{kb_id}-{i:04d}",
            "content": chunk_text,
            "embedding": emb,
            "source": source_detail,
            "metadata": {"kb_id": kb_id, "chunk_index": i},
        }
        for i, (chunk_text, emb) in enumerate(zip(text_chunks, embeddings))
    ]

    saved_count = save_chunks(collection=kb_id, chunks=chunk_records)

    # 4. Save metadata to knowledge_bases table
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO knowledge_bases
        (id, name, icon, description, source_type, source_detail, embedding_provider, embedding_model, chunk_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kb_id,
            req.name,
            req.icon,
            req.description,
            req.source_type,
            source_detail,
            req.embedding_provider,
            req.embedding_model,
            saved_count,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    return _get_kb(kb_id)


@router.post("/upload")
async def upload_and_create_knowledge_base(
    name: str = Form(...),
    icon: str = Form("📚"),
    description: str = Form(""),
    embedding_provider: str = Form("local"),
    embedding_model: str = Form("sentence-transformers/all-MiniLM-L6-v2"),
    api_key: str = Form(""),
    chunk_size: int = Form(500),
    chunk_overlap: int = Form(50),
    file: UploadFile = File(...),
):
    """Create a knowledge base from an uploaded file (PDF, TXT, MD, JSON)."""
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()
    filename = file.filename or "uploaded_file"

    content_bytes = await file.read()
    raw_text = ""

    if filename.lower().endswith(".pdf"):
        try:
            import io
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content_bytes))
            raw_text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            raw_text = content_bytes.decode("utf-8", errors="replace")
    else:
        raw_text = content_bytes.decode("utf-8", errors="replace")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Uploaded file contains no readable text.")

    text_chunks = split_text(raw_text, "recursive_character", chunk_size, chunk_overlap)
    embeddings = await embed_texts(
        text_chunks,
        provider=embedding_provider,
        model=embedding_model,
        api_key=api_key,
    )

    chunk_records = [
        {
            "chunk_id": f"{kb_id}-{i:04d}",
            "content": chunk_text,
            "embedding": emb,
            "source": filename,
            "metadata": {"kb_id": kb_id, "chunk_index": i},
        }
        for i, (chunk_text, emb) in enumerate(zip(text_chunks, embeddings))
    ]

    saved_count = save_chunks(collection=kb_id, chunks=chunk_records)

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO knowledge_bases
        (id, name, icon, description, source_type, source_detail, embedding_provider, embedding_model, chunk_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            kb_id,
            name,
            icon,
            description,
            "file",
            filename,
            embedding_provider,
            embedding_model,
            saved_count,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    return _get_kb(kb_id)


@router.get("/{kb_id}")
def get_knowledge_base(kb_id: str):
    """Get single knowledge base metadata."""
    kb = _get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.delete("/{kb_id}")
def delete_knowledge_base(kb_id: str):
    """Delete knowledge base and clear its vector index."""
    ensure_table()
    conn = get_db_connection()
    conn.execute("DELETE FROM rag_chunks WHERE collection = ?", (kb_id,))
    cur = conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return {"deleted": True, "id": kb_id}


@router.post("/{kb_id}/query")
async def query_knowledge_base(kb_id: str, req: KnowledgeBaseQueryRequest):
    """Run semantic similarity search against this specific knowledge base."""
    kb = _get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    q_req = QueryRequest(
        collection=kb_id,
        query=req.query,
        top_k=req.top_k,
        score_threshold=req.score_threshold,
        embedding_provider=kb.get("embedding_provider", "local"),
        embedding_model=kb.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2"),
        embedding_api_key=req.api_key,
    )
    res = await query_rag_endpoint(q_req)

    return {
        "kb_id": kb_id,
        "name": kb.get("name"),
        "query": req.query,
        "results": res.get("results", []),
        "count": len(res.get("results", [])),
    }
