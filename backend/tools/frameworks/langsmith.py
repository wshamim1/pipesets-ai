"""LangSmith — `langsmith` (catalog only: no runtime yet)."""

from tools.base import ToolSpec

TOOL = ToolSpec(
    id="langsmith",
    name="LangSmith",
    icon="🔭",
    group="frameworks",
    description="Trace, debug, and monitor every LLM call and chain in your pipeline. Logs inputs, outputs, latency, and token usage to LangSmith for full observability.",
    default_config={
        "api_key": "",
        "project": "default",
        "endpoint": "https://api.smith.langchain.com",
        "tracing": True,
    },
    order=50,
)
