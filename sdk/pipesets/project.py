"""
A tool project on disk — what ``pipesets tool init`` writes and ``deploy`` reads:

    jira_lookup/
      pipesets.toml       name, entry file, description, icon, config keys
      tool.py             the @tool function
      requirements.txt    pip specs installed into the tool's sandbox (one per line)
      tests/test_tool.py  pytest, using pipesets.testing — no backend needed

``pipesets.toml``::

    [tool]
    name = "jira_lookup"
    entry = "tool.py"
    description = ""            # optional; default: @tool(description=...) or the docstring
    icon = "🔧"
    config_keys = []            # added to @tool(secrets=[...])
"""

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MANIFEST = "pipesets.toml"


@dataclass
class Project:
    root: str
    name: str
    entry: str = "tool.py"
    description: str = ""
    icon: str = "🔧"
    config_keys: List[str] = field(default_factory=list)

    @property
    def entry_path(self) -> str:
        return os.path.join(self.root, self.entry)

    def requirements(self) -> List[str]:
        path = os.path.join(self.root, "requirements.txt")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            return [line.split("#")[0].strip() for line in fh if line.split("#")[0].strip()]

    def bundle(self, note: Optional[str] = None) -> Dict[str, Any]:
        """The body of PUT /v1/tools/{name}."""
        with open(self.entry_path, encoding="utf-8") as fh:
            code = fh.read()
        body: Dict[str, Any] = {"code": code, "description": self.description, "icon": self.icon,
                                "requirements": self.requirements(), "config_keys": self.config_keys}
        if note:
            body["note"] = note
        return body


def _parse_toml(text: str) -> Dict[str, Any]:
    try:
        import tomllib   # Python 3.11+
        return tomllib.loads(text)
    except ModuleNotFoundError:
        pass
    # The flat form `init` writes: [section], key = "string" | ["a", "b"] | true / false / numbers
    import ast
    out: Dict[str, Any] = {}
    section = out
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"\[([\w.-]+)\]", line)
        if m:
            section = out.setdefault(m.group(1), {})
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ValueError(f"{MANIFEST}: can't read line {raw!r}")
        value = value.strip()
        section[key.strip()] = {"true": True, "false": False}.get(value) if value in ("true", "false") \
            else ast.literal_eval(value)
    return out


def find(start: str = ".") -> Project:
    """The project whose pipesets.toml is in ``start`` or a parent directory."""
    here = os.path.abspath(start)
    while True:
        path = os.path.join(here, MANIFEST)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                data = _parse_toml(fh.read()).get("tool", {})
            if not data.get("name"):
                raise ValueError(f"{path}: [tool] needs a name")
            return Project(root=here, name=data["name"], entry=data.get("entry", "tool.py"),
                           description=data.get("description", ""), icon=data.get("icon", "🔧"),
                           config_keys=list(data.get("config_keys", [])))
        parent = os.path.dirname(here)
        if parent == here:
            raise FileNotFoundError(f"No {MANIFEST} here or in a parent directory (run `pipesets tool init <name>`)")
        here = parent


TOOL_TEMPLATE = '''"""{name} — a Pipesets custom tool."""
from pipesets import tool


@tool(description="Describe what {name} does, for the model", secrets=[])
def {name}(query: str, limit: int = 5, *, config) -> str:
    """One line on what the tool does.

    Args:
        query: What to look up
        limit: How many results to return
    """
    return f"{{limit}} results for {{query}}"
'''

TEST_TEMPLATE = '''from pipesets.testing import call, load

{name} = load("tool.py")


def test_{name}_answers():
    assert call({name}, {{"query": "hello"}}) == "5 results for hello"


def test_{name}_checks_its_arguments():
    import pytest
    from pipesets.testing import ToolArgumentError
    with pytest.raises(ToolArgumentError):
        call({name}, {{}})
'''

MANIFEST_TEMPLATE = '''[tool]
name = "{name}"
entry = "tool.py"
description = ""
icon = "🔧"
config_keys = []
'''


def init(name: str, directory: Optional[str] = None) -> str:
    """Scaffold a tool project; returns its directory."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name):
        raise ValueError("A tool name is a Python identifier: letters, digits and _, not starting with a digit")
    root = os.path.abspath(directory or name)
    if os.path.exists(os.path.join(root, MANIFEST)):
        raise FileExistsError(f"{root} already has a {MANIFEST}")
    os.makedirs(os.path.join(root, "tests"), exist_ok=True)
    files = {MANIFEST: MANIFEST_TEMPLATE, "tool.py": TOOL_TEMPLATE, "requirements.txt": "",
             os.path.join("tests", "test_tool.py"): TEST_TEMPLATE}
    for rel, template in files.items():
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(template.format(name=name))
    return root
