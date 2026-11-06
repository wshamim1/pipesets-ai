"""
base.py — the gateway's own types and the contract every LLM backend implements.

Nothing outside ``llm/backends/`` sees a provider SDK's objects: callers build an
``LLMRequest`` and get back an ``LLMResponse`` or an ``LLMStream`` of ``Chunk``s.

Messages and tool schemas stay in the OpenAI chat format (``{"role": ..., "content": ...}``,
``{"type": "function", "function": {...}}``) — it's what the runtime already builds and
stores everywhere; a backend for a provider with a different format converts at its edge.
"""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Protocol


@dataclass
class LLMRequest:
    provider: str
    model: str
    messages: List[Dict[str, Any]]
    # The node's key as configured: plaintext, a "secret://" ref, a sealed value or "".
    # The gateway resolves it before a backend sees it.
    api_key: str = ""
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[str] = None
    # Per-request timeout enforced by the backend's client. Callers that wrap the call in
    # asyncio.wait_for (with retries / fallback) leave it unset.
    timeout_s: Optional[float] = None


@dataclass
class Usage:
    prompt_tokens: int = 0          # includes cache_read_tokens and cache_write_tokens
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens}


@dataclass
class ToolCallDelta:
    """A fragment of a streamed tool call; fragments with the same index belong together."""
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class Chunk:
    text: str = ""
    tool_calls: List[ToolCallDelta] = field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Optional[Usage] = None
    # Finished reasoning blocks in the provider's own format (Anthropic thinking / redacted_thinking).
    # Opaque: the caller puts them on the assistant message as ``thinking_blocks`` when it sends
    # the turn back (tool loop), and the backend that produced them restores them.
    thinking_blocks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class LLMResponse:
    text: str
    finish_reason: str = "stop"
    usage: Optional[Usage] = None
    cost_usd: float = 0.0
    backend: str = ""               # id of the backend that served it; set by the gateway


class LLMError(RuntimeError):
    """A provider refused or failed a call. ``str()`` is the message shown to the user."""

    def __init__(self, message: str, *, provider: str = "", status: Optional[int] = None,
                 retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retryable = retryable


class LLMStream(Protocol):
    """Async iterator of Chunks. ``usage`` is final once iteration ends."""

    usage: Optional[Usage]

    def __aiter__(self) -> AsyncIterator[Chunk]: ...


class LLMBackend(Protocol):
    id: str

    def supports(self, provider: str) -> bool: ...

    async def complete(self, req: LLMRequest) -> LLMResponse: ...

    async def stream(self, req: LLMRequest) -> LLMStream: ...
