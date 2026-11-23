"""
scim.py — SCIM 2.0 provisioning (RFC 7643 / 7644) from an identity provider into one workspace.

An owner turns SCIM on for an SSO provider (Settings → Single sign-on) and gets a bearer token
(``scim_<43 chars>``, only its SHA-256 is kept). The IdP (Okta, Entra ID, OneLogin, JumpCloud…) calls
``/scim/v2/Users`` and ``/scim/v2/Groups`` with it; routers/scim.py turns those calls into the functions here.
The token identifies the provider, and so the one tenant everything below happens in.

Model
-----
* A SCIM **User** is a Pipesets user plus a ``scim_users`` row (the IdP's externalId / userName / active).
  Creating one links an existing account with that email, or creates one without a password (they sign in
  with SSO). Emails must be in the provider's ``email_domains``; SCIM can't be turned on without them, so a
  workspace can't claim addresses it doesn't own.
* A SCIM **Group** is stored as is. Its display name is matched against the provider's role mappings (the
  same table SSO sign-in uses): members get the highest mapped role and the mapped Pipesets groups; without a
  match, ``default_role`` (or no access when that's empty).
* ``recompute()`` turns that into the user's ``tenant_memberships`` row and group memberships after every
  change. Deactivating (``active: false``) or deleting a user removes their membership in this workspace and
  ends the sessions SSO opened there, immediately. The workspace's last owner is never removed or demoted.
* SCIM only ever touches this tenant: it never disables the global account (the person may belong to other
  workspaces), and it renames / re-addresses only accounts it created itself.

While a provider has SCIM on, its users' roles come from SCIM, not from the claims at sign-in, and a
deactivated user can't sign in with it (services/sso.complete_login checks ``scim_status``).
"""

import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from db import get_db_connection, insert_ignore
from services import sso

log = logging.getLogger(__name__)

TOKEN_PREFIX = "scim_"
USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
MAX_PAGE = 200
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FILTER_RE = re.compile(r'^\s*([A-Za-z.]+)\s+eq\s+"((?:[^"\\]|\\.)*)"\s*$', re.I)
_MEMBER_PATH_RE = re.compile(r'^members\[\s*value\s+eq\s+"([^"]+)"\s*\]$', re.I)


class ScimError(Exception):
    def __init__(self, status: int, detail: str, scim_type: Optional[str] = None):
        super().__init__(detail)
        self.status, self.detail, self.scim_type = status, detail, scim_type

    def body(self) -> Dict[str, Any]:
        out = {"schemas": [ERROR_SCHEMA], "status": str(self.status), "detail": self.detail}
        if self.scim_type:
            out["scimType"] = self.scim_type
        return out


def _now() -> str:
    return datetime.utcnow().isoformat()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── Tokens ────────────────────────────────────────────────────────────────────

def issue_token(provider_id: str, tenant_id: str) -> str:
    """A new SCIM token for the provider (replacing any previous one). Returned once."""
    p = sso.get_provider(provider_id, tenant_id)
    if not p:
        raise LookupError("Identity provider not found")
    if not p["email_domains"]:
        raise sso.SSOError("Set the provider's email domains first: SCIM may only provision emails at them.")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    conn = get_db_connection()
    try:
        conn.execute("UPDATE sso_providers SET scim_token_hash = ?, scim_token_prefix = ?, updated_at = ? WHERE id = ?",
                     (_hash(token), token[:12], _now(), provider_id))
        conn.commit()
    finally:
        conn.close()
    return token


def revoke_token(provider_id: str, tenant_id: str) -> bool:
    conn = get_db_connection()
    try:
        n = conn.execute("UPDATE sso_providers SET scim_token_hash = NULL, scim_token_prefix = NULL, updated_at = ? "
                         "WHERE id = ? AND tenant_id = ?", (_now(), provider_id, tenant_id)).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def provider_for_token(token: str) -> Optional[Dict[str, Any]]:
    if not token.startswith(TOKEN_PREFIX) or len(token) > 100:
        return None
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT s.id FROM sso_providers s JOIN tenants t ON t.id = s.tenant_id "
                           "WHERE s.scim_token_hash = ? AND t.status = 'active'", (_hash(token),)).fetchone()
    finally:
        conn.close()
    return sso.get_provider(row["id"]) if row else None


