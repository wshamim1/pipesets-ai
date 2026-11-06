# LLM contract cassettes

What a provider sends back, and what every backend must turn it into. `tests/gateway/test_llm_contract.py`
replays each cassette under every backend that speaks its wire format for that provider — our own
adapter and LiteLLM — and checks they produce the same text, tool calls, finish reason, usage, cost
and typed `LLMError`. A provider moves from LiteLLM to our adapter (`llm/backends/__init__.py`)
only once its cassettes pass on the adapter.

- `openai_chat/` — Chat Completions (`/chat/completions`, SSE `data:` lines)
- `anthropic_messages/` — Messages API (`/v1/messages`, SSE `event:` + `data:`)

A cassette:

```json
{
  "source": "where the responses came from (recording or API reference)",
  "providers": {"openai": "gpt-4o-mini", "jan": "llama3.2-3b"},   // provider -> model to request
  "modes": ["stream", "complete"],                                 // default: both
  "request": {"messages": [...], "max_tokens": 64, "tools": [...]},
  "responses": {
    "stream":   {"status": 200, "events": [{...}, "[DONE]"]},      // or "raw": "<SSE text>"
    "complete": {"status": 200, "body": {...}}
  },
  "expect": {"text": "...", "finish_reason": "stop|length|tool_calls", "tool_calls": [...],
             "usage": {...}}                                       // or {"error": {...}}
}
```

Cost is never written down: it must equal `llm.pricing.cost_usd(provider, model, expected usage)`
for every backend, so a price-table update doesn't break the suite but a backend that loses
cache tokens does. The fake transport blocks real sockets, so a test can never reach a provider.
