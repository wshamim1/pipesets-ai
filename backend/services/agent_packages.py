"""agent_packages.py — Settings → Agents: which built-in agents (backend/agents/) a workspace has
installed. Only installed ones are offered in the builder's sidebar; like tool packages, installing
is a visibility choice and the same rules apply (a workspace choice → the defaults, i.e. the starter
roles → a pipeline already uses it, found by the ``builtin_agent_id`` its child node records).
"""

import re

import agents
from services.tool_packages import PackageStore

_AGENT_ID = re.compile(r'"builtin_agent_id"\s*:\s*"([^"]+)"')

STORE = PackageStore("agent_packages", "agent_id", _AGENT_ID,
                     {s.id for s in agents.all_specs() if s.default_installed})
