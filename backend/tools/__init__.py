"""
Built-in tool registry.

Every module in this package (searched recursively) that defines ``TOOL`` / ``TOOLS``
(see tools/base.py) is registered automatically — adding a tool is adding one file.

``execute()`` is the single entry point for running any tool (built-in, MCP, custom):
it decrypts secret refs, dispatches by id and applies the fallbacks. ``catalog()``
builds the ``GET /api/tools`` payload from the specs.

``reload()`` picks up added, edited and deleted modules without a restart (``POST /api/tools/reload``;
with ``TOOLS_AUTO_RELOAD=1`` it also runs by itself, at most once a second, when the catalog is
fetched or a tool runs). Runs already in progress finish on the code they started with. Changes to
this file, or a new pip dependency, still need a restart.
"""

import importlib
import logging
import os
import pkgutil
import sys
import threading
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from services import secret_store
from tools.base import ToolSpec

logger = logging.getLogger("pipesets-ai-backend")

Runner = Callable[[str, Dict[str, Any], str], Awaitable[Optional[str]]]

# Catalog sections, in display order
GROUPS = [
    ("agentic_tools", "Built-in Tools"),
    ("mcp_servers", "Model Context Protocol (MCP)"),
    ("frameworks", "Frameworks"),
]

# Sidebar sub-groups per catalog section, in display order (unknown categories go last)
CATEGORY_ORDER = {
    "agentic_tools": [
        "Web Search", "Research & Knowledge", "Data & Files", "Code & Compute",
        "Communication", "Productivity", "Business Apps", "Jobs & Careers", "APIs & Integrations", "Everyday Utilities",
    ],
    "mcp_servers": ["Databases & Data", "Developer Tools", "DevOps & Observability", "Web & Browser",
                    "Productivity", "AI & Memory"],
}

_specs: Dict[str, ToolSpec] = {}
_runners: Dict[str, Runner] = {}
_loaded = False

Registered = Tuple[List[ToolSpec], Optional[Runner]]
_modules: Dict[str, Registered] = {}   # tool module → the specs and run() it registered
_mtimes: Dict[str, int] = {}           # every module in the package → its file's mtime when imported
_lock = threading.RLock()
_next_auto_check = 0.0


def _scan() -> Dict[str, Tuple[str, bool]]:
    """Every module in the package: name → (file path, whether it's a tool module). Helpers
    (``_x.py``), ``base.py`` and sub-package ``__init__`` files are modules but not tool modules."""
    found = {}
    for info in pkgutil.walk_packages(__path__, prefix=f"{__name__}."):
        short = info.name.rsplit(".", 1)[-1]
        folder = getattr(info.module_finder, "path", "")
        path = os.path.join(folder, short, "__init__.py") if info.ispkg else os.path.join(folder, f"{short}.py")
        found[info.name] = (path, not info.ispkg and not short.startswith("_") and info.name != f"{__name__}.base")
    return found


