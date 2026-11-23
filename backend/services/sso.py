"""
sso.py — single sign-on for workspaces: identity providers, sign-in state, provisioning and role mapping.

A workspace (tenant) owner adds identity providers in Settings → Single sign-on. Each provider speaks
OIDC (services/sso_oidc.py) or SAML 2.0 (services/sso_saml.py); this module holds what they share.

Sign-in
-------
1. The UI asks ``GET /api/auth/sso/discover?email=`` which providers cover the email's domain, then
   navigates to ``/api/auth/sso/{id}/start``. A single-use ``login`` state (10 minutes) records the
   nonce / PKCE verifier / SAML request id and where to send the browser back.
2. The IdP returns to the callback (OIDC) or ACS (SAML). The protocol module verifies the response and
   hands ``complete_login()`` a verified subject, email, name and the values of the role claim.
3. ``complete_login()`` links or creates the user, applies the role mapping and returns the user id.
   The router creates a session **scoped to the provider's tenant** and redirects to the UI with a
   one-time ``handoff`` code (60 s); the UI exchanges it for the session token, so the token never
   appears in a URL.

Security model
--------------
* A session made by SSO reaches only the tenant of the provider that vouched for the user, and never
  carries server-admin rights (services/request_context.py). A workspace owner controls their IdP, so
  they can only ever vouch for access to their own workspace.
* An IdP subject is linked to a Pipesets user once (``sso_identities``); later sign-ins match on the
  subject, not the email. A first sign-in links to an existing account with the same email only if
  that account already belongs to the workspace, or ``auto_provision`` is on (then it is added).
* ``email_domains`` restricts which emails a provider may assert.
* Roles: the highest role whose mapping value appears in the role claim; else ``default_role``; an
  empty default refuses the sign-in. With ``sync_roles`` the role and mapped groups are re-applied at
  every sign-in, except that the workspace's last owner is never demoted.
* ``enforce``: members (not owners — they keep password access as a break-glass) must use SSO for this
  workspace; password sessions can't open it.
"""

import json
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from db import get_db_connection, insert_ignore
from services import secret_store

log = logging.getLogger(__name__)

PROTOCOLS = ("oidc", "saml")
ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}
LOGIN_TTL = timedelta(minutes=10)
HANDOFF_TTL = timedelta(seconds=60)
MAX_MAPPINGS = 100
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$")

# Config keys per protocol, and which of them are secrets (sealed at rest, never returned)
CONFIG_KEYS = {
    "oidc": ("issuer", "client_id", "client_secret", "scopes", "email_claim", "name_claim"),
    "saml": ("idp_entity_id", "idp_sso_url", "idp_certificate", "email_attribute", "name_attribute",
             "name_id_format"),
}
SECRET_KEYS = {"client_secret"}


class SSOError(Exception):
    """A sign-in or configuration problem; the message is safe to show the user."""


def _now() -> datetime:
    return datetime.utcnow()


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


# ── URLs ──────────────────────────────────────────────────────────────────────

def public_base(request_base: str) -> str:
    """The backend's public base URL (callbacks / ACS / SP entity id)."""
    return (os.getenv("PIPESETS_PUBLIC_URL", "").strip() or request_base).rstrip("/")


def _origin(url: str) -> Optional[str]:
    p = urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}".lower()


def safe_return_to(return_to: str, request_base: str) -> str:
    """The UI origin to send the browser back to: ``return_to`` if it is a known UI origin (the
    backend's own, PIPESETS_APP_URL, PIPESETS_PUBLIC_URL or CORS_ORIGINS / CORS_ORIGIN_REGEX), else the
    default UI. Prevents the sign-in from being used as an open redirect."""
    default = (os.getenv("PIPESETS_APP_URL", "").strip() or public_base(request_base)).rstrip("/")
    origin = _origin(return_to)
    if not origin:
        return default
    allowed = {o for o in (_origin(default), _origin(public_base(request_base)), _origin(request_base)) if o}
    allowed |= {o for v in (os.getenv("CORS_ORIGINS") or "http://localhost:5173,http://127.0.0.1:5173").split(",")
                if (o := _origin(v.strip()))}
    regex = os.getenv("CORS_ORIGIN_REGEX")
    if origin in allowed or (regex and re.fullmatch(regex, origin)):
        return origin
    return default


# ── Providers ─────────────────────────────────────────────────────────────────

