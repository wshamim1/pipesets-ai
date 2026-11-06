"""
secret_store.py — encrypted storage for API keys and tokens used by tools.

Values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) under a master key from
``PIPESETS_MASTER_KEY``, AWS KMS or HashiCorp Vault (see services/master_key.py). Several
keys are accepted: the first encrypts, all of them decrypt, so a key can be rotated by
prepending a new one and running ``python manage.py rotate-secrets``. Without any of them, a
key is generated once into ``.secrets_master_key`` in the data folder (paths.DATA_DIR —
``backend/`` unless ``PIPESETS_DATA_DIR`` is set; fine for local dev, not for production).

Secrets are write-only over the API: listings return the name and last 4 characters,
never the value. Tool configs reference a secret as ``"secret://<id>"`` and the value is
substituted server-side just before the tool runs (``resolve_refs``), so it never lives
in a saved flow, an export or the browser.

A secret belongs to a tenant and either one project or, with project_id NULL, every
project in the tenant. A secret can be the project's default key for an LLM provider
(``default_for``), used whenever a model node has no key of its own.

Every secret has a kind, enforced whenever it is decrypted: ``llm`` keys only reach
model/embedding calls, ``tool`` keys only reach tools. So a pipeline author can't route
the OpenAI key into, say, the HTTP tool's headers (or a Serper key into a model call).

Sealed values (``"enc://<ciphertext>"``) are the inline form, used for connection
credentials: the ciphertext itself travels in the config (opaque to the browser) and is
decrypted at the same point refs are resolved, without a lookup. Webhook signing secrets
and notification channel URLs are stored sealed too.

Saved flows may hold credentials only as refs or sealed values: ``plaintext_credentials``
lists the offending fields so the apps API can refuse the save.
"""

import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from db import get_db_connection
from services import master_key

logger = logging.getLogger("pipesets-ai-backend")

KINDS = ("llm", "tool")
KIND_LABELS = {"llm": "an LLM provider key", "tool": "a tool / integration key"}

REF_PREFIX = "secret://"
SEALED_PREFIX = "enc://"
_REF_RE = re.compile(r"^secret://([A-Za-z0-9_-]+)$")

# (tenant_id, project_id) of the current request — bound per request in main.py so tool
# execution deep in the call stack can resolve references without threading ctx through.
request_scope: ContextVar[Optional[Tuple[str, str]]] = ContextVar("secret_request_scope", default=None)

_fernet: Optional[MultiFernet] = None


class SecretError(Exception):
    pass


# ── Encryption ────────────────────────────────────────────────────────────────

def _cipher() -> MultiFernet:
    global _fernet
    if _fernet is None:
        _fernet = MultiFernet([Fernet(k) for k in master_key.load_keys()])
    return _fernet


def encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise SecretError("Secret can't be decrypted — was PIPESETS_MASTER_KEY changed?") from e


# ── CRUD ──────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat()


def _public(row) -> Dict[str, Any]:
    d = dict(row)
    d.pop("ciphertext", None)
    d["scope"] = "tenant" if d.get("project_id") is None else "project"
    d["ref"] = f"{REF_PREFIX}{d['id']}"
    return d


_COLUMNS = ("id, tenant_id, project_id, name, kind, provider, default_for, last4, created_by, created_at, "
            "updated_at, last_used_at")