def scim_status(provider_id: str, user_id: str) -> Optional[bool]:
    """True / False when SCIM manages this user for the provider (active or not); None when it doesn't."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT s.active FROM scim_users s JOIN sso_providers p ON p.id = s.provider_id "
                           "WHERE s.provider_id = ? AND s.user_id = ? AND p.scim_token_hash IS NOT NULL",
                           (provider_id, user_id)).fetchone()
    finally:
        conn.close()
    return None if row is None else bool(row["active"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _bool(value: Any) -> bool:
    """SCIM booleans; Entra ID sends "True" / "False" strings."""
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "")
    return bool(value)


def _email_of(body: Dict[str, Any]) -> str:
    emails = body.get("emails") if isinstance(body.get("emails"), list) else []
    primary = next((e for e in emails if isinstance(e, dict) and _bool(e.get("primary", False))), None)
    chosen = (primary or next((e for e in emails if isinstance(e, dict)), {}) or {}).get("value") or ""
    if not chosen and "@" in str(body.get("userName") or ""):
        chosen = body["userName"]
    return str(chosen).strip().lower()


def _display_of(body: Dict[str, Any]) -> str:
    name = body.get("name") if isinstance(body.get("name"), dict) else {}
    return str(body.get("displayName") or name.get("formatted")
               or " ".join(x for x in (name.get("givenName"), name.get("familyName")) if x) or "").strip()


def _check_email(p: Dict[str, Any], email: str) -> None:
    if not _EMAIL_RE.match(email):
        raise ScimError(400, "The user needs an email address (emails[].value, or an email as userName).",
                        "invalidValue")
    if email.rsplit("@", 1)[1] not in p["email_domains"]:
        raise ScimError(400, f"{email} isn't at one of this provider's email domains.", "invalidValue")


def parse_filter(filt: Optional[str], allowed: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """``attr eq "value"`` → (column, value). Only the equality filters IdPs actually send."""
    if not filt:
        return None
    m = _FILTER_RE.match(filt)
    if not m or m.group(1).lower() not in allowed:
        raise ScimError(400, f"Unsupported filter: {filt}", "invalidFilter")
    return allowed[m.group(1).lower()], m.group(2).replace('\\"', '"')


def _page(start_index: int, count: Optional[int]) -> Tuple[int, int]:
    start = max(1, int(start_index or 1))
    n = MAX_PAGE if count is None else max(0, min(int(count), MAX_PAGE))
    return start, n


def list_response(resources: List[Dict[str, Any]], total: int, start: int) -> Dict[str, Any]:
    return {"schemas": [LIST_SCHEMA], "totalResults": total, "startIndex": start,
            "itemsPerPage": len(resources), "Resources": resources}


# ── Membership ────────────────────────────────────────────────────────────────

def recompute(conn, p: Dict[str, Any], user_id: str) -> None:
    """Apply what SCIM says about ``user_id`` to their membership and groups in the provider's tenant."""
    tenant_id, now = p["tenant_id"], _now()
    row = conn.execute("SELECT active FROM scim_users WHERE provider_id = ? AND user_id = ?",
                       (p["id"], user_id)).fetchone()
    names = [r[0] for r in conn.execute(
        "SELECT g.display_name FROM scim_groups g JOIN scim_group_members m ON m.group_id = g.id "
        "WHERE g.provider_id = ? AND m.user_id = ?", (p["id"], user_id)).fetchall()]
    role, groups, managed = sso.map_roles(p, names)
    if not row or not row["active"]:
        role, groups = None, []
    current = conn.execute("SELECT role FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?",
                           (tenant_id, user_id)).fetchone()
    last_owner = bool(current and current["role"] == "owner" and conn.execute(
        "SELECT COUNT(1) FROM tenant_memberships WHERE tenant_id = ? AND role = 'owner'",
        (tenant_id,)).fetchone()[0] <= 1)

    if role is None:
        if current and last_owner:
            log.warning("SCIM would remove the last owner of %s; kept", tenant_id)
            return
        if current:
            conn.execute("DELETE FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?", (tenant_id, user_id))
        conn.execute("DELETE FROM group_memberships WHERE tenant_id = ? AND user_id = ?", (tenant_id, user_id))
        conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND tenant_id = ? AND revoked_at IS NULL",
                     (now, user_id, tenant_id))
        return

    if not current:
        conn.execute("INSERT INTO tenant_memberships (tenant_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
                     (tenant_id, user_id, role, now))
    elif current["role"] != role and not (last_owner and role != "owner"):
        conn.execute("UPDATE tenant_memberships SET role = ? WHERE tenant_id = ? AND user_id = ?",
                     (role, tenant_id, user_id))
    for gid in managed:
        if gid not in groups:
            conn.execute("DELETE FROM group_memberships WHERE group_id = ? AND user_id = ? AND tenant_id = ?",
                         (gid, user_id, tenant_id))
    for gid in groups:
        if conn.execute("SELECT 1 FROM groups WHERE id = ? AND tenant_id = ?", (gid, tenant_id)).fetchone():
            insert_ignore(conn, "group_memberships",
                          {"group_id": gid, "user_id": user_id, "tenant_id": tenant_id, "created_at": now},
                          key=("group_id", "user_id"))


