"""
skills_runtime.py — skills an LLM node loads when a request needs them (plan.md C10, step 1).

Two modes, set on the LLM node (``PromptRunRequest.skill_mode``):

  on_demand (default)  the system prompt lists each attached skill as ``name — when to use`` and the
                       model gets one built-in tool, ``use_skill(name)``. Loading a skill returns its
                       instructions as the tool result and switches on the tools it needs. Attached
                       tools a skill lists in ``required_tools`` stay hidden until one of those skills
                       is loaded; every other attached tool is on from the start
  always               today's behaviour: every skill's instructions in the prompt, every tool on.
                       For small models that don't call tools well, and for runs that can't call
                       tools at all (the mock provider, local servers), which always use it

A Skill node holds ``skill_id`` (and optionally a pinned ``skill_version``); the skill is read from
the database when the run starts, so editing a skill reaches every pipeline that uses it. Old
graphs with only an inline copy (name / instructions / tool_ids) keep working with that copy.

At most ``max_active`` skills load in one run (default 3), so one run can't pull in everything.
Loading is deterministic given the model's calls, so a resumed run that replays its saved
``use_skill`` calls (checkpoints) ends up with the same skills and tools switched on.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

USE_SKILL = "use_skill"
DEFAULT_MAX_ACTIVE = 3
WHEN_TO_USE_MAX = 300


def _scope() -> Tuple[str, str]:
    from services.long_term_memory import current
    who = current()
    return who.tenant_id, who.project_id


def resolve(attached: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The attached skills as the run uses them: from the database when the node names a skill
    (in the run's own project, or a built-in), else the node's inline copy."""
    from routers.skills import load_skills   # lazy: routers import services

    tenant_id, project_id = _scope()
    out = []
    for s in attached or []:
        sid = s.get("skill_id") or ""
        pinned = s.get("skill_version")
        loaded = load_skills([sid], tenant_id, project_id, {sid: int(pinned)} if pinned else None) if sid else []
        src = loaded[0] if loaded else s
        name = (src.get("name") or s.get("label") or "Skill").strip()
        out.append({
            "id": sid, "name": name, "version": src.get("version") if loaded else None,
            "when_to_use": (src.get("when_to_use") or src.get("description") or "").strip()[:WHEN_TO_USE_MAX],
            "instructions": (src.get("instructions") or src.get("description") or "").strip(),
            "required_tools": list(src.get("required_tools") or src.get("tool_ids") or []),
        })
    return out


