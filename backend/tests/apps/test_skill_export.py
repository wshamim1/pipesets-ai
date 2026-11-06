"""Export a published app as an Agent Skill (exporters/skill_exporter.py): the zip's SKILL.md and run script,
and the script really running the app through /v1 on a live server. Exports only see the caller's
tenant / project."""
import io
import os
import subprocess
import sys
import zipfile

import pytest

import main
from helpers import hdr, mock_flow, serve
from services import api_keys
from services.request_context import RequestContext


@pytest.fixture(scope="module")
def app_id(client):
    app = client.post("/api/apps", headers=hdr(), json={
        "name": "Licence Status Check!", "description": "Checks a facility's licence status.",
        "flow_data": mock_flow("llm-1")}).json()
    return app["id"]


@pytest.fixture(scope="module")
def unzipped(client, app_id, tmp_path_factory):
    assert client.post(f"/api/apps/{app_id}/publish", headers=hdr()).status_code == 200
    res = client.get(f"/api/export/{app_id}", params={"format": "skill"}, headers=hdr())
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    assert 'filename="licence-status-check.zip"' in res.headers["content-disposition"]
    out = tmp_path_factory.mktemp("skill")
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        assert sorted(z.namelist()) == ["licence-status-check/SKILL.md", "licence-status-check/scripts/run.py"]
        z.extractall(out)
    return out / "licence-status-check"


@pytest.fixture(scope="module")
def base():
    yield from serve(main.app)


def test_draft_apps_cant_be_exported_as_skills(client):
    draft = client.post("/api/apps", headers=hdr(), json={"name": "Draft", "flow_data": mock_flow("d")}).json()
    res = client.get(f"/api/export/{draft['id']}/preview", params={"format": "skill"}, headers=hdr())
    assert res.status_code == 409 and "Publish" in res.json()["detail"]


def test_skill_md_has_frontmatter_and_no_secrets(unzipped, app_id):
    md = (unzipped / "SKILL.md").read_text()
    head = md.split("---")[1]
    assert "name: licence-status-check\n" in head
    assert 'description: "Checks a facility\'s licence status. Runs the \\"Licence Status Check!\\" pipeline' in head
    assert app_id in md and "PIPESETS_API_KEY" in md
    assert "Human approval" not in md, "no gate in this flow"
    script = (unzipped / "scripts" / "run.py").read_text()
    assert f'APP_ID = "{app_id}"' in script and "ps_" not in script


def test_preview_is_the_skill_md(client, app_id, unzipped):
    res = client.get(f"/api/export/{app_id}/preview", params={"format": "skill"}, headers=hdr())
    assert res.text == (unzipped / "SKILL.md").read_text()


def test_other_tenants_apps_cant_be_exported(client):
    from db import get_db_connection
    conn = get_db_connection()
    conn.execute("INSERT INTO apps (id, tenant_id, project_id, owner_user_id, name, description, flow_data, status, "
                 "version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 ("app_foreign", "tenant_other", "proj_other", "someone", "Theirs", "", "{}", "published", 1, "t", "t"))
    conn.commit()
    conn.close()
    for fmt in ("native_json", "skill"):
        assert client.get("/api/export/app_foreign", params={"format": fmt}, headers=hdr()).status_code == 404
        assert client.get("/api/export/app_foreign/preview", params={"format": fmt}, headers=hdr()).status_code == 404


def _run(unzipped, base, *args, key=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PIPESETS_")}
    env["PIPESETS_BASE_URL"] = base
    if key:
        env["PIPESETS_API_KEY"] = key
    return subprocess.run([sys.executable, "-I", str(unzipped / "scripts" / "run.py"), *args],
                          capture_output=True, text=True, env=env, timeout=60)


def test_the_script_runs_the_published_app_over_v1(unzipped, base):
    key, _ = api_keys.create_key(RequestContext(tenant_id="tenant_demo", project_id="proj_research",
                                                user_id="user_admin"), "skill export test")
    done = _run(unzipped, base, "Is facility 42 licensed?", key=key)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip()

    missing = _run(unzipped, base, "hi")
    assert missing.returncode != 0 and "PIPESETS_API_KEY is not set" in missing.stderr

    bad = _run(unzipped, base, "hi", key="ps_wrong")
    assert bad.returncode == 1 and "HTTP 403" in bad.stderr


def test_gates_memory_and_docs_shape_the_skill():
    from exporters.skill_exporter import to_skill_md, to_skill_zip
    app = {"id": "app_x", "name": "Ops", "description": "", "docs": "# Ops\nDetails.",
           "flow_data": {"nodes": [{"id": "g", "type": "human_gate"}, {"id": "m", "type": "memory"}], "edges": []}}
    md = to_skill_md(app)
    assert "## Human approval" in md and "Never approve" in md and "--session" in md
    assert "[reference.md](reference.md)" in md
    assert 'description: "Runs the \\"Ops\\" pipeline on Pipesets.' in md
    with zipfile.ZipFile(io.BytesIO(to_skill_zip(app, "http://x"))) as z:
        assert z.read("ops/reference.md").decode() == "# Ops\nDetails."
