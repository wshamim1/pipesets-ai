"""
The ``@tool`` decorator: write a Pipesets custom tool as a typed Python function.

    from pipesets import tool

    @tool(description="Look up a Jira issue by key", secrets=["jira_token"], requirements=["requests>=2.31"])
    def jira_lookup(issue_key: str, include_comments: bool = False, *, config) -> str:
        \"\"\"Look up a Jira issue.

        Args:
            issue_key: The issue key, e.g. OPS-1
        \"\"\"
        ...

The parameters become the JSON schema the model calls the tool with: the type from the annotation,
``default`` from the default, required when there is none, the description from the docstring's
Args section or ``Annotated[str, "…"]``. ``config`` is reserved for the node's config (secrets
decrypted) and is never shown to the model. The decorator returns the function unchanged, so it can
be called and tested like any other.

On deploy the server reads the same signature from the code without running it; ``schema()`` here
is for local runs and tests. Arguments to ``@tool`` must be literals, since the server reads them.
"""

import inspect
import types
import typing
from collections import abc
from typing import Any, Callable, Dict, List, Optional, Sequence

_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object",
          tuple: "array", set: "array"}
_UnionType = getattr(types, "UnionType", None)   # X | None, Python 3.10+


def tool(fn: Optional[Callable] = None, *, description: Optional[str] = None, secrets: Sequence[str] = (),
         requirements: Sequence[str] = (), name: Optional[str] = None):
    """Mark a function as a Pipesets tool: ``@tool`` or ``@tool(description=..., secrets=[...])``."""
    def mark(f: Callable) -> Callable:
        f.__pipesets_tool__ = {"name": name or f.__name__, "description": description or _summary(f.__doc__),
                               "secrets": list(secrets), "requirements": list(requirements)}
        return f
    return mark(fn) if fn is not None else mark


def is_tool(obj: Any) -> bool:
    return callable(obj) and hasattr(obj, "__pipesets_tool__")


def _summary(doc: Optional[str]) -> str:
    return " ".join(inspect.cleandoc(doc or "").split("\n\n")[0].split())


def _arg_docs(doc: Optional[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    in_args, current = False, None
    for raw in inspect.cleandoc(doc or "").splitlines():
        line = raw.strip()
        if line.rstrip(":").lower() in ("args", "arguments", "parameters", "params"):
            in_args, current = True, None
            continue
        if not in_args:
            continue
        if not line:
            current = None
            continue
        if line.endswith(":") and " " not in line.rstrip(":"):
            break
        head, sep, rest = line.partition(":")
        key = head.split("(")[0].strip()
        if sep and key.isidentifier():
            current = key
            out[key] = rest.strip()
        elif current:
            out[current] = f"{out[current]} {line}".strip()
    return out


def _schema_for(hint: Any) -> Dict[str, Any]:
    """JSON schema for a type hint; {} when it says nothing we understand."""
    if hint is inspect.Parameter.empty or hint is Any:
        return {}
    if hint is type(None):
        return {"type": "null"}
    origin, args = typing.get_origin(hint), typing.get_args(hint)
    if origin is typing.Annotated:
        schema = dict(_schema_for(args[0]))
        for extra in args[1:]:
            if isinstance(extra, str):
                schema["description"] = extra
        return schema
    if origin is typing.Union or (_UnionType is not None and origin is _UnionType):   # Optional[X], X | None
        rest = [a for a in args if a is not type(None)]
        return _schema_for(rest[0]) if len(rest) == 1 else {}
    if origin is typing.Literal:
        schema: Dict[str, Any] = {"enum": list(args)}
        kinds = {type(a) for a in args}
        if len(kinds) == 1 and next(iter(kinds)) in _TYPES:
            schema["type"] = _TYPES[type(args[0])]
        return schema
    if origin in (list, tuple, set, frozenset, abc.Sequence, abc.Set):
        return {"type": "array", "items": _schema_for(args[0])} if args else {"type": "array"}
    if origin in (dict, abc.Mapping):
        return {"type": "object"}
    t = _TYPES.get(hint)
    return {"type": t} if t else {}


def schema(fn: Callable) -> Dict[str, Any]:
    """The JSON schema of the tool's parameters, as the model sees it."""
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:  # noqa: BLE001 — unresolvable forward refs: no types
        hints = {}
    docs = _arg_docs(fn.__doc__)
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for p in inspect.signature(fn).parameters.values():
        if p.name == "config":
            continue
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            raise TypeError(f"{fn.__name__} takes *args / **kwargs; give each parameter a name and a type")
        s = _schema_for(hints.get(p.name, p.annotation))
        if p.name in docs and "description" not in s:
            s["description"] = docs[p.name]
        if p.default is inspect.Parameter.empty:
            required.append(p.name)
        else:
            s["default"] = p.default
        properties[p.name] = s
    out: Dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


def takes_config(fn: Callable) -> bool:
    return "config" in inspect.signature(fn).parameters


def validate(parameters: Dict[str, Any], args: Any) -> Optional[str]:
    """Why ``args`` don't fit the schema, or None — the same checks the server makes."""
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    props = parameters.get("properties", {})
    missing = [k for k in parameters.get("required", []) if k not in args]
    if missing:
        return f"missing {', '.join(missing)}"
    if parameters.get("additionalProperties") is False:
        unknown = [k for k in args if k not in props]
        if unknown:
            return f"unknown argument(s) {', '.join(unknown)}; expected {', '.join(props) or 'none'}"
    checks = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    for k, v in args.items():
        s = props.get(k, {})
        t = s.get("type")
        wrong_type = t in checks and v is not None and not isinstance(v, checks[t])
        if wrong_type or (t in ("integer", "number") and isinstance(v, bool)):
            return f"{k} must be {t}"
        if "enum" in s and v not in s["enum"]:
            return f"{k} must be one of {', '.join(map(str, s['enum']))}"
    return None

