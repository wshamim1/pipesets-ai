"""
base.py — building blocks for built-in tools.

A tool is a module under ``backend/tools/`` that defines:

    TOOL = ToolSpec(id=..., name=..., icon=..., description=..., category=..., ...)

    async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> str:
        ...

``inp`` is the stripped input, ``cfg`` the node config with every "secret://" ref and
sealed value already decrypted (by the registry, never by the tool). A module serving
several ids defines ``TOOLS = [...]`` instead of ``TOOL``. A spec without ``run`` is
listed in the catalog only.

The spec is the single source of truth: the catalog served by ``GET /api/tools``, the
dropdowns in the Tool panel (``selects``) and missing-key validation (``required``) are
all generated from it.

Typed parameters: a spec with ``parameters`` (a JSON schema, e.g. from ``query_params``) is
offered to the model as a real function. One argument (``input_param``) becomes ``inp``, and every
other declared argument overrides the node config key of the same name for that call. Or
``to_input`` builds ``inp`` from the arguments (``json_input`` / ``json_value`` for tools that read
JSON), and only the arguments in ``config_args`` override config. Only declared arguments ever reach ``cfg``, so
keep credentials, base URLs and other node settings out of ``parameters``. A spec without them
gets one ``input`` string, as before.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Select:
    """A config setting with a fixed set of choices — rendered as a dropdown."""
    label: str
    options: Sequence[Tuple[str, str]]  # (value, label)
    hint: str = ""

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"label": self.label, "options": [{"value": v, "label": l} for v, l in self.options]}
        if self.hint:
            out["hint"] = self.hint
        return out


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    icon: str
    description: str
    default_config: Dict[str, Any] = field(default_factory=dict)
    type: str = "tool"              # tool | mcp
    group: str = "agentic_tools"    # catalog section: agentic_tools | mcp_servers | frameworks
    category: str = ""              # sidebar sub-group (built-in tools only)
    order: int = 1000               # position within its category; ties sort by name
    required: Tuple[str, ...] = ()  # config keys the tool can't run without
    selects: Dict[str, Select] = field(default_factory=dict)
    hidden: bool = False            # runnable (old pipelines) but not offered in the catalog
    is_new: bool = False            # show a "NEW" badge in the sidebar
    parameters: Optional[Dict[str, Any]] = None   # JSON schema the model calls it with; None = one input string
    input_param: str = ""           # the argument that becomes ``inp``
    to_input: Optional[Callable[[Dict[str, Any]], str]] = field(default=None, compare=False)
    config_args: Tuple[str, ...] = ()   # with to_input: the arguments that override config instead

    def call_input(self, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """(inp, config overrides) for a call with typed ``args``."""
        props = (self.parameters or {}).get("properties", {})
        if self.to_input:
            overrides = {k: args[k] for k in self.config_args if k in props and args.get(k) is not None}
            return self.to_input({k: v for k, v in args.items() if k not in self.config_args}), overrides
        overrides = {k: v for k, v in args.items() if k in props and k != self.input_param and v is not None}
        return str(args.get(self.input_param, "") or ""), overrides

    def catalog_entry(self) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"id": self.id, "name": self.name, "type": self.type}
        if self.category:
            entry["category"] = self.category
        entry.update(icon=self.icon, description=self.description, default_config=dict(self.default_config))
        if self.required:
            entry["required_config"] = list(self.required)
        if self.selects:
            entry["config_options"] = {k: s.as_dict() for k, s in self.selects.items()}
        if self.parameters:
            entry["parameters"] = self.parameters
        if self.is_new:
            entry["is_new"] = True
        return entry


def params(required: Dict[str, Dict[str, Any]], optional: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """A tool's parameter schema from {name: property schema} for required and optional arguments."""
    return {"type": "object", "properties": {**required, **(optional or {})}, "required": list(required),
            "additionalProperties": False}


MAX_RESULTS = {"type": "integer", "minimum": 1, "maximum": 20, "description": "How many results to return"}


def query_params(what: str = "What to search for", **optional: Dict[str, Any]) -> Dict[str, Any]:
    """``query`` (the input) plus ``max_results`` and any extra optional arguments."""
    return params({"query": {"type": "string", "description": what}}, {"max_results": MAX_RESULTS, **optional})


def enum(values: Sequence[str], description: str) -> Dict[str, Any]:
    return {"type": "string", "enum": list(values), "description": description}


def json_input(args: Dict[str, Any]) -> str:
    """``to_input`` for tools whose input is a JSON object of their arguments."""
    return json.dumps({k: v for k, v in args.items() if v is not None})


def json_value(key: str) -> Callable[[Dict[str, Any]], str]:
    """``to_input`` for tools whose input is one JSON value: the ``key`` argument."""
    return lambda args: json.dumps(args.get(key)) if args.get(key) is not None else ""


# ── Helpers shared by file-based tools ────────────────────────────────────────

def tool_path(inp: str, cfg: Dict[str, Any], label: str):
    """Input path, joined to and confined within cfg["allowed_dir"] when set → (path, error)."""
    path = inp.strip().strip("'\"")
    if not path:
        return "", f"[{label}] Please provide a file path."
    allowed_dir = (cfg.get("allowed_dir") or "").strip()
    if allowed_dir:
        root = os.path.realpath(allowed_dir)
        path = os.path.realpath(os.path.join(root, path))
        if os.path.commonpath([root, path]) != root:
            return "", f"[{label}] Access denied: path is outside allowed directory '{allowed_dir}'"
    return path, None


def markdown_table(header: list, rows: list) -> str:
    width = len(header)
    cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    lines = ["| " + " | ".join(cell(h) for h in header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(cell(r[i]) if i < len(r) else "" for i in range(width)) + " |" for r in rows]
    return "\n".join(lines)