class SkillSet:
    def __init__(self, attached_skills: Optional[List[Dict[str, Any]]], mode: Optional[str],
                 max_active: Optional[int], can_call_tools: bool):
        self.skills = resolve(attached_skills or []) if attached_skills else []
        self.on_demand = bool(self.skills) and (mode or "on_demand") != "always" and can_call_tools
        self.max_active = max(1, int(max_active or DEFAULT_MAX_ACTIVE))
        self.active: List[Dict[str, Any]] = []
        # tool id -> the skills that need it (hidden until one of them is loaded)
        self.gated: Dict[str, List[str]] = {}
        if self.on_demand:
            for s in self.skills:
                for t in s["required_tools"]:
                    self.gated.setdefault(t, []).append(s["name"])

    # ── What the model sees ──────────────────────────────────────────────────

    def prompt_section(self) -> str:
        if not self.skills:
            return ""
        if not self.on_demand:   # always: every body in the prompt, as before
            bodies = [f"### Skill: {s['name']}\n{s['instructions']}" for s in self.skills if s["instructions"]]
            return "\n\n## Activated Skills & SOPs:\n" + "\n\n".join(bodies) if bodies else ""
        lines = "\n".join(f"- {s['name']} — {s['when_to_use'] or 'no description'}" for s in self.skills)
        return ("\n\n## Skills\nLoad a skill with the `use_skill` tool when the request matches what it is for; "
                "it gives you its instructions and switches on the tools it needs. Don't load skills you "
                f"don't need (at most {self.max_active} per request).\n{lines}")

    def schemas(self) -> List[Dict[str, Any]]:
        if not self.on_demand:
            return []
        return [{"type": "function", "function": {
            "name": USE_SKILL,
            "description": "Load a skill: returns its instructions and switches on its tools.",
            "parameters": {"type": "object", "properties": {
                "name": {"type": "string", "enum": [s["name"] for s in self.skills], "description": "The skill to load"},
            }, "required": ["name"]},
        }}]

    def tool_visible(self, tool_id: Optional[str]) -> bool:
        needed_by = self.gated.get(tool_id or "")
        return not needed_by or any(a["name"] in needed_by for a in self.active)

    def visible_tools(self, attached_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [t for t in attached_tools if self.tool_visible(t.get("toolId"))]

    def blocked_by(self, tool_id: Optional[str]) -> Optional[str]:
        """The skill to load before ``tool_id`` may run, when it's still hidden."""
        return None if self.tool_visible(tool_id) else self.gated[tool_id or ""][0]

    # ── use_skill ────────────────────────────────────────────────────────────

    def _find(self, name: str) -> Optional[Dict[str, Any]]:
        key = (name or "").strip().lower()
        return next((s for s in self.skills if key in (s["name"].lower(), (s["id"] or "").lower())), None)

    def load(self, name: str, attached_tools: List[Dict[str, Any]],
             func_name: Callable[[Dict[str, Any]], str]) -> Tuple[str, Optional[Dict[str, Any]]]:
        """(tool result for the model, the loaded skill's record — None when nothing was loaded)."""
        skill = self._find(name)
        if skill is None:
            return (f"Unknown skill '{name}'. Skills you can load: "
                    f"{', '.join(s['name'] for s in self.skills)}."), None
        if any(a["name"] == skill["name"] for a in self.active):
            return f"Skill '{skill['name']}' is already loaded; its tools are available.", None
        if len(self.active) >= self.max_active:
            return (f"Can't load '{skill['name']}': at most {self.max_active} skills per request "
                    f"(loaded: {', '.join(a['name'] for a in self.active)})."), None
        by_id = {t.get("toolId"): t for t in attached_tools}
        enabled = [func_name(by_id[t]) for t in skill["required_tools"] if t in by_id]
        missing = [t for t in skill["required_tools"] if t not in by_id]
        record = {"name": skill["name"], "id": skill["id"], "version": skill["version"],
                  "tools": enabled, "missing_tools": missing}
        self.active.append(record)
        version = f" (v{skill['version']})" if skill["version"] else ""
        text = f"# Skill loaded: {skill['name']}{version}\n\n{skill['instructions']}"
        if enabled:
            text += f"\n\nTools now available: {', '.join(enabled)}."
        if missing:
            text += (f"\n\nNot attached to this agent, so you can't use them: {', '.join(missing)}. "
                     "Say so if the task needs them.")
        return text, record

    @property
    def used(self) -> List[Dict[str, Any]]:
        return [{"name": a["name"], "id": a["id"], "version": a["version"]} for a in self.active]


# ── Readiness: can this flow's skills actually do their job? ──────────────────

def readiness(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """For every Skill node wired to an LLM node, what's missing before its skill can work: required
    tools not attached to that LLM node, and attached ones without a setting they can't run without
    (``ToolSpec.required``, after the linked Connection node's settings are merged in). Only skills
    with a problem are listed. Publishing refuses a flow with any (routers/apps.py)."""
    import tools as tool_registry
    from services.pipeline_runner import _merge_connection, _neighbours

    by_id = {n.get("id"): n for n in nodes}
    issues = []
    for skill_node in (n for n in nodes if n.get("type") == "skill"):
        resolved = resolve([skill_node.get("data") or {}])[0]
        required = resolved["required_tools"]
        if not required:
            continue
        for llm_id in _neighbours(skill_node["id"], edges):
            llm = by_id.get(llm_id)
            if not llm or llm.get("type") != "llm":
                continue
            attached: Dict[str, Dict[str, Any]] = {}
            for nid in _neighbours(llm_id, edges):
                t = by_id.get(nid)
                if t and t.get("type") == "tool":
                    data = _merge_connection(t.get("data") or {}, nodes, _neighbours(nid, edges))
                    attached.setdefault(data.get("toolId"), {**data, "_node": nid})
            missing = [t for t in required if t not in attached]
            unconfigured = []
            for t in required:
                if t not in attached:
                    continue
                spec = tool_registry.get_spec(t)
                cfg = attached[t].get("config") or {}
                keys = [k for k in (spec.required if spec else ()) if not str(cfg.get(k) or "").strip()]
                if keys:
                    unconfigured.append({"tool_id": t, "node_id": attached[t]["_node"],
                                         "label": attached[t].get("label") or t, "missing_settings": keys})
            if missing or unconfigured:
                issues.append({"skill_node_id": skill_node["id"], "skill": resolved["name"], "llm_node_id": llm_id,
                               "missing_tools": missing, "unconfigured_tools": unconfigured})
    return issues


def describe(issue: Dict[str, Any]) -> str:
    parts = []
    if issue["missing_tools"]:
        parts.append(f"attach {', '.join(issue['missing_tools'])}")
    for u in issue["unconfigured_tools"]:
        parts.append(f"set {', '.join(u['missing_settings'])} on {u['label']}")
    return f"Skill '{issue['skill']}' isn't ready: " + "; ".join(parts)
