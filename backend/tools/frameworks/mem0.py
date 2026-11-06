"""mem0 — `mem0` (catalog only: no runtime yet)."""

from tools.base import ToolSpec

TOOL = ToolSpec(
    id="mem0",
    name="mem0",
    icon="🧠",
    group="frameworks",
    description="Long-term personalized memory for AI agents. Stores user preferences, past interactions, and facts across sessions. Supports vector, graph, and key-value backends.",
    default_config={
        "api_key": "",
        "user_id": "",
        "agent_id": "",
        "operation": "search",
        "query": "",
        "memory_text": "",
    },
    order=70,
)
