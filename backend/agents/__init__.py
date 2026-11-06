"""
Built-in agent registry (plan.md C11 step 3).

Every module in this package that defines ``AGENT`` / ``AGENTS`` (see agents/base.py) is registered
when the package is first used — adding a built-in agent is adding one file. ``GET /api/agent-catalog``
(routers/agent_catalog.py) serves them with each workspace's install state; Settings → Agents
installs them (services/agent_packages.py).
"""

import importlib
import pkgutil
from typing import Dict, List, Optional

from agents.base import AgentSpec, EvalCase, ToolNeed  # noqa: F401 — re-exported

# Sidebar groups, in display order (unknown groups go last)
GROUPS = ["Orchestration", "Research & analysis", "Writing & language", "Data & code", "Data platform",
          "DevOps & SRE", "Engineering", "Business & productivity", "Routing & support", "Build your own"]

_specs: Dict[str, AgentSpec] = {}


def _load() -> None:
    if _specs:
        return
    found: Dict[str, AgentSpec] = {}
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_") or mod.name == "base":
            continue
        module = importlib.import_module(f"{__name__}.{mod.name}")
        for spec in list(getattr(module, "AGENTS", ())) + ([module.AGENT] if hasattr(module, "AGENT") else []):
            if spec.id in found:
                raise ValueError(f"Duplicate built-in agent id '{spec.id}' in agents/{mod.name}.py")
            found[spec.id] = spec
    _specs.update(found)


def _sort_key(s: AgentSpec):
    group = GROUPS.index(s.group) if s.group in GROUPS else len(GROUPS)
    return group, s.order, s.name.lower()


def all_specs() -> List[AgentSpec]:
    _load()
    return sorted(_specs.values(), key=_sort_key)


def get(agent_id: str) -> Optional[AgentSpec]:
    _load()
    return _specs.get(agent_id)
