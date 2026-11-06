"""
tool_signature.py — a custom tool's entry point and parameter JSON schema, read from its code.

The code is parsed, never run (it only ever runs in the sandbox). Two shapes:

Typed (SDK-style) — one function decorated with ``@tool`` (``from pipesets import tool``), or a
function named ``run`` with named, annotated parameters::

    @tool(description="Look up a Jira issue", secrets=["jira_token"], requirements=["requests>=2.31"])
    def jira_lookup(issue_key: str, include_comments: bool = False, *, config) -> str:
        \"\"\"Look up a Jira issue.

        Args:
            issue_key: The issue key, e.g. OPS-1
        \"\"\"

  Each parameter becomes a property of the schema the model calls the tool with (type from the
  annotation, ``default`` from the default, required when there is none, description from the
  docstring's Args section or ``Annotated[str, "…"]``). ``config`` is reserved: the node's config
  (secrets decrypted) is passed to it, never shown to the model.

Legacy — ``def run(input_text, config)``: the model sends one ``input`` string, as before.

Annotations understood: str, int, float, bool, list / List[X], dict / Dict[...], Optional[X] /
X | None, Literal[...], Annotated[X, "description"]. Anything else is accepted with no type.
Decorator arguments must be literals (they are read, not evaluated).
"""

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

LEGACY_SCHEMA = {"type": "object", "properties": {"input": {"type": "string", "description": "Input text for this tool"}},
                 "required": ["input"]}
_TYPES = {"str": "string", "int": "integer", "float": "number", "bool": "boolean", "list": "array",
          "dict": "object", "List": "array", "Dict": "object", "Sequence": "array", "Mapping": "object",
          "tuple": "array", "Tuple": "array", "set": "array", "Set": "array"}


class ToolCodeError(ValueError):
    """The code can't be a tool; the message says why (shown to whoever saved it)."""


@dataclass
class ToolSignature:
    entrypoint: str
    legacy: bool
    parameters: Dict[str, Any]
    takes_config: bool = False
    description: str = ""
    name: str = ""                      # @tool(name=...) or the function name
    secrets: List[str] = field(default_factory=list)
    requirements: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"entrypoint": self.entrypoint, "legacy": self.legacy, "parameters": self.parameters,
                "takes_config": self.takes_config, "description": self.description, "name": self.name,
                "secrets": self.secrets, "requirements": self.requirements}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ToolSignature":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def _is_tool_decorator(dec: ast.expr) -> bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    return (isinstance(target, ast.Name) and target.id == "tool") or \
           (isinstance(target, ast.Attribute) and target.attr == "tool")


def _decorator_kwargs(fn: ast.FunctionDef) -> Dict[str, Any]:
    for dec in fn.decorator_list:
        if _is_tool_decorator(dec) and isinstance(dec, ast.Call):
            out = {}
            for kw in dec.keywords:
                try:
                    out[kw.arg] = ast.literal_eval(kw.value)
                except ValueError:
                    raise ToolCodeError(f"@tool({kw.arg}=...) must be a literal (a string or a list of strings)")
            if dec.args:
                try:
                    out.setdefault("description", ast.literal_eval(dec.args[0]))
                except ValueError:
                    pass
            return out
    return {}


def _name_of(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str):   # "str" as a string annotation
        return node.value
    return ""


def _schema_for(ann: Optional[ast.expr]) -> Dict[str, Any]:
    """JSON schema for an annotation; {} when it says nothing we understand."""
    if ann is None:
        return {}
    if isinstance(ann, ast.Constant) and ann.value is None:
        return {"type": "null"}
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):   # X | None
        parts = [p for p in (ann.left, ann.right) if not (isinstance(p, ast.Constant) and p.value is None)]
        return _schema_for(parts[0]) if len(parts) == 1 else {}
    if isinstance(ann, ast.Subscript):
        outer = _name_of(ann.value)
        inner = ann.slice
        items = list(inner.elts) if isinstance(inner, ast.Tuple) else [inner]
        if outer == "Optional":
            return _schema_for(items[0])
        if outer == "Union":
            rest = [i for i in items if not (isinstance(i, ast.Constant) and i.value is None)]
            return _schema_for(rest[0]) if len(rest) == 1 else {}
        if outer == "Literal":
            values = [i.value for i in items if isinstance(i, ast.Constant)]
            types = {type(v).__name__ for v in values}
            schema: Dict[str, Any] = {"enum": values}
            if len(types) == 1 and _TYPES.get(types.pop()):
                schema["type"] = _TYPES[type(values[0]).__name__]
            return schema
        if outer == "Annotated":
            schema = dict(_schema_for(items[0]))
            for extra in items[1:]:
                if isinstance(extra, ast.Constant) and isinstance(extra.value, str):
                    schema["description"] = extra.value
            return schema
        if _TYPES.get(outer) == "array":
            return {"type": "array", "items": _schema_for(items[0])} if items else {"type": "array"}
        if _TYPES.get(outer) == "object":
            return {"type": "object"}
        return {}
    t = _TYPES.get(_name_of(ann))
    return {"type": t} if t else {}


