"""
Built-in agent specs (plan.md C11 step 3). A module in ``backend/agents/`` defines ``AGENT`` or
``AGENTS`` and the registry (agents/__init__.py) picks it up.

Two kinds of built-in:

  starter  a role with a system prompt and no tools (Researcher, Writer, …) — what the sidebar's
           Agents section always offered. Installed by default.
  agent    a specialist that does its job with tools (and optionally skills). It lists the tools it
           needs; each need can be met by any one of several tools (any web search tool, say), so
           it's ready when an installed tool covers every required need. Comes with an eval set:
           ``evals``, cases written for the ``llm_judge`` scorer (``expected`` says what a good answer
           does), which "Create eval set" copies into an eval dataset for the pipeline it's in.
           Not installed by default.

Dropping a built-in onto the canvas makes a child agent (``builtin_agent_id`` on its data, which is
also how "used in a pipeline" is found) plus a tool node per need and a skill node per skill.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set, Tuple


@dataclass(frozen=True)
class ToolNeed:
    ids: Tuple[str, ...]          # any one of these tools / MCP servers meets the need
    optional: bool = False
    why: str = ""                 # shown in Settings → Agents, e.g. "searches the web"

    def pick(self, installed: Set[str]) -> Optional[str]:
        """The tool that meets this need in a workspace: the first installed one."""
        return next((t for t in self.ids if t in installed), None)


@dataclass(frozen=True)
class EvalCase:
    prompt: str
    expected: str                 # what a good answer does — read by the llm_judge scorer
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    icon: str
    group: str                    # sidebar group (GROUPS in agents/__init__.py)
    description: str
    role: str
    system_prompt: str = ""
    kind: str = "llm"             # llm | external
    starter: bool = False
    tools: Tuple[ToolNeed, ...] = ()
    skills: Tuple[str, ...] = ()  # built-in skill ids (routers/skills.py)
    evals: Tuple[EvalCase, ...] = ()
    order: int = 1000             # position in its group
    is_new: bool = False
    extra: Dict[str, Any] = field(default_factory=dict, compare=False)   # more child node data

    @property
    def default_installed(self) -> bool:
        return self.starter

    def catalog_entry(self, installed_tools: Set[str]) -> Dict[str, Any]:
        needs = []
        for n in self.tools:
            picked = n.pick(installed_tools)
            needs.append({"ids": list(n.ids), "optional": n.optional, "why": n.why, "installed": picked,
                          "use": picked or n.ids[0]})
        missing = [n["use"] for n in needs if not n["optional"] and not n["installed"]]
        return {
            "id": self.id, "name": self.name, "icon": self.icon, "group": self.group,
            "description": self.description, "role": self.role, "system_prompt": self.system_prompt,
            "kind": self.kind, "starter": self.starter, "tools": needs, "skills": list(self.skills),
            "order": self.order, "is_new": self.is_new, "extra": dict(self.extra), "eval_cases": len(self.evals),
            "ready": not missing, "missing_tools": missing,
        }
