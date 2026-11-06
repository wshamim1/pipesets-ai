"""Contract every built-in tool keeps (tools/ registry), run offline: whatever the input, run()
returns a string and never raises; a tool missing a required config key says which one and
gives up before touching the network; and the spec is consistent with the catalog.

The network is cut for the whole module — sockets, plus the clients that don't go through
Python's socket module (ddgs, psycopg2, MCP servers started as subprocesses) — so a tool that
reaches for it has to turn the failure into a message like any other error."""
import asyncio
import os
import socket
import sys
import types

import pytest

import tools

RUNNABLE = sorted(sid for sid in (s.id for s in tools.all_specs()) if sid in tools._runners)
REQUIRING = sorted(s.id for s in tools.all_specs() if s.required)
INPUTS = ["", "hello", '{"broken": ', "x" * 5000, "ünïcödé ✓ — '; DROP TABLE t; --"]
TIMEOUT_S = 10
# Env vars a tool may fall back to for a required key (BRAVE_API_KEY, WOLFRAM_APP_ID, …)
FALLBACK_ENV_SUFFIXES = ("_API_KEY", "_APP_ID", "_TOKEN", "_WEBHOOK_URL")


class Offline(OSError):
    pass


@pytest.fixture
def offline(monkeypatch):
    """Cut the network; return the list of attempts made."""
    attempts = []

    def refuse(*args, **_kwargs):
        attempts.append(args[1:] or args)
        raise Offline("network disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)

    async def no_subprocess(*args, **_kwargs):
        refuse(None, *args)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_subprocess)

    class DDGS:
        def __init__(self, *a, **k):
            pass

        def text(self, *a, **k):
            refuse(None, "ddgs")
    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=DDGS))
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(
        connect=lambda *a, **k: refuse(None, "psycopg2"), Error=Exception, OperationalError=Exception))

    for name in list(os.environ):
        if name.endswith(FALLBACK_ENV_SUFFIXES):
            monkeypatch.delenv(name)
    return attempts


def call(tool_id, inp, cfg):
    return asyncio.run(asyncio.wait_for(tools._runners[tool_id](inp, cfg, tool_id), TIMEOUT_S))


@pytest.mark.parametrize("tool_id", RUNNABLE)
def test_returns_a_string_and_never_raises(tool_id, offline, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # file tools resolve relative paths here, not in the repo
    cfg = dict(tools.get_spec(tool_id).default_config)
    for inp in INPUTS:
        result = call(tool_id, inp, dict(cfg))
        assert isinstance(result, str), (tool_id, inp[:40], result)


@pytest.mark.parametrize("tool_id", REQUIRING)
def test_refuses_a_missing_required_key_offline(tool_id, offline):
    spec = tools.get_spec(tool_id)
    filled = {**spec.default_config, **{k: f"test-{k}" for k in spec.required}}
    for missing in spec.required:
        for absent in (None, ""):
            cfg = dict(filled)
            if absent is None:
                cfg.pop(missing)
            else:
                cfg[missing] = absent
            result = call(tool_id, "hello", cfg)
            assert isinstance(result, str) and missing in result, (tool_id, missing, result)
    assert not offline, f"{tool_id} reached for the network before checking its required keys"


def test_specs_are_consistent():
    for spec in tools.all_specs():
        assert spec.id and spec.name and spec.description, spec.id
        assert len(set(spec.required)) == len(spec.required), spec.id
        for key in spec.required:
            assert key in spec.default_config, f"{spec.id}: required key {key!r} has no config field"
        for key, select in spec.selects.items():
            values = [v for v, _ in select.options]
            assert values, (spec.id, key)
            if key in spec.default_config:
                assert spec.default_config[key] in values, (spec.id, key, spec.default_config[key])


def test_every_catalog_tool_runs():
    """A catalog entry without run() executes as a placeholder echo — only frameworks may do that."""
    for spec in tools.all_specs():
        if spec.id not in tools._runners and not spec.hidden:
            assert spec.group == "frameworks" or spec.id.startswith("mcp_"), spec.id
