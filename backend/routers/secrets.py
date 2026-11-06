"""
secrets.py — the encrypted secrets vault (API keys and tokens for tools).

GET    /api/secrets          — secrets visible in the caller's project (never the values)
POST   /api/secrets          — store a secret; returns its "secret://<id>" reference
PUT    /api/secrets/{id}     — rename, re-tag or replace the value
DELETE /api/secrets/{id}     — delete (tools referencing it fail with a clear error)

Values are write-only: no route ever returns one. ``kind`` decides who may decrypt a
secret: "llm" keys only model/embedding calls, "tool" keys only tools. Requires the ``secrets`` ACL
(read to list, write to change); tenant owners have it implicitly.
"""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services import secret_store
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/secrets", tags=["secrets"])


class SecretCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    value: str = Field(..., min_length=1, max_length=20000)
    provider: str = Field(default="", max_length=64)
    shared: bool = Field(default=False, description="true = every project in the tenant can use it")
    default_for: str = Field(default="", max_length=64, description="LLM provider this is the default key for")
    kind: Literal["llm", "tool"] = Field(default="tool", description="llm: model calls only · tool: tools only")


class SecretUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    value: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    provider: Optional[str] = Field(default=None, max_length=64)
    default_for: Optional[str] = Field(default=None, max_length=64, description='"" = no longer a default')
    kind: Optional[Literal["llm", "tool"]] = None


@router.get("")
def list_secrets(request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "secrets", "read")
    return secret_store.list_secrets(ctx.tenant_id, ctx.project_id)


@router.post("", status_code=201)
def create_secret(req: SecretCreate, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "secrets", "write")
    try:
        return secret_store.create_secret(ctx.tenant_id, ctx.project_id, ctx.user_id, req.name, req.value,
                                          req.provider, req.shared, req.default_for, req.kind)
    except secret_store.SecretError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{secret_id}")
def update_secret(secret_id: str, req: SecretUpdate, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "secrets", "write")
    try:
        updated = secret_store.update_secret(secret_id, ctx.tenant_id, ctx.project_id,
                                             req.name, req.value, req.provider, req.default_for, req.kind)
    except secret_store.SecretError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="Secret not found")
    return updated


@router.delete("/{secret_id}")
def delete_secret(secret_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "secrets", "write")
    if not secret_store.delete_secret(secret_id, ctx.tenant_id, ctx.project_id):
        raise HTTPException(status_code=404, detail="Secret not found")
    return {"deleted": secret_id}
