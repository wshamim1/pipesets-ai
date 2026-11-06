"""
litellm.py — optional legacy fallback backend on LiteLLM.

Every provider we ship now has its own adapter (llm/backends/); this backend remains for an
explicit Settings → Model backends choice, for a provider without an adapter, and for installs
that still have the package. All LiteLLM specifics live here: model-string prefixes, auth
kwargs, response and stream objects and exceptions (turned into ``LLMError``). It reports token
usage (cache reads / writes included); the gateway prices it.
"""

import json
import os
import re
from typing import Any, AsyncIterator, Dict, Optional

import litellm

from llm.base import Chunk, LLMError, LLMRequest, LLMResponse, ToolCallDelta, Usage
from models import JAN_DEFAULT_BASE

# Silence LiteLLM's verbose logging
litellm.suppress_debug_info = True
os.environ.setdefault("LITELLM_LOG", "ERROR")

# Used when neither the node nor Settings → Model backends gives a base URL
# watsonx.ai is per region; the project comes from WATSONX_PROJECT_ID, which LiteLLM reads itself
DEFAULT_BASES = {"ollama": "http://localhost:11434", "jan": JAN_DEFAULT_BASE,
                 "watsonx": os.getenv("WATSONX_URL") or "https://us-south.ml.cloud.ibm.com"}

# LiteLLM drops a streamed response's usage unless the request asks for it, and then the run
# is priced at $0 (tests/gateway/test_llm_contract.py). Jan's server may not know stream_options.
NO_STREAM_USAGE = {"jan"}
_REASONING = re.compile(r"^(o\d|gpt-5)(?!.*-chat)")


def _is_reasoning_model(model: str) -> bool:
    return bool(_REASONING.match(model or ""))


def model_string(provider: str, model: str) -> str:
    """LiteLLM's "<route>/<model>" name for a provider + model."""
    p = (provider or "").lower()
    if p == "openai":
        return model
    if p == "llamacpp":
        # llama.cpp's llama-server is OpenAI-compatible; LiteLLM's llamafile route targets it
        # (defaults to http://127.0.0.1:8080/v1, no key needed; api_base overrides).
        return f"llamafile/{model}"
    if p == "jan":
        # Jan's local server is OpenAI-compatible; without a base URL this route would mean api.openai.com
        return f"openai/{model}"
    if p == "nvidia":
        return f"nvidia_nim/{model}"
    if p in ("together", "fireworks"):
        # LiteLLM's routes are together_ai/ and fireworks_ai/; plain together/ is rejected
        return f"{p}_ai/{model}"
    if p in ("ollama", "huggingface", "anthropic", "deepseek", "xai", "cerebras", "perplexity",
             "groq", "gemini", "bedrock", "azure", "cohere", "mistral", "watsonx"):
        return f"{p}/{model}"
    return model


def _auth_kwargs(provider: str, key: str) -> Dict[str, Any]:
    """{"api_key": ...} or {} for env/keyless (LiteLLM then reads the server's env vars)."""
    p = (provider or "").lower()
    if not key:
        # Jan rides on LiteLLM's openai/ route, which would otherwise pick up OPENAI_API_KEY
        return {"api_key": "jan-local"} if p == "jan" else {}
    if p == "bedrock":
        return {"aws_access_key_id": key}
    return {"api_key": key}


def _kwargs(req: LLMRequest) -> Dict[str, Any]:
    provider = req.provider.lower()
    reasoning = provider in ("openai", "azure") and _is_reasoning_model(req.model)
    kwargs: Dict[str, Any] = {
        "model": model_string(provider, req.model),
        "messages": req.messages,
        **_auth_kwargs(provider, req.api_key),
    }
    base_url = req.base_url or DEFAULT_BASES.get(provider)
    if base_url:
        kwargs["api_base"] = base_url
    if req.temperature is not None:
        kwargs["temperature"] = 1 if reasoning and req.temperature != 1 else req.temperature
    if req.max_tokens is not None:
        kwargs["max_completion_tokens" if reasoning else "max_tokens"] = req.max_tokens
    if req.top_p is not None and not reasoning:
        kwargs["top_p"] = req.top_p
    for name in ("tools", "tool_choice"):
        value = getattr(req, name)
        if value is not None:
            kwargs[name] = value
    if req.timeout_s is not None:
        kwargs["timeout"] = req.timeout_s
    return kwargs


