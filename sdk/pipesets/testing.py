"""
Test Pipesets tools locally, with no backend:

    from pipesets.testing import call, load

    weather = load("tool.py")
    assert call(weather, {"city": "Oslo"}, config={"weather_token": "x"})["city"] == "Oslo"

``call`` checks the arguments against the tool's schema first (as the server does before running it)
and passes ``config`` only when the tool takes one, so a test sees what a pipeline run would.
"""

import importlib.util
import json
import os
import sys
from typing import Any, Callable, Dict, Optional

from .tooling import is_tool, schema, takes_config, validate


class ToolArgumentError(ValueError):
    """The arguments don't fit the tool's schema (the model would get this message)."""


def load(path: str = "tool.py") -> Callable:
    """Import ``path`` and return its @tool function (or ``run`` for a legacy tool)."""
    path = os.path.abspath(path)
    name = f"pipesets_tool_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    found = [v for v in vars(module).values() if is_tool(v) and getattr(v, "__module__", "") == name]
    if len(found) > 1:
        raise ValueError(f"{path}: one @tool function per file; found {', '.join(f.__name__ for f in found)}")
    if found:
        return found[0]
    run = getattr(module, "run", None)
    if callable(run):
        return run
    raise ValueError(f"{path}: no @tool function or run(input_text, config)")


def call(fn: Callable, args: Optional[Dict[str, Any]] = None, *, config: Optional[Dict[str, Any]] = None) -> Any:
    """Call a tool as a pipeline would: validated ``args`` (and ``config`` when it takes one).
    A legacy run(input_text, config) tool takes ``{"input": ...}``."""
    args = dict(args or {})
    if not is_tool(fn) and fn.__name__ == "run" and len(_params(fn)) == 2 and _params(fn)[1] in ("config", "cfg"):
        return fn(args.get("input", ""), config or {})
    problem = validate(schema(fn), args)
    if problem:
        raise ToolArgumentError(f"Invalid arguments for {fn.__name__}: {problem}")
    if takes_config(fn):
        args["config"] = config or {}
    return fn(**args)


def output(fn: Callable, args: Optional[Dict[str, Any]] = None, *, config: Optional[Dict[str, Any]] = None) -> str:
    """The text the model would get back: strings as they are, anything else as JSON."""
    result = call(fn, args, config=config)
    return result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)


def _params(fn: Callable):
    import inspect
    return list(inspect.signature(fn).parameters)
