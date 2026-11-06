"""Picking up tool modules without a restart (tools.reload(), POST /api/tools/reload, TOOLS_AUTO_RELOAD):
new, edited, broken, deleted and duplicate modules, a changed helper reaching the tools that use it,
and who may trigger it. The modules live in a temp folder added to the package's search path, so the
source tree is never touched."""
import asyncio
import os
import sys
import textwrap

import pytest

import tools
from helpers import hdr


@pytest.fixture
def pkg(tmp_path, monkeypatch):
    """A folder searched as part of the ``tools`` package; write(name, source) adds or edits a module."""
    tools._load()
    monkeypatch.setattr(tools, "__path__", [*tools.__path__, str(tmp_path)])
    bumps = {}

    def write(name, source):
        path = tmp_path / f"{name}.py"
        path.write_text(textwrap.dedent(source))
        # mtimes can tie within one test; move each write forward so it reads as a change
        bumps[name] = bumps.get(name, 0) + 1
        os.utime(path, ns=(path.stat().st_mtime_ns + bumps[name] * 10**9,) * 2)
        return path

    yield write, tmp_path
    for f in tmp_path.glob("*.py"):
        f.unlink()
    monkeypatch.undo()
    tools.reload()
    assert not [n for n in sys.modules if n.startswith("tools.zz")]


def tool_source(tool_id, reply, extra=""):
    return f'''
        from tools.base import ToolSpec
        {extra}
        TOOL = ToolSpec(id="{tool_id}", name="{tool_id}", icon="x", description="test tool", category="Everyday Utilities")

        async def run(inp, cfg, tool_type):
            return {reply}
        '''


def execute(tool_id, inp="hi"):
    return asyncio.run(tools.execute(tool_id, inp, {}))


def test_new_edited_and_deleted_modules(pkg):
    write, folder = pkg
    assert tools.reload()["changed"] is False, "nothing on disk changed"

    write("zz_echo", tool_source("zz_echo", 'f"v1:{inp}"'))
    result = tools.reload()
    assert result["changed"] and result["added"] == ["zz_echo"] and result["errors"] == []
    assert execute("zz_echo") == "v1:hi"
    assert any(t["id"] == "zz_echo" for s in tools.catalog() for t in s["tools"])
    assert tools.reload()["changed"] is False

    write("zz_echo", tool_source("zz_echo", 'f"v2:{inp}"'))
    result = tools.reload()
    assert result["modules"] == 1 and result["added"] == [] and execute("zz_echo") == "v2:hi"

    (folder / "zz_echo.py").unlink()
    result = tools.reload()
    assert result["removed"] == ["zz_echo"] and tools.get_spec("zz_echo") is None
    assert "tools.zz_echo" not in sys.modules


def test_a_broken_edit_keeps_the_previous_version(pkg):
    write, _ = pkg
    write("zz_echo", tool_source("zz_echo", '"good"'))
    tools.reload()

    write("zz_echo", "def run(:\n")
    result = tools.reload()
    assert result["errors"][0]["module"] == "tools.zz_echo" and "SyntaxError" in result["errors"][0]["error"]
    assert execute("zz_echo") == "good", "the last working version still runs"
    assert tools.reload()["changed"] is False, "a broken file isn't retried until it changes again"

    write("zz_echo", tool_source("zz_echo", '"fixed"'))
    assert tools.reload()["errors"] == [] and execute("zz_echo") == "fixed"


def test_a_new_module_that_fails_to_import_is_skipped(pkg):
    write, _ = pkg
    write("zz_needs_dep", tool_source("zz_needs_dep", '"x"', extra="import zz_not_installed_anywhere"))
    write("zz_fine", tool_source("zz_fine", '"ok"'))
    result = tools.reload()
    assert result["added"] == ["zz_fine"]
    assert [e["module"] for e in result["errors"]] == ["tools.zz_needs_dep"]
    assert "ModuleNotFoundError" in result["errors"][0]["error"]
    assert tools.get_spec("zz_needs_dep") is None and execute("zz_fine") == "ok"


def test_a_changed_helper_reaches_the_tools_that_import_it(pkg):
    write, _ = pkg
    write("_zz_helper", 'GREETING = "hello"\n')
    write("zz_greeter", tool_source("zz_greeter", 'f"{GREETING} {inp}"', extra="from tools._zz_helper import GREETING"))
    tools.reload()
    assert execute("zz_greeter", "ana") == "hello ana"

    write("_zz_helper", 'GREETING = "hola"\n')
    result = tools.reload()
    assert result["modules"] > 2, "every module is re-imported when a helper changes"
    assert result["errors"] == [] and execute("zz_greeter", "ana") == "hola ana"
    assert execute("calculator", "2+2").endswith("4"), "built-in tools still work after a full reload"


def test_a_duplicate_id_is_reported_and_the_first_kept(pkg):
    write, _ = pkg
    write("zz_a", tool_source("zz_dup", '"a"'))
    write("zz_b", tool_source("zz_dup", '"b"'))
    result = tools.reload()
    assert result["added"] == ["zz_dup"] and execute("zz_dup") == "a"
    assert result["errors"] == [{"module": "tools.zz_b", "error": "Tool id 'zz_dup' is defined twice"}]


def test_reload_endpoint_is_for_server_admins(pkg, client):
    write, _ = pkg
    write("zz_echo", tool_source("zz_echo", '"v1"'))
    assert client.post("/api/tools/reload", headers=hdr("user_viewer")).status_code == 403
    assert tools.get_spec("zz_echo") is None

    r = client.post("/api/tools/reload", headers=hdr())
    assert r.status_code == 200 and r.json()["added"] == ["zz_echo"]
    assert client.get("/api/tools/packages", headers=hdr()).json()["can_reload"] is True
    assert client.get("/api/tools/packages", headers=hdr("user_analyst")).json()["can_reload"] is False


def test_auto_reload_picks_changes_up_when_the_catalog_is_fetched(pkg, client, monkeypatch):
    write, _ = pkg
    monkeypatch.setattr(tools, "_next_auto_check", 0.0)
    write("zz_echo", tool_source("zz_echo", '"v1"'))
    ids = lambda: {t["id"] for s in client.get("/api/tools", headers=hdr()).json()["categories"] for t in s["tools"]}  # noqa: E731
    assert "zz_echo" not in ids(), "off unless TOOLS_AUTO_RELOAD is set"

    monkeypatch.setenv("TOOLS_AUTO_RELOAD", "1")
    assert "zz_echo" in ids()
    write("zz_echo", tool_source("zz_echo", '"v2"'))
    assert execute("zz_echo") == "v1", "checked at most once a second"
    monkeypatch.setattr(tools, "_next_auto_check", 0.0)
    assert execute("zz_echo") == "v2", "a tool run checks too"