# ── Users ─────────────────────────────────────────────────────────────────────

def _user_resource(conn, p: Dict[str, Any], row, base: str) -> Dict[str, Any]:
    user = conn.execute("SELECT email FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    groups = conn.execute("SELECT g.id, g.display_name FROM scim_groups g JOIN scim_group_members m "
                          "ON m.group_id = g.id WHERE g.provider_id = ? AND m.user_id = ? ORDER BY g.display_name",
                          (p["id"], row["user_id"])).fetchall()
    email = user["email"] if user else ""
    out = {"schemas": [USER_SCHEMA], "id": row["user_id"], "userName": row["user_name"],
           "displayName": row["display_name"], "name": {"formatted": row["display_name"]},
           "emails": [{"value": email, "primary": True, "type": "work"}] if email else [],
           "active": bool(row["active"]),
           "groups": [{"value": g["id"], "display": g["display_name"], "$ref": f"{base}/Groups/{g['id']}"} for g in groups],
           "meta": {"resourceType": "User", "created": row["created_at"] + "Z", "lastModified": row["updated_at"] + "Z",
                    "location": f"{base}/Users/{row['user_id']}"}}
    if row["external_id"]:
        out["externalId"] = row["external_id"]
    return out


def _scim_user(conn, p: Dict[str, Any], user_id: str):
    row = conn.execute("SELECT * FROM scim_users WHERE provider_id = ? AND user_id = ?", (p["id"], user_id)).fetchone()
    if not row:
        raise ScimError(404, f"User {user_id} not found")
    return row


def list_users(p, base: str, filt: Optional[str], start_index: int = 1, count: Optional[int] = None) -> Dict[str, Any]:
    f = parse_filter(filt, {"username": "s.user_name", "externalid": "s.external_id", "emails.value": "u.email",
                            "id": "s.user_id"})
    start, n = _page(start_index, count)
    where, args = "s.provider_id = ?", [p["id"]]
    if f:
        col, val = f
        where += f" AND LOWER({col}) = LOWER(?)" if col in ("s.user_name", "u.email") else f" AND {col} = ?"
        args.append(val)
    conn = get_db_connection()
    try:
        total = conn.execute(f"SELECT COUNT(1) FROM scim_users s JOIN users u ON u.id = s.user_id WHERE {where}",
                             args).fetchone()[0]
        rows = conn.execute(f"SELECT s.* FROM scim_users s JOIN users u ON u.id = s.user_id WHERE {where} "
                            f"ORDER BY s.created_at, s.user_id LIMIT ? OFFSET ?", (*args, n, start - 1)).fetchall()
        return list_response([_user_resource(conn, p, r, base) for r in rows], total, start)
    finally:
        conn.close()


def get_user(p, user_id: str, base: str) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        return _user_resource(conn, p, _scim_user(conn, p, user_id), base)
    finally:
        conn.close()


def create_user(p, body: Dict[str, Any], base: str) -> Dict[str, Any]:
    user_name = str(body.get("userName") or "").strip()
    if not user_name:
        raise ScimError(400, "userName is required", "invalidValue")
    email = _email_of(body)
    _check_email(p, email)
    display = _display_of(body) or email.split("@")[0]
    active = _bool(body.get("active", True))
    now = _now()
    conn = get_db_connection()
    try:
        if conn.execute("SELECT 1 FROM scim_users WHERE provider_id = ? AND LOWER(user_name) = LOWER(?)",
                        (p["id"], user_name)).fetchone():
            raise ScimError(409, f"User {user_name} already exists", "uniqueness")
        user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        created = 0
        if user:
            user_id = user["id"]
            if conn.execute("SELECT 1 FROM scim_users WHERE provider_id = ? AND user_id = ?", (p["id"], user_id)).fetchone():
                raise ScimError(409, f"A user with {email} already exists", "uniqueness")
        else:
            user_id, created = f"user_{uuid.uuid4().hex[:8]}", 1
            conn.execute("INSERT INTO users (id, email, display_name, status, password_hash, server_admin, created_at, "
                         "updated_at) VALUES (?, ?, ?, 'active', NULL, 0, ?, ?)", (user_id, email, display[:100], now, now))
        conn.execute("INSERT INTO scim_users (provider_id, user_id, tenant_id, external_id, user_name, display_name, "
                     "active, created_user, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (p["id"], user_id, p["tenant_id"], str(body.get("externalId") or "")[:512], user_name[:512],
                      display[:200], 1 if active else 0, created, now, now))
        recompute(conn, p, user_id)
        conn.commit()
        return _user_resource(conn, p, _scim_user(conn, p, user_id), base)
    finally:
        conn.close()


