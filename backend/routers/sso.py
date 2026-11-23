"""
sso.py — single sign-on routes (services/sso.py, sso_oidc.py, sso_saml.py).

Public (``public_router``; the single-use state / handoff code is the credential):
GET  /api/auth/sso/discover?email=          — providers covering the email's domain
GET  /api/auth/sso/{provider_id}/start      — redirect to the IdP (``return_to`` = the UI origin)
GET  /api/auth/sso/oidc/callback            — OIDC redirect URI
GET  /api/auth/sso/saml/{provider_id}/metadata — SP metadata (also the SP entity id)
POST /api/auth/sso/saml/{provider_id}/acs   — SAML Assertion Consumer Service (HTTP-POST)
POST /api/auth/sso/exchange                 — the UI trades the one-time code for a session

Workspace owners (``router``, signed in; audited):
GET    /api/iam/sso                 — this workspace's identity providers
POST   /api/iam/sso                 — add one
PUT    /api/iam/sso/{provider_id}   — change one (an empty client secret keeps the saved one)
DELETE /api/iam/sso/{provider_id}   — remove one (ends the sessions it created)
POST   /api/iam/sso/{provider_id}/test — check the configuration (discovery / certificate)
"""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

from db import get_db_connection
from routers.auth import session_response
from services import sso, sso_oidc, sso_saml
from services.request_context import get_request_context

log = logging.getLogger(__name__)

public_router = APIRouter(prefix="/api/auth/sso", tags=["auth"])
router = APIRouter(prefix="/api/iam/sso", tags=["iam"])


def _base(request: Request) -> str:
    return sso.public_base(str(request.base_url))


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _back(return_to: str, **params: str) -> RedirectResponse:
    return RedirectResponse(f"{return_to.rstrip('/')}/?{urlencode(params)}", status_code=303)


def _enabled(provider_id: str) -> Dict[str, Any]:
    p = sso.get_provider(provider_id)
    if not p or not p["enabled"]:
        raise HTTPException(status_code=404, detail="Sign-in method not found.")
    conn = get_db_connection()
    active = conn.execute("SELECT 1 FROM tenants WHERE id = ? AND status = 'active'", (p["tenant_id"],)).fetchone()
    conn.close()
    if not active:
        raise HTTPException(status_code=404, detail="Sign-in method not found.")
    return p


# ── Public sign-in ────────────────────────────────────────────────────────────

@public_router.get("/discover")
def discover(email: str = ""):
    return {"providers": sso.providers_for_email(email[:254])}


@public_router.get("/{provider_id}/start")
async def start(provider_id: str, request: Request, return_to: str = ""):
    p = _enabled(provider_id)
    back = sso.safe_return_to(return_to, str(request.base_url))
    try:
        module = sso_oidc if p["protocol"] == "oidc" else sso_saml
        url = await module.authorize_url(p, _base(request), back)
    except sso.SSOError as e:
        return _back(back, sso_error=str(e))
    return RedirectResponse(url, status_code=302)


async def _complete(request: Request, p: Dict[str, Any], identity: Dict[str, Any], back: str) -> RedirectResponse:
    try:
        user_id = sso.complete_login(p, subject=identity["subject"], email=identity["email"],
                                     name=identity.get("name", ""), claims=identity.get("claims", []))
    except sso.SSOError as e:
        sso.record_login(p, "", "denied", _ip(request), f"{identity.get('email', '')}: {e}")
        return _back(back, sso_error=str(e))
    code = sso.put_state(p["id"], "handoff", {"user_id": user_id}, sso.HANDOFF_TTL)
    sso.record_login(p, user_id, "success", _ip(request))
    return _back(back, sso_code=code)


@public_router.get("/oidc/callback")
async def oidc_callback(request: Request, state: str = "", code: str = "", error: str = "",
                        error_description: str = ""):
    default = sso.safe_return_to("", str(request.base_url))
    try:
        provider_id, st = sso.take_state(state, "login")
    except sso.SSOError as e:
        return _back(default, sso_error=str(e))
    back = st.get("return_to") or default
    p = sso.get_provider(provider_id)
    if not p or not p["enabled"] or p["protocol"] != "oidc":
        return _back(back, sso_error="This sign-in method is no longer available.")
    if error or not code:
        return _back(back, sso_error=f"The identity provider didn't sign you in: {error_description or error or 'no code'}"[:300])
    try:
        identity = await sso_oidc.finish(p, st, code, _base(request))
    except sso.SSOError as e:
        sso.record_login(p, "", "denied", _ip(request), str(e))
        return _back(back, sso_error=str(e))
    return await _complete(request, p, identity, back)


@public_router.get("/saml/{provider_id}/metadata")
def saml_metadata(provider_id: str, request: Request):
    p = sso.get_provider(provider_id)
    if not p or p["protocol"] != "saml":
        raise HTTPException(status_code=404, detail="Not found")
    return Response(sso_saml.sp_metadata(p, _base(request)), media_type="application/samlmetadata+xml")


