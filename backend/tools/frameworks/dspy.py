"""DSPy — `dspy` (catalog only: no runtime yet)."""

from tools.base import ToolSpec

TOOL = ToolSpec(
    id="dspy",
    name="DSPy",
    icon="🧪",
    group="frameworks",
    description="Optimize LLM prompts and pipelines automatically using DSPy. Define a signature and a metric — DSPy finds the best prompt, few-shot examples, and chain-of-thought automatically.",
    default_config={
        "api_key": "",
        "model": "gpt-4o-mini",
        "optimizer": "BootstrapFewShot",
        "metric": "exact_match",
        "num_trials": 10,
        "signature": "question -> answer",
    },
    order=80,
)