def _row_to_provider(row) -> Dict[str, Any]:
    p = dict(row)
    for k, default in (("config", {}), ("email_domains", []), ("role_mappings", [])):
        try:
            p[k] = json.loads(p.get(k) or json.dumps(default))
        except ValueError:
            p[k] = default
    for k in ("enabled", "auto_provision", "sync_roles", "enforce"):
        p[k] = bool(p.get(k))
    return p


def public_view(p: Dict[str, Any], request_base: str = "") -> Dict[str, Any]:
    """A provider as the admin UI sees it: secrets replaced by ``<key>_set`` flags, plus the URLs to
    register at the IdP."""
    cfg = {k: v for k, v in p["config"].items() if k not in SECRET_KEYS}
    for k in SECRET_KEYS & set(CONFIG_KEYS[p["protocol"]]):
        cfg[f"{k}_set"] = bool(p["config"].get(k))
    out = {k: p[k] for k in ("id", "tenant_id", "name", "protocol", "enabled", "email_domains", "role_claim",
                             "role_mappings", "default_role", "auto_provision", "sync_roles", "enforce",
                             "created_at", "updated_at")}
    out["config"] = cfg
    out["scim_enabled"] = bool(p.get("scim_token_hash"))
    out["scim_token_prefix"] = p.get("scim_token_prefix") or None
    if request_base:
        base = public_base(request_base)
        out["scim_base_url"] = f"{base}/scim/v2"
        if p["protocol"] == "oidc":
            out["redirect_uri"] = f"{base}/api/auth/sso/oidc/callback"
        else:
            out["sp_entity_id"] = f"{base}/api/auth/sso/saml/{p['id']}/metadata"
            out["acs_url"] = f"{base}/api/auth/sso/saml/{p['id']}/acs"
            out["metadata_url"] = out["sp_entity_id"]
    return out