@public_router.post("/saml/{provider_id}/acs")
async def saml_acs(provider_id: str, request: Request, SAMLResponse: str = Form(default=""),
                   RelayState: str = Form(default="")):
    default = sso.safe_return_to("", str(request.base_url))
    try:
        state_provider, st = sso.take_state(RelayState, "login")
    except sso.SSOError:
        return _back(default, sso_error="Start the sign-in from Pipesets (IdP-initiated sign-in isn't supported).")
    back = st.get("return_to") or default
    p = sso.get_provider(provider_id)
    if state_provider != provider_id or not p or not p["enabled"] or p["protocol"] != "saml":
        return _back(back, sso_error="This sign-in doesn't belong to this identity provider.")
    try:
        identity = sso_saml.finish(p, st, SAMLResponse, _base(request))
    except sso.SSOError as e:
        sso.record_login(p, "", "denied", _ip(request), str(e))
        return _back(back, sso_error=str(e))
    return await _complete(request, p, identity, back)


class ExchangeRequest(BaseModel):
    code: str = Field(..., max_length=128)


@public_router.post("/exchange")
def exchange(req: ExchangeRequest, request: Request):
    try:
        provider_id, data = sso.take_state(req.code, "handoff")
    except sso.SSOError as e:
        raise HTTPException(status_code=401, detail=str(e))
    p = sso.get_provider(provider_id)
    if not p:
        raise HTTPException(status_code=401, detail="This sign-in method is no longer available.")
    return session_response(data["user_id"], request, p["tenant_id"], p["id"])


# ── Workspace owners ──────────────────────────────────────────────────────────

class ProviderRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    protocol: Optional[str] = Field(default=None, max_length=16)
    enabled: Optional[bool] = None
    config: Dict[str, Optional[str]] = Field(default_factory=dict)
    email_domains: Optional[List[str]] = None
    role_claim: Optional[str] = Field(default=None, max_length=200)
    role_mappings: Optional[List[Dict[str, Any]]] = None
    default_role: Optional[str] = Field(default=None, max_length=32)
    auto_provision: Optional[bool] = None
    sync_roles: Optional[bool] = None
    enforce: Optional[bool] = None


def _owner_ctx(request: Request):
    ctx = get_request_context(request)
    conn = get_db_connection()
    row = conn.execute("SELECT role FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?",
                       (ctx.tenant_id, ctx.user_id)).fetchone()
    conn.close()
    if not row or row[0] != "owner":
        raise HTTPException(status_code=403, detail="Only a workspace owner can manage single sign-on.")
    return ctx


def _fields(req: ProviderRequest) -> Dict[str, Any]:
    return {k: v for k, v in req.model_dump().items() if v is not None}


@router.get("")
def list_providers(request: Request):
    ctx = _owner_ctx(request)
    base = str(request.base_url)
    return {"providers": [sso.public_view(p, base) for p in sso.list_providers(ctx.tenant_id)],
            "oidc_redirect_uri": sso_oidc.redirect_uri(_base(request))}


@router.post("", status_code=201)
def create_provider(req: ProviderRequest, request: Request):
    ctx = _owner_ctx(request)
    try:
        p = sso.save_provider(ctx.tenant_id, ctx.user_id, _fields(req))
    except sso.SSOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sso.public_view(p, str(request.base_url))


@router.put("/{provider_id}")
def update_provider(provider_id: str, req: ProviderRequest, request: Request):
    ctx = _owner_ctx(request)
    fields = _fields(req)
    fields.pop("protocol", None)
    try:
        p = sso.save_provider(ctx.tenant_id, ctx.user_id, fields, provider_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    except sso.SSOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sso.public_view(p, str(request.base_url))


@router.delete("/{provider_id}")
def delete_provider(provider_id: str, request: Request):
    ctx = _owner_ctx(request)
    if ctx.sso_tenant and getattr(request.state, "session_id", None):
        conn = get_db_connection()
        mine = conn.execute("SELECT sso_provider_id FROM auth_sessions WHERE id = ?",
                            (request.state.session_id,)).fetchone()
        conn.close()
        if mine and mine[0] == provider_id:
            raise HTTPException(status_code=409, detail="You signed in with this identity provider. "
                                                        "Sign in with your password (or another provider) to remove it.")
    if not sso.delete_provider(provider_id, ctx.tenant_id):
        raise HTTPException(status_code=404, detail="Identity provider not found")
    return {"deleted": True, "id": provider_id}


@router.post("/{provider_id}/test")
async def test_provider(provider_id: str, request: Request):
    ctx = _owner_ctx(request)
    p = sso.get_provider(provider_id, ctx.tenant_id)
    if not p:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    try:
        if p["protocol"] == "oidc":
            meta = await sso_oidc.metadata(p["config"])
            detail = f"Discovery OK: {meta['issuer']}"
        else:
            cert = sso_saml.load_certificate(p["config"]["idp_certificate"])
            detail = f"Certificate OK: {cert.subject.rfc4514_string()}, valid until {cert.not_valid_after_utc:%Y-%m-%d}"
    except sso.SSOError as e:
        return {"ok": False, "detail": str(e)}
    return {"ok": True, "detail": detail}
