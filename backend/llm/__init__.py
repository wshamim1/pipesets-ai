"""
llm — Pipesets' LLM gateway. Every model call in the backend goes through here.

    import llm
    resp = await llm.complete(llm.LLMRequest(provider="openai", model="gpt-4o", messages=[...]))
    stream = await llm.stream(req)
    async for chunk in stream: ...

The gateway resolves the node's API key (plaintext, "secret://" ref, sealed value or the
project's default for the provider — see services/llm_auth.py) so no backend can skip the
vault's kind checks, then hands the request to a backend in ``llm/backends/``. Cost comes
from the gateway's own price table (llm/pricing.py) and the usage the backend reports —
``resp.cost_usd``, or ``stream.cost_usd`` once a stream has been read to the end.

Backend choice and the provider's base URL come from Settings → Model backends
(services/llm_settings.py), most specific first: project → workspace → ``LLM_BACKEND_<PROVIDER>``
→ ``LLM_BACKEND`` → ``auto``; a node's own base URL beats the settings. ``auto`` — and a named
backend that can't serve the provider — means the first backend in ``llm/backends/`` that
supports it, in ``llm.backends.auto_order`` (our own adapters first, LiteLLM only as a legacy
fallback for providers without one). Responses and streams carry the id of the backend that served them
(``.backend``). Retries, fallback models and overall timeouts stay with the callers for now.

``with llm.metered() as meter:`` adds up the cost of every call made inside the block, including
in tasks it starts — how an eval prices a whole pipeline run (``meter.usd``).
"""

import contextlib
import dataclasses
from contextvars import ContextVar
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from llm import pricing
from llm.backends import BACKENDS, auto_order
from llm.base import (  # noqa: F401 — re-exported
    Chunk, LLMBackend, LLMError, LLMRequest, LLMResponse, LLMStream, ToolCallDelta, Usage,
)
from services import llm_settings
from services.llm_auth import resolve_api_key


class BackendUnavailable(RuntimeError):
    pass


class CostMeter:
    def __init__(self) -> None:
        self.usd = 0.0
        self.calls = 0

    def add(self, usd: float) -> None:
        self.usd += usd
        self.calls += 1


_meter: ContextVar[Optional[CostMeter]] = ContextVar("llm_cost_meter", default=None)


@contextlib.contextmanager
def metered() -> Iterator[CostMeter]:
    """Meter the calls made inside the block. Nested blocks each get their own meter and also
    count towards the outer one."""
    outer = _meter.get()
    meter = CostMeter()
    if outer is not None:
        inner_add = meter.add

        def add(usd: float) -> None:
            inner_add(usd)
            outer.add(usd)
        meter.add = add  # type: ignore[method-assign]
    token = _meter.set(meter)
    try:
        yield meter
    finally:
        _meter.reset(token)


def _record(usd: float, meter: Optional[CostMeter] = None) -> None:
    meter = meter or _meter.get()
    if meter is not None:
        meter.add(usd)


def backends_for(provider: str) -> List[str]:
    """Ids of the backends that can serve ``provider``, in ``auto`` order."""
    return [b.id for b in auto_order(provider) if b.supports(provider)]


def backend_for(provider: str, wanted: Optional[str] = None) -> LLMBackend:
    """The backend for ``provider``: ``wanted`` if given, else the effective setting."""
    wanted = (wanted or llm_settings.effective(provider)["backend"]).strip().lower()
    known = {b.id: b for b in BACKENDS}
    if wanted != "auto":
        if wanted not in known:
            raise BackendUnavailable(f"Unknown LLM backend '{wanted}' (available: {', '.join(known)})")
        if known[wanted].supports(provider):
            return known[wanted]
    for backend in auto_order(provider):
        if backend.supports(provider):
            return backend
    raise BackendUnavailable(f"No LLM backend supports provider '{provider}' (available: {', '.join(known)})")


def request_from_config(cfg: Any, messages: List[Dict[str, Any]], **params: Any) -> LLMRequest:
    """Request for an LLM node config (models.LLMConfig or anything with provider / model /
    api_key / base_url). Sampling settings are not copied — pass them in ``params``."""
    return LLMRequest(provider=cfg.provider, model=cfg.model, messages=messages,
                      api_key=cfg.api_key or "", base_url=cfg.base_url or None, **params)


def _resolved(req: LLMRequest) -> LLMRequest:
    base_url = req.base_url or llm_settings.effective(req.provider)["base_url"] or None
    return dataclasses.replace(req, api_key=resolve_api_key(req.provider, req.api_key), base_url=base_url)


class PricedStream:
    """A backend's stream plus its cost, priced from the usage it reported."""

    def __init__(self, inner: LLMStream, provider: str, model: str, backend: str):
        self._inner = inner
        self._provider = provider
        self._model = model
        self.backend = backend
        self._meter = _meter.get()   # where the stream was opened, not where it's read

    async def __aiter__(self) -> AsyncIterator[Chunk]:
        async for chunk in self._inner:
            yield chunk
        _record(self.cost_usd, self._meter)

    @property
    def usage(self) -> Optional[Usage]:
        return self._inner.usage

    @property
    def cost_usd(self) -> float:
        return pricing.cost_usd(self._provider, self._model, self.usage)


async def complete(req: LLMRequest, backend_id: Optional[str] = None) -> LLMResponse:
    """``backend_id`` forces a backend (Settings → Test); normally the setting decides."""
    backend = backend_for(req.provider, backend_id)
    resp = await backend.complete(_resolved(req))
    resp.cost_usd = pricing.cost_usd(req.provider, req.model, resp.usage)
    resp.backend = backend.id
    _record(resp.cost_usd)
    return resp


async def stream(req: LLMRequest, backend_id: Optional[str] = None) -> PricedStream:
    backend = backend_for(req.provider, backend_id)
    inner = await backend.stream(_resolved(req))
    return PricedStream(inner, req.provider, req.model, backend.id)
