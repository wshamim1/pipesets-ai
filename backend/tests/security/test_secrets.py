"""The encrypted secrets vault: API, write-only values, encryption at rest, ACLs, project /
tenant scoping, run-time resolution of "secret://" refs, sealed values in connections, flows,
webhooks and channels, migration 0009, log redaction, master key providers and rotation.
The tests are steps of one scenario, in order."""
import asyncio
import base64
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.fernet import Fernet

from db import get_db_connection
from helpers import hdr, mock_flow
from routers.tools import execute_tool_real
from services import master_key, secret_store
from services import webhooks as webhook_service
from services.llm_auth import resolve_api_key
from services.pipeline_runner import RunScope, _resolve_key, current_scope

VALUE = "serper-key-1234567890abcd"
SLACK_URL = "https://hooks.slack.com/services/T000/B000/XXXXSECRET"
BODY = b'{"x": 1}'
state = {}   # records created by earlier steps


def raw(secret_id):
    conn = get_db_connection()
    try:
        return dict(conn.execute("SELECT * FROM secrets WHERE id = ?", (secret_id,)).fetchone())
    finally:
        conn.close()


def column(table, col, row_id):
    conn = get_db_connection()
    try:
        return conn.execute(f"SELECT {col} FROM {table} WHERE id = ?", (row_id,)).fetchone()[col]
    finally:
        conn.close()


def in_scope(project, fn):
    async def go():
        token = current_scope.set(RunScope(tenant_id="tenant_demo", project_id=project, user_id="user_admin"))
        try:
            return fn()
        finally:
            current_scope.reset(token)
    return asyncio.run(go())


def tool_run(client, pattern, text, project="proj_research"):
    """The regex tool echoes matches, so a pattern that is a secret ref proves it was substituted."""
    return client.post("/api/tools/execute", headers=hdr(project=project), json={
        "tool_type": "regex_tool", "input_text": text, "config": {"pattern": pattern, "action": "findall"},
    }).json()["output"]


def flow_with(**data):
    return {"nodes": [{"id": "n1", "type": data.pop("type", "llm"), "data": {"label": "Answer", **data}}], "edges": []}


@pytest.fixture(scope="module", autouse=True)
def _no_provider_env(env):
    env.delenv("OPENAI_API_KEY", raising=False)


def test_create_and_list(client):
    r = client.post("/api/secrets", json={"name": "Serper prod", "value": VALUE, "provider": "Serper"}, headers=hdr())
    assert r.status_code == 201
    sec = state["sec"] = r.json()
    assert sec["ref"] == f"secret://{sec['id']}"
    assert VALUE not in r.text and "ciphertext" not in sec, "the value is never returned"
    assert sec["last4"] == "abcd" and sec["scope"] == "project" and sec["provider"] == "serper"

    listing = client.get("/api/secrets", headers=hdr())
    assert [s["id"] for s in listing.json()] == [sec["id"]]
    assert VALUE not in listing.text and "ciphertext" not in listing.text
    row = raw(sec["id"])
    assert VALUE not in row["ciphertext"] and secret_store.decrypt(row["ciphertext"]) == VALUE


def test_acls_and_scoping(client):
    sec = state["sec"]
    assert client.get("/api/secrets", headers=hdr("user_viewer")).status_code == 403
    assert client.get("/api/secrets", headers=hdr("user_analyst")).status_code == 200
    assert client.get("/api/secrets", headers=hdr("user_analyst", "proj_support")).status_code == 403
    assert client.get("/api/secrets", headers=hdr(project="proj_support")).json() == []
    assert client.put(f"/api/secrets/{sec['id']}", json={"value": "x"}, headers=hdr(project="proj_support")).status_code == 404

    shared = state["shared"] = client.post("/api/secrets", json={"name": "Shared Tavily", "value": "tvly-shared-9999",
                                                                 "shared": True}, headers=hdr()).json()
    assert shared["scope"] == "tenant" and shared["project_id"] is None
    assert [s["id"] for s in client.get("/api/secrets", headers=hdr(project="proj_support")).json()] == [shared["id"]]


