"""
retrieval.py — RAG pipeline endpoints.

Endpoints
---------
POST /api/retrieval/ingest   — Load, split, embed, and store document chunks.
POST /api/retrieval/query    — Similarity search over stored chunks.
GET  /api/retrieval/collections — List all collections with chunk counts.
DELETE /api/retrieval/collections/{collection} — Drop a collection.

Storage
-------
Each collection lives in one vector store backend — "local" (SQLite, the
default) or "pgvector" — chosen at ingest time via `store_type`. See
services/vector_store.py.

Embeddings
----------
- OpenAI: calls /v1/embeddings via httpx (requires api_key).
- Local:  uses sentence-transformers if installed; otherwise falls back to a
          random unit-vector stub so the UI still works without heavy deps.

Splitting
---------
Pure-Python recursive character splitter — no langchain required.
"""

import json
import os
import math
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel, Field

from db import get_db_connection
from services import secret_store
import loaders as doc_loaders
from loaders.base import LoaderError
from loaders.databases._sql import _fetch_mysql_records, _fetch_postgres_records, _fetch_sqlite_records
from services.llm_auth import resolve_api_key
from services.vector_store import (
    LocalStore,
    VectorStoreError,
    cosine_similarity as _cosine_similarity,
    drop_collection as _drop_collection,
    list_collections as _list_collections,
    store_for,
    write_chunks,
)

router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])


# ── Storage ───────────────────────────────────────────────────────────────────
# Backends live in services/vector_store.py; these wrappers keep the names that
# knowledge_base.py imports.

def ensure_table() -> None:
    conn = get_db_connection()
    LocalStore._ensure_table(conn)
    conn.commit()
    conn.close()


def save_chunks(collection: str, chunks: List[Dict[str, Any]], store_type: str = "local", dsn: str = "") -> int:
    try:
        return write_chunks(collection, chunks, store_type, dsn)
    except VectorStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Text splitting ─────────────────────────────────────────────────────────────