def _apply_user_fields(conn, p, row, fields: Dict[str, Any]) -> None:
    """Update a SCIM user from (already merged) attributes."""
    sets: Dict[str, Any] = {}
    if "userName" in fields and str(fields["userName"] or "").strip():
        sets["user_name"] = str(fields["userName"]).strip()[:512]
    if "externalId" in fields:
        sets["external_id"] = str(fields["externalId"] or "")[:512]
    display = _display_of(fields)
    if display:
        sets["display_name"] = display[:200]
    if "active" in fields:
        sets["active"] = 1 if _bool(fields["active"]) else 0
    email = _email_of(fields) if ("emails" in fields or "userName" in fields) else ""
    if email and row["created_user"]:
        _check_email(p, email)
        clash = conn.execute("SELECT id FROM users WHERE email = ? AND id != ?", (email, row["user_id"])).fetchone()
        if clash:
            raise ScimError(409, f"Another account uses {email}", "uniqueness")
        conn.execute("UPDATE users SET email = ?, updated_at = ? WHERE id = ?", (email, _now(), row["user_id"]))
    if display and row["created_user"]:
        conn.execute("UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?", (display[:100], _now(), row["user_id"]))
    if sets:
        sets["updated_at"] = _now()
        conn.execute(f"UPDATE scim_users SET {', '.join(f'{k} = ?' for k in sets)} WHERE provider_id = ? AND user_id = ?",
                     (*sets.values(), p["id"], row["user_id"]))


def replace_user(p, user_id: str, body: Dict[str, Any], base: str) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        row = _scim_user(conn, p, user_id)
        _apply_user_fields(conn, p, row, {"active": True, **body})
        recompute(conn, p, user_id)
        conn.commit()
        return _user_resource(conn, p, _scim_user(conn, p, user_id), base)
    finally:
        conn.close()


def _set_path(target: Dict[str, Any], path: str, value: Any) -> None:
    """Patch a (lower-cased) attribute path like ``name.formatted`` or ``emails[type eq "work"].value``."""
    path = re.sub(r"\[.*?\]", "", path)      # emails[type eq "work"].value → emails.value
    if path.startswith(USER_SCHEMA.lower() + ":"):
        path = path[len(USER_SCHEMA) + 1:]
    parts = path.split(".")
    key = {"username": "userName", "displayname": "displayName", "externalid": "externalId", "active": "active",
           "emails": "emails", "name": "name"}.get(parts[0], parts[0])
    if key == "emails":
        target["emails"] = value if isinstance(value, list) else [{"value": value, "primary": True}]
    elif key == "name" and len(parts) > 1:
        target.setdefault("name", {})[{"formatted": "formatted", "givenname": "givenName",
                                       "familyname": "familyName"}.get(parts[1], parts[1])] = value
    else:
        target[key] = value