_RETRYABLE = tuple(getattr(litellm, name) for name in (
    "Timeout", "APIConnectionError", "RateLimitError", "ServiceUnavailableError", "InternalServerError",
    "MidStreamFallbackError") if hasattr(litellm, name))


def _message(e: Exception) -> str:
    """LiteLLM's message without its own prefixes ("litellm.RateLimitError: AnthropicException - ")
    and, when the rest is the provider's JSON error body, just the provider's message."""
    text = str(getattr(e, "message", None) or e)
    text = re.sub(r"^(litellm\.\w+:\s*)+", "", text)
    text = re.sub(r"^(\w+Error:\s*)?\w+(Exception|Error)\s*-\s*", "", text).strip()
    try:
        body = json.loads(text)
        err = body.get("error") if isinstance(body, dict) else None
        text = (err.get("message") if isinstance(err, dict) else err) or text
    except ValueError:
        pass
    return str(text)[:500]


def _error(provider: str, e: Exception) -> LLMError:
    status = getattr(e, "status_code", None)
    status = status if isinstance(status, int) else None
    retryable = isinstance(e, _RETRYABLE) or status in (408, 409, 429) or (status or 0) >= 500
    where = f"returned HTTP {status}" if status else "call failed"
    return LLMError(f"{provider} {where}: {_message(e)}", provider=provider, status=status, retryable=retryable)


def _is_litellm_error(e: Exception) -> bool:
    return type(e).__module__.split(".")[0] in ("litellm", "openai", "httpx")


def _usage(raw: Any) -> Optional[Usage]:
    u = getattr(raw, "usage", None)
    if not u:
        return None
    # LiteLLM counts cache reads / writes inside prompt_tokens for every provider
    details = getattr(u, "prompt_tokens_details", None)
    return Usage(
        prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(u, "completion_tokens", 0) or 0,
        total_tokens=getattr(u, "total_tokens", 0) or 0,
        cache_read_tokens=(getattr(details, "cached_tokens", None)
                           or getattr(u, "cache_read_input_tokens", None) or 0),
        cache_write_tokens=(getattr(u, "cache_creation_input_tokens", None)
                            or getattr(details, "cache_creation_tokens", None) or 0),
    )


def _chunk(raw: Any) -> Chunk:
    choice = raw.choices[0] if getattr(raw, "choices", None) else None
    if not choice:
        return Chunk(usage=_usage(raw))
    delta = choice.delta
    tool_calls = []
    for tc in getattr(delta, "tool_calls", None) or []:
        fn = getattr(tc, "function", None)
        tool_calls.append(ToolCallDelta(
            index=tc.index,
            id=tc.id or "",
            name=(fn.name if fn else None) or "",
            arguments=(fn.arguments if fn else None) or "",
        ))
    return Chunk(text=delta.content or "", tool_calls=tool_calls,
                 finish_reason=choice.finish_reason, usage=_usage(raw))


class LiteLLMStream:
    def __init__(self, raw_stream: Any, provider: str):
        self._raw_stream = raw_stream
        self._provider = provider
        self.usage: Optional[Usage] = None

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        try:
            async for raw in self._raw_stream:
                chunk = _chunk(raw)
                if chunk.usage:
                    self.usage = chunk.usage
                yield chunk
        except Exception as e:
            if _is_litellm_error(e):
                raise _error(self._provider, e) from e
            raise


class LiteLLMBackend:
    id = "litellm"

    def supports(self, provider: str) -> bool:
        return True

    async def complete(self, req: LLMRequest) -> LLMResponse:
        try:
            raw = await litellm.acompletion(**_kwargs(req))
        except Exception as e:
            if _is_litellm_error(e):
                raise _error(req.provider, e) from e
            raise
        choice = raw.choices[0] if raw.choices else None
        return LLMResponse(
            text=(choice.message.content if choice else None) or "",
            finish_reason=(choice.finish_reason if choice else None) or "stop",
            usage=_usage(raw),
        )

    async def stream(self, req: LLMRequest) -> LiteLLMStream:
        kwargs = _kwargs(req)
        if req.provider.lower() not in NO_STREAM_USAGE:
            kwargs["stream_options"] = {"include_usage": True}
        try:
            raw_stream = await litellm.acompletion(stream=True, **kwargs)
        except Exception as e:
            if _is_litellm_error(e):
                raise _error(req.provider, e) from e
            raise
        return LiteLLMStream(raw_stream, req.provider)