def test_resolution_at_tool_run_time(client):
    sec = state["sec"]
    assert VALUE in tool_run(client, sec["ref"], f"token={VALUE};"), "substituted server-side"
    assert raw(sec["id"])["last_used_at"] is not None
    assert "not found in this project" in tool_run(client, sec["ref"], VALUE, project="proj_support")
    assert "signed-in request or pipeline run" in asyncio.run(execute_tool_real("regex_tool", VALUE, {"pattern": sec["ref"]})), \
        "outside a request or run, refs are refused"

    async def in_run_scope():
        token = current_scope.set(RunScope(tenant_id="tenant_demo", project_id="proj_research", user_id="user_admin"))
        try:
            return await execute_tool_real("regex_tool", VALUE, {"pattern": sec["ref"]})
        finally:
            current_scope.reset(token)
    assert VALUE in asyncio.run(in_run_scope()), "published / scheduled runs resolve through RunScope"
    plain = asyncio.run(execute_tool_real("regex_tool", "a1b2", {"pattern": r"\d"}))
    assert '"1"' in plain and '"2"' in plain, "configs without refs are untouched"


def test_update_and_delete(client):
    sec = state["sec"]
    upd = client.put(f"/api/secrets/{sec['id']}", json={"name": "Serper (rotated)", "value": "new-serper-key-WXYZ"},
                     headers=hdr()).json()
    assert upd["name"] == "Serper (rotated)" and upd["last4"] == "WXYZ"
    assert secret_store.decrypt(raw(sec["id"])["ciphertext"]) == "new-serper-key-WXYZ"
    assert client.delete(f"/api/secrets/{sec['id']}", headers=hdr()).status_code == 200
    assert "may have been deleted" in tool_run(client, sec["ref"], "x")


def test_llm_provider_defaults(client):
    d1 = state["d1"] = client.post("/api/secrets", json={"name": "OpenAI shared", "value": "sk-shared-1111", "shared": True,
                                                         "kind": "llm", "default_for": "openai"}, headers=hdr()).json()
    d2 = state["d2"] = client.post("/api/secrets", json={"name": "OpenAI research", "value": "sk-research-2222",
                                                         "kind": "llm", "default_for": "openai"}, headers=hdr()).json()
    assert d2["default_for"] == "openai"
    assert in_scope("proj_research", lambda: secret_store.default_ref("openai")) == d2["ref"], "project beats shared"
    assert in_scope("proj_support", lambda: secret_store.default_ref("openai")) == d1["ref"]
    assert in_scope("proj_research", lambda: resolve_api_key("openai", "")) == "sk-research-2222"
    assert in_scope("proj_research", lambda: resolve_api_key("openai", d1["ref"])) == "sk-shared-1111", "node ref wins"
    assert resolve_api_key("anthropic", "sk-ant-x") == "sk-ant-x", "plaintext passes through"
    assert in_scope("proj_research", lambda: resolve_api_key("anthropic", "")) == "", "no key → server env"
    assert "OPENAI_API_KEY" not in os.environ, "keys are never written to the process environment"
    assert in_scope("proj_research", lambda: _resolve_key("openai", "", {})) == d2["ref"]
    assert in_scope("proj_research", lambda: _resolve_key("openai", "", {"openai": "sk-x"})) == "sk-x"

    d3 = client.post("/api/secrets", json={"name": "OpenAI new", "value": "sk-new-3333", "kind": "llm",
                                           "default_for": "openai"}, headers=hdr()).json()
    defaults = {s["id"]: s["default_for"] for s in client.get("/api/secrets", headers=hdr()).json()}
    assert defaults[d2["id"]] is None, "claiming a default releases the previous one at the same scope"
    assert defaults[d1["id"]] == "openai", "…but leaves the shared default alone"
    client.put(f"/api/secrets/{d3['id']}", json={"default_for": ""}, headers=hdr())
    assert in_scope("proj_research", lambda: secret_store.default_ref("openai")) == d1["ref"]