def patch_user(p, user_id: str, body: Dict[str, Any], base: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    for op in body.get("Operations") or []:
        kind = str(op.get("op") or "").lower()
        path = str(op.get("path") or "").strip().lower()
        value = op.get("value")
        if kind not in ("add", "replace", "remove"):
            raise ScimError(400, f"Unsupported patch op {op.get('op')!r}", "invalidSyntax")
        if kind == "remove":
            if path == "externalid":
                fields["externalId"] = ""
            continue                              # other removals (phone numbers…) have nothing to clear here
        if path:
            _set_path(fields, path, value)
        elif isinstance(value, dict):
            for k, v in value.items():
                _set_path(fields, k.lower(), v)
    conn = get_db_connection()
    try:
        row = _scim_user(conn, p, user_id)
        _apply_user_fields(conn, p, row, fields)
        recompute(conn, p, user_id)
        conn.commit()
        return _user_resource(conn, p, _scim_user(conn, p, user_id), base)
    finally:
        conn.close()


def delete_user(p, user_id: str) -> None:
    conn = get_db_connection()
    try:
        _scim_user(conn, p, user_id)
        conn.execute("UPDATE scim_users SET active = 0 WHERE provider_id = ? AND user_id = ?", (p["id"], user_id))
        recompute(conn, p, user_id)           # removes the membership and ends SSO sessions
        conn.execute("DELETE FROM scim_group_members WHERE user_id = ? AND group_id IN "
                     "(SELECT id FROM scim_groups WHERE provider_id = ?)", (user_id, p["id"]))
        conn.execute("DELETE FROM scim_users WHERE provider_id = ? AND user_id = ?", (p["id"], user_id))
        conn.commit()
    finally:
        conn.close()


# ── Groups ────────────────────────────────────────────────────────────────────

def _group_row(conn, p, group_id: str):
    row = conn.execute("SELECT * FROM scim_groups WHERE id = ? AND provider_id = ?", (group_id, p["id"])).fetchone()
    if not row:
        raise ScimError(404, f"Group {group_id} not found")
    return row


def _group_resource(conn, p, row, base: str, members: bool = True) -> Dict[str, Any]:
    out = {"schemas": [GROUP_SCHEMA], "id": row["id"], "displayName": row["display_name"],
           "meta": {"resourceType": "Group", "created": row["created_at"] + "Z", "lastModified": row["updated_at"] + "Z",
                    "location": f"{base}/Groups/{row['id']}"}}
    if row["external_id"]:
        out["externalId"] = row["external_id"]
    if members:
        out["members"] = [{"value": r["user_id"], "display": r["user_name"], "$ref": f"{base}/Users/{r['user_id']}"}
                          for r in conn.execute(
                              "SELECT m.user_id, s.user_name FROM scim_group_members m JOIN scim_users s "
                              "ON s.user_id = m.user_id AND s.provider_id = ? WHERE m.group_id = ? ORDER BY s.user_name",
                              (p["id"], row["id"])).fetchall()]
    return out


def _member_ids(value: Any) -> List[str]:
    items = value if isinstance(value, list) else [value]
    return [str(m.get("value")) for m in items if isinstance(m, dict) and m.get("value")]


def _set_members(conn, p, group_id: str, add: Iterable[str] = (), remove: Iterable[str] = (),
                 replace: Optional[Iterable[str]] = None) -> set:
    """Change a group's members (only users this provider provisioned); returns the users affected."""
    known = {r[0] for r in conn.execute("SELECT user_id FROM scim_users WHERE provider_id = ?", (p["id"],)).fetchall()}
    current = {r[0] for r in conn.execute("SELECT user_id FROM scim_group_members WHERE group_id = ?",
                                          (group_id,)).fetchall()}
    target = set(current)
    if replace is not None:
        target = set(replace)
    target = (target | set(add)) - set(remove)
    unknown = target - known - current
    if unknown:
        raise ScimError(400, f"Unknown member(s): {', '.join(sorted(unknown))}", "invalidValue")
    for uid in target - current:
        conn.execute("INSERT INTO scim_group_members (group_id, user_id) VALUES (?, ?)", (group_id, uid))
    for uid in current - target:
        conn.execute("DELETE FROM scim_group_members WHERE group_id = ? AND user_id = ?", (group_id, uid))
    return target ^ current


def list_groups(p, base: str, filt: Optional[str], start_index: int = 1, count: Optional[int] = None,
                excluded: str = "") -> Dict[str, Any]:
    f = parse_filter(filt, {"displayname": "display_name", "externalid": "external_id", "id": "id"})
    start, n = _page(start_index, count)
    where, args = "provider_id = ?", [p["id"]]
    if f:
        where += f" AND {f[0]} = ?"
        args.append(f[1])
    conn = get_db_connection()
    try:
        total = conn.execute(f"SELECT COUNT(1) FROM scim_groups WHERE {where}", args).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM scim_groups WHERE {where} ORDER BY created_at, id LIMIT ? OFFSET ?",
                            (*args, n, start - 1)).fetchall()
        members = "members" not in (excluded or "").lower()
        return list_response([_group_resource(conn, p, r, base, members) for r in rows], total, start)
    finally:
        conn.close()


def get_group(p, group_id: str, base: str, excluded: str = "") -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        return _group_resource(conn, p, _group_row(conn, p, group_id), base, "members" not in (excluded or "").lower())
    finally:
        conn.close()


