"""
openai_compat.py — our own backend for providers that speak OpenAI's Chat Completions API
(``POST {base}/chat/completions``, SSE streaming), on httpx. No provider SDK.

Each provider is a row in ``PROVIDERS``: default base URL, where its key comes from, and the
few places it differs from OpenAI. Adding an OpenAI-compatible provider is one row.

OpenAI reasoning models (o1 / o3 / o4 / gpt-5) take ``max_completion_tokens`` and reject
``top_p`` and any temperature but 1, so those are dropped for them rather than sent and
refused. Azure OpenAI uses a deployment URL and the ``api-key`` header instead of a bearer
token; both are fields on its row.
"""

import asyncio
import json
import os
import re
import weakref
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Tuple
from urllib.parse import quote, urlparse

import httpx

from llm.base import Chunk, LLMError, LLMRequest, LLMResponse, ToolCallDelta, Usage
from models import JAN_DEFAULT_BASE

AZURE_API_VERSION = os.getenv("AZURE_API_VERSION") or "2024-10-21"


@dataclass(frozen=True)
class Provider:
    base_url: str
    key_env: str = ""             # server-wide key when the node has none
    key_envs: Tuple[str, ...] = ()  # alternative env names, tried when key_env is unset
    default_key: str = ""         # sent when there is no key at all (servers that want one)
    local: bool = False           # base URL is a local server: "/v1" appended when missing
    stream_usage: bool = True     # send stream_options.include_usage
    api_key_header: str = "Authorization"   # Azure uses "api-key"
    api_version: str = ""         # query parameter required by Azure's deployment routes
    deployment_url: bool = False  # Azure: {base}/openai/deployments/{model}/chat/completions


PROVIDERS: Dict[str, Provider] = {
    "openai": Provider(os.getenv("OPENAI_API_BASE") or "https://api.openai.com/v1", key_env="OPENAI_API_KEY"),
    "groq": Provider(os.getenv("GROQ_API_BASE") or "https://api.groq.com/openai/v1", key_env="GROQ_API_KEY"),
    "mistral": Provider(os.getenv("MISTRAL_API_BASE") or "https://api.mistral.ai/v1",
                        key_env="MISTRAL_API_KEY"),
    "together": Provider(os.getenv("TOGETHER_API_BASE") or "https://api.together.xyz/v1",
                         key_env="TOGETHERAI_API_KEY"),
    "fireworks": Provider(os.getenv("FIREWORKS_API_BASE") or "https://api.fireworks.ai/inference/v1",
                          key_env="FIREWORKS_AI_API_KEY"),
    # Hugging Face's Inference Providers router. HF_TOKEN is the current name; older installs
    # (and LiteLLM) use HUGGINGFACE_API_KEY.
    "huggingface": Provider(os.getenv("HUGGINGFACE_API_BASE") or "https://router.huggingface.co/v1",
                            key_envs=("HF_TOKEN", "HUGGINGFACE_API_KEY")),
    "deepseek": Provider(os.getenv("DEEPSEEK_API_BASE") or "https://api.deepseek.com/v1",
                         key_env="DEEPSEEK_API_KEY"),
    "xai": Provider(os.getenv("XAI_API_BASE") or "https://api.x.ai/v1", key_env="XAI_API_KEY"),
    "cerebras": Provider(os.getenv("CEREBRAS_API_BASE") or "https://api.cerebras.ai/v1",
                         key_env="CEREBRAS_API_KEY"),
    # Perplexity's API root has no /v1. It reports usage on streamed calls without
    # stream_options, so don't ask for it (older routes reject the field).
    "perplexity": Provider(os.getenv("PERPLEXITY_API_BASE") or "https://api.perplexity.ai",
                           key_env="PERPLEXITY_API_KEY", stream_usage=False),
    "cohere": Provider(os.getenv("COHERE_API_BASE") or "https://api.cohere.ai/compatibility/v1",
                       key_env="COHERE_API_KEY"),
    # Azure needs the resource endpoint (there is no shared default) and deployment-style URLs.
    # AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY are the names the Azure SDK uses.
    "azure": Provider(os.getenv("AZURE_API_BASE") or os.getenv("AZURE_OPENAI_ENDPOINT") or "",
                      key_envs=("AZURE_API_KEY", "AZURE_OPENAI_API_KEY"),
                      api_key_header="api-key", api_version=AZURE_API_VERSION, deployment_url=True),
    # NVIDIA's hosted API catalog; a self-hosted NIM container is the same API at its own base URL.
    # Same env names as LiteLLM's nvidia_nim route, so one key serves both engines.
    "nvidia": Provider(os.getenv("NVIDIA_NIM_API_BASE") or "https://integrate.api.nvidia.com/v1",
                       key_env="NVIDIA_NIM_API_KEY"),
    "ollama": Provider(os.getenv("OLLAMA_API_BASE") or "http://localhost:11434", local=True),
    "llamacpp": Provider(os.getenv("LLAMACPP_API_BASE") or "http://127.0.0.1:8080", local=True),
    # Jan's server is llama.cpp-based; don't assume it knows stream_options
    "jan": Provider(JAN_DEFAULT_BASE, key_env="JAN_API_KEY", default_key="jan-local", local=True,
                    stream_usage=False),
}