def list_secrets(tenant_id: str, project_id: str) -> List[Dict[str, Any]]:
    """Secrets visible in a project: its own plus tenant-wide ones."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM secrets WHERE tenant_id = ? AND (project_id = ? OR project_id IS NULL) "
            "ORDER BY name",
            (tenant_id, project_id),
        ).fetchall()
        return [_public(r) for r in rows]
    finally:
        conn.close()


def get_secret(secret_id: str, tenant_id: str, project_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM secrets WHERE id = ? AND tenant_id = ? AND (project_id = ? OR project_id IS NULL)",
            (secret_id, tenant_id, project_id),
        ).fetchone()
        return _public(row) if row else None
    finally:
        conn.close()


def _claim_default(conn, secret_id: str, tenant_id: str, scope_project: Optional[str], provider: str) -> None:
    """Make ``secret_id`` the only default for ``provider`` at its own scope level."""
    scope_sql = "project_id IS NULL" if scope_project is None else "project_id = ?"
    conn.execute(
        f"UPDATE secrets SET default_for = NULL WHERE tenant_id = ? AND {scope_sql} AND default_for = ? AND id <> ?",
        (tenant_id, *([] if scope_project is None else [scope_project]), provider, secret_id),
    )


def _check_kind(kind: str, default_for: Optional[str]) -> None:
    if kind not in KINDS:
        raise SecretError(f"Unknown secret kind '{kind}' (use one of: {', '.join(KINDS)}).")
    if default_for and kind != "llm":
        raise SecretError("Only LLM provider keys can be a provider's default key.")


def create_secret(tenant_id: str, project_id: str, user_id: str, name: str, value: str,
                  provider: str = "", shared: bool = False, default_for: str = "",
                  kind: str = "tool") -> Dict[str, Any]:
    secret_id = f"sec_{uuid.uuid4().hex[:16]}"
    now = _now()
    scope_project = None if shared else project_id
    default_for = default_for.strip().lower() or None
    _check_kind(kind, default_for)
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO secrets (id, tenant_id, project_id, name, kind, provider, default_for, ciphertext, last4, "
            "created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (secret_id, tenant_id, scope_project, name.strip(), kind, provider.strip().lower(), default_for,
             encrypt(value), value[-4:], user_id, now, now),
        )
        if default_for:
            _claim_default(conn, secret_id, tenant_id, scope_project, default_for)
        conn.commit()
    finally:
        conn.close()
    return get_secret(secret_id, tenant_id, project_id)  # type: ignore[return-value]


def update_secret(secret_id: str, tenant_id: str, project_id: str, name: Optional[str] = None,
                  value: Optional[str] = None, provider: Optional[str] = None,
                  default_for: Optional[str] = None, kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """``default_for``: None leaves it, "" clears it, a provider name claims that default."""
    existing = get_secret(secret_id, tenant_id, project_id)
    if not existing:
        return None
    new_default = existing["default_for"] if default_for is None else (default_for.strip().lower() or None)
    _check_kind(kind or existing["kind"], new_default)
    sets, params = ["updated_at = ?"], [_now()]
    if name is not None:
        sets.append("name = ?")
        params.append(name.strip())
    if provider is not None:
        sets.append("provider = ?")
        params.append(provider.strip().lower())
    if value is not None:
        sets += ["ciphertext = ?", "last4 = ?"]
        params += [encrypt(value), value[-4:]]
    if default_for is not None:
        sets.append("default_for = ?")
        params.append(default_for.strip().lower() or None)
    if kind is not None:
        sets.append("kind = ?")
        params.append(kind)
    conn = get_db_connection()
    try:
        conn.execute(f"UPDATE secrets SET {', '.join(sets)} WHERE id = ? AND tenant_id = ?",
                     (*params, secret_id, tenant_id))
        if default_for:
            _claim_default(conn, secret_id, tenant_id, existing["project_id"], default_for.strip().lower())
        conn.commit()
    finally:
        conn.close()
    return get_secret(secret_id, tenant_id, project_id)


def delete_secret(secret_id: str, tenant_id: str, project_id: str) -> bool:
    if not get_secret(secret_id, tenant_id, project_id):
        return False
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM secrets WHERE id = ? AND tenant_id = ?", (secret_id, tenant_id))
        conn.commit()
    finally:
        conn.close()
    return True


def _rotate_sealed_tree(value: Any) -> Tuple[Any, int]:
    """``value`` with every sealed string at any depth re-encrypted under the primary key."""
    if is_sealed(value):
        token = _cipher().rotate(value[len(SEALED_PREFIX):].encode("ascii")).decode("ascii")
        return SEALED_PREFIX + token, 1
    if isinstance(value, dict):
        out, n = {}, 0
        for k, v in value.items():
            out[k], c = _rotate_sealed_tree(v)
            n += c
        return out, n
    if isinstance(value, list):
        pairs = [_rotate_sealed_tree(v) for v in value]
        return [v for v, _ in pairs], sum(c for _, c in pairs)
    return value, 0


def rotate_all() -> int:
    """Re-encrypt every secret and sealed value (connection credentials, credentials in saved
    flows, webhook signing secrets, notification URLs, MCP OAuth tokens, chat link tokens) under the
    primary (first) master key.
    Returns how many values were re-encrypted."""
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT id, ciphertext FROM secrets").fetchall()
        for r in rows:
            conn.execute("UPDATE secrets SET ciphertext = ? WHERE id = ?",
                         (_cipher().rotate(r["ciphertext"].encode("ascii")).decode("ascii"), r["id"]))
        count = len(rows)
        # (table, JSON column, key columns)
        for table, col, keys in (("connections", "config", ("id",)), ("apps", "flow_data", ("id",)),
                                 ("app_versions", "flow_data", ("app_id", "version"))):
            for r in conn.execute(f"SELECT {', '.join(keys)}, {col} FROM {table}").fetchall():
                try:
                    doc = json.loads(r[col] or "{}")
                except ValueError:
                    continue
                rotated, n = _rotate_sealed_tree(doc)
                if n:
                    conn.execute(f"UPDATE {table} SET {col} = ? WHERE {' AND '.join(f'{k} = ?' for k in keys)}",
                                 (json.dumps(rotated), *(r[k] for k in keys)))
                    count += n
        for table, col in (("webhooks", "secret"), ("notification_channels", "url"), ("custom_mcp_servers", "oauth"),
                           ("chat_links", "token_sealed")):
            for r in conn.execute(f"SELECT id, {col} FROM {table} WHERE {col} LIKE 'enc://%'").fetchall():
                conn.execute(f"UPDATE {table} SET {col} = ? WHERE id = ?", (_rotate_sealed_tree(r[col])[0], r["id"]))
                count += 1
        conn.commit()
        return count
    finally:
        conn.close()


# ── Sealed (inline-encrypted) values ──────────────────────────────────────────

def seal(value: str) -> str:
    return SEALED_PREFIX + encrypt(value)


def is_sealed(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(SEALED_PREFIX) and len(value) > len(SEALED_PREFIX)


def unseal(value: str) -> str:
    return decrypt(value[len(SEALED_PREFIX):])


def is_protected(value: Any) -> bool:
    """A vault ref or a sealed value — never plaintext, and only meaningful on this server."""
    return is_ref(value) or is_sealed(value)


def open_sealed(value: Optional[str]) -> Optional[str]:
    """Plaintext of a sealed column value (webhook secret, channel URL); anything else as is."""
    return unseal(value) if is_sealed(value) else value


# ── Credentials in saved flows ────────────────────────────────────────────────

# Node fields that hold credentials. Mirrors isSecretConfigKey in frontend/src/utils/secrets.ts;
# "max_tokens", "project_key" and the like deliberately don't match.
_CREDENTIAL_KEY_RE = re.compile(
    r"(^|_)(api_?key|api_?secret|token|secret|secret_key|password|passwd|webhook_url|access_key_id|"
    r"secret_access_key|routing_key|integration_key|connection_string|dsn|private_key)$",
    re.I,
)


def _is_base_url(value: str) -> bool:
    """An http(s) address with nothing secret in it. Ollama / llama.cpp embedding nodes keep
    their server's base URL in the "api_key" field (see routers/retrieval.py)."""
    u = urlparse(value.strip())
    return u.scheme in ("http", "https") and bool(u.netloc) and not u.username and not u.password and not u.query


