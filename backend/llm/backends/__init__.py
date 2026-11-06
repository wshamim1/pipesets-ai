"""LLM backends, in the order ``auto`` tries them. Imported explicitly (not discovered) so the
PyInstaller build sees every module.

Our own adapters come first for every provider they serve; LiteLLM is kept only as an optional
fallback for providers with no adapter yet (and as an explicit choice in Settings → Model
backends). ``ADAPTER_FIRST`` lists the providers whose own adapter is covered by the gateway tests
(tests/gateway/test_llm_openai_compat.py, test_llm_watsonx.py, …). A provider should still get a live
check and contract cassettes before it is considered done.
"""

from typing import List

from llm.backends.anthropic import AnthropicBackend
from llm.backends.bedrock import BedrockBackend
from llm.backends.cohere import CohereBackend
from llm.backends.gemini import GeminiBackend
from llm.backends.mistral import MistralBackend
from llm.backends.ollama import OllamaBackend
from llm.backends.openai_compat import OpenAICompatBackend
from llm.backends.watsonx import WatsonXBackend

try:                                  # optional: providers without an adapter still use it
    from llm.backends.litellm import LiteLLMBackend
    _LITELLM = [LiteLLMBackend()]
except ImportError:                   # litellm not installed — every shipped provider has an adapter
    _LITELLM = []

# Native adapters for providers openai_compat also serves (Mistral, Cohere, Ollama) come after it,
# so `auto` keeps the live-checked path; pick them in Settings → Model backends. Not live-checked yet.
BACKENDS = [OpenAICompatBackend(), AnthropicBackend(), BedrockBackend(), GeminiBackend(),
            WatsonXBackend(), MistralBackend(), CohereBackend(), OllamaBackend()] + _LITELLM

# Providers `auto` sends to our adapters instead of LiteLLM. openai_compat serves every
# OpenAI-compatible provider; anthropic / gemini / bedrock / watsonx have their own adapters
# (mistral / cohere / ollama have native ones too, opt-in).
ADAPTER_FIRST = {
    "openai", "ollama", "llamacpp", "groq", "mistral", "together", "fireworks", "huggingface",
    "deepseek", "xai", "cerebras", "perplexity", "cohere", "azure", "nvidia",
    "anthropic", "gemini", "bedrock", "watsonx",
}


def auto_order(provider: str) -> List:
    """BACKENDS in the order ``auto`` tries them for ``provider``."""
    if (provider or "").lower() in ADAPTER_FIRST:
        return [b for b in BACKENDS if b.id != "litellm"] + [b for b in BACKENDS if b.id == "litellm"]
    # A provider without an adapter keeps LiteLLM first, as before (e.g. Jan, TypeSafe)
    return [b for b in BACKENDS if b.id == "litellm"] + [b for b in BACKENDS if b.id != "litellm"]
