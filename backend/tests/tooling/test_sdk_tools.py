"""
The SDK side of tools as code (sdk/pipesets): the @tool schema matches what the server reads from the
same code (they're two implementations — runtime type hints vs. the syntax tree — so this guards
drift), pipesets.testing calls tools as a run would, and a scaffolded project deploys as is.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "sdk"))

from pipesets import project, testing  # noqa: E402
from pipesets.tooling import schema  # noqa: E402

from services.tool_signature import analyze  # noqa: E402

CODES = {
    "weather": '''
from typing import Annotated, List, Literal, Optional
from pipesets import tool

@tool(description="Weather", secrets=["token"])
def weather(city: str, units: Literal["metric", "imperial"] = "metric", days: Annotated[int, "how many"] = 1,
            tags: Optional[List[str]] = None, strict: bool = False, *, config) -> dict:
    """Weather.

    Args:
        city: City name
    """
    return {"city": city, "units": units, "days": days, "token": config.get("token")}
''',
    "plain": "def run(query: str, limit: int = 3):\n    return query * limit\n",
}


def _load(tmp_path, name, code):
    path = tmp_path / f"{name}.py"
    path.write_text(code)
    return testing.load(str(path))


@pytest.mark.parametrize("name", list(CODES))
def test_sdk_and_server_read_the_same_schema(tmp_path, name):
    assert schema(_load(tmp_path, name, CODES[name])) == analyze(CODES[name]).parameters


def test_testing_calls_tools_as_a_run_would(tmp_path):
    weather = _load(tmp_path, "weather", CODES["weather"])
    assert testing.call(weather, {"city": "Oslo"}, config={"token": "t"}) == \
        {"city": "Oslo", "units": "metric", "days": 1, "token": "t"}
    assert testing.output(weather, {"city": "Oslo"}).startswith('{"city": "Oslo"')
    with pytest.raises(testing.ToolArgumentError, match="must be one of"):
        testing.call(weather, {"city": "Oslo", "units": "kelvin"})
    legacy = _load(tmp_path, "legacy", "def run(input_text, config):\n    return input_text.upper()\n")
    assert testing.call(legacy, {"input": "hi"}) == "HI"


def test_a_scaffolded_project_reads_back_and_bundles(tmp_path):
    root = project.init("jira_lookup", str(tmp_path / "jira_lookup"))
    (tmp_path / "jira_lookup" / "requirements.txt").write_text("requests>=2.31  # http\n\n")
    proj = project.find(os.path.join(root, "tests"))
    assert (proj.name, proj.entry, proj.root) == ("jira_lookup", "tool.py", root), "found from a subdirectory"
    bundle = proj.bundle(note="abc123")
    assert bundle["requirements"] == ["requests>=2.31"] and bundle["note"] == "abc123"
    sig = analyze(bundle["code"])
    assert sig.entrypoint == "jira_lookup" and sig.parameters["required"] == ["query"], "the template deploys"
    assert testing.call(testing.load(proj.entry_path), {"query": "x"}) == "5 results for x"
    with pytest.raises(FileExistsError):
        project.init("jira_lookup", root)
    with pytest.raises(ValueError):
        project.init("not-an-identifier", str(tmp_path / "bad"))


def test_the_manifest_reader_without_tomllib():
    text = '[tool]\nname = "x"  # the name\nentry = "main.py"\nconfig_keys = ["a", "b"]\nicon = "🔧"\nflag = true\n'
    import builtins
    real_import = builtins.__import__

    def no_tomllib(name, *a, **kw):
        if name == "tomllib":
            raise ModuleNotFoundError(name)
        return real_import(name, *a, **kw)
    builtins.__import__ = no_tomllib
    try:
        data = project._parse_toml(text)
    finally:
        builtins.__import__ = real_import
    assert data == {"tool": {"name": "x", "entry": "main.py", "config_keys": ["a", "b"], "icon": "🔧", "flag": True}}
