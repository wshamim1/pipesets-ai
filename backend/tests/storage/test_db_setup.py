"""Choosing the database from Settings → Database on a fresh install (services/db_setup.py,
/api/system/database/setup|test). The copy itself is tested in test_db_copy.py; here the copy is
stubbed so the rules around it — who, when, where DATABASE_URL is saved — run on any CI leg."""

import os
import stat

import pytest
from dotenv import dotenv_values

import db
from helpers import hdr, mock_flow
from services import db_copy, db_setup

ADMIN = hdr()
ANALYST = hdr("user_analyst")
TARGET = {"host": "db.example.internal", "port": 5432, "database": "pipesets", "user": "app",
          "password": "p@ss:w/rd", "sslmode": "require"}


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(db_setup, "ENV_FILE", str(path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return path


@pytest.fixture
def fake_copy(monkeypatch):
    calls = []
    monkeypatch.setattr(db_setup, "test_connection", lambda t: {"ok": True, "message": "Connected", "empty": True})
    monkeypatch.setattr(db_setup, "copy_database",
                        lambda src, dst, **kw: calls.append((src, dst, kw)) or db_copy.CopyReport(rows={"users": 3}))
    return calls


def test_config_source(env_file, monkeypatch):
    assert db_setup.config_source() == "default"
    env_file.write_text('DATABASE_URL="postgresql+psycopg2://a@h/d"\n')
    assert db_setup.config_source() == "env_file"
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://a@h/d")   # what load_dotenv does at start
    assert db_setup.config_source() == "env_file"
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://other@h/d")
    assert db_setup.config_source() == "environment", "the process environment wins over .env"
    env_file.unlink()
    monkeypatch.setenv("DATABASE_URL", "")
    assert db_setup.config_source() == "environment", "Compose sets it even when empty"


def test_only_server_admins(client, env_file):
    for method, path in (("get", "/api/system/database/setup"), ("post", "/api/system/database/test"),
                         ("post", "/api/system/database/setup")):
        kwargs = {"json": TARGET} if method == "post" else {}
        assert getattr(client, method)(path, headers=ANALYST, **kwargs).status_code == 403, path


def test_apply_copies_and_saves_the_url_for_the_next_start(client, env_file, fake_copy):
    state = client.get("/api/system/database/setup", headers=ADMIN).json()
    assert state["can_configure"] is True and state["source"] == "default" and state["pending_restart"] is None

    r = client.post("/api/system/database/setup", json=TARGET, headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["restart_required"] and r.json()["copied_rows"] == 3

    src, dst, kw = fake_copy[0]
    assert src == db.DATABASE_URL and kw["skip_orphans"] is True
    saved = dotenv_values(env_file)["DATABASE_URL"]
    assert saved == "postgresql+psycopg2://app:p%40ss%3Aw%2Frd@db.example.internal:5432/pipesets?sslmode=require", \
        "the password is URL-escaped, and the test-only connect_timeout isn't saved"
    assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600, "it holds a password"

    state = client.get("/api/system/database/setup", headers=ADMIN).json()
    assert state["pending_restart"] == "postgresql+psycopg2://app:***@db.example.internal:5432/pipesets?sslmode=require"
    assert "p@ss" not in str(state)

    entry = client.get("/api/audit-log", params={"action": "database."}, headers=ADMIN).json()["entries"][0]
    assert entry["action"] == "database.configure" and entry["outcome"] == "success"


def test_other_settings_in_env_are_kept(client, env_file, fake_copy):
    env_file.write_text("OPENAI_API_KEY=sk-keep-me\n# a comment\n")
    assert client.post("/api/system/database/setup", json=TARGET, headers=ADMIN).status_code == 200
    values = dotenv_values(env_file)
    assert values["OPENAI_API_KEY"] == "sk-keep-me" and values["DATABASE_URL"].startswith("postgresql")
    assert "# a comment" in env_file.read_text()


def test_refused_when_the_environment_sets_it(client, env_file, fake_copy, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    state = client.get("/api/system/database/setup", headers=ADMIN).json()
    assert state["can_configure"] is False and "environment" in state["reasons"][0]
    r = client.post("/api/system/database/setup", json=TARGET, headers=ADMIN)
    assert r.status_code == 409 and not fake_copy and not env_file.exists()


def test_refused_once_pipelines_exist(client, env_file, fake_copy):
    client.post("/api/apps", json={"name": "Real work", "flow_data": mock_flow()}, headers=ADMIN)
    state = client.get("/api/system/database/setup", headers=ADMIN).json()
    assert state["can_configure"] is False and "db copy" in state["reasons"][0] and "apps" in state["reasons"][0]
    assert client.post("/api/system/database/setup", json=TARGET, headers=ADMIN).status_code == 409


def test_connection_failure_is_reported_not_raised(client):
    r = client.post("/api/system/database/test", headers=ADMIN,
                    json={**TARGET, "host": "127.0.0.1", "port": 1, "sslmode": "disable"})
    assert r.status_code == 200 and r.json()["ok"] is False and "Couldn't connect" in r.json()["message"]
    bad = client.post("/api/system/database/test", headers=ADMIN, json={**TARGET, "sslmode": "sometimes"})
    assert bad.status_code == 422