_REASONING = re.compile(r"^(o\d|gpt-5)(?!.*-chat)")
CONNECT_TIMEOUT_S = 10.0
DEFAULT_TIMEOUT_S = 600.0     # callers enforce the node's timeout with asyncio.wait_for


def is_reasoning_model(model: str) -> bool:
    return bool(_REASONING.match(model or ""))


def _env_key(p: Provider) -> str:
    for name in ((p.key_env,) if p.key_env else ()) + p.key_envs:
        value = os.getenv(name, "")
        if value:
            return value
    return ""


def endpoint(provider: str, base_url: Optional[str], model: str = "") -> str:
    p = PROVIDERS[provider]
    base = (base_url or p.base_url).rstrip("/")
    if not base:
        raise LLMError(f"No {provider} base URL: set one on the node, in Settings → Model backends, "
                       f"or in the server's environment", provider=provider)
    if p.deployment_url:
        # Azure's newer OpenAI-compatible route already has /openai/v1 and takes the deployment
        # as `model`; the classic route puts it in the path and requires an api-version.
        if base.endswith("/openai/v1"):
            return f"{base}/chat/completions"
        if "/openai/deployments/" not in base:
            base += f"/openai/deployments/{quote(model, safe='')}"
        return f"{base}/chat/completions?api-version={quote(p.api_version)}"
    if p.local and not urlparse(base).path.rstrip("/").endswith("/v1"):
        base += "/v1"
    return f"{base}/chat/completions"


def headers(provider: str, key: str) -> Dict[str, str]:
    p = PROVIDERS[provider]
    key = key or _env_key(p) or p.default_key
    h = {"Content-Type": "application/json"}
    if key:
        if p.api_key_header == "api-key":
            h["api-key"] = key
        else:
            h["Authorization"] = f"Bearer {key}"
    return h


def body(req: LLMRequest, stream: bool) -> Dict[str, Any]:
    provider = req.provider.lower()
    # thinking_blocks are Anthropic's (a fallback can switch provider mid-run); OpenAI rejects unknown keys
    messages = [{k: v for k, v in m.items() if k != "thinking_blocks"} if "thinking_blocks" in m else m
                for m in req.messages]
    b: Dict[str, Any] = {"model": req.model, "messages": messages}
    reasoning = provider in ("openai", "azure") and is_reasoning_model(req.model)
    if req.max_tokens is not None:
        b["max_completion_tokens" if reasoning else "max_tokens"] = req.max_tokens
    if req.temperature is not None and not (reasoning and req.temperature != 1):
        b["temperature"] = req.temperature
    if req.top_p is not None and not reasoning:
        b["top_p"] = req.top_p
    if req.tools:
        b["tools"] = req.tools
    if req.tool_choice:
        b["tool_choice"] = req.tool_choice
    if stream:
        b["stream"] = True
        if PROVIDERS[provider].stream_usage:
            b["stream_options"] = {"include_usage": True}
    return b


def _usage(u: Optional[Dict[str, Any]]) -> Optional[Usage]:
    if not u:
        return None
    details = u.get("prompt_tokens_details") or {}
    # DeepSeek reports cache hits / misses at the top level (older API) as well as in details.
    cache_read = (details.get("cached_tokens") or u.get("prompt_cache_hit_tokens")
                  or u.get("cache_read_tokens") or 0)
    cache_write = details.get("cache_creation_tokens") or u.get("cache_write_tokens") or 0
    return Usage(
        prompt_tokens=u.get("prompt_tokens") or u.get("input_tokens") or 0,
        completion_tokens=u.get("completion_tokens") or u.get("output_tokens") or 0,
        total_tokens=u.get("total_tokens") or 0,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )


def _chunk(data: Dict[str, Any]) -> Chunk:
    choices = data.get("choices") or []
    if not choices:
        return Chunk(usage=_usage(data.get("usage")))
    choice = choices[0]
    delta = choice.get("delta") or {}
    tool_calls = []
    for tc in delta.get("tool_calls") or []:
        fn = tc.get("function") or {}
        tool_calls.append(ToolCallDelta(index=tc.get("index", 0), id=tc.get("id") or "",
                                        name=fn.get("name") or "", arguments=fn.get("arguments") or ""))
    return Chunk(text=delta.get("content") or "", tool_calls=tool_calls,
                 finish_reason=choice.get("finish_reason"), usage=_usage(data.get("usage")))


def _error(provider: str, status: int, raw: bytes) -> LLMError:
    try:
        err = json.loads(raw).get("error")
        message = (err.get("message") if isinstance(err, dict) else err) or raw.decode(errors="replace")
    except (ValueError, AttributeError):
        message = raw.decode(errors="replace")
    return LLMError(f"{provider} returned HTTP {status}: {str(message).strip()[:500]}",
                    provider=provider, status=status, retryable=status in (408, 409, 429) or status >= 500)


def _unreachable(provider: str, url: str, e: Exception) -> LLMError:
    hint = " — is the local server running?" if PROVIDERS[provider].local else ""
    return LLMError(f"Can't reach {provider} at {url}{hint} ({type(e).__name__}: {e})",
                    provider=provider, retryable=True)


class OpenAICompatStream:
    def __init__(self, provider: str, response: httpx.Response):
        self._provider = provider
        self._response = response
        self.usage: Optional[Usage] = None

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        try:
            async for line in self._response.aiter_lines():
                if not line.startswith("data:"):
                    continue          # SSE comments, keep-alives, event: lines
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                if data.get("error"):
                    raise _error(self._provider, self._response.status_code, payload.encode())
                chunk = _chunk(data)
                if chunk.usage:
                    self.usage = chunk.usage
                yield chunk
        except httpx.HTTPError as e:
            raise LLMError(f"{self._provider} stream broke off ({type(e).__name__}: {e})",
                           provider=self._provider, retryable=True) from e
        finally:
            await self._response.aclose()


class OpenAICompatBackend:
    id = "openai_compat"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None):
        # One pooled client per event loop (a client can't be shared across loops).
        # ``transport`` replaces the network, for tests.
        self.transport = transport
        self._clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = \
            weakref.WeakKeyDictionary()

    def supports(self, provider: str) -> bool:
        return (provider or "").lower() in PROVIDERS

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._clients.get(loop)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=httpx.Timeout(DEFAULT_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
                                       transport=self.transport)
            self._clients[loop] = client
        return client

    def _request(self, req: LLMRequest, stream: bool) -> httpx.Request:
        provider = req.provider.lower()
        timeout = (httpx.Timeout(req.timeout_s, connect=min(req.timeout_s, CONNECT_TIMEOUT_S))
                   if req.timeout_s else None)
        return self._client().build_request(
            "POST", endpoint(provider, req.base_url, req.model), headers=headers(provider, req.api_key),
            json=body(req, stream), **({"timeout": timeout} if timeout else {}),
        )

    async def complete(self, req: LLMRequest) -> LLMResponse:
        provider = req.provider.lower()
        request = self._request(req, stream=False)
        try:
            resp = await self._client().send(request)
        except httpx.HTTPError as e:
            raise _unreachable(provider, str(request.url), e) from e
        if resp.status_code != 200:
            raise _error(provider, resp.status_code, resp.content)
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        return LLMResponse(
            text=(choice.get("message") or {}).get("content") or "",
            finish_reason=choice.get("finish_reason") or "stop",
            usage=_usage(data.get("usage")),
        )

    async def stream(self, req: LLMRequest) -> OpenAICompatStream:
        provider = req.provider.lower()
        request = self._request(req, stream=True)
        try:
            resp = await self._client().send(request, stream=True)
        except httpx.HTTPError as e:
            raise _unreachable(provider, str(request.url), e) from e
        if resp.status_code != 200:
            raw = await resp.aread()
            await resp.aclose()
            raise _error(provider, resp.status_code, raw)
        return OpenAICompatStream(provider, resp)