def test_secret_kinds(client):
    shared, d1, d2 = state["shared"], state["d1"], state["d2"]
    assert shared["kind"] == "tool" and d2["kind"] == "llm"
    leak = tool_run(client, d1["ref"], "sk-shared-1111")
    assert "sk-shared-1111" not in leak and "is an LLM provider key and can't be used by tools" in leak
    with pytest.raises(secret_store.SecretError, match="tool / integration key and can't be used by model calls"):
        in_scope("proj_research", lambda: resolve_api_key("openai", shared["ref"]))
    assert client.post("/api/secrets", json={"name": "x", "value": "y", "kind": "tool", "default_for": "openai"},
                       headers=hdr()).status_code == 400
    assert client.post("/api/secrets", json={"name": "x", "value": "y", "kind": "admin"}, headers=hdr()).status_code == 422
    assert client.put(f"/api/secrets/{shared['id']}", json={"default_for": "openai"}, headers=hdr()).status_code == 400


def test_sealed_connection_credentials(client):
    from routers.connections import seal_plaintext_connections

    conn = client.post("/api/connections", headers=hdr(), json={
        "name": "PG", "type": "postgres",
        "config": {"host": "127.0.0.1", "port": "1", "database": "x", "user": "u", "password": "pg-pass-777"},
    }).json()
    assert "pg-pass-777" not in json.dumps(conn)
    assert secret_store.is_sealed(conn["config"]["password"])
    assert secret_store.unseal(conn["config"]["password"]) == "pg-pass-777"
    sealed_before = conn["config"]["password"]
    upd = client.put(f"/api/connections/{conn['id']}", headers=hdr(),
                     json={"config": {**conn["config"], "password": "", "host": "127.0.0.2"}}).json()
    assert upd["config"]["password"] == sealed_before, "a blank password keeps the saved one"
    upd = client.put(f"/api/connections/{conn['id']}", headers=hdr(),
                     json={"config": {**upd["config"], "password": "pg-pass-888"}}).json()
    assert secret_store.unseal(upd["config"]["password"]) == "pg-pass-888"
    state["conn"] = conn["id"]
    assert "pg-pass-888" in tool_run(client, upd["config"]["password"], "pw=pg-pass-888"), "tools get the unsealed value"

    # Legacy rows (saved before sealing) are sealed at startup — including Connection nodes in saved apps
    db = get_db_connection()
    db.execute("INSERT INTO connections (id, name, type, config, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
               ("conn_legacy", "Old", "mysql", json.dumps({"host": "h", "password": "legacy-pw"}), "t", "t"))
    legacy_flow = {"nodes": [{"id": "n1", "type": "connection",
                              "data": {"connection_id": "conn_legacy", "config": {"host": "h", "password": "legacy-pw"}}}]}
    db.execute("INSERT INTO apps (id, tenant_id, project_id, owner_user_id, name, description, flow_data, status, "
               "version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               ("app_legacy", "tenant_demo", "proj_research", "user_admin", "L", "", json.dumps(legacy_flow), "draft",
                0, "t", "t"))
    db.commit()
    db.close()
    assert seal_plaintext_connections() == 2
    assert "legacy-pw" not in column("connections", "config", "conn_legacy")
    assert "legacy-pw" not in column("apps", "flow_data", "app_legacy")
    assert "enc://" in column("apps", "flow_data", "app_legacy")
    assert seal_plaintext_connections() == 0, "idempotent"
    export = client.get("/api/export/app_legacy", params={"format": "langchain"}, headers=hdr())
    assert export.status_code == 200 and "enc://" not in export.text, "code exports drop sealed values"


