"""LangFuse — `langfuse` (catalog only: no runtime yet)."""

from tools.base import ToolSpec

TOOL = ToolSpec(
    id="langfuse",
    name="LangFuse",
    icon="🌸",
    group="frameworks",
    description="Open-source LLM observability. Trace pipelines, score outputs, run evaluations, and manage prompts. Self-hostable alternative to LangSmith.",
    default_config={
        "public_key": "",
        "secret_key": "",
        "host": "https://cloud.langfuse.com",
        "project": "",
        "tracing": True,
    },
    order=60,
)
