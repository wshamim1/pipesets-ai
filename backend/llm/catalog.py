"""
catalog.py — the providers and models offered on LLM nodes and in Settings → Model backends.

Every model listed for a paid provider must have a price in ``llm/prices/<provider>.json``,
otherwise its runs record $0 (``tests/gateway/test_llm_catalog.py`` enforces this). A provider we
can't price from a table sets ``unpriced`` to the reason. Local providers' models are
discovered from their server when /api/models is called. ``frontend/src/hooks/useCatalogData.ts``
mirrors this list as the fallback shown before /api/models answers.
"""

from typing import Any, Dict, List

PROVIDERS: List[Dict[str, Any]] = [
    {"id": "openai",       "name": "OpenAI",
     "models": ["gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-4.1", "gpt-4o", "gpt-4o-mini",
                "o3", "o4-mini"]},
    {"id": "anthropic",    "name": "Anthropic",
     "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]},
    {"id": "groq",         "name": "Groq (ultra-fast)",
     "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]},
    {"id": "gemini",       "name": "Google Gemini",
     "models": ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview",
                "gemini-2.5-pro", "gemini-2.5-flash"]},
    {"id": "mistral",      "name": "Mistral AI",
     "models": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest",
                "codestral-latest"]},
    {"id": "together",     "name": "Together AI",
     "models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "deepseek-ai/DeepSeek-V3.1",
                "Qwen/Qwen2.5-72B-Instruct-Turbo", "openai/gpt-oss-120b"]},
    {"id": "huggingface",  "name": "HuggingFace",
     "models": ["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-72B-Instruct",
                "deepseek-ai/DeepSeek-V3.1", "openai/gpt-oss-120b"],
     "unpriced": "billed by whichever inference provider Hugging Face routes the call to"},
    {"id": "fireworks",    "name": "Fireworks AI",
     "models": ["accounts/fireworks/models/llama-v3p1-70b-instruct",
                "accounts/fireworks/models/llama-v3p3-70b-instruct",
                "accounts/fireworks/models/qwen2p5-72b-instruct",
                "accounts/fireworks/models/mixtral-8x22b-instruct"]},
    {"id": "deepseek",     "name": "DeepSeek",
     "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-coder"]},
    {"id": "xai",          "name": "xAI (Grok)",
     "models": ["grok-4.5", "grok-4.3", "grok-4.20-non-reasoning", "grok-code-fast-1"]},
    {"id": "cerebras",     "name": "Cerebras",
     "models": ["gpt-oss-120b", "qwen-3-32b", "llama-3.3-70b", "llama3.1-8b"]},
    {"id": "perplexity",   "name": "Perplexity",
     "models": ["sonar", "sonar-pro", "sonar-reasoning-pro", "sonar-deep-research"]},
    {"id": "ollama",       "name": "Ollama (Local)",
     "models": [], "local": True},
    {"id": "llamacpp",     "name": "llama.cpp (Local)",
     "models": [], "local": True},
    {"id": "jan",          "name": "Jan (Local)",
     "models": [], "local": True},
    {"id": "azure",        "name": "Azure OpenAI",
     "models": ["gpt-4o", "gpt-4-turbo", "gpt-35-turbo"]},
    {"id": "bedrock",      "name": "AWS Bedrock",
     "models": ["anthropic.claude-3-5-sonnet-20241022-v2:0", "amazon.titan-text-express-v1",
                "amazon.nova-pro-v1:0", "meta.llama3-70b-instruct-v1:0",
                "mistral.mistral-large-2402-v1:0"]},
    {"id": "nvidia",       "name": "NVIDIA NIM",
     "models": ["nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3-ultra-550b-a55b",
                "nvidia/nemotron-3.5-lightning-30b-a3b", "moonshotai/kimi-k2.6",
                "mistralai/mistral-large-4-1t-a52b", "openai/gpt-oss-20b"],
     "unpriced": "NVIDIA's API catalog runs on trial credits and publishes no per-token prices; "
                 "self-hosted NIM runs on your own GPUs"},
    {"id": "watsonx",      "name": "IBM watsonx.ai",
     "models": ["ibm/granite-4-h-small", "meta-llama/llama-3-3-70b-instruct",
                "meta-llama/llama-4-maverick-17b-128e-instruct-fp8", "mistralai/mistral-medium-2505",
                "openai/gpt-oss-120b"]},
    {"id": "typesafe",     "name": "TypeSafe (Jev)",
     "models": ["jev-1", "jev-fast", "jev-classifier"],
     "unpriced": "TypeSafe publishes no per-token prices"},
    {"id": "mock",         "name": "Mock / Simulator",
     "models": ["mock-gpt-4", "mock-claude"]},
]

# Built but not offered for now: left out of /api/models, Settings → Model backends and the
# pickers. Remove an id to offer it again.
HIDDEN_PROVIDERS = {"jan"}
PROVIDERS = [p for p in PROVIDERS if p["id"] not in HIDDEN_PROVIDERS]

# Model used when a request names none, and for Settings → Model backends' Test call
DEFAULT_MODELS: Dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "claude-haiku-5-5",
    "groq": "openai/gpt-oss-20b",
    "gemini": "gemini-3.5-flash",
    "mistral": "mistral-small-latest",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "azure": "gpt-4o",
    "bedrock": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "nvidia": "nvidia/nemotron-3-super-120b-a12b",
    "watsonx": "ibm/granite-4-h-small",
    "typesafe": "jev-fast",
    "ollama": "llama3.2",
    "llamacpp": "default",
    "jan": "default",
    "mock": "mock-gpt-4",
}
DEFAULT_MODELS = {k: v for k, v in DEFAULT_MODELS.items() if k not in HIDDEN_PROVIDERS}