def create_group(p, body: Dict[str, Any], base: str) -> Dict[str, Any]:
    name = str(body.get("displayName") or "").strip()
    if not name:
        raise ScimError(400, "displayName is required", "invalidValue")
    now, gid = _now(), f"scimg_{uuid.uuid4().hex[:12]}"
    conn = get_db_connection()
    try:
        if conn.execute("SELECT 1 FROM scim_groups WHERE provider_id = ? AND display_name = ?", (p["id"], name)).fetchone():
            raise ScimError(409, f"Group {name} already exists", "uniqueness")
        conn.execute("INSERT INTO scim_groups (id, provider_id, tenant_id, display_name, external_id, created_at, "
                     "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (gid, p["id"], p["tenant_id"], name[:256], str(body.get("externalId") or "")[:512], now, now))
        for uid in _set_members(conn, p, gid, add=_member_ids(body.get("members") or [])):
            recompute(conn, p, uid)
        conn.commit()
        return _group_resource(conn, p, _group_row(conn, p, gid), base)
    finally:
        conn.close()


def _rename(conn, p, row, name: str) -> set:
    name = str(name or "").strip()
    if not name or name == row["display_name"]:
        return set()
    conn.execute("UPDATE scim_groups SET display_name = ?, updated_at = ? WHERE id = ?", (name[:256], _now(), row["id"]))
    # The name decides the role: every member is affected
    return {r[0] for r in conn.execute("SELECT user_id FROM scim_group_members WHERE group_id = ?", (row["id"],))}


def replace_group(p, group_id: str, body: Dict[str, Any], base: str) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        row = _group_row(conn, p, group_id)
        affected = _rename(conn, p, row, body.get("displayName") or row["display_name"])
        if "externalId" in body:
            conn.execute("UPDATE scim_groups SET external_id = ? WHERE id = ?", (str(body["externalId"] or "")[:512], group_id))
        if "members" in body:
            affected |= _set_members(conn, p, group_id, replace=_member_ids(body.get("members") or []))
        for uid in affected:
            recompute(conn, p, uid)
        conn.commit()
        return _group_resource(conn, p, _group_row(conn, p, group_id), base)
    finally:
        conn.close()


def patch_group(p, group_id: str, body: Dict[str, Any], base: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = _group_row(conn, p, group_id)
        affected: set = set()
        for op in body.get("Operations") or []:
            kind = str(op.get("op") or "").lower()
            path = str(op.get("path") or "").strip()
            value = op.get("value")
            m = _MEMBER_PATH_RE.match(path)
            if kind not in ("add", "replace", "remove"):
                raise ScimError(400, f"Unsupported patch op {op.get('op')!r}", "invalidSyntax")
            if path.lower() == "members":
                if kind == "add":
                    affected |= _set_members(conn, p, group_id, add=_member_ids(value))
                elif kind == "remove":
                    affected |= _set_members(conn, p, group_id, remove=_member_ids(value) if value else
                                             [r[0] for r in conn.execute("SELECT user_id FROM scim_group_members "
                                                                          "WHERE group_id = ?", (group_id,))])
                else:
                    affected |= _set_members(conn, p, group_id, replace=_member_ids(value or []))
            elif m and kind == "remove":
                affected |= _set_members(conn, p, group_id, remove=[m.group(1)])
            elif path.lower() == "displayname":
                affected |= _rename(conn, p, row, value)
            elif path.lower() == "externalid":
                conn.execute("UPDATE scim_groups SET external_id = ? WHERE id = ?", (str(value or "")[:512], group_id))
            elif not path and isinstance(value, dict):
                if "displayName" in value:
                    affected |= _rename(conn, p, row, value["displayName"])
                if "members" in value:
                    affected |= _set_members(conn, p, group_id, add=_member_ids(value["members"]))
            row = _group_row(conn, p, group_id)
        for uid in affected:
            recompute(conn, p, uid)
        conn.execute("UPDATE scim_groups SET updated_at = ? WHERE id = ?", (_now(), group_id))
        conn.commit()
        return _group_resource(conn, p, _group_row(conn, p, group_id), base)
    finally:
        conn.close()


def delete_group(p, group_id: str) -> None:
    conn = get_db_connection()
    try:
        _group_row(conn, p, group_id)
        members = [r[0] for r in conn.execute("SELECT user_id FROM scim_group_members WHERE group_id = ?", (group_id,))]
        conn.execute("DELETE FROM scim_group_members WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM scim_groups WHERE id = ?", (group_id,))
        for uid in members:
            recompute(conn, p, uid)
        conn.commit()
    finally:
        conn.close()