def _recursive_split(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Simple recursive character splitter — no external deps."""
    separators = ["\n\n", "\n", ". ", " ", ""]
    for sep in separators:
        if sep == "":
            # Base case: hard-split by character count
            chunks = []
            start = 0
            while start < len(text):
                end = min(start + chunk_size, len(text))
                chunks.append(text[start:end])
                start += chunk_size - chunk_overlap
            return [c for c in chunks if c.strip()]
        parts = text.split(sep)
        if len(parts) <= 1:
            continue
        # Merge short parts back up to chunk_size
        merged: List[str] = []
        current = ""
        for part in parts:
            candidate = (current + sep + part).strip() if current else part.strip()
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    merged.append(current)
                # If single part is too long, recurse
                if len(part) > chunk_size:
                    merged.extend(_recursive_split(part, chunk_size, chunk_overlap))
                    current = ""
                else:
                    current = part.strip()
        if current:
            merged.append(current)
        # Apply overlap by re-appending tail of previous chunk
        if chunk_overlap > 0:
            overlapped: List[str] = []
            for i, chunk in enumerate(merged):
                if i > 0:
                    prev_tail = merged[i - 1][-chunk_overlap:]
                    chunk = prev_tail + " " + chunk
                overlapped.append(chunk.strip())
            return [c for c in overlapped if c.strip()]
        return [c for c in merged if c.strip()]
    return [text]


def split_text(text: str, splitter_type: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    if splitter_type == "token":
        # Approximate: 1 token ≈ 4 chars
        cs = chunk_size * 4
        co = chunk_overlap * 4
        return _recursive_split(text, cs, co)
    elif splitter_type == "markdown":
        # Split on markdown headers first, then recurse
        parts = re.split(r"(?m)^(#{1,6} )", text)
        merged_parts: List[str] = []
        i = 0
        while i < len(parts):
            if re.match(r"^#{1,6} $", parts[i]) and i + 1 < len(parts):
                merged_parts.append(parts[i] + parts[i + 1])
                i += 2
            else:
                if parts[i].strip():
                    merged_parts.append(parts[i])
                i += 1
        chunks: List[str] = []
        for part in merged_parts:
            chunks.extend(_recursive_split(part, chunk_size, chunk_overlap))
        return chunks
    else:
        # recursive_character (default)
        return _recursive_split(text, chunk_size, chunk_overlap)


# ── Embedding ──────────────────────────────────────────────────────────────────

async def embed_texts_openai(texts: List[str], model: str, api_key: str) -> List[List[float]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]


async def embed_texts_cohere(texts: List[str], model: str, api_key: str) -> List[List[float]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.cohere.com/v1/embed",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "texts": texts, "input_type": "search_document"},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]


async def embed_texts_google(texts: List[str], model: str, api_key: str) -> List[List[float]]:
    """Google Generative Language embedding API."""
    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for text in texts:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent",
                params={"key": api_key},
                json={"model": f"models/{model}", "content": {"parts": [{"text": text}]}},
            )
            resp.raise_for_status()
            results.append(resp.json()["embedding"]["values"])
    return results


async def embed_texts_mistral(texts: List[str], model: str, api_key: str) -> List[List[float]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.mistral.ai/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": texts},
        )
        resp.raise_for_status()
        return [item["embedding"] for item in resp.json()["data"]]


async def embed_texts_voyage(texts: List[str], model: str, api_key: str) -> List[List[float]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": texts},
        )
        resp.raise_for_status()
        return [item["embedding"] for item in resp.json()["data"]]


async def embed_texts_nomic(texts: List[str], model: str, api_key: str) -> List[List[float]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api-atlas.nomic.ai/v1/embedding/text",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "texts": texts},
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]


def embed_texts_ollama(texts: List[str], model: str, base_url: str) -> List[List[float]]:
    """Synchronous Ollama embedding via the /api/embed endpoint."""
    import urllib.request, json as _json
    url = base_url.rstrip("/") + "/api/embed"
    results = []
    for text in texts:
        payload = _json.dumps({"model": model, "input": text}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            results.append(_json.loads(r.read())["embeddings"][0])
    return results


def embed_texts_llamacpp(texts: List[str], model: str, base_url: str) -> List[List[float]]:
    """Synchronous llama.cpp embedding via llama-server's OpenAI-compatible /v1/embeddings
    (the server must be started with --embeddings)."""
    import urllib.request, json as _json
    base = base_url.rstrip("/")
    url = base + ("/embeddings" if base.endswith("/v1") else "/v1/embeddings")
    payload = _json.dumps({"model": model, "input": texts}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = _json.loads(r.read())["data"]
    return [d["embedding"] for d in sorted(data, key=lambda d: d.get("index", 0))]


async def embed_texts_bedrock(texts: List[str], model: str, api_key: str) -> List[List[float]]:
    """AWS Bedrock embedding — requires boto3 and AWS credentials in env."""
    try:
        import boto3, json as _json
        client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        results = []
        for text in texts:
            body = _json.dumps({"inputText": text})
            resp = client.invoke_model(modelId=model, body=body, contentType="application/json", accept="application/json")
            results.append(_json.loads(resp["body"].read())["embedding"])
        return results
    except ImportError:
        raise RuntimeError("boto3 is required for AWS Bedrock embeddings. Run: pip install boto3")


def embed_texts_local(texts: List[str], model: str) -> List[List[float]]:
    try:
        from sentence_transformers import SentenceTransformer
        st_model = SentenceTransformer(model)
        return st_model.encode(texts, convert_to_numpy=True).tolist()
    except ImportError:
        # Stub: return random unit vectors (dim=384) so UI works without deps
        import random
        dim = 384
        embeddings = []
        for text in texts:
            # Deterministic-ish stub based on text hash
            seed = hash(text) % (2**31)
            r = random.Random(seed)
            vec = [r.gauss(0, 1) for _ in range(dim)]
            mag = math.sqrt(sum(v * v for v in vec)) or 1.0
            embeddings.append([v / mag for v in vec])
        return embeddings


async def embed_texts(
    texts: List[str],
    provider: str,
    model: str,
    api_key: str,
) -> List[List[float]]:
    """Route to the correct embedding backend by provider name."""
    p = provider.lower()
    if p not in ("ollama", "llamacpp"):  # for local servers the "key" field carries the base URL
        api_key = resolve_api_key({"azure_openai": "azure", "google": "gemini"}.get(p, p), api_key)
    if p == "openai" and api_key:
        return await embed_texts_openai(texts, model, api_key)
    if p == "azure_openai" and api_key:
        # Azure uses the same OpenAI embeddings API surface via langchain; here we use direct REST
        return await embed_texts_openai(texts, model, api_key)
    if p == "cohere" and api_key:
        return await embed_texts_cohere(texts, model, api_key)
    if p == "google" and api_key:
        return await embed_texts_google(texts, model, api_key)
    if p == "mistral" and api_key:
        return await embed_texts_mistral(texts, model, api_key)
    if p in ("voyage", "anthropic") and api_key:
        return await embed_texts_voyage(texts, model, api_key)
    if p == "nomic" and api_key:
        return await embed_texts_nomic(texts, model, api_key)
    if p == "bedrock":
        return await embed_texts_bedrock(texts, model, api_key)
    if p == "ollama":
        base = api_key or "http://localhost:11434"
        return embed_texts_ollama(texts, model, base)
    if p == "llamacpp":
        base = api_key or "http://localhost:8080"
        return embed_texts_llamacpp(texts, model, base)
    # fallback: local sentence-transformers / HuggingFace
    return embed_texts_local(texts, model)


# ── Request / Response models ──────────────────────────────────────────────────

class IngestRequest(BaseModel):
    text: Optional[str] = None
    collection: str = "default"
    source: str = ""
    splitter_type: str = "recursive_character"
    chunk_size: int = 512
    chunk_overlap: int = 50
    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_api_key: str = ""
    store_type: str = "local"           # local | pgvector
    vector_store_dsn: str = ""          # pgvector DSN (falls back to PGVECTOR_URL)


class DatabaseIngestRequest(BaseModel):
    db_type: str = "postgres"  # postgres | mysql | sqlite | sql_database
    connection_string: Optional[str] = None
    host: Optional[str] = "localhost"
    port: Optional[int] = None
    database: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    table: Optional[str] = None
    query: Optional[str] = None
    max_rows: int = 1000
    collection: str = "default"
    splitter_type: str = "recursive_character"
    chunk_size: int = 512
    chunk_overlap: int = 50
    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_api_key: str = ""
    store_type: str = "local"
    vector_store_dsn: str = ""


class QueryRequest(BaseModel):
    query: str
    collection: str = "default"
    top_k: int = 5
    score_threshold: float = 0.0
    search_type: str = "similarity"   # similarity | mmr | bm25_hybrid
    rerank: bool = False
    embedding_provider: str = "local"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_api_key: str = ""


class ChunkResult(BaseModel):
    chunk_id: str
    content: str
    score: float
    source: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/ingest")
async def ingest(req: IngestRequest):
    """Split text, embed chunks, and store in the collection."""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="'text' field is required and must not be empty.")

    chunks_text = split_text(req.text, req.splitter_type, req.chunk_size, req.chunk_overlap)
    if not chunks_text:
        raise HTTPException(status_code=400, detail="Text produced 0 chunks after splitting.")

    embeddings = await embed_texts(chunks_text, req.embedding_provider, req.embedding_model, req.embedding_api_key)

    chunks = [
        {
            "chunk_id": str(uuid.uuid4()),
            "content": text,
            "embedding": emb,
            "source": req.source,
            "metadata": {"chunk_index": i, "ingested_at": datetime.utcnow().isoformat()},
        }
        for i, (text, emb) in enumerate(zip(chunks_text, embeddings))
    ]

    count = save_chunks(req.collection, chunks, req.store_type, req.vector_store_dsn)
    return {
        "success": True,
        "collection": req.collection,
        "chunks_ingested": count,
        "store_type": req.store_type,
        "source": req.source,
        "embedding_provider": req.embedding_provider,
        "embedding_model": req.embedding_model,
    }


@router.post("/ingest/database")
async def ingest_database(req: DatabaseIngestRequest):
    """
    Query rows from a database (PostgreSQL, MySQL, SQLite), format each record into
    structured document text, chunk and embed them, and store into the vector collection.
    """
    # Credentials copied from a Connection node arrive sealed ("enc://…") or as vault refs
    try:
        req = req.model_copy(update={
            "password": secret_store.reveal_value(req.password),
            "connection_string": secret_store.reveal_value(req.connection_string),
        })
    except secret_store.SecretError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db_type = (req.db_type or "postgres").lower()
    try:
        if db_type in ("postgres", "postgresql"):
            tables, doc_texts = _fetch_postgres_records(req)
        elif db_type in ("mysql", "mariadb"):
            tables, doc_texts = _fetch_mysql_records(req)
        elif db_type in ("sqlite", "sqlite3"):
            tables, doc_texts = _fetch_sqlite_records(req)
        else:
            tables, doc_texts = _fetch_postgres_records(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Database extraction error ({db_type}): {e}")

    if not doc_texts:
        raise HTTPException(status_code=400, detail="Database query returned 0 records to ingest.")

    full_text = "\n\n---\n\n".join(doc_texts)
    chunks_text = split_text(full_text, req.splitter_type, req.chunk_size, req.chunk_overlap)
    if not chunks_text:
        chunks_text = doc_texts

    embeddings = await embed_texts(chunks_text, req.embedding_provider, req.embedding_model, req.embedding_api_key)

    source_label = req.connection_string or f"{db_type}://{req.host}:{req.port or ''}/{req.database or ''}"
    chunks = [
        {
            "chunk_id": str(uuid.uuid4()),
            "content": text,
            "embedding": emb,
            "source": source_label,
            "metadata": {
                "chunk_index": i,
                "db_type": db_type,
                "tables": tables,
                "ingested_at": datetime.utcnow().isoformat(),
            },
        }
        for i, (text, emb) in enumerate(zip(chunks_text, embeddings))
    ]

    count = save_chunks(req.collection, chunks, req.store_type, req.vector_store_dsn)
    return {
        "success": True,
        "collection": req.collection,
        "store_type": req.store_type,
        "records_ingested": len(doc_texts),
        "chunks_ingested": count,
        "tables": tables,
        "source": source_label,
        "embedding_provider": req.embedding_provider,
        "embedding_model": req.embedding_model,
    }


class LoaderIngestRequest(IngestRequest):
    loader_type: str
    loader_config: Dict[str, Any] = Field(default_factory=dict)   # loader settings (max_pages, db_table, …)
    connection: Dict[str, Any] = Field(default_factory=dict)      # linked Connection node config (sealed creds)


MAX_INGEST_CHUNKS = 20000


@router.get("/loaders")
def list_loaders():
    """Document loader catalog — `available: false` ones are listed but not built yet."""
    return {"loaders": doc_loaders.catalog()}


@router.post("/ingest/loader")
async def ingest_loader(req: LoaderIngestRequest):
    """Run a document loader on `source`, then split, embed and store every document it returns."""
    try:
        cfg = {**req.loader_config, "connection": secret_store.resolve_refs(req.connection)}
        docs = await doc_loaders.load_documents(req.loader_type, req.source, cfg)
    except (LoaderError, secret_store.SecretError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{req.loader_type} loader failed: {type(e).__name__}: {e}")

    pieces = []   # (chunk text, document metadata)
    for doc in docs:
        for chunk in split_text(doc["text"], req.splitter_type, req.chunk_size, req.chunk_overlap) or [doc["text"]]:
            if chunk.strip():
                pieces.append((chunk, doc["metadata"]))
    if not pieces:
        raise HTTPException(status_code=400, detail="The loader returned no text to ingest.")
    if len(pieces) > MAX_INGEST_CHUNKS:
        raise HTTPException(status_code=400, detail=f"That's {len(pieces):,} chunks — more than {MAX_INGEST_CHUNKS:,}. "
                                                    "Narrow the source or raise chunk_size.")

    embeddings = await embed_texts([p[0] for p in pieces], req.embedding_provider, req.embedding_model, req.embedding_api_key)
    now = datetime.utcnow().isoformat()
    loader_type = doc_loaders.resolve(req.loader_type) or req.loader_type
    chunks = [
        {
            "chunk_id": str(uuid.uuid4()),
            "content": text,
            "embedding": emb,
            "source": meta.get("source") or req.source,
            "metadata": {**meta, "chunk_index": i, "loader_type": loader_type, "ingested_at": now},
        }
        for i, ((text, meta), emb) in enumerate(zip(pieces, embeddings))
    ]
    count = save_chunks(req.collection, chunks, req.store_type, req.vector_store_dsn)
    return {
        "success": True,
        "collection": req.collection,
        "loader_type": loader_type,
        "documents_loaded": len(docs),
        "chunks_ingested": count,
        "store_type": req.store_type,
        "source": req.source,
        "embedding_provider": req.embedding_provider,
        "embedding_model": req.embedding_model,
    }


@router.post("/ingest/path")
async def ingest_path(req: IngestRequest):
    """Ingest a local file by path. `source` must be an absolute or relative file path."""
    import os
    path = req.source
    if not path:
        raise HTTPException(status_code=400, detail="'source' must be a file path.")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    if path.lower().endswith(".pdf"):
        try:
            import pypdf
            from io import BytesIO
            with open(path, "rb") as f:
                reader = pypdf.PdfReader(f)
                text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise HTTPException(status_code=422, detail="pypdf not installed. Run: pip install pypdf")
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

    if not text.strip():
        raise HTTPException(status_code=400, detail="File produced no text after extraction.")

    filled = req.model_copy(update={"text": text})
    return await ingest(filled)


def _extract_text_from_bytes(filename: str, content_bytes: bytes) -> str:
    """Extract plain text from PDF, DOCX, TXT, MD, CSV, JSON, code files."""
    fn_lower = filename.lower()
    if fn_lower.endswith(".pdf"):
        try:
            import pypdf
            from io import BytesIO
            reader = pypdf.PdfReader(BytesIO(content_bytes))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise HTTPException(status_code=422, detail="pypdf not installed. Run: pip install pypdf")
        except Exception:
            return content_bytes.decode("utf-8", errors="replace")
    elif fn_lower.endswith(".docx"):
        try:
            import docx
            from io import BytesIO
            doc = docx.Document(BytesIO(content_bytes))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return content_bytes.decode("utf-8", errors="replace")
    else:
        return content_bytes.decode("utf-8", errors="replace")


@router.post("/upload")
async def upload_documents(
    files: List[UploadFile] = File(...),
):
    """
    Upload one or multiple files or a .zip archive to the backend uploads directory.
    Returns saved file info and paths for use in DocLoader or RAG pipelines.
    """
    import os
    import zipfile
    import io

    from paths import data_path

    upload_dir = data_path("uploads")
    os.makedirs(upload_dir, exist_ok=True)

    saved_files = []
    total_bytes = 0

    for file in files:
        filename = file.filename or f"doc_{uuid.uuid4().hex[:6]}"
        content = await file.read()
        total_bytes += len(content)

        if filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for zip_info in zf.infolist():
                        if zip_info.is_dir():
                            continue
                        zip_fn = os.path.basename(zip_info.filename)
                        if not zip_fn or zip_fn.startswith(".") or zip_fn.startswith("__MACOSX"):
                            continue
                        extracted_bytes = zf.read(zip_info.filename)
                        save_name = f"{uuid.uuid4().hex[:6]}_{zip_fn}"
                        save_path = os.path.join(upload_dir, save_name)
                        with open(save_path, "wb") as out_f:
                            out_f.write(extracted_bytes)
                        saved_files.append({
                            "original_name": zip_fn,
                            "stored_name": save_name,
                            "path": save_path,
                            "size": len(extracted_bytes),
                        })
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to extract zip file: {e}")
        else:
            save_name = f"{uuid.uuid4().hex[:6]}_{filename}"
            save_path = os.path.join(upload_dir, save_name)
            with open(save_path, "wb") as out_f:
                out_f.write(content)
            saved_files.append({
                "original_name": filename,
                "stored_name": save_name,
                "path": save_path,
                "size": len(content),
            })

    if not saved_files:
        raise HTTPException(status_code=400, detail="No valid files were uploaded or extracted.")

    # Primary path will be the first file or multi-file summary
    primary_path = saved_files[0]["path"] if len(saved_files) == 1 else upload_dir
    file_names = [f["original_name"] for f in saved_files]

    return {
        "success": True,
        "count": len(saved_files),
        "files": saved_files,
        "primary_path": primary_path,
        "file_names": file_names,
        "total_bytes": total_bytes,
    }


@router.post("/ingest/file")
async def ingest_file(
    collection: str = Form("default"),
    source_label: str = Form(""),
    splitter_type: str = Form("recursive_character"),
    chunk_size: int = Form(512),
    chunk_overlap: int = Form(50),
    embedding_provider: str = Form("local"),
    embedding_model: str = Form("sentence-transformers/all-MiniLM-L6-v2"),
    embedding_api_key: str = Form(""),
    store_type: str = Form("local"),
    vector_store_dsn: str = Form(""),
    file: UploadFile = File(...),
):
    """Upload a file (PDF, TXT, DOCX, ZIP, etc.). Extracts text, then ingests."""
    import zipfile
    import io

    raw = await file.read()
    filename = file.filename or "upload"
    all_texts: List[str] = []

    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                for zip_info in zf.infolist():
                    if zip_info.is_dir() or os.path.basename(zip_info.filename).startswith("."):
                        continue
                    extracted = zf.read(zip_info.filename)
                    t = _extract_text_from_bytes(zip_info.filename, extracted)
                    if t.strip():
                        all_texts.append(f"--- File: {zip_info.filename} ---\n" + t)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse zip: {e}")
        text = "\n\n".join(all_texts)
    else:
        text = _extract_text_from_bytes(filename, raw)

    if not text.strip():
        raise HTTPException(status_code=400, detail="Uploaded file(s) contained no readable text.")

    req = IngestRequest(
        text=text,
        collection=collection,
        source=source_label or filename,
        splitter_type=splitter_type,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_api_key=embedding_api_key,
        store_type=store_type,
        vector_store_dsn=vector_store_dsn,
    )
    return await ingest(req)


def _bm25_score(query_terms: List[str], content: str, avg_dl: float, k1: float = 1.5, b: float = 0.75) -> float:
    """Simple in-memory BM25 score for one document."""
    words = content.lower().split()
    dl = len(words)
    score = 0.0
    for term in query_terms:
        tf = words.count(term)
        if tf == 0:
            continue
        idf = math.log(1 + 1)  # simplified IDF (no corpus stats needed for single-doc)
        score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(avg_dl, 1)))
    return score


def _mmr_select(
    query_emb: List[float],
    candidates: List[Dict[str, Any]],
    top_k: int,
    lambda_mult: float = 0.5,
) -> List[Dict[str, Any]]:
    """Max Marginal Relevance selection — balances relevance and diversity."""
    selected: List[Dict[str, Any]] = []
    remaining = list(candidates)

    while remaining and len(selected) < top_k:
        if not selected:
            # Pick the most relevant first
            best = max(remaining, key=lambda c: c["_sim"])
        else:
            # Balance relevance and redundancy
            def mmr_score(c: Dict[str, Any]) -> float:
                rel = c["_sim"]
                red = max(_cosine_similarity(c["embedding"], s["embedding"]) for s in selected)
                return lambda_mult * rel - (1 - lambda_mult) * red

            best = max(remaining, key=mmr_score)
        selected.append(best)
        remaining.remove(best)

    return selected


@router.post("/query")
async def query(req: QueryRequest):
    """Embed the query and return top-k chunks using the requested search strategy."""
    try:
        store = store_for(req.collection)
        total = store.count(req.collection)
        if not total:
            return {"collection": req.collection, "results": [], "total_chunks": 0, "search_type": req.search_type}

        query_emb = (await embed_texts([req.query], req.embedding_provider, req.embedding_model, req.embedding_api_key))[0]

        # MMR and hybrid re-rank a wider pool of nearest neighbours.
        pool = req.top_k if req.search_type == "similarity" else max(req.top_k * 5, 50)
        stored = store.search(req.collection, query_emb, pool)
    except VectorStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ── Apply score threshold ──────────────────────────────────────────────────
    candidates = [ch for ch in stored if ch["_sim"] >= req.score_threshold]
    if not candidates:
        candidates = stored  # fall back — don't return empty if threshold too strict

    if req.search_type == "mmr":
        top_raw = _mmr_select(query_emb, candidates, req.top_k)

    elif req.search_type == "bm25_hybrid":
        # Compute BM25 scores and combine with cosine via linear fusion
        query_terms = req.query.lower().split()
        avg_dl = sum(len(ch["content"].split()) for ch in candidates) / max(len(candidates), 1)
        for ch in candidates:
            bm25 = _bm25_score(query_terms, ch["content"], avg_dl)
            # Normalise BM25 to [0,1] range for fusion — use tanh squashing
            ch["_bm25"] = math.tanh(bm25 / 5.0)
        # Hybrid score: 50% cosine + 50% BM25
        for ch in candidates:
            ch["_hybrid"] = 0.5 * ch["_sim"] + 0.5 * ch["_bm25"]
        candidates.sort(key=lambda c: c["_hybrid"], reverse=True)
        top_raw = candidates[: req.top_k]

    else:
        # similarity (default)
        candidates.sort(key=lambda c: c["_sim"], reverse=True)
        top_raw = candidates[: req.top_k]

    results = [
        ChunkResult(
            chunk_id=ch["chunk_id"],
            content=ch["content"],
            score=round(ch.get("_hybrid", ch["_sim"]), 4),
            source=ch["source"],
        )
        for ch in top_raw
    ]

    return {
        "collection": req.collection,
        "query": req.query,
        "search_type": req.search_type,
        "results": [r.model_dump() for r in results],
        "total_chunks": total,
    }


@router.get("/collections")
def list_collections():
    """List all collections with their chunk counts and backend."""
    return {"collections": _list_collections()}


@router.delete("/collections/{collection}")
def drop_collection(collection: str):
    """Delete all chunks in a collection, in whichever backend holds it."""
    try:
        _drop_collection(collection)
    except VectorStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "collection": collection, "dropped": True}