def _mtime(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:   # frozen desktop build: no source files
        return 0


def _registered(module) -> Registered:
    specs = getattr(module, "TOOLS", None) or ([module.TOOL] if hasattr(module, "TOOL") else [])
    return list(specs), getattr(module, "run", None)


def _tables(modules: Dict[str, Registered]):
    """(specs, runners, errors) from each module's registrations; a repeated id keeps the first."""
    specs: Dict[str, ToolSpec] = {}
    runners: Dict[str, Runner] = {}
    errors = []
    for name in sorted(modules):
        mod_specs, run = modules[name]
        for spec in mod_specs:
            if spec.id in specs:
                errors.append({"module": name, "error": f"Tool id '{spec.id}' is defined twice"})
                continue
            specs[spec.id] = spec
            if run is not None:
                runners[spec.id] = run
    return specs, runners, errors


def _load() -> None:
    global _loaded, _specs, _runners
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        for name, (path, is_tool) in _scan().items():
            module = importlib.import_module(name)
            _mtimes[name] = _mtime(path)
            if is_tool:
                _modules[name] = _registered(module)
        specs, runners, errors = _tables(_modules)
        if errors:
            raise RuntimeError(f"{errors[0]['error']} ({errors[0]['module']})")
        _specs, _runners = specs, runners
        _loaded = True


def reload() -> Dict[str, Any]:
    """Re-scan the package and import what changed since the last load: new modules, edited ones,
    and every module when a helper (``_x.py``, ``base.py``) changed, since tool modules bind its
    names at import. Deleted modules drop out. A module that fails to import is reported and keeps
    its previous version (a new one is skipped); it's retried once its file changes again.

    → {"changed", "modules" (how many were re-imported or dropped), "added" / "removed" (tool ids),
    "errors" [{module, error}]}. Only this process is reloaded; with several workers, use
    TOOLS_AUTO_RELOAD so each one picks the change up itself."""
    global _specs, _runners, _modules
    _load()
    with _lock:
        if getattr(sys, "frozen", False):
            return {"changed": False, "modules": 0, "added": [], "removed": [], "errors": [],
                    "note": "The desktop app ships its tools in the build; install an update to get new ones."}
        importlib.invalidate_caches()
        found = _scan()
        changed = [n for n, (path, _) in found.items() if _mtimes.get(n) != _mtime(path)]
        removed = [n for n in _mtimes if n not in found]
        if not changed and not removed:
            return {"changed": False, "modules": 0, "added": [], "removed": [], "errors": []}

        helper_changed = any(n in _mtimes and not found[n][1] for n in changed)
        targets = sorted(found if helper_changed else changed, key=lambda n: (found[n][1], n))
        if helper_changed:
            # Helpers first, twice: one helper can import another (_http imports _stdio)
            targets = [n for n in targets if not found[n][1]] + targets
        modules = {n: reg for n, reg in _modules.items() if n in found}
        errors = []
        failed = set()
        for name in targets:
            path, is_tool = found[name]
            if name in failed:
                continue
            try:
                if os.path.exists(path):   # a syntax error is caught before the live module is touched
                    with open(path, encoding="utf-8") as f:
                        compile(f.read(), path, "exec")
                module = importlib.reload(sys.modules[name]) if name in sys.modules else importlib.import_module(name)
                if is_tool:
                    modules[name] = _registered(module)
            except Exception as e:   # a broken file must not take the registry down
                failed.add(name)
                errors.append({"module": name, "error": f"{type(e).__name__}: {e}"})
                logger.warning("Tool reload: %s failed to import: %s", name, e)
            _mtimes[name] = _mtime(path)
        for name in removed:
            _mtimes.pop(name, None)
            modules.pop(name, None)
            sys.modules.pop(name, None)

        specs, runners, dupes = _tables(modules)
        before = set(_specs)
        _specs, _runners, _modules = specs, runners, modules
        return {"changed": True, "modules": len(set(targets)) + len(removed),
                "added": sorted(set(specs) - before), "removed": sorted(before - set(specs)),
                "errors": errors + dupes}


def maybe_reload() -> None:
    """With TOOLS_AUTO_RELOAD=1 (start.sh sets it for development), reload() at most once a second."""
    global _next_auto_check
    if os.environ.get("TOOLS_AUTO_RELOAD", "").lower() not in ("1", "true", "yes"):
        return
    now = time.monotonic()
    if now < _next_auto_check:
        return
    _next_auto_check = now + 1.0
    result = reload()
    if result["changed"]:
        logger.info("Tool registry reloaded: %d module(s), added %s, removed %s",
                    result["modules"], result["added"] or "none", result["removed"] or "none")


def get_spec(tool_id: str) -> Optional[ToolSpec]:
    _load()
    return _specs.get(tool_id)


def all_specs() -> List[ToolSpec]:
    _load()
    return list(_specs.values())


def _sort_key(spec: ToolSpec):
    order = CATEGORY_ORDER.get(spec.group, [])
    cat = order.index(spec.category) if spec.category in order else len(order)
    return (cat, spec.category, spec.order, spec.name.lower())


def catalog() -> List[Dict[str, Any]]:
    """The tool catalog, grouped into sections — the GET /api/tools payload."""
    _load()
    return [
        {"id": gid, "name": gname,
         "tools": [s.catalog_entry() for s in sorted(
             (s for s in _specs.values() if s.group == gid and not s.hidden), key=_sort_key)]}
        for gid, gname in GROUPS
    ]


async def discover(tool_type: str, config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """An MCP server node's tools — [{name, description, inputSchema}]: listed by the built-in server
    now, or a custom server's discovered ones (refreshed when it can be reached). Raises ValueError
    for a node that isn't an MCP server or can't be launched, RuntimeError when listing fails."""
    _load()
    cfg = secret_store.resolve_refs(config or {})
    if tool_type.startswith("custom_mcp_"):
        from routers.custom_mcp import _get_server, discover_mcp_tools
        scope = secret_store.current_scope_ids()
        server = _get_server(tool_type, *scope) if scope else None
        if not server:
            raise ValueError(f"Custom MCP server {tool_type} not found")
        try:
            return await discover_mcp_tools(server["transport"], server["command"], server["args"], server["env_vars"],
                                            server["url"], server["headers"], tool_type)
        except Exception:
            if server.get("tools_cache"):
                return server["tools_cache"]
            raise
    listing = getattr(_runners.get(tool_type), "discover", None)
    if listing is None:
        raise ValueError(f"{tool_type} has no built-in launcher; add it as a custom MCP server to list its tools")
    return await listing(cfg, tool_type)


async def execute(tool_type: str, input_text: str, config: Optional[Dict[str, Any]] = None,
                  args: Optional[Dict[str, Any]] = None) -> str:
    """Run any tool and return its text output. ``args`` are the model's function-call arguments
    for a tool with typed parameters (a custom tool, or a built-in spec with ``parameters``);
    other tools take ``input_text``."""
    _load()
    maybe_reload()
    cfg = config or {}
    inp = input_text.strip()

    spec = _specs.get(tool_type)
    if args is not None and spec is not None and spec.parameters:
        from services.tool_signature import validate_args
        problem = validate_args(spec.parameters, args)
        if problem:
            return f"[{spec.name}] Invalid arguments: {problem}"
        inp, overrides = spec.call_input(args)
        inp = inp.strip()
        cfg = {**cfg, **overrides}   # declared arguments only (see ToolSpec.parameters)

    # "secret://<id>" values are decrypted here, server-side, just before use
    try:
        cfg = secret_store.resolve_refs(cfg)
    except secret_store.SecretError as e:
        return f"[{tool_type}] {e}"

    # Custom MCP servers share the mcp_ prefix space, so they're matched first
    if tool_type.startswith("custom_mcp_"):
        from routers.custom_mcp import execute_custom_mcp
        return await execute_custom_mcp(tool_type, inp, cfg)

    run = _runners.get(tool_type)
    if run is not None:
        result = await run(inp, cfg, tool_type)
        if result is not None:
            return result

    elif tool_type.startswith("mcp_"):
        # An MCP id with no built-in server (e.g. from an older catalog or a blueprint)
        return (
            f"[MCP {tool_type}]\n"
            f"Transport: stdio  Input: {inp[:200]}\n"
            f"Note: Add this server via the Custom MCP panel and configure its command."
        )

    elif tool_type.startswith("custom_"):
        from routers.custom_tools import execute_custom_tool
        return await execute_custom_tool(tool_type[len("custom_"):], inp, cfg, args)

    return f"[{tool_type}] executed with input: {inp}"