def test_flows_refuse_plaintext_credentials(client):
    r = client.post("/api/apps", json={"name": "Leaky", "flow_data": flow_with(provider="openai",
                                                                               api_key="sk-typed-in-1234")}, headers=hdr())
    assert r.status_code == 422
    assert r.json()["detail"]["fields"] == ["Answer → api_key"]
    assert "sk-typed-in-1234" not in r.text
    ok_app = client.post("/api/apps", json={"name": "Refs", "flow_data": flow_with(
        provider="openai", api_key=state["d1"]["ref"], fallback_api_key=secret_store.seal("sk-fallback"),
        max_tokens=512)}, headers=hdr())
    assert ok_app.status_code == 200, "refs and sealed values save fine"
    url = f"/api/apps/{ok_app.json()['id']}"
    r = client.put(url, json={"flow_data": flow_with(type="tool", toolId="slack", config={
        "webhook_url": "https://hooks.slack.com/services/T0/B0/xyz", "channel": "#ops"})}, headers=hdr())
    assert r.status_code == 422 and r.json()["detail"]["fields"] == ["Answer → config.webhook_url"]
    r = client.put(url, json={"flow_data": flow_with(type="tool", toolId="wolfram_alpha", config={"app_id": "WOLF-123"})},
                   headers=hdr())
    assert r.status_code == 422, "a tool's app_id is a credential"
    r = client.put(url, json={"flow_data": {"nodes": [
        {"id": "a", "type": "child_agent", "data": {"label": "Sub", "kind": "pipeline", "app_id": "app-123"}},
        {"id": "e", "type": "embedding", "data": {"label": "Emb", "provider": "ollama", "api_key": "http://localhost:11434"}},
        {"id": "m", "type": "memory", "data": {"label": "Mem", "token_budget": 2000, "session_id": "s1"}},
    ]}}, headers=hdr())
    assert r.status_code == 200, "a pipeline app_id, a local server URL and token settings are not credentials"
    assert secret_store.plaintext_credentials(flow_with(api_key="http://u:pw@localhost:11434")) == ["Answer → api_key"]


def test_webhook_and_channel_secrets_sealed_at_rest(client):
    app = client.post("/api/apps", json={"name": "Hooked", "flow_data": mock_flow("m")}, headers=hdr()).json()
    client.post(f"/api/apps/{app['id']}/publish", headers=hdr())
    hook = state["hook"] = client.post("/api/webhooks", json={"app_id": app["id"], "secret": "hmac-signing-secret"},
                                       headers=hdr()).json()
    chan = state["chan"] = client.post("/api/notifications", json={"kind": "slack", "url": SLACK_URL}, headers=hdr()).json()
    stored = column("webhooks", "secret", hook["id"])
    assert secret_store.is_sealed(stored) and secret_store.open_sealed(stored) == "hmac-signing-secret"
    assert hook["has_secret"] is True and "hmac-signing" not in json.dumps(hook)
    assert secret_store.is_sealed(column("notification_channels", "url", chan["id"]))
    assert chan["url"] == "https://hooks.slack.com/…"
    sign = webhook_service.sign
    assert client.post(f"/v1/hooks/{hook['token']}", content=BODY,
                       headers={"X-Pipesets-Signature": sign("hmac-signing-secret", BODY)}).status_code == 202
    assert client.post(f"/v1/hooks/{hook['token']}", content=BODY,
                       headers={"X-Pipesets-Signature": sign("wrong", BODY)}).status_code == 401


def test_migration_0009_seals_legacy_plaintext():
    from alembic import command
    from alembic.config import Config

    from db import BACKEND_DIR, migrate, migration_connection

    def downgrade_to(rev):
        cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
        cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
        with migration_connection() as connection, connection.begin():
            cfg.attributes["connection"] = connection
            command.downgrade(cfg, rev)

    hook, chan = state["hook"], state["chan"]
    downgrade_to("0008_llm_settings")
    assert column("webhooks", "secret", hook["id"]) == "hmac-signing-secret", "downgrade opens the column"
    assert column("notification_channels", "url", chan["id"]) == SLACK_URL
    db = get_db_connection()
    db.execute("UPDATE apps SET flow_data = ? WHERE id = 'app_legacy'", (json.dumps(flow_with(
        provider="openai", api_key="sk-legacy-plain-5555", config={"app_id": "WOLF-1", "channel": "#x"})),))
    db.commit()
    db.close()

    migrate()
    assert secret_store.is_sealed(column("webhooks", "secret", hook["id"]))
    assert secret_store.is_sealed(column("notification_channels", "url", chan["id"]))
    legacy = json.loads(column("apps", "flow_data", "app_legacy"))
    assert secret_store.plaintext_credentials(legacy) == []
    assert secret_store.unseal(legacy["nodes"][0]["data"]["api_key"]) == "sk-legacy-plain-5555"
    assert legacy["nodes"][0]["data"]["config"]["channel"] == "#x"
    sealed_flow = column("apps", "flow_data", "app_legacy")
    downgrade_to("0008_llm_settings")
    migrate()
    assert column("apps", "flow_data", "app_legacy") == sealed_flow, "re-running doesn't double-seal"

    db = get_db_connection()
    dump = "\n".join(str(v) for t in ("apps", "app_versions", "webhooks", "notification_channels", "connections")
                     for r in db.execute(f"SELECT * FROM {t}").fetchall() for v in dict(r).values())
    db.close()
    assert not any(s in dump for s in ("hmac-signing-secret", "XXXXSECRET", "sk-legacy-plain", "legacy-pw", "pg-pass",
                                       "WOLF-1")), "no plaintext credential left in the DB"


