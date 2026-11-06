# 7. Guardrails and budgets

## Guardrails (Middleware nodes)

A **Middleware** node checks what goes into and comes out of a model. Drag one from **Control &
safety**, pick its **Type**, and **connect it to the LLM node it guards**; it only guards LLM nodes
it's wired to. Stack several on one LLM node. Each card 4 has **Test** to try it with a sample
before saving.

Guardrails apply to normal and streaming runs. A streamed answer that fails a check is pulled back
mid-stream.

### Accuracy

| Type | What it does | Settings |
|---|---|---|
| **Grounding Check** | Stops made-up answers not backed by tool output or documents | **When it triggers:** when every tool returns nothing ("no results", `[]`, `{}`…). **Then:** reply with a fixed message (safest), block, warn the model nothing was found, or let it through flagged. Also checks numbers in the answer against the sources (**Min digits**, **Allowed misses**). |
| **Custom Rule** | Your rules in plain English, checked by a model after every answer | **Every answer must follow these rules** (one per line; all checked in one call). **Checked by:** the node's own model or a different one. **If the judge can't answer:** what to do. Small models (under ~7B) judge poorly. |

### Safety

| Type | What it does | Settings |
|---|---|---|
| **Content Moderation** | Blocks harmful input and detects personal data (PII) | Sensitivity: low (fewest false positives), medium (recommended), high (strictest). Extra patterns. |
| **Prompt Injection** | Detects jailbreaks and "ignore your instructions" attempts | Sensitivity; action: block or flag |
| **Custom Pattern** | Your own words, phrases or regular expressions | **Match:** words or regex. **Check:** the prompt, the answer or both. Action and message. |

### Limits

| Type | What it does | Settings |
|---|---|---|
| **Cost Tracker** | A hard cap per run | Max tokens, Max cost USD (0 = unlimited), Alert above USD |
| **Rate Limiter** | Limits requests in a time window | Max requests, Window (seconds), **Count per:** session (each conversation), caller (each API key or user) or app (everyone together). Over the limit: throttle (HTTP 429), block or flag. |

### Actions

- **Block:** stop the run with a clear reason.
- **Flag:** let it through, marked in the trace. Use it while tuning a new rule, then switch to block.
- **Throttle:** for rate limits, reject with HTTP 429 so callers can retry.

### Choosing guardrails

| Pipeline | Start with |
|---|---|
| Public chat link or customer-facing bot | Prompt Injection, Content Moderation, Rate Limiter (per session), Cost Tracker |
| RAG / document Q&A | Grounding Check, Custom Rule ("cite the source for every figure") |
| Internal tool with real actions (email, writes) | Custom Rule, a Human Gate before the action, Cost Tracker |
| Batch or scheduled jobs | Cost Tracker |

## Budgets

Budgets cap spend across runs, not one run.

1. **Monitor → Costs & budgets → Spend Budgets.**
2. Choose the scope (**Global** or one **Pipeline**), the period (**Daily**, **Monthly** or
   **Total**), and the amount in USD.
3. Choose what happens when it's exceeded: **Block runs** or **Warn only**.

Exceeded budgets are marked "⚠ exceeded". Costs come from Pipesets' own price table for each model
and count every model call a run makes, including nested pipelines and agents.

Runs from API keys, schedules, webhooks and chat links all act as a user, so that user's budgets
and guardrails apply. There's no way around them by calling the API.
