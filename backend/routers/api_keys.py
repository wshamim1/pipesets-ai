"""
api_keys.py — manage API keys for the public /v1 API (internal admin routes).

GET    /api/api-keys            — keys in the caller's tenant/project (no secrets)
POST   /api/api-keys            — issue a key; the plaintext is returned ONCE
DELETE /api/api-keys/{key_id}   — revoke a key (immediate; cannot be undone)

Requires the ``api_keys:admin`` ACL (tenant owners have it implicitly). A new key
acts as the caller, so it can never exceed the caller's own access.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services import api_keys
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: List[str] = Field(default_factory=lambda: list(api_keys.DEFAULT_SCOPES))
    rate_limit_rpm: int = Field(default=60, ge=0, le=10000, description="0 = unlimited")
    expires_in_days: Optional[int] = Field(default=None, ge=1, le=3650)


@router.get("")
def list_api_keys(request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "api_keys", "admin")
    return api_keys.list_keys(ctx.tenant_id, ctx.project_id)


@router.post("", status_code=201)
def create_api_key(req: ApiKeyCreate, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "api_keys", "admin")
    try:
        plaintext, record = api_keys.create_key(
            ctx, req.name, req.scopes, req.rate_limit_rpm, req.expires_in_days,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {**record, "key": plaintext, "warning": "Store this key now — it will not be shown again."}


@router.delete("/{key_id}")
def revoke_api_key(key_id: str, request: Request):
    ctx = get_request_context(request)
    require_access(ctx, "api_keys", "admin")
    if not api_keys.revoke_key(key_id, ctx.tenant_id):
        raise HTTPException(status_code=404, detail="API key not found or already revoked")
    return {"revoked": True, "id": key_id}