@pytest.mark.parametrize("text, want", [
    ("key sk-proj-abcdefghijklmnop1234 used", "key sk-[REDACTED] used"),
    ("Authorization: Bearer ps_abcdefghijklmnopqrstuvwx", "Authorization: Bearer [REDACTED]"),
    ("X-API-Key header ps_abcdefghijklmnopqrstuvwx", "X-API-Key header ps_[REDACTED]"),
    ("Authorization: Bearer eyJhbGciOi.payload.sig", "Authorization: Bearer [REDACTED]"),
    ("POST /v1/hooks/whk_abcdefghijklmnopqrstuvwxyz HTTP/1.1", "POST /v1/hooks/whk_[REDACTED] HTTP/1.1"),
    ("cfg {'api_key': 'gsk_live_1234567890abcdef'}", "cfg {'api_key': '[REDACTED]'}"),
    ('body {"password": "hunter2!", "user": "a"}', 'body {"password": "[REDACTED]", "user": "a"}'),
    ("url https://hooks.slack.com/services/T0/B0/abc", "url https://hooks.slack.com/services/[REDACTED]"),
    ("sealed enc://gAAAAABkZ== value", "sealed enc://[REDACTED] value"),
    ("?key=AIzaSyA1234567890abcdefghijklmnopqrstu", "?key=AIza[REDACTED]"),
    ("max_tokens=512 and tokens: 40", "max_tokens=512 and tokens: 40"),
])
def test_redact(text, want):
    from services.log_redaction import redact
    assert redact(text) == want


def test_log_records_are_redacted():
    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.lines = []

        def emit(self, record):
            self.lines.append(self.format(record))

    cap = Capture()
    log = logging.getLogger("redaction-check")
    log.addHandler(cap)
    try:
        log.warning("calling with %s", "sk-ant-api03-abcdefghijklmnop")
        try:
            raise ValueError("bad key sk-abcdefghijklmnopqrstu")
        except ValueError:
            log.exception("failed")
    finally:
        log.removeHandler(cap)
    assert cap.lines[0] == "calling with sk-[REDACTED]"
    assert "sk-abcdefghijklmnopqrstu" not in cap.lines[1] and "sk-[REDACTED]" in cap.lines[1], "tracebacks too"
    access = logging.getLogger("uvicorn.access").makeRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "POST", "/v1/hooks/whk_abcdefghijklmnopqrstuv", "1.1", 202), None)
    assert isinstance(access.args, tuple) and len(access.args) == 5, "uvicorn access args keep their shape"
    assert access.args[2] == "/v1/hooks/whk_[REDACTED]"


class FakeKMS:
    """Encrypt = a marker prefix; enough to prove the wiring."""

    def encrypt(self, KeyId, Plaintext):
        return {"CiphertextBlob": b"kms:" + KeyId.encode() + b":" + Plaintext}

    def generate_data_key(self, KeyId, KeySpec):
        return {"CiphertextBlob": b"kms:" + KeyId.encode() + b":" + os.urandom(32)}

    def decrypt(self, CiphertextBlob):
        if not CiphertextBlob.startswith(b"kms:"):
            raise RuntimeError("InvalidCiphertextException")
        return {"Plaintext": CiphertextBlob.split(b":", 2)[2]}


