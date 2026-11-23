"""
scim.py — the SCIM 2.0 endpoint identity providers call (services/scim.py).

Base URL ``<public>/scim/v2``; ``Authorization: Bearer scim_…`` (issued in Settings → Single sign-on). The token
names one SSO provider and so one workspace. Every change is written to that workspace's audit log as
``scim.*`` with the provider as actor.

GET  /ServiceProviderConfig  /ResourceTypes  /Schemas      discovery
GET  /Users?filter=userName eq "a@b.com"&startIndex&count   POST /Users
GET|PUT|PATCH|DELETE /Users/{id}
GET  /Groups?filter=displayName eq "Admins"                 POST /Groups
GET|PUT|PATCH|DELETE /Groups/{id}
"""

import json
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from services import audit, scim, sso

router = APIRouter(prefix="/scim/v2", tags=["scim"])
MEDIA = "application/scim+json"
MAX_BODY = 1024 * 1024


def _json(body: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, media_type=MEDIA)


def _base(request: Request) -> str:
    return sso.public_base(str(request.base_url)) + "/scim/v2"


async def _call(request: Request, fn: Callable[..., Any], *args, action: Optional[str] = None,
                status: int = 200, needs_body: bool = False) -> Response:
    token = request.headers.get("authorization", "")
    p = scim.provider_for_token(token[7:].strip()) if token.lower().startswith("bearer ") else None
    if not p:
        return _json(scim.ScimError(401, "Invalid or missing SCIM token").body(), 401)
    try:
        if needs_body:
            raw = await request.body()
            if len(raw) > MAX_BODY:
                raise scim.ScimError(413, "Request too large")
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                raise scim.ScimError(400, "The body isn't valid JSON", "invalidSyntax")
            if not isinstance(body, dict):
                raise scim.ScimError(400, "The body must be a JSON object", "invalidSyntax")
            args = (*args, body)
        result = await run_in_threadpool(fn, p, *args)
    except scim.ScimError as e:
        return _json(e.body(), e.status)
    if action:
        target = (result or {}).get("id") if isinstance(result, dict) else (args[0] if args else "")
        await run_in_threadpool(audit.record, tenant_id=p["tenant_id"], project_id="", actor=f"scim:{p['id']}",
                                action=action, target_id=str(target or ""), outcome="success", status=status,
                                method=request.method, path=request.url.path,
                                ip=request.client.host if request.client else "")
    if status == 204:
        return Response(status_code=204)
    return _json(result, status)


# ── Discovery ─────────────────────────────────────────────────────────────────

@router.get("/ServiceProviderConfig")
async def service_provider_config(request: Request):
    return await _call(request, lambda p: {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True}, "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": scim.MAX_PAGE}, "changePassword": {"supported": False},
        "sort": {"supported": False}, "etag": {"supported": False},
        "authenticationSchemes": [{"type": "oauthbearertoken", "name": "Bearer token", "primary": True,
                                   "description": "The SCIM token from Settings → Single sign-on"}]})


@router.get("/ResourceTypes")
async def resource_types(request: Request):
    def types(p):
        rt = [{"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"], "id": n, "name": n,
               "endpoint": f"/{n}s", "schema": s} for n, s in (("User", scim.USER_SCHEMA), ("Group", scim.GROUP_SCHEMA))]
        return scim.list_response(rt, len(rt), 1)
    return await _call(request, types)


@router.get("/Schemas")
async def schemas(request: Request):
    def schema_list(p):
        out = [{"id": scim.USER_SCHEMA, "name": "User", "attributes": [
                   {"name": n, "type": t, "multiValued": m, "required": r} for n, t, m, r in (
                       ("userName", "string", False, True), ("displayName", "string", False, False),
                       ("name", "complex", False, False), ("emails", "complex", True, True),
                       ("active", "boolean", False, False), ("externalId", "string", False, False))]},
               {"id": scim.GROUP_SCHEMA, "name": "Group", "attributes": [
                   {"name": "displayName", "type": "string", "multiValued": False, "required": True},
                   {"name": "members", "type": "complex", "multiValued": True, "required": False}]}]
        return scim.list_response(out, len(out), 1)
    return await _call(request, schema_list)


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/Users")
async def list_users(request: Request, filter: Optional[str] = None, startIndex: int = 1, count: Optional[int] = None):
    return await _call(request, lambda p: scim.list_users(p, _base(request), filter, startIndex, count))


@router.post("/Users")
async def create_user(request: Request):
    return await _call(request, lambda p, b: scim.create_user(p, b, _base(request)), action="scim.user_create",
                       status=201, needs_body=True)


@router.get("/Users/{user_id}")
async def get_user(user_id: str, request: Request):
    return await _call(request, lambda p: scim.get_user(p, user_id, _base(request)))


@router.put("/Users/{user_id}")
async def replace_user(user_id: str, request: Request):
    return await _call(request, lambda p, b: scim.replace_user(p, user_id, b, _base(request)),
                       action="scim.user_update", needs_body=True)


@router.patch("/Users/{user_id}")
async def patch_user(user_id: str, request: Request):
    return await _call(request, lambda p, b: scim.patch_user(p, user_id, b, _base(request)),
                       action="scim.user_update", needs_body=True)


@router.delete("/Users/{user_id}")
async def delete_user(user_id: str, request: Request):
    return await _call(request, lambda p: scim.delete_user(p, user_id) or {"id": user_id},
                       action="scim.user_delete", status=204)


# ── Groups ────────────────────────────────────────────────────────────────────

@router.get("/Groups")
async def list_groups(request: Request, filter: Optional[str] = None, startIndex: int = 1,
                      count: Optional[int] = None, excludedAttributes: str = ""):
    return await _call(request, lambda p: scim.list_groups(p, _base(request), filter, startIndex, count,
                                                           excludedAttributes))


@router.post("/Groups")
async def create_group(request: Request):
    return await _call(request, lambda p, b: scim.create_group(p, b, _base(request)), action="scim.group_create",
                       status=201, needs_body=True)


@router.get("/Groups/{group_id}")
async def get_group(group_id: str, request: Request, excludedAttributes: str = ""):
    return await _call(request, lambda p: scim.get_group(p, group_id, _base(request), excludedAttributes))


@router.put("/Groups/{group_id}")
async def replace_group(group_id: str, request: Request):
    return await _call(request, lambda p, b: scim.replace_group(p, group_id, b, _base(request)),
                       action="scim.group_update", needs_body=True)


@router.patch("/Groups/{group_id}")
async def patch_group(group_id: str, request: Request):
    return await _call(request, lambda p, b: scim.patch_group(p, group_id, b, _base(request)),
                       action="scim.group_update", needs_body=True)


@router.delete("/Groups/{group_id}")
async def delete_group(group_id: str, request: Request):
    return await _call(request, lambda p: scim.delete_group(p, group_id) or {"id": group_id},
                       action="scim.group_delete", status=204)
