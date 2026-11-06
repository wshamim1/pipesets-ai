"""A3 hardening: MCP stdio servers get a scrubbed environment, not the backend's, and every
response carries the browser security headers."""
import asyncio
import json
import sys

from services.child_env import scrubbed_env
from tools.mcp._stdio import execute_stdio

# A minimal MCP server: answers the handshake, then returns its environment as the tool result.
FAKE_SERVER = r"""
import json, os, sys
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {}}), flush=True)
    elif msg.get("method") == "tools/call":
        text = json.dumps(dict(os.environ))
        print(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                          "result": {"content": [{"type": "text", "text": text}]}}), flush=True)
"""


def test_scrubbed_env_keeps_only_allowlisted_vars():
    base = {"PATH": "/bin", "HOME": "/h", "LC_ALL": "C", "HTTPS_PROXY": "http://proxy",
            "PIPESETS_MASTER_KEY": "k", "OPENAI_API_KEY": "sk-x", "DATABASE_URL": "postgres://u:p@h/db"}
    assert scrubbed_env({"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp"}, base=base) == {
        "PATH": "/bin", "HOME": "/h", "LC_ALL": "C", "HTTPS_PROXY": "http://proxy",
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp"}


def test_mcp_stdio_child_does_not_see_backend_secrets(env, tmp_path):
    env.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    env.setenv("DATABASE_URL", "postgres://u:p@h/db")
    script = tmp_path / "server.py"
    script.write_text(FAKE_SERVER)

    def prepare(config, input_text, args, env_vars, defaults):
        env_vars["SERVER_TOKEN"] = "configured"
        return args, "dump_env", {}

    out = asyncio.run(execute_stdio("mcp_fake", "", {}, {"command": sys.executable, "args": [str(script)]}, prepare))
    child_env = json.loads(out)
    assert child_env["SERVER_TOKEN"] == "configured"
    assert "PATH" in child_env
    for leaked in ("OPENAI_API_KEY", "DATABASE_URL", "PIPESETS_MASTER_KEY", "PIPESETS_DATA_DIR"):
        assert leaked not in child_env, leaked


def test_api_response_has_security_headers(client):
    r = client.get("/health")
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in r.headers   # plain HTTP


def test_hsts_only_over_https(client):
    r = client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["strict-transport-security"].startswith("max-age=")


def test_docs_page_gets_relaxed_csp(client):
    r = client.get("/docs")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in csp and "frame-ancestors 'none'" in csp