@pytest.fixture
def fresh_cipher():
    """Re-read the master key before and after the test."""
    secret_store._fernet = None
    yield
    secret_store._fernet = None


def test_master_key_from_aws_kms(monkeypatch, fresh_cipher):
    monkeypatch.setattr(master_key, "_kms_client", lambda: FakeKMS())
    env_key = os.environ["PIPESETS_MASTER_KEY"]
    probe = secret_store.encrypt("kms-probe")
    wrapped = master_key.kms_wrap("alias/pipesets", env_key)
    fresh = master_key.kms_wrap("alias/pipesets")
    monkeypatch.delenv("PIPESETS_MASTER_KEY")
    monkeypatch.setenv("PIPESETS_MASTER_KEY_KMS", f"{fresh},{wrapped}")
    secret_store._fernet = None
    assert master_key.provider() == "aws_kms"
    assert secret_store.decrypt(probe) == "kms-probe", "KMS-wrapped keys decrypt existing values"
    assert secret_store._cipher()._fernets[0]._encryption_key != base64.urlsafe_b64decode(env_key)[16:], \
        "a fresh KMS data key becomes the primary key"
    monkeypatch.setenv("PIPESETS_MASTER_KEY_KMS", base64.b64encode(b"garbage").decode())
    with pytest.raises(master_key.MasterKeyError, match="KMS could not decrypt"):
        master_key.load_keys()


def test_master_key_from_vault(monkeypatch, fresh_cipher):
    env_key = os.environ["PIPESETS_MASTER_KEY"]
    probe = secret_store.encrypt("vault-probe")

    class VaultHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            ok = self.path == "/v1/secret/data/pipesets" and self.headers.get("X-Vault-Token") == "vt-123"
            body = json.dumps({"data": {"data": {"master_key": env_key}}} if ok else {"errors": ["denied"]}).encode()
            self.send_response(200 if ok else 403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    vault = HTTPServer(("127.0.0.1", 0), VaultHandler)
    threading.Thread(target=vault.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("VAULT_ADDR", f"http://127.0.0.1:{vault.server_port}")
        monkeypatch.setenv("VAULT_TOKEN", "vt-123")
        monkeypatch.setenv("PIPESETS_MASTER_KEY_VAULT_PATH", "secret/data/pipesets")
        monkeypatch.delenv("PIPESETS_MASTER_KEY")
        secret_store._fernet = None
        assert master_key.provider() == "vault"
        assert secret_store.decrypt(probe) == "vault-probe", "Vault KV v2 key decrypts existing values"
        monkeypatch.setenv("VAULT_TOKEN", "wrong")
        with pytest.raises(master_key.MasterKeyError, match="HTTP 403"):
            master_key.load_keys()
    finally:
        vault.shutdown()


def test_rotation(client, monkeypatch, fresh_cipher):
    old_key = os.environ["PIPESETS_MASTER_KEY"]
    new_key = Fernet.generate_key().decode()
    monkeypatch.setenv("PIPESETS_MASTER_KEY", f"{new_key},{old_key}")
    secret_store._fernet = None
    # 4 live secrets (shared + 3 OpenAI keys) + 2 sealed connection passwords (PG, legacy MySQL)
    # + 2 sealed values in app_legacy's flow + the webhook signing secret + the channel URL
    assert secret_store.rotate_all() == 10
    monkeypatch.setenv("PIPESETS_MASTER_KEY", new_key)
    secret_store._fernet = None
    assert secret_store.decrypt(raw(state["shared"]["id"])["ciphertext"]) == "tvly-shared-9999", "old key can go"
    pw = client.get(f"/api/connections/{state['conn']}", headers=hdr()).json()["config"]["password"]
    assert secret_store.unseal(pw) == "pg-pass-888"
    assert client.post(f"/v1/hooks/{state['hook']['token']}", content=BODY, headers={
        "X-Pipesets-Signature": webhook_service.sign("hmac-signing-secret", BODY)}).status_code == 202
    legacy = json.loads(column("apps", "flow_data", "app_legacy"))
    assert secret_store.unseal(legacy["nodes"][0]["data"]["api_key"]) == "sk-legacy-plain-5555"