def _arg_docs(doc: str) -> Dict[str, str]:
    """``name: description`` (or ``name (type): description``) lines of an Args / Parameters section."""
    out: Dict[str, str] = {}
    in_args, current = False, None
    for raw in (doc or "").splitlines():
        line = raw.strip()
        if line.rstrip(":").lower() in ("args", "arguments", "parameters", "params"):
            in_args, current = True, None
            continue
        if not in_args:
            continue
        if not line:
            current = None
            continue
        if line.endswith(":") and " " not in line.rstrip(":"):   # next section, e.g. "Returns:"
            break
        head, sep, rest = line.partition(":")
        name = head.split("(")[0].strip()
        if sep and name.isidentifier():
            current = name
            out[name] = rest.strip()
        elif current:
            out[current] = f"{out[current]} {line}".strip()
    return out


def _summary(doc: str) -> str:
    return " ".join((doc or "").strip().split("\n\n")[0].split())


def analyze(code: str) -> ToolSignature:
    """Read the tool's entry point and schema. Raises ToolCodeError with a fixable message."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ToolCodeError(f"Syntax error in tool code (line {e.lineno}): {e.msg}")
    fns = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    decorated = [f for f in fns if any(_is_tool_decorator(d) for d in f.decorator_list)]
    if len(decorated) > 1:
        raise ToolCodeError(f"One @tool function per tool; found {', '.join(f.name for f in decorated)}")
    fn = decorated[0] if decorated else next((f for f in fns if f.name == "run"), None)
    if fn is None:
        raise ToolCodeError("Define the tool as a function decorated with @tool, or as run(input_text, config)")
    if isinstance(fn, ast.AsyncFunctionDef):
        raise ToolCodeError(f"'{fn.name}' is async; tools are plain functions")

    a = fn.args
    params = [*a.posonlyargs, *a.args]
    doc = ast.get_docstring(fn) or ""
    meta = _decorator_kwargs(fn)
    legacy = not decorated and len(params) == 2 and params[1].arg in ("config", "cfg") \
        and not (a.kwonlyargs or a.vararg or a.kwarg)
    if legacy:
        return ToolSignature(entrypoint=fn.name, legacy=True, parameters=LEGACY_SCHEMA, takes_config=True,
                             description=_summary(doc), name=fn.name)
    if a.vararg or a.kwarg:
        raise ToolCodeError(f"'{fn.name}' takes *args / **kwargs; give each parameter a name and a type")

    defaults = dict(zip([p.arg for p in params][len(params) - len(a.defaults):], a.defaults))
    defaults.update({p.arg: d for p, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None})
    docs = _arg_docs(doc)
    properties: Dict[str, Any] = {}
    required: List[str] = []
    takes_config = False
    for p in [*params, *a.kwonlyargs]:
        if p.arg == "config":
            takes_config = True
            continue
        if p.arg in ("self", "cls"):
            raise ToolCodeError(f"'{fn.name}' looks like a method; tools are module-level functions")
        schema = _schema_for(p.annotation)
        if p.arg in docs and "description" not in schema:
            schema["description"] = docs[p.arg]
        if p.arg in defaults:
            try:
                schema["default"] = ast.literal_eval(defaults[p.arg])
            except ValueError:
                pass
        else:
            required.append(p.arg)
        properties[p.arg] = schema
    parameters: Dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        parameters["required"] = required

    for key in ("secrets", "requirements"):
        value = meta.get(key, [])
        if not (isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value)):
            raise ToolCodeError(f"@tool({key}=...) must be a list of strings")
    return ToolSignature(entrypoint=fn.name, legacy=False, parameters=parameters, takes_config=takes_config,
                         description=str(meta.get("description") or _summary(doc)),
                         name=str(meta.get("name") or fn.name),
                         secrets=list(meta.get("secrets", [])), requirements=list(meta.get("requirements", [])))


def validate_args(parameters: Dict[str, Any], args: Any) -> Optional[str]:
    """Why ``args`` don't fit the schema (for the model to correct), or None."""
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
        schema = props.get(k, {})
        t = schema.get("type")
        wrong_type = t in checks and v is not None and not isinstance(v, checks[t])
        if wrong_type or (t in ("integer", "number") and isinstance(v, bool)):
            return f"{k} must be {t}"
        if "enum" in schema and v not in schema["enum"]:
            return f"{k} must be one of {', '.join(map(str, schema['enum']))}"
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if ("minimum" in schema and v < schema["minimum"]) or ("maximum" in schema and v > schema["maximum"]):
                return f"{k} must be between {schema.get('minimum', '-∞')} and {schema.get('maximum', '∞')}"
    return None


def single_text_parameter(parameters: Dict[str, Any]) -> Optional[str]:
    """The parameter plain text input can go to (paths that pre-run tools without the model choosing
    arguments): the only required one, or the first string one."""
    props = parameters.get("properties", {})
    required = parameters.get("required", [])
    if len(required) == 1:
        return required[0]
    if not required:
        return next((k for k, s in props.items() if s.get("type") in ("string", None)), None)
    return None