def get_provider(provider_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        if tenant_id is None:
            row = conn.execute("SELECT * FROM sso_providers WHERE id = ?", (provider_id,)).fetchone()
        else:
            row = conn.execute("SELECT * FROM sso_providers WHERE id = ? AND tenant_id = ?",
                               (provider_id, tenant_id)).fetchone()
    finally:
        conn.close()
    return _row_to_provider(row) if row else None


def list_providers(tenant_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM sso_providers WHERE tenant_id = ? ORDER BY created_at",
                            (tenant_id,)).fetchall()
    finally:
        conn.close()
    return [_row_to_provider(r) for r in rows]


def secret(p: Dict[str, Any], key: str) -> str:
    value = p["config"].get(key) or ""
    return secret_store.unseal(value) if secret_store.is_sealed(value) else value


def _normalize_domains(domains: Iterable[str]) -> List[str]:
    out = []
    for d in domains or []:
        d = str(d).strip().lower().lstrip("@")
        if not d:
            continue
        if not _DOMAIN_RE.match(d):
            raise SSOError(f"'{d}' is not a valid email domain.")
        if d not in out:
            out.append(d)
    return out


def _normalize_mappings(mappings: Any, tenant_id: str, conn) -> List[Dict[str, str]]:
    if not isinstance(mappings, list):
        raise SSOError("role_mappings must be a list.")
    if len(mappings) > MAX_MAPPINGS:
        raise SSOError(f"At most {MAX_MAPPINGS} role mappings.")
    out = []
    for m in mappings:
        if not isinstance(m, dict) or not str(m.get("value") or "").strip():
            raise SSOError("Each role mapping needs a claim value.")
        role = str(m.get("role") or "").strip()
        group_id = str(m.get("group_id") or "").strip()
        if role and role not in ROLE_RANK:
            raise SSOError(f"Unknown role '{role}'. Use owner, editor or viewer.")
        if not role and not group_id:
            raise SSOError(f"The mapping for '{m['value']}' needs a role, a group or both.")
        if group_id and not conn.execute("SELECT 1 FROM groups WHERE id = ? AND tenant_id = ?",
                                         (group_id, tenant_id)).fetchone():
            raise SSOError(f"Group '{group_id}' is not in this workspace.")
        out.append({"value": str(m["value"]).strip(), "role": role, "group_id": group_id})
    return out


def _validate_config(protocol: str, cfg: Dict[str, Any]) -> None:
    from services import sso_oidc, sso_saml  # lazy: they import this module

    (sso_oidc if protocol == "oidc" else sso_saml).validate_config(cfg)


def save_provider(tenant_id: str, user_id: str, fields: Dict[str, Any],
                  provider_id: Optional[str] = None) -> Dict[str, Any]:
    """Create (no ``provider_id``) or update a provider. Secrets left empty on update are kept."""
    current = get_provider(provider_id, tenant_id) if provider_id else None
    if provider_id and not current:
        raise LookupError("Identity provider not found")
    protocol = (current or {}).get("protocol") or str(fields.get("protocol") or "").lower()
    if protocol not in PROTOCOLS:
        raise SSOError("protocol must be oidc or saml.")

    cfg = dict((current or {}).get("config") or {})
    for k, v in (fields.get("config") or {}).items():
        if k not in CONFIG_KEYS[protocol]:
            continue
        v = "" if v is None else str(v).strip()
        if k in SECRET_KEYS:
            if v:
                cfg[k] = secret_store.seal(v)
            continue
        cfg[k] = v
    _validate_config(protocol, {**cfg, **{k: secret({"config": cfg}, k) for k in SECRET_KEYS if k in cfg}})

    name = str(fields.get("name", (current or {}).get("name", "")) or "").strip()
    if not name:
        raise SSOError("Give the identity provider a name.")
    default_role = str(fields.get("default_role", (current or {}).get("default_role", "viewer")) or "").strip()
    if default_role and default_role not in ROLE_RANK:
        raise SSOError("default_role must be owner, editor, viewer or empty (refuse unmapped users).")
    if default_role == "owner":
        raise SSOError("default_role can't be owner. Map an IdP group to the owner role instead.")

    def flag(key: str, default: bool) -> int:
        return 1 if bool(fields.get(key, (current or {}).get(key, default))) else 0

    conn = get_db_connection()
    try:
        mappings = _normalize_mappings(fields.get("role_mappings", (current or {}).get("role_mappings", [])),
                                       tenant_id, conn)
        row = {
            "name": name[:200],
            "enabled": flag("enabled", True),
            "config": json.dumps(cfg),
            "email_domains": json.dumps(_normalize_domains(fields.get("email_domains",
                                                                      (current or {}).get("email_domains", [])))),
            "role_claim": str(fields.get("role_claim", (current or {}).get("role_claim", "")) or "").strip()[:200],
            "role_mappings": json.dumps(mappings),
            "default_role": default_role,
            "auto_provision": flag("auto_provision", True),
            "sync_roles": flag("sync_roles", True),
            "enforce": flag("enforce", False),
            "updated_at": _iso(),
        }
        if current:
            conn.execute(f"UPDATE sso_providers SET {', '.join(f'{k} = ?' for k in row)} WHERE id = ?",
                         (*row.values(), provider_id))
        else:
            provider_id = f"sso_{uuid.uuid4().hex[:12]}"
            row.update({"id": provider_id, "tenant_id": tenant_id, "protocol": protocol, "created_by": user_id,
                        "created_at": row["updated_at"]})
            conn.execute(f"INSERT INTO sso_providers ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                         tuple(row.values()))
        conn.commit()
    finally:
        conn.close()
    return get_provider(provider_id, tenant_id)


def delete_provider(provider_id: str, tenant_id: str) -> bool:
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM sso_providers WHERE id = ? AND tenant_id = ?",
                            (provider_id, tenant_id)).fetchone():
            return False
        conn.execute("DELETE FROM sso_identities WHERE provider_id = ?", (provider_id,))
        conn.execute("DELETE FROM sso_states WHERE provider_id = ?", (provider_id,))
        # SCIM's records go with it; the memberships it created stay (an owner can remove people)
        conn.execute("DELETE FROM scim_group_members WHERE group_id IN (SELECT id FROM scim_groups WHERE provider_id = ?)",
                     (provider_id,))
        conn.execute("DELETE FROM scim_groups WHERE provider_id = ?", (provider_id,))
        conn.execute("DELETE FROM scim_users WHERE provider_id = ?", (provider_id,))
        # Sessions it created end with it
        conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE sso_provider_id = ? AND revoked_at IS NULL",
                     (_iso(), provider_id))
        conn.execute("DELETE FROM sso_providers WHERE id = ?", (provider_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def providers_for_email(email: str) -> List[Dict[str, Any]]:
    """Enabled providers whose email domains cover ``email`` — what the sign-in screen offers."""
    domain = email.strip().lower().rsplit("@", 1)[-1] if "@" in email else ""
    if not domain:
        return []
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT p.*, t.name AS tenant_name FROM sso_providers p JOIN tenants t ON t.id = p.tenant_id "
            "WHERE p.enabled = 1 AND t.status = 'active' ORDER BY p.created_at").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        p = _row_to_provider(r)
        if domain in p["email_domains"]:
            out.append({"id": p["id"], "name": p["name"], "protocol": p["protocol"],
                        "workspace": r["tenant_name"]})
    return out


def enforced_tenants(conn) -> set:
    """Tenants where members must sign in with SSO (an enabled provider has ``enforce``)."""
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT tenant_id FROM sso_providers WHERE enabled = 1 AND enforce = 1").fetchall()}


# ── Single-use state ──────────────────────────────────────────────────────────

def put_state(provider_id: str, kind: str, data: Dict[str, Any], ttl: timedelta) -> str:
    state_id = secrets.token_urlsafe(32)
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM sso_states WHERE expires_at < ?", (_iso(),))
        conn.execute("INSERT INTO sso_states (id, provider_id, kind, data, expires_at) VALUES (?, ?, ?, ?, ?)",
                     (state_id, provider_id, kind, secret_store.seal(json.dumps(data)), _iso(_now() + ttl)))
        conn.commit()
    finally:
        conn.close()
    return state_id


def take_state(state_id: str, kind: str) -> Tuple[str, Dict[str, Any]]:
    """Consume a state: (provider id, data). Raises SSOError when unknown, used or expired."""
    if not state_id or len(state_id) > 128:
        raise SSOError("This sign-in link is invalid. Start again.")
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT provider_id, data, expires_at FROM sso_states WHERE id = ? AND kind = ?",
                           (state_id, kind)).fetchone()
        # Single use even under concurrent callbacks: only the request that deletes the row proceeds
        deleted = conn.execute("DELETE FROM sso_states WHERE id = ? AND kind = ?", (state_id, kind)).rowcount if row else 0
        conn.commit()
    finally:
        conn.close()
    if not row or deleted != 1 or row["expires_at"] < _iso():
        raise SSOError("This sign-in has expired or was already used. Start again.")
    return row["provider_id"], json.loads(secret_store.unseal(row["data"]))


