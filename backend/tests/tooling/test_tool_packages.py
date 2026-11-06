"""Settings → Tools & MCP packages: the default install set, tools a pipeline uses counting as
installed, install / uninstall / reset through the API, the ``installed`` flag on the catalog,
access rules, and that an uninstalled tool still runs."""
import asyncio

import pytest

import tools
from helpers import hdr
from services import tool_packages


@pytest.fixture(autouse=True)
def fresh(client):
    client.delete("/api/tools/packages", headers=hdr())
    yield
    client.delete("/api/tools/packages", headers=hdr())


def catalog_flags(client):
    sections = client.get("/api/tools", headers=hdr()).json()["categories"]
    return {t["id"]: t.get("installed") for s in sections for t in s["tools"]}


def packages(client):
    return {p["id"]: p for p in client.get("/api/tools/packages", headers=hdr()).json()["packages"]}


def test_defaults_are_real_packages():
    tools._load()
    known = {t["id"] for s in tools.catalog() if s["id"] in tool_packages.SECTIONS for t in s["tools"]}
    assert tool_packages.DEFAULTS <= known, tool_packages.DEFAULTS - known


def test_catalog_marks_installed_packages(client):
    flags = catalog_flags(client)
    assert flags["calculator"] is True and flags["mcp_filesystem"] is True, "defaults are installed"
    assert flags["snowflake_cortex_search"] is False and flags["mcp_snowflake_managed"] is False
    frameworks = [t for s in client.get("/api/tools", headers=hdr()).json()["categories"]
                  if s["id"] == "frameworks" for t in s["tools"]]
    assert frameworks and all("installed" not in t for t in frameworks), "frameworks aren't packages"


def test_install_uninstall_and_reset(client):
    r = client.put("/api/tools/packages", json={"tool_ids": ["snowflake_catalog", "mcp_databricks"], "installed": True},
                   headers=hdr())
    assert r.status_code == 200 and all(p["installed"] and p["source"] == "choice" for p in r.json()["packages"])
    client.put("/api/tools/packages", json={"tool_ids": ["calculator"], "installed": False}, headers=hdr())
    flags = catalog_flags(client)
    assert flags["snowflake_catalog"] and flags["mcp_databricks"] and flags["calculator"] is False

    p = packages(client)["calculator"]
    assert p == {"id": "calculator", "installed": False, "source": "choice", "in_use": p["in_use"], "default": True}

    assert client.delete("/api/tools/packages", headers=hdr()).status_code == 200
    flags = catalog_flags(client)
    assert flags["calculator"] is True and flags["snowflake_catalog"] is False


def test_tools_used_by_a_pipeline_count_as_installed(client):
    flow = {"nodes": [{"id": "t", "type": "tool", "data": {"label": "Genie", "toolId": "databricks_genie",
                                                          "toolType": "tool", "config": {}}}], "edges": []}
    app_id = client.post("/api/apps", json={"name": "Uses genie", "flow_data": flow}, headers=hdr()).json()["id"]
    try:
        tool_packages.clear_cache()
        p = packages(client)["databricks_genie"]
        assert p["installed"] and p["source"] == "in_use" and p["in_use"]
        client.put("/api/tools/packages", json={"tool_ids": ["databricks_genie"], "installed": False}, headers=hdr())
        assert catalog_flags(client)["databricks_genie"] is False, "an explicit uninstall wins"
    finally:
        client.delete(f"/api/apps/{app_id}", headers=hdr())


def test_unknown_ids_and_access(client):
    r = client.put("/api/tools/packages", json={"tool_ids": ["nope"], "installed": True}, headers=hdr())
    assert r.status_code == 404 and "nope" in r.json()["detail"]
    r = client.put("/api/tools/packages", json={"tool_ids": ["calculator"], "installed": False},
                   headers=hdr("user_viewer", "proj_support"))
    assert r.status_code == 403
    assert client.delete("/api/tools/packages", headers=hdr("user_viewer", "proj_support")).status_code == 403


def test_changes_are_audited(client):
    client.put("/api/tools/packages", json={"tool_ids": ["snowflake_task"], "installed": True}, headers=hdr())
    entries = client.get("/api/audit-log?action=tool_package", headers=hdr()).json()
    rows = entries.get("entries", entries) if isinstance(entries, dict) else entries
    assert any(e["action"] == "tool_package.update" for e in rows)


def test_uninstalled_tools_still_run(client):
    client.put("/api/tools/packages", json={"tool_ids": ["calculator"], "installed": False}, headers=hdr())
    assert asyncio.run(tools.execute("calculator", "", {}, {"expression": "2 + 3"})) == "2 + 3 = 5"