def _plaintext_fields(value: Any, in_config: bool = False, path: str = ""):
    """(container, key, path) of every non-empty credential string that isn't a ref or sealed.
    ``app_id`` is a credential only inside a tool's ``config`` (Wolfram Alpha); elsewhere it
    names a pipeline."""
    if isinstance(value, dict):
        for k, v in value.items():
            sub = f"{path}.{k}" if path else str(k)
            if isinstance(v, str):
                key = str(k)
                if (v.strip() and not is_protected(v.strip())
                        and (_CREDENTIAL_KEY_RE.search(key) or (in_config and key == "app_id"))
                        and not (key.lower().endswith("api_key") and _is_base_url(v))):
                    yield value, k, sub
            else:
                yield from _plaintext_fields(v, in_config or k == "config", sub)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _plaintext_fields(v, in_config, f"{path}[{i}]")


def _flow_nodes(flow: Any) -> List[Dict[str, Any]]:
    nodes = flow.get("nodes") if isinstance(flow, dict) else None
    return [n for n in nodes or [] if isinstance(n, dict) and isinstance(n.get("data"), dict)]


def plaintext_credentials(flow: Any) -> List[str]:
    """"<node label> → <field>" for each credential a flow holds in plain text."""
    return [f"{node['data'].get('label') or node.get('id') or 'node'} → {path}"
            for node in _flow_nodes(flow) for _, _, path in _plaintext_fields(node["data"])]