# ── Completing a sign-in ──────────────────────────────────────────────────────

def map_roles(p: Dict[str, Any], claim_values: Iterable[str]) -> Tuple[Optional[str], List[str], List[str]]:
    """(role or None to refuse, groups to add, groups the mapping manages) for the claim values."""
    values = {str(v).strip() for v in claim_values if str(v).strip()}
    role, groups, managed = None, [], []
    for m in p["role_mappings"]:
        if m.get("group_id"):
            managed.append(m["group_id"])
        if m["value"] in values:
            if m.get("role") and (role is None or ROLE_RANK[m["role"]] > ROLE_RANK[role]):
                role = m["role"]
            if m.get("group_id") and m["group_id"] not in groups:
                groups.append(m["group_id"])
    return role or (p["default_role"] or None), groups, managed


def claim_values(value: Any) -> List[str]:
    """A role claim as a list of strings (a list, a single string, or a space/comma separated string)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if isinstance(v, (str, int))]
    if isinstance(value, str):
        return [v for v in re.split(r"[,\s]+", value) if v] if ("," in value or " " in value) else [value]
    return [str(value)]


def complete_login(p: Dict[str, Any], *, subject: str, email: str, name: str = "",
                   claims: Iterable[str] = ()) -> str:
    """Link or create the user behind a verified assertion and apply the role mapping → user id."""
    if not p["enabled"]:
        raise SSOError("This sign-in method is turned off.")
    subject = (subject or "").strip()
    email = (email or "").strip().lower()
    if not subject:
        raise SSOError("The identity provider didn't send a user identifier.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise SSOError("The identity provider didn't send a valid email address. Map the email claim or attribute.")
    domain = email.rsplit("@", 1)[1]
    if p["email_domains"] and domain not in p["email_domains"]:
        raise SSOError(f"Emails at {domain} can't sign in with {p['name']}.")

    role, groups, managed = map_roles(p, claims)
    unassigned = "Your account isn't assigned to Pipesets in the identity provider. Ask your administrator."

    tenant_id, now = p["tenant_id"], _iso()
    conn = get_db_connection()
    try:
        link = conn.execute("SELECT user_id FROM sso_identities WHERE provider_id = ? AND subject = ?",
                            (p["id"], subject)).fetchone()
        user_id = link["user_id"] if link else None
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() if user_id else None
        if user_id and not user:          # the linked account was deleted: link again from scratch
            conn.execute("DELETE FROM sso_identities WHERE provider_id = ? AND subject = ?", (p["id"], subject))
            user_id = None
        if not user_id:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if user:
                member = conn.execute("SELECT 1 FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?",
                                      (tenant_id, user["id"])).fetchone()
                if not member and not p["auto_provision"]:
                    raise SSOError("Your account isn't a member of this workspace. Ask an owner to add you.")
                user_id = user["id"]
            elif not p["auto_provision"]:
                raise SSOError("There's no Pipesets account for this email. Ask an owner to add you.")
            else:
                user_id = f"user_{uuid.uuid4().hex[:8]}"
                conn.execute(
                    "INSERT INTO users (id, email, display_name, status, password_hash, server_admin, created_at, "
                    "updated_at) VALUES (?, ?, ?, 'active', NULL, 0, ?, ?)",
                    (user_id, email, (name or email.split("@")[0]).strip()[:100], now, now))
                user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            conn.execute("INSERT INTO sso_identities (provider_id, subject, user_id, email, created_at) "
                         "VALUES (?, ?, ?, ?, ?)", (p["id"], subject, user_id, email, now))
        if user["status"] != "active":
            raise SSOError("This account is disabled.")

        current = conn.execute("SELECT role FROM tenant_memberships WHERE tenant_id = ? AND user_id = ?",
                               (tenant_id, user_id)).fetchone()
        # With SCIM on, the IdP provisions this workspace's members, their roles and groups (services/scim.py)
        scim_row = conn.execute("SELECT s.active FROM scim_users s JOIN sso_providers p ON p.id = s.provider_id "
                                "WHERE s.provider_id = ? AND s.user_id = ? AND p.scim_token_hash IS NOT NULL",
                                (p["id"], user_id)).fetchone()
        if scim_row is not None and not scim_row["active"]:
            raise SSOError("Your organization has turned off your access to this workspace.")
        if scim_row is not None:
            if not current:
                raise SSOError(unassigned)
            groups, managed = [], []          # SCIM keeps roles and groups; nothing to sync from the claims
        elif role is None:
            raise SSOError(unassigned)
        elif not current:
            if not p["auto_provision"]:
                raise SSOError("Your account isn't a member of this workspace. Ask an owner to add you.")
            conn.execute("INSERT INTO tenant_memberships (tenant_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
                         (tenant_id, user_id, role, now))
        elif p["sync_roles"] and current["role"] != role:
            last_owner = current["role"] == "owner" and conn.execute(
                "SELECT COUNT(1) FROM tenant_memberships WHERE tenant_id = ? AND role = 'owner'",
                (tenant_id,)).fetchone()[0] <= 1
            if last_owner:
                log.warning("SSO role mapping would demote the last owner of %s; kept owner", tenant_id)
            else:
                conn.execute("UPDATE tenant_memberships SET role = ? WHERE tenant_id = ? AND user_id = ?",
                             (role, tenant_id, user_id))

        if scim_row is None and (p["sync_roles"] or not current):
            for gid in managed:
                if gid not in groups:
                    conn.execute("DELETE FROM group_memberships WHERE group_id = ? AND user_id = ? AND tenant_id = ?",
                                 (gid, user_id, tenant_id))
            for gid in groups:
                if conn.execute("SELECT 1 FROM groups WHERE id = ? AND tenant_id = ?", (gid, tenant_id)).fetchone():
                    insert_ignore(conn, "group_memberships",
                                  {"group_id": gid, "user_id": user_id, "tenant_id": tenant_id, "created_at": now},
                                  key=("group_id", "user_id"))

        conn.execute("UPDATE sso_identities SET last_login_at = ?, email = ? WHERE provider_id = ? AND subject = ?",
                     (now, email, p["id"], subject))
        conn.commit()
    finally:
        conn.close()
    return user_id


def record_login(p: Dict[str, Any], user_id: str, outcome: str, ip: str, detail: str = "") -> None:
    """An ``sso.login`` entry in the workspace's audit log (the route middleware can't: the caller
    isn't signed in yet)."""
    from services import audit

    try:
        audit.record(tenant_id=p["tenant_id"], project_id="", actor=user_id or "anonymous", action="sso.login",
                     target_id=p["id"], outcome=outcome, status=200 if outcome == "success" else 403,
                     method="GET" if p["protocol"] == "oidc" else "POST",
                     path=f"/api/auth/sso/{p['protocol']}" + (f" ({detail[:200]})" if detail else ""), ip=ip)
    except Exception:  # auditing must not break sign-in
        log.exception("couldn't record sso.login")