def seal_flow_credentials(flow: Any) -> int:
    """Seal, in place, every plaintext credential in a flow's nodes. Returns how many."""
    count = 0
    for node in _flow_nodes(flow):
        for container, key, _ in list(_plaintext_fields(node["data"])):
            container[key] = seal(container[key].strip())
            count += 1
    return count


# ── Resolving references at run time ──────────────────────────────────────────

def _current_scope() -> Optional[Tuple[str, str]]:
    # Published/API/scheduled runs carry a RunScope; interactive requests bind request_scope
    from services.pipeline_runner import current_scope  # lazy: avoids an import cycle
    run_scope = current_scope.get()
    if run_scope is not None:
        return run_scope.tenant_id, run_scope.project_id
    return request_scope.get()


def current_scope_ids() -> Optional[Tuple[str, str]]:
    """(tenant_id, project_id) of the run or request in progress, or None outside one."""
    return _current_scope()


def _reveal(secret_id: str, scope: Tuple[str, str], purpose: str) -> str:
    tenant_id, project_id = scope
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT name, kind, ciphertext FROM secrets WHERE id = ? AND tenant_id = ? "
            "AND (project_id = ? OR project_id IS NULL)",
            (secret_id, tenant_id, project_id),
        ).fetchone()
        if not row:
            raise SecretError(f"Secret '{secret_id}' was not found in this project — it may have been deleted.")
        if row["kind"] != purpose:
            user = "model calls" if purpose == "llm" else "tools"
            raise SecretError(f"Secret '{row['name']}' is {KIND_LABELS.get(row['kind'], row['kind'])} "
                              f"and can't be used by {user}. Pick {KIND_LABELS[purpose]}.")
        conn.execute("UPDATE secrets SET last_used_at = ? WHERE id = ?", (_now(), secret_id))
        conn.commit()
        return decrypt(row["ciphertext"])
    finally:
        conn.close()


def is_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_REF_RE.match(value))


def resolve_refs(config: Dict[str, Any], purpose: str = "tool") -> Dict[str, Any]:
    """Copy of ``config`` with every "secret://<id>" ref and "enc://" sealed value replaced
    by the decrypted plaintext. ``purpose`` ("tool" | "llm") must match each secret's kind."""
    values = list(_walk(config))
    if not any(is_protected(v) for v in values):
        return config
    scope = _current_scope() if any(is_ref(v) for v in values) else None
    if scope is None and any(is_ref(v) for v in values):
        raise SecretError("Secrets can only be used inside a signed-in request or pipeline run.")

    def sub(value: Any) -> Any:
        if is_sealed(value):
            return unseal(value)
        if is_ref(value):
            return _reveal(_REF_RE.match(value).group(1), scope, purpose)  # type: ignore[union-attr,arg-type]
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [sub(v) for v in value]
        return value

    return sub(config)


def reveal_value(value: Any, purpose: str = "tool") -> str:
    """A single key that may be plaintext, a "secret://" ref or a sealed value → plaintext."""
    if not isinstance(value, str) or not value:
        return value or ""
    if is_protected(value):
        return resolve_refs({"v": value}, purpose)["v"]
    return value


def default_ref(provider: str, scope: Optional[Tuple[str, str]] = None) -> str:
    """The "secret://" ref of the default key for ``provider`` (project default beats a
    shared one), or "" when there is none or no scope to look in."""
    scope = scope or _current_scope()
    provider = (provider or "").strip().lower()
    if not scope or not provider:
        return ""
    tenant_id, project_id = scope
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id FROM secrets WHERE tenant_id = ? AND default_for = ? AND (project_id = ? OR project_id IS NULL) "
            "ORDER BY CASE WHEN project_id IS NULL THEN 1 ELSE 0 END LIMIT 1",
            (tenant_id, provider, project_id),
        ).fetchone()
        return f"{REF_PREFIX}{row['id']}" if row else ""
    finally:
        conn.close()


def _walk(value: Any):
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)
    else:
        yield value
