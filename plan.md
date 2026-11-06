# Pipesets AI — Plan

> Everything still open, merged from `90_day_mvp_plan.md`, `next_90_days_plan.md` and
> `desktop_app_plan.md` (2026-10-28). Shipped work lives in [done.md](done.md) — when an item
> lands, move it there.
>
> Theme: **turn a feature-complete MVP into something a pilot customer can safely run** —
> harden first, scale the runtime second, then add agent capabilities and the developer
> workflow.

---

## 0) Priority Order

0. **P1** Document extraction for the first design partner (lease, license and rent roll
   abstraction with citations and human review) — first version shipped 2026-11-02, see below
1. **A2** Test harness + CI — guards everything after it
2. **A5** Own LLM gateway — every adapter is built; left: live checks, recorded cassettes, then
   drop the LiteLLM package (see A5 status)
3. **A3** Finish the security pass
4. **A4** Edge + network isolation
5. Phase B built (B1 job queue, B2 shared state, B3 observability); leftovers listed under each
6. **C1** Store node + long-term memory
7. **D** MVP verification, docs, pilot
8. **C2–C7**, desktop packaging, in whatever order pilots ask for
9. **C9** Embeddable chat — public chat links shipped 2026-11-01 (anyone with the link); next:
   passcode and sign-in links, then the Streamlit example, website embed and demo site
10. §4b product features — built 2026-11-03: **F2** feedback into evals, **F5** batch runs, **F6**
    step-through debugging (first versions; none tried in a browser or with a real model yet).
    F5 documents as batch input built too (P1's real-lease check is ready to run), and **C10** step 1
    (skills on demand, skill readiness). **A3: connections aren't tenant-scoped** — fix before a
    second tenant uses the system. Then the rest of **F1** (chat edits to a scaffold); F3, F4,
    F7–F10 after

Desktop work (§5) runs in parallel; it doesn't block the pilot.

---

## P1 — Document Extraction (design partner pilot)

Goal: turn leases, licenses, rent rolls and operator emails into reviewed, cited records. Every
field carries its source page and quote, and a person approves it before anything relies on it.
First version shipped 2026-11-02 (see [done.md](done.md#document-extraction-plan-md-p1)): OCR
engines (Tesseract, OCRmyPDF, Docling, vision model) for scanned PDFs and images, Docling loader,
email loader, Yardi report export loader, Structured Extract tool with quote checks, review queue
with export to eval datasets.

### Remaining
- **Real-world check:** run Structured Extract on 20–30 real leases with a real model; measure
  per-field accuracy against hand abstraction (target 95%+ on dates and rent) and tune the prompt.
  Ready to run since 2026-11-03: a document batch (Automation → Batches → Documents, prompt
  `{path}`) files every field under the batch's name, and Review → Accuracy reports on the set
- **Compare OCR engines on real scans:** Tesseract vs OCRmyPDF vs Docling vs a vision model on a
  handful of real scanned leases (accuracy on dates, rent tables, signatures pages; time; cost),
  then pick the default
- ✅ 2026-11-02: **Docling runs on the Intel Mac dev venv.** torch stops at 2.2.2 there, so
  `requirements.txt` pins `numpy<2` and `transformers<5` for macOS x86_64 only (the Linux lock
  keeps torch 2.15 / NumPy 2). docling-parse's macOS x86_64 build segfaults on scanned PDFs (Linux
  is fine), so `_docling.py` uses the pypdfium2 PDF backend there. Checked for real: text PDF,
  scanned PDF, `ocr_engine` docling and tesseract, image OCR
- Docling joins a paragraph that runs across a page break into the first page, so a quote from
  the continuation is cited one page early
- **OCRmyPDF not tried for real** (no ghostscript on the dev machine); its flags
  (`--skip-text --rotate-pages --pages`) are untested
- **Vision OCR:** the gateway passes images only for OpenAI-compatible, Anthropic and Ollama models —
  add image parts to the Gemini and Bedrock adapters. Not tried against a real model yet
- **Cloud OCR engines** (Azure Document Intelligence Layout, AWS Textract — the Textract loader is
  still "Soon"): add as `ocr_engine` options with a Connection for credentials, for table-heavy
  exhibits
- **RapidOCR for the desktop app** (no torch; the desktop build has no Docling)
- Backend Docker image with `tesseract-ocr` not built yet — build it and run the real-scan test inside
- `requirements.lock` "via" comments don't list `pypdfium2` / `pillow` as direct requirements yet
  (same versions; regenerate the lock with the command in its header)
- **Yardi export loader:** check against real Voyager exports (rent roll, lease expiration,
  tenancy schedule) and add the column spellings they use; `.xls` isn't read
- **Yardi API connection:** only once API / interface access is confirmed
- **Inbox loader (IMAP / Microsoft Graph):** the email loader reads saved `.eml` / `.msg` files;
  pulling straight from a mailbox needs a Connection type and a loader
- **`.msg` support** needs `extract-msg` in requirements (left out to keep the lock file unchanged)
- **Review queue:**
  - ✅ 2026-11-02: cited page (text, quote highlighted), bulk approve, accuracy report — see done.md
  - The page view shows the page's text, not the scan; showing the page image needs the file kept
    (or rendered) at filing time
  - Eval datasets aren't tenant-scoped (existing gap), so exported cases are visible across tenants
- **Long documents:** ✅ 2026-11-02 split into parts and merged (done.md). Still open: try it on a
  real 100+ page lease with a real model (cost, and whether the section-start split lands well
  on Docling / OCR text); a term defined in one part ("Commencement Date" in Article 1) and used
  in another isn't resolved across parts — the model only sees its own part
- **Entity matching:** link Yardi tenants, lease operators and licensees that are written
  differently (fuzzy match + review), the next step after extraction

---

## 1) Phase A — Production Hardening 🔴 Pilot blocker

### A2. Test harness + CI — remaining
- First fully green CI run: since the CPU lock the SQLite leg, frontend and Docker builds pass;
  the Postgres leg failed on SQLite-only SQL (fixed 2026-10-29, reproduced and passing against a
  local Postgres 16) — confirm on the next push
- Frontend: deeper tests for the large panels (Tool, Middleware, Child agent, Doc loader) beyond
  the shared contract; `PromptRunner` and `App` untested
- Branch protection on `main` requiring the CI checks (GitHub setting)

### A3. Security pass — remaining
- Adversarial suite — next: record the judge cases from a real model
  (`PIPESETS_RECORD_JUDGE=…`, see `tests/security/adversarial/README.md`); `custom_rule` judges the answer
  only, after the model ran — a prompt-side judge would stop paraphrased injection before the
  model; aggregate per-project cap across API keys if a pilot asks
- Sandbox runner: build and run the image for real (compose and k8s) — only tested with a stand-in
  engine so far; check nested rootless podman applies `--memory` / `--cpus` inside it
- Per-tool network allowlist in the sandbox
- **Connections aren't tenant-scoped (found 2026-11-03):** the `connections` table has no tenant /
  project columns and `/api/connections` lists, reads, updates, tests and deletes every connection
  for every workspace (`routers/connections.py`). Credentials stay sealed, but any signed-in user
  sees every connection's name and settings and can edit, delete or use them. Add `tenant_id` /
  `project_id` (migration, backfill to the demo tenant), scope every query, ACL checks, and a
  scoping test like `test_skills_scoping.py`

### A4. Edge + network isolation — remaining
- Built 2026-10-29 (see done.md). Still open: first real Let's Encrypt issuance on a public host;
  apply `ingress.yaml` + `networkpolicy.yaml` on a cluster with an enforcing CNI and check probes
  still pass; `FORWARDED_ALLOW_IPS` for the k8s backend (client IPs in the audit log)

### A5. Own LLM gateway (replace the LiteLLM dependency)

**Status (2026-11-01):** code done, verification and removal open.

| Backend | Providers `auto` sends to it | Unit tests | Live-checked | Contract cassettes |
|---|---|---|---|---|
| `openai_compat` | openai, ollama, llamacpp | ✅ | ✅ | ✅ |
| `openai_compat` | groq, mistral, together, fireworks, huggingface, deepseek, xai, cerebras, perplexity, cohere, azure, nvidia | ✅ | ❌ | ❌ |
| `anthropic` | anthropic | ✅ | ❌ | ✅ (hand-written) |
| `gemini` | gemini | ✅ | ❌ | ❌ |
| `bedrock` | bedrock | ✅ | ❌ | ❌ |
| `watsonx` | watsonx | ✅ | ❌ | ❌ |
| `mistral` (native) | none by default — opt-in for mistral | ✅ | ❌ **not tested** | ❌ |
| `cohere` (native v2) | none by default — opt-in for cohere | ✅ | ❌ **not tested** | ❌ |
| `ollama` (native `/api/chat`) | none by default — opt-in for ollama | ✅ | ❌ **not tested** | ❌ |
| `litellm` | typesafe only (and anyone who picks it in Settings) | — | — | — |

**Native adapters (2026-11-01) — built, NOT TESTED against the real APIs.** For providers that
`openai_compat` also serves but that have their own API: `llm/backends/mistral.py` (9-char
tool-call ids mapped consistently, Magistral content chunks — thinking dropped, `any` for
`required`, no `stream_options`), `llm/backends/cohere.py` (`/v2/chat`, typed stream events,
`p` clamped to 0.01–0.99, `tool_plan`, priced on `billed_units`; a saved `/compatibility/v1` base
URL is rewritten), `llm/backends/ollama.py` (`/api/chat` NDJSON, `options.num_predict`, whole tool
calls numbered `call_N`, `tool_name` on results, base64 `images`, `thinking` not shown; a saved
`/v1` base URL is stripped). Unit tests only, on hand-written responses
(`tests/gateway/test_llm_native.py`, 14 cases). Registered after `openai_compat`, so `auto` does not use
them: pick them per provider in Settings → Model backends. Make one the `auto` default only after
its live check passes. The other OpenAI-format providers (Groq, Together, Fireworks, DeepSeek,
xAI, Cerebras, NVIDIA, Azure, Hugging Face, Perplexity) need no separate adapter: that format is
their native API.

LiteLLM is still installed: pinned in `requirements.txt` and the lock, bundled by
`pipesets-backend.spec` (and in the current `dist/` build), imported in a `try` by
`llm/backends/__init__.py`. Saved Settings rows that say `litellm` keep using it until switched —
**Settings → Model backends → Migrate LiteLLM overrides** (`POST /api/llm-settings/migrate-litellm`)
moves them to `auto`. `mock` never reaches the gateway (simulated in `run.py` / `llm_runner.py`).

**Left to finish A5**
- [ ] Live check anthropic, gemini, bedrock, watsonx and each `openai_compat` cloud provider
  (complete, stream, streamed tool call, tool-result turn, `length`, bad key / bad model) — same
  checklist OpenAI passed on 2026-10-31
- [ ] Live check the native `mistral`, `cohere` and `ollama` adapters (same checklist; for Ollama
  also a thinking model and an image), then decide whether `auto` should prefer them
- [ ] Ollama native: show `message.thinking` as thoughts (the runtime has no field for it yet)
- [ ] Contract cassettes recorded from the real APIs (add a recorder); cassettes for gemini,
  bedrock, watsonx and the `openai_compat` cloud providers
- [ ] TypeSafe: decide — own small adapter for its evaluation API, or drop it from the catalog
- [x] ~~Remove LiteLLM~~ — **decided 2026-11-01: keep LiteLLM** as the optional fallback (and for
  TypeSafe). Every provider still runs without it installed
- [ ] Measure desktop build size and backend startup with and without the LiteLLM package
- [ ] Per-node "Engine" override; grey out features the chosen backend lacks
- [ ] Show thinking: Ollama's streamed `reasoning` field, Anthropic summarized thinking
- [ ] Retire `o4-mini` from the catalog (404 at OpenAI)

**Decision (2026-10-28):** build our own in-process LLM gateway instead of depending on LiteLLM.
LiteLLM supports 140+ providers, but we use 21 and only two of its functions
(`acompletion`, `completion_cost`), called directly from 7 files (`routers/run.py`,
`routers/agents.py`, `routers/eval.py`, `routers/apps.py`, `services/llm_auth.py`,
`services/guardrail_judge.py`, `services/llm_runner.py`). The requirement is unpinned
(`litellm>=1.40.0`) and it releases several times a week, so any install can change streamed
tool-call parsing, error mapping or prices; it has also shipped compromised PyPI releases.
Owning the gateway removes that risk, shrinks the desktop build and speeds up startup.
LangChain and Pydantic AI were considered and rejected for model calls — both wrap the same
official SDKs and add their own churn.

**Layout** — same registry pattern as `backend/tools/` and `backend/loaders/`:

```
backend/llm/
  __init__.py        # registry + routing: picks the backend, fallback chain, timeouts
  base.py            # LLMBackend protocol + our types: Message, ToolCall, Chunk, Usage, LLMError
  pricing.py         # price table (versioned JSON) × token usage — cost never depends on the backend
  backends/
    openai_compat.py # httpx, /chat/completions + SSE — 15 providers
    anthropic.py     # official anthropic SDK
    gemini.py        # httpx, GenerateContent / streamGenerateContent
    bedrock.py       # boto3 Converse (SigV4)
    watsonx.py       # httpx, IBM Cloud IAM token + /ml/v1/text/chat
    mistral.py       # httpx, Mistral native rules (opt-in, not tested)
    cohere.py        # httpx, Cohere /v2/chat (opt-in, not tested)
    ollama.py        # httpx, Ollama /api/chat NDJSON (opt-in, not tested)
    litellm.py       # optional legacy fallback, imported only if installed — to be removed
```

```python
class LLMBackend(Protocol):
    id: str
    capabilities: set[str]                    # tools, stream_usage, parallel_tools, reasoning, vision
    def supports(self, provider: str) -> bool
    async def stream(self, req: LLMRequest) -> AsyncIterator[Chunk]   # text / tool-call delta / usage
    async def complete(self, req: LLMRequest) -> LLMResponse
```

**Provider coverage**
- `openai_compat` (our code on `httpx`): openai, azure, groq, mistral, deepseek, xai,
  cerebras, perplexity, together, fireworks, huggingface, cohere, nvidia, ollama, llamacpp, jan
  (hidden) — per-provider differences are flags (`stream_usage`, `parallel_tools`, auth header),
  not code paths
- `anthropic`: official SDK (content blocks, thinking, prompt caching)
- `gemini`: native API on `httpx` (built instead of Gemini's OpenAI-compatible endpoint)
- `bedrock`: `boto3` — not worth reimplementing request signing
- `watsonx`: own adapter on `httpx` (IAM token exchange, cached per key)
- `mistral`, `cohere`, `ollama`: native adapters as an opt-in alternative to `openai_compat`
  (2026-11-01, not tested against the real APIs)

**Stays in the gateway, never in a backend**
- `secret://` resolution and `llm` / `tool` kind checks — a backend receives a finished key
- Cost from `pricing.py`; fallback models; timeouts; which backend ran is recorded in the trace
- Middleware, guardrails, budgets and checkpointing stay in the runtime above the gateway

**Backend selection** (most specific wins): LLM node "Engine" setting → project setting →
`LLM_BACKEND` in `.env` → `auto` (first backend whose `supports(provider)` is true, in a
configured order). If the choice can't serve the provider, fall back to the next and say so in
the trace. The UI greys out features the chosen backend's capabilities lack.
— 🟡 built 2026-10-28: **Settings → Model backends** (`routers/llm_settings.py`,
`services/llm_settings.py`, migration `0008_llm_settings`, `ModelBackendsPanel.tsx`): engine and
base URL per provider, for the project or the whole workspace, with a Test call; project →
workspace → `LLM_BACKEND_<PROVIDER>` → `LLM_BACKEND` → `auto`, each field on its own; `secrets`
ACL; 10 s cache. `/api/models` asks local servers at the configured address. The serving backend
is in every LLM trace. Still open: a per-node "Engine" override; greying out unsupported features

**Steps**
1. `backend/llm/` interface + types; move today's LiteLLM calls behind it from all 7 files — no
   behaviour change; pin LiteLLM to an exact version with hashes meanwhile
   — 🟡 built on branch `feat/llm-gateway` (2026-10-28): 8 files moved (incl. `routers/build.py`),
   `litellm==1.103.2` pinned, `tests/gateway/test_llm_gateway.py` added. `requirements.lock` (hashes)
   installed with `--require-hashes` in CI and the Dockerfile (A2)
2. `pricing.py` seeded from LiteLLM's current price map; costs read from it everywhere
   — 🟡 built 2026-10-28: `llm/prices/<provider>.json`, one file per provider (1,474 models,
   cache read / write rates, long-context tiers) from `scripts/seed_prices.py`;
   `<data dir>/prices/<provider>.json` overrides model by model; unknown paid model
   logs a warning. Matches LiteLLM for every catalog model it prices (`tests/gateway/test_llm_pricing.py`).
   Deliberate differences: Perplexity cache / tier rates and four DeepSeek flash/v4 models follow
   the listed price, where LiteLLM applies its own adjustments
2b. **Refresh the model catalog** (`/api/models` in `routers/run.py`, mirrored in
   `frontend/src/hooks/useCatalogData.ts`): many listed models have no price and look retired
   upstream — every Anthropic, Groq, Gemini, Together, Hugging Face, xAI and Perplexity entry, plus
   `o1-mini` — so their runs record $0. Move the catalog next to `llm/prices/` and add a CI check
   that every listed paid model has a price
   — ✅ built 2026-10-28: catalog and default models in `llm/catalog.py`; retired models replaced
   with priced current ones (chosen from `llm/prices/`, not live-checked against each provider).
   `tests/gateway/test_llm_catalog.py` fails CI on a listed paid model without a price, and when the
   frontend fallback (`useCatalogData.ts`) or the agent panels drift from the catalog.
   HuggingFace and TypeSafe are marked `unpriced` (no per-token price table) and still record $0
3. `openai_compat` adapter — openai + local providers (ollama, llamacpp, jan) first
   — 🟡 built 2026-10-28 (`llm/backends/openai_compat.py`, httpx, pooled client): reasoning-model
   rules (o1/o3/o4/gpt-5: `max_completion_tokens`, no `top_p` / temperature ≠ 1 — LiteLLM
   refuses these today because nodes default to `top_p=1.0`), stream usage, typed `LLMError`s,
   `LLM_BACKEND` / `LLM_BACKEND_<PROVIDER>` opt-in, serving backend in trace metadata.
   `tests/gateway/test_llm_openai_compat.py`. Live-checked against local Ollama (qwen3) and llama.cpp
   (gemma-3-1b); not yet against the OpenAI API. Still `auto` → LiteLLM. Follow-up: surface
   Ollama's streamed `reasoning` field as thoughts
4. `anthropic` adapter, then `bedrock`
   — 🟡 `anthropic` built 2026-10-28 (`llm/backends/anthropic.py`, official SDK 2.3.0 as locked): OpenAI-format
   messages / tools converted at the edge (leading system → `system`, later system messages → text in
   the user turn, parallel tool results in one user turn, images); streamed text, tool calls,
   usage incl. cache read / write; thinking blocks returned to the tool loop and sent back with the
   tool results (`Chunk.thinking_blocks`); typed `LLMError`s incl. mid-stream errors; SDK retries off.
   Never sends `temperature` / `top_p` — API version 2026-10-21 (SDK ≥ 2.0) rejects them on every
   model; LiteLLM still sends them on its own (older) API version. `tests/gateway/test_llm_anthropic.py` on
   hand-written events; **not yet live-checked** against the API. Opt in with
   `LLM_BACKEND_ANTHROPIC=anthropic`; `auto` stays LiteLLM. Not done: server-side refusal
   `fallbacks` (would bill a different model than the node's — needs pricing by served model),
   showing summarized thinking as thoughts
   — ✅ `bedrock` (`llm/backends/bedrock.py`, boto3 Converse / ConverseStream) and `gemini`
   (`llm/backends/gemini.py`, native GenerateContent on httpx) built 2026-10-31, with
   `tests/gateway/test_llm_bedrock.py` / `test_llm_gemini.py` on hand-written responses; neither live-checked.
   `auto` now uses the `anthropic` adapter too (switched 2026-11-01 without a live check)
5. Contract tests per backend × provider on recorded responses (streamed text, streamed tool
   calls, usage, errors, cost) in CI; switch providers to our adapters one at a time
   — 🟡 suite built 2026-10-29 (`tests/gateway/test_llm_contract.py`, cassettes in `tests/gateway/llm_contract/`):
   96 cases, every cassette under our adapter and LiteLLM — all pass on our adapters for openai,
   ollama, llamacpp, jan, anthropic. Cassettes are written from the API references, not yet
   recorded from the real APIs (add a recorder). `auto` now uses our adapter for ollama and llamacpp
   (`ADAPTER_FIRST`, live-checked again 2026-10-29). OpenAI switched 2026-10-31: live-checked on
   gpt-4o, gpt-4o-mini, gpt-4.1, gpt-5.5, gpt-5.4-mini, gpt-5.4-nano and o3 (complete, stream,
   streamed tool call, tool-result turn, `length`, bad model / bad key) — same text, finish,
   usage and cost as LiteLLM, except gpt-5.x tool calls: LiteLLM silently moves those to the
   Responses API (fewer prompt tokens: 52 vs 134); we stay on Chat Completions. `o4-mini` is
   retired by OpenAI (404) but still in the catalog. Jan hidden 2026-10-31 (`HIDDEN_PROVIDERS` in
   `llm/catalog.py`, Lab tab removed), so it no longer blocks step 6. Still open: anthropic needs
   a live check before it switches; cassettes for the other 16 providers as they get adapters; Ollama's
   streamed `reasoning` field (thinking models) is dropped by both backends — show it as thoughts
   — ✅ adapters built for every remaining provider 2026-11-01: `openai_compat` rows for Mistral,
   Together, Fireworks, Hugging Face (Inference Providers router), DeepSeek, xAI, Cerebras,
   Perplexity (no `/v1`), Cohere's compatibility API, Azure (deployment URL + `api-key` + api-version)
   and NVIDIA; `watsonx.py` does the IBM Cloud IAM token exchange (cached per key),
   `/ml/v1/text/chat`, streaming and tools. `auto` now uses our adapter for all 19 offered
   providers; LiteLLM is imported only if installed. Tests: `tests/gateway/test_llm_watsonx.py` and new
   URL / auth / Azure / DeepSeek cases in `tests/gateway/test_llm_openai_compat.py`. Still open: a live
   check and recorded cassettes per provider; TypeSafe is an evaluation API, not a chat adapter.
6. Remove LiteLLM from `requirements.txt` and the desktop build once every provider passes
   — 🟡 2026-11-01: `llm/backends/__init__.py` imports it in a `try`, so an install without the
   package runs every offered provider; `routers/llm_settings.py` no longer imports it. The
   package, lock entries and PyInstaller data remain for the explicit fallback. Settings →
   Model backends has a **Migrate LiteLLM overrides** button (`/api/llm-settings/migrate-litellm`,
   dry-run supported) that moves saved `litellm` rows to `auto`. Only TypeSafe still needs LiteLLM.

Effort: ~1.5–2 weeks. Steps 1–2 are safe now; steps 3–6 need A2's CI.

**Exit criteria**
- No file outside `backend/llm/backends/litellm.py` imports `litellm`; then none at all
- All 21 providers pass the contract suite on our adapters
- The same run costs the same whichever backend served it
- Desktop build size and backend startup time measured before and after

**Phase A exit criteria**
- No plaintext secret in the DB (CI check greps a seeded DB)
- A custom tool that reads `os.environ` or the DB file gets nothing back (CI test)
- CI green on every PR; red build blocks merge
- External request to `/api/apps` is refused; `/v1/apps` with a valid key succeeds; invalid key
  → 403; over the limit → 429

---

## 2) Phase B — Scale-Out Runtime

Today scheduler, webhooks and runs are in-process `asyncio.create_task` and the rate limiter is
per-process, so a second replica double-fires schedules.

### B1. Durable job queue — remaining
Built 2026-10-29 (steps 1–3, see [done.md](done.md)): queue in the app DB, worker process,
retries + dead-letter view, periodic loops taking turns across processes, Human Gate sweeper,
heartbeat-based stale agent runs, job purge, worker in compose / k8s.
- Eval publish gate as a job instead of inline in the publish request (deferred: makes publish async)
- Interactive agent runs (`/api/agents/run`, `/v1` Master Agent runs) still execute inside the
  request; a crash marks them interrupted (heartbeat) but nothing resumes them automatically
- Verify the exit criteria below with a real soak (3 API + 2 workers on Postgres, 24 h)

### B2. Shared state — remaining
Built 2026-10-29 (see [done.md](done.md)): pluggable shared state (memory / database / redis) for
rate limits, login lockouts and cancel signals; cancel for running jobs and Master Agent runs.
- Cache node on Redis: entries are already in the app DB, so replicas share them; Redis would
  only make lookups faster
- `llm_settings` keeps a 10 s per-process cache, so a change reaches other replicas within 10 s
- Cancel for single-LLM streaming runs started from another connection (today the browser's
  Stop closes its own stream, which works on any replica)

### B3. Observability — done
Built 2026-10-29, finished 2026-10-31 (see [done.md](done.md)): Prometheus `/metrics` (API and
workers), OpenTelemetry traces per run over OTLP/HTTP, job spans, per-step `trace` stream events,
simulated runs, middleware / retrieval / embedding spans, Grafana dashboard. Nothing open.

### Alerts
- Email channel

**Exit criteria**
- 3 API replicas + 2 workers: each schedule fires exactly once over a 24h soak
- Killing a worker mid-run → run resumes or is marked failed and retried; never lost
- Alert to a failing Slack endpoint retries and lands in the dead-letter view

---

## 3) Phase C — Agent Capabilities

### C1. Store node + long-term memory — remaining
Built 2026-10-29 (see [done.md](done.md)): conversation memory scoped by tenant / project; long-term
memory with extraction, recall, opt-in, PII redaction and an inspector; exit criterion in CI.
Key-value store tool, its inspector and exported code built 2026-10-30.
- Facts are ranked by shared words, not embeddings; embeddings would help users with many facts
- Long-term memory on Master Agent runs (today: LLM-node pipelines)
- Redis / S3 backends (app DB today)

### C2. Vector store parity
- Add Qdrant (or Chroma) as a real backend in `services/vector_store.py` (today `local` +
  `pgvector` only)
- UI lists only stores the backend reports via `GET /api/retrieval/stores` (the Vector Store node
  still offers unsupported types)
- Re-index command for moving a collection between stores

### C3. Checkpointing for every run — remaining
Built 2026-10-30 (see [done.md](done.md)): LLM-node runs checkpointed and resumable (editor, `/v1`,
retried automation), Checkpointer node, re-run from a step in the trace drawer.
- Master Agent runs write no trace rows, so they can't be re-run from a step in the drawer yet
- Nested pipeline runs (a pipeline child inside a run) aren't checkpointed themselves; the outer
  run's step for the child is
- Mock-provider (simulated) runs save steps but write no trace, so they have no spans to re-run from

### C4. Remote MCP server — remaining
Built 2026-10-29: `/v1/mcp` (see [done.md](done.md)), verified with the official MCP Python SDK.
- Verify in Claude Desktop / Claude Code as real clients. Claude Desktop's remote connectors
  expect OAuth, not a static header, so it needs OAuth on `/v1/mcp` or the `mcp-remote` bridge

### C10. Agent skills, step 1 — remaining
LLM nodes load skills on demand since 2026-11-03 (`services/skills_runtime.py`): the model sees only
each skill's name and "when to use", loads one with `use_skill` when a request needs it, and gets
that skill's tools only then. Export to other agents is built too: Export App → Agent Skill (a
`SKILL.md` zip that runs the published app over `/v1`); not in the SDK / CLI yet (`pipesets export`
handles text formats only).

**0. Tenant scoping** — done 2026-11-03 (see done.md)

**Steps 1, 2, 4, 6, 7 built 2026-11-03** (see [done.md](done.md#product-features-plan-md-4b)):
versions and `skill_versions`, Skill nodes read the library copy (pin a version on the node),
`use_skill` with hidden tools until loaded, `skill_mode` (on demand / always), max loaded per
request, resume restores loaded skills, four starter skills, guide 05 rewritten. Remaining:

- **3. Required connections — reframed and built as skill readiness (2026-11-03):** Airflow,
  Databricks and Kafka have no connection type (their tools take URL / token in each tool node's
  settings), so instead the Skill node shows whether its required tools are attached to its LLM node
  and have their required settings; a flow with an unready skill is a blocking validation issue and
  publishing refuses it (409). Still open, only if pilots ask: real connection types for those
  platforms, so a skill's tools could use the LLM node's connection or a project default instead of
  per-tool settings (`required_connections` is stored but not checked)
- **5. Traces and UI, rest:** the trace drawer shows the "Loaded skill" span like any other (a
  dedicated row above the tool calls it led to is open); usage counts per skill across runs; a full
  skill editor replacing the catalog modal (markdown instructions, a tool / MCP picker from the
  installed packages instead of typed ids, version history with diff and restore); the Skill node
  card still shows tags, not its tools and connection status
- **Attach a skill's tools for you:** they're attached by hand; the Skill node's "⚠ Needs" could
  get an "Attach them" button
- ~~**Child agents** still get every skill's instructions in their prompt (no tool loop)~~ — built
  2026-11-04 as C11 step 1
- Not tried with a real model: how reliably real models call `use_skill` (and whether "when to
  use" lines need a stricter format) is unmeasured — add an eval set per starter skill
- Later steps (unchanged): `SKILL.md` import / export with bundled files and sandboxed scripts →
  skills in tool packages and the marketplace → draft a skill from a good run, evals per skill,
  skills over `/v1/mcp`

**Exit criteria (step 1)** — ✅ in CI (`tests/runtime/test_skills_runtime.py`, scripted model): with
the 4 starter skills and their 15 tools attached, the first model call offers only `use_skill` and
the directly attached tool; the run loads the Airflow skill, gets its tools, uses one and answers;
another tenant's skill never loads (`tests/security/test_skills_scoping.py`)

### C11. Agents — mostly user-built, a few built-in
Decision (2026-11-04): the platform's job is to make agents easy to build, save and share; we ship
only a handful of our own, as templates users can fork. A built-in agent must use tools and come
with an eval set — prompt-only roles stay starter presets (`frontend/src/utils/agentPresets.ts`).

**1. Child agents run the tool loop** — built 2026-11-04 (`services/child_tool_loop.py`):
Tool / Toolkit / MCP server and Skill nodes wired to a child are sent as `attached_tools` /
`attached_skills` (editor and published flows) and the child runs the LLM node's loop without
streaming: typed and MCP tool schemas, `use_skill` with hidden tools, failures handed back to the
model, up to `MAX_AGENT_STEPS` turns. Step traces carry `tool_calls` and `skills_used`. Mock,
keyless and non-function-calling children keep the single call with skills in the prompt;
`allowed_tool_ids` / `skill_ids` still work for older callers. Tests: `tests/runtime/test_child_tool_loop.py`.
Remaining:
- A child is one checkpointed step, so an interrupted child re-runs whole (no per-tool checkpoints)
- No editor pins / breakpoints on a child's tool nodes; no grounding or output parser for children
- The trace drawer doesn't show a child's `tool_calls` yet; the Child agent card's "Tools: N" counts
  `allowed_tool_ids`, not wired tool nodes
- Skill readiness (`skills_runtime.readiness`) checks LLM nodes only, not child agents
- `routers/build.py` (AI builder) still describes children with `allowed_tool_ids`

**2. Saved agents (user-built)** — built 2026-11-04 (`routers/saved_agents.py`, `utils/savedAgents.ts`,
migration 0034): "Save as agent" (card 5 of a child's config panel) stores the child's settings plus
the tool, toolkit and skill nodes wired to it as a versioned spec (`saved_agent_versions`), scoped to
the project (ACL resource `agents`). Credential-like values are blanked on save (`secret://` refs
kept) and the panel says how many. Saved agents show in the sidebar under Agents → Saved agents;
dropping one recreates the child, its tools and skills, wired up, and the child records
`saved_agent_id` / `saved_agent_version`. Update (next version), save as new, delete. Tests:
`tests/apps/test_saved_agents.py`, `src/utils/savedAgents.test.ts`. Remaining:
- Dropping copies the spec: pipelines don't follow later versions, and nothing says "newer version
  available" on the canvas yet (Pipeline children do this; same pattern)
- No version history / restore UI (the API has `/versions`); no rename, icon or description editing in
  the UI (the API takes them)
- Middleware and human-gate nodes wired to the child aren't saved with it
- Not tried by hand in the browser yet (drag from the sidebar, drop, run)

**3. Agent registry + Settings → Agents** — built 2026-11-04: built-in agents are `AgentSpec`s in
`backend/agents/` (one module per agent or group, auto-registered; `agents/starters.py` holds the 14
starter roles moved from the deleted `frontend/src/utils/agentPresets.ts`). A spec lists `ToolNeed`s
(any one of several tools meets a need, optional or not) and skills. `GET /api/agent-catalog` serves
them with install state and readiness; the sidebar's Agents section, the Specialist Role dropdown and
a dropped starter's prompt read it (`utils/agentCatalog.ts`). Settings → Agents installs and
uninstalls with the tool-packages rules (`services/agent_packages.py` on the now-shared
`PackageStore`; starters are the defaults; a child's `builtin_agent_id` counts as in use), and
"Install + N tools" also installs the tools an agent is missing. Dropping a tool-backed built-in makes
the child plus a tool node per need and a skill node per skill. Installs are audited. Tests:
`tests/tooling/test_agent_catalog.py`, `AgentPackagesPanel.test.tsx`, `agentCatalog.test.ts`. Remaining:
- No tool-backed built-ins yet (step 4), so "Install + N tools" and the tool-backed drop are covered by
  tests only
- The agent registry doesn't hot-reload like `backend/tools/` (needs a restart)
- A dropped built-in is a copy, like a saved agent; nothing flags a newer spec
- Not tried by hand in the browser yet

**4. Built-in agents, each with an eval set** — 28 built 2026-11-04 (ELT Pipeline Doctor and Kubernetes
Troubleshooter came with the third tool batch, Log Investigator and Alert Triage with the observability
batch, Job Search Assistant with the Jobs & Careers tools). Research & analysis: Web
Researcher, Academic Researcher, Company Analyst, News Monitor (`agents/research.py`). Data platform:
SQL Analyst, Airflow DAG Doctor, Databricks Job Triage, Snowflake Cost Optimizer, Kafka Lag
Investigator (`agents/data_platform.py`). DevOps & SRE: Incident Responder, Domain & Website Checker
(`agents/sre.py`). Engineering: Issue Triage, Release Notes Writer, CI Build Doctor, Dependency
Checker, Dev Help Researcher (`agents/engineering.py`). Business & productivity: Support Desk Agent,
Inbox Triage, Invoice & Receipt Parser, Billing Assistant, Store Order Assistant, Meeting Prep, Lead
Researcher (`agents/business.py`). They use regular tools only: MCP servers need "Discover tools" on
their node before an agent can call them, so none is a required need yet. Each lists its tool needs
(any search tool / any SQL tool, …; optional extras) and 5–6 `EvalCase`s written for the `llm_judge`
scorer, including a safety or no-answer case. A dropped built-in's config panel offers "Create eval
dataset" (`POST /api/agent-catalog/{id}/eval-dataset`, linked to the pipeline), and Settings → Agents
shows the case count. CI: every built-in has ≥ 5 cases with a safety / no-answer one, points at real
tools, and runs as dropped (offered one function per tool node, calls one, answers) —
`tests/runtime/test_builtin_agents.py`. Remaining:
- **Not measured with real models yet**: run each eval set with a real model and record pass rates
  here; tighten the prompts that fail
- Settings → Agents shows tool names per need and wraps its buttons (fixed 2026-11-04 after the first
  look); still not checked on a narrow screen
- Eval datasets aren't tenant-scoped (pre-existing in `routers/eval.py`), so a dataset created from an
  agent is visible to every workspace on the server — fix with the eval router, not here
- The eval cases assume data the user's systems have (an `orders` table, an `orders_daily` DAG); users
  edit them to fit, there are no fixtures

**Later:** agents in the marketplace, draft an agent from a good run, agents over `/v1/mcp` and A2A.

**Exit criteria**
- A child agent with a search tool wired to it searches and cites results with a real model (eval)
- A user saves a configured child as an agent, drops it into another pipeline and it runs unchanged
- Installing a built-in agent from Settings → Agents also offers its missing tools

**Exit criteria**
- Agent recalls a user preference stated in a previous session (eval case in CI)
- Pipeline built on Qdrant passes the same RAG eval as pgvector
- Any interrupted run resumes from its last step
- Claude Desktop lists and runs a published app via the remote MCP server

---

## 4) Phase C — Developer Workflow

### C5. Built-in MCP servers — remaining
Reworked 2026-11-02 (see [done.md](done.md)): 46 servers added so far, broken / deprecated /
unvetted ones replaced, every package pinned. This includes MongoDB, ClickHouse, MySQL, Snowflake,
BigQuery, Elasticsearch, Grafana, Prometheus, Datadog, Salesforce, Figma, Discord, Neon,
MotherDuck, DynamoDB, Netlify, Postman, PostHog, Apify, Browserbase, Todoist, Hugging Face,
Redshift, DBHub, Cloudflare, Render, New Relic, Honeycomb, monday.com, Jina AI, Hyperbrowser and
E2B. Checked against each package's source and docs only, **not launched** (auto mode blocked
running third-party packages). Still open:
- Live check: launch every stdio server once and compare `tools/list` with its `DEFAULT_TOOL` and
  argument names; call the remote servers (GitHub, Linear, Datadog, Neon, Postman, PostHog,
  Hugging Face, Cloudflare, Render, New Relic, Honeycomb, monday.com, Jina AI) with real tokens.
  Linear's default tool (`list_issues`) isn't in its public docs;
  Datadog's tool names are under active development (its default `search_datadog_logs` was
  renamed from `get_logs`). Postman uses its minimal endpoint; Netlify's aggregated
  `netlify-project-services-reader` name, PostHog's `execute-sql` arguments, New Relic's
  `execute_nrql_query` argument names (`account_id` / `nrql`), monday's `search` parameters and
  Jina's tool set should be confirmed against a live `tools/list`
- The AWS Labs DynamoDB server is a data-modeling assistant (prompt, schema conversion / validation,
  cost and CDK generation), not a general-purpose table CRUD server
- Slack, Google Drive, Google Maps: deprecated reference servers, pinned to their last release.
  Slack's own server is remote with OAuth (needs a Slack app); revisit with the OAuth client
- `asana-mcp` is an individual's package; Asana's own server is remote with OAuth only
- Salesforce uses `@salesforce/mcp`, which has no static credentials: the org has to be authorized
  on the backend machine with `sf org login web`, and the node only passes `--orgs` / `--toolsets`
- Datadog is header-auth only here (API key + application key); its OAuth flow is not wired up.
  Grafana wants a service-account token; `GRAFANA_API_KEY` is deprecated upstream
- Cloudflare's remote server is code mode by default (`docs` / `search` / `execute`), so the model
  writes JavaScript against the OpenAPI spec rather than calling one tool per endpoint; API tokens
  with Client IP Address Filtering don't work
- New Relic's user API key goes in `api-key` (not `Authorization`) and cannot use the OAuth-only
  tools (`natural_language_to_nrql_query`, the report generators)
- Honeycomb's key must be a management API key in `KEY_ID:SECRET_KEY` form; EU lives on a separate
  `mcp.eu1.honeycomb.io` endpoint
- Redshift is read-only by default (`ACCESS_MODE`); DBHub needs Node.js 22.5+ and sets read-only in
  `dbhub.toml` — its `--readonly` flag was removed
- SQLite and Sentry reference servers last released in 2025; check they're still maintained
- A version-bump routine: a CI job or script listing pinned packages with newer releases
- Third batch (2026-11-04) live check: launch Argo CD, PagerDuty, CloudWatch and dbt once and compare
  `tools/list`; confirm `uvx --python 3.12` resolves for PagerDuty on the deploy image. The seven new
  built-in tools (dbt Cloud, Fivetran, Airbyte, Prefect, Kubernetes, GitHub Actions) were tested
  against fake vendor APIs only — Service Status was run live
- Observability batch live check: OpenSearch `tools/list`; Elastic Agent Builder's tool names over MCP
  (the default `platform.core.list_indices` comes from Elastic's docs, which don't say which tools the
  MCP endpoint exposes); the seven new tools against real Grafana / Loki / Tempo / Alertmanager /
  Datadog / Splunk / Elasticsearch

### C6. Tools-as-code SDK — remaining
Built 2026-10-30 (see [done.md](done.md)): typed custom tools (schema read from the code), versions
with pinning and rollback, `/v1/tools` + `tools:*` scopes, `@tool` / `pipesets.testing` / `pipesets
tool …` in the SDK, CI recipe, UI read-only SDK tools with fork, versions tab and version picker.
- The 8 framework integrations (DSPy, Guardrails, Instructor, Langfuse, …) still take one `input`
  string; MCP servers without a built-in launcher (AWS KB, Everything, Slack, Google Maps) can't be
  discovered until added as custom MCP servers
- MCP tool schemas are checked by the server, not before the call (they can use anyOf / $ref etc.)
- Version diff view (versions can be viewed and rolled back, not compared)
- `pipesets tool logs`: tool calls are in run traces (spans with input / output / duration), not
  yet queryable per tool
- Multi-file tools (a bundle is one file today)

### C7. Git integration (pipelines as code)
Git holds the reviewed, deployable definition; the DB stays the runtime store and draft
workspace. Today apps live only as `flow_data` blobs, and `native_json` export is a raw
`json.dumps(app)` with volatile React Flow ids and positions. Shares the bundle format with C6.

**Repo layout**

```
pipesets.yaml                 # project, environments, connection refs
apps/support-bot/
  app.yaml                    # nodes + edges by stable name, no secrets
  layout.json                 # canvas positions only (ignored in review)
  publish-gate.yaml
  evals/cases.yaml
tools/jira_lookup/            # same bundle as C6
schedules.yaml
webhooks.yaml
```

**Canonical serializer** (`git_exporter.py` + importer)
- Secrets replaced with refs (`connection: jira-prod`); export fails if a raw secret remains
- Stable node ids derived from names; sorted keys; layout split out
- Round-trip test: DB → files → DB → files is byte-identical

**CLI** — works with any Git host

```
pipesets pull                      # DB → files
pipesets validate                  # schema + graph checks, offline
pipesets plan  --env staging       # diff files vs deployed
pipesets apply --env staging       # upsert apps/tools/schedules, run publish gate, publish
```

CI flow: PR → `validate` + `plan` + eval gate → merge → `apply --env prod`.

**Project modes**
- UI-managed (default) — optional "commit snapshot on publish" for backup and history
- Git-managed — Git is the source of truth; published apps read-only on canvas; "Edit" creates a
  draft and "Propose change" opens a PR; merge triggers `apply`

**Environments & promotion** — dev / staging / prod per project mapped to branches or overlays;
env-specific connection refs and variables; `apply` records the deployed commit SHA on each app
version (shown in UI and traces)

**Provider integration** — GitHub App first (open PR from the UI, sync on push, status checks);
GitLab and plain Git-over-HTTPS next

**Phasing** — file format + serializer + CLI (~2 weeks) → Git-managed mode + GitHub App
(~2 weeks) → environments & promotion (~1 week)

**Exit criteria**
- A tool scaffolded with `pipesets tool init` passes `pipesets tool test`, deploys, and is called
  by an LLM with typed arguments — without opening the UI
- Redeploying the same tool creates a new version; rollback restores the old one
- An app pulled to Git contains no secrets, round-trips byte-identically, and a canvas move
  changes only `layout.json`
- A merged PR deploys to staging via `pipesets apply`; promoting to prod changes only env refs;
  each app version shows its commit SHA

### C9. Embeddable chat (websites, Streamlit, other apps)
**Chat links — shipped 2026-11-01 (see done.md):** a published pipeline gets a `/c/pc_…` URL anyone can
open on a phone or laptop to chat, no account; per-link limits, revoke, QR code, Chat link dialog
in the Build toolbar. Only `access = 'public'` exists. Next, in order:

**Verify first** (checked with tests, a dev server and a phone-width screenshot only)
- Open a link on a real phone through ngrok, and on a public host behind the edge (`/c/*` on
  `PUBLIC_HOST`) with a real model: streaming, Stop, New chat, reload keeps the conversation
- Chat link dialog in the Build toolbar: create / edit / turn off, QR code scans, ✨ Generate sample
  prompts with a real model

**0a. Link + passcode** (~2 days)
- `chat_links.access = 'passcode'`; `passcode_hash` column (argon2/bcrypt, like account passwords),
  set / changed / removed in the Chat link dialog; shown once when generated
- `POST /v1/chat/{token}/session` takes `passcode`; a session is only issued after it matches, so
  `/message` needs no change (the encrypted session already proves it)
- Failed tries count per link + IP through shared state (lockout like login: 5 tries / 15 min), and
  show in the link's usage; the page asks for the passcode before the chat
- Changing the passcode ends existing sessions: put a `session_epoch` in the session token and bump it

**0b. Sign-in required** (~3–4 days)
- `access = 'members'`: only signed-in users with `apps:read` on the project (or a listed group) can chat
- Visitors sign in on the chat page with the existing auth (`/api/auth/login`); on the edge that
  means serving the login route on the public host too, or putting the chat page on `UI_HOST`
  for these links — decide when building
- Runs act as the visitor, not the link's creator (their ACLs and budget); `end_user` = their id, so
  long-term memory works per person; usage per user in the Chat link dialog
- Later, with enterprise SSO: allow-list by email domain (`@acme.com`) instead of project membership

**0c. Link leftovers**
- Per-link daily **cost** cap (today: a message cap; budgets still apply to the creator)
- Expiry date per link; rotate a link (new URL, same settings)
- "Open in Pipesets" only opens the pipeline when it's in the user's current project; switch to the
  link's workspace / project first (needs the scope in the link)
- Dark theme; file upload; the builder's logo / colours on the page
- Show tool calls on the page as they happen ("Checking the weather…"), when the link allows it
- Feedback (👍 / 👎) per answer into traces and eval datasets
- Phone layout plan (§11) can reuse the chat page as its Run tab
- Embed tokens (step 2 below) should build on `chat_links` (same tokens, limits and session handling)
  plus an origin allowlist, rather than a second token table; the iframe page is the chat page

Let a published app's chat live outside Pipesets. Server-side callers (Streamlit, Django, a bot)
already work with `/v1/apps/{id}/run` and an API key; they need examples, not new API. Browsers
can't use `/v1`: a `ps_...` key is a project-wide secret, and CORS only allows the dev UI.

**1. Streamlit example** (`examples/streamlit_chat/`)
- `app.py`: `st.chat_input` + `write_stream` over `PipesetsClient.v1_stream`, one `session_id`
  per browser session, the key from `st.secrets`; shows tool calls / sources when the app emits them
- README: create the key (scope `apps:run`), publish the app, `streamlit run app.py`
- Same pattern as short snippets in the docs for FastAPI / Flask / Node (server holds the key)

**2. Embed tokens** (`services/embed_tokens.py`, migration)
- Per published app, public `pe_...` tokens: can only chat with that one app, nothing else in `/v1`
- Origin allowlist per token (`acme.com`, `*.acme.com`; `localhost` only when flagged dev)
- Own limits: per-token and per-IP rate limit, max message length, max turns per session,
  optional daily budget cap (feeds the existing budget checks); revoke instantly
- Runs act as the token's creator, `RunScope.caller = "embed:<token_id>"`, so traces, metrics and
  the audit log tell embed traffic apart
- Optional Cloudflare Turnstile check per session for public sites

**3. Endpoints** (`routers/v1_embed.py`, served on `PUBLIC_HOST`)
- `POST /v1/embed/{token}/session` → server-made `session_id` (signed), greeting, theme config
- `POST /v1/embed/{token}/chat` → SSE, the same events as `/v1/apps/{id}/run`; reuses its run path
  (memory, middleware, checkpoints). Visitors can't pick a `session_id`, so they can't read
  another visitor's history
- CORS decided per token from its allowlist, not the global `CORS_ORIGINS`; `Origin` missing or
  not allowed → 403
- No provider keys from the browser: the project vault or server env only

**4. Embed front-ends** (built from `frontend/`, served as static files)
- ✅ 2026-11-01, on chat links: `<iframe src="https://<public>/c/pc_…?embed=1">` (embed mode: no page
  chrome) and a copy-paste chat button (plain HTML/CSS/JS, iframe loaded on first click) in Chat link →
  Embed on a website; sample page download and `examples/chat-embed/`. Left for this step:
- Per-link **allowed websites**: today any site can frame a link (as anyone can open it). Serve
  `Content-Security-Policy: frame-ancestors <allowlist>` for `/c/<token>` (the page would need to come
  from the backend or the edge per token) and refuse `/v1/chat` sessions from other `Origin`s
- Builder UI pages send no `frame-ancestors` / `X-Frame-Options` yet; add `frame-ancestors 'none'`
  everywhere except `/c/*` (frontend nginx + edge)
- `<script src="https://<public>/embed.js" data-token="pe_..." async></script>`: floating bubble in a
  shadow DOM (the host page's CSS can't break it); `data-title`, `data-greeting`, `data-theme`,
  `data-position`, `data-open`; JS API `Pipesets.open() / close() / send(text)`; under ~30 KB gzip
- Markdown + code rendering, stop button, "new chat", keeps the session in `sessionStorage`

**5. UI: Share → Embed tab** on a published app
- Create / revoke tokens, edit the allowlist and limits, pick the theme
- Copy-paste snippets (script, iframe, Streamlit, curl) with the token filled in
- Live preview of the bubble; usage per token (messages, cost, blocked origins)

**6. Demo website** (`examples/demo_site/`)
- A small static "Acme Outdoor Gear" store (home, product list, FAQ, contact), plain HTML/CSS,
  no build step; serve with `python -m http.server 8080`
- Ships a sample published app (support agent with a KB of the site's FAQ / return policy,
  `examples/demo_site/pipeline.json`) and `seed.py` that imports and publishes it, creates an
  embed token for `localhost:8080` and writes it into `config.js`
- The bubble on every page; `/help.html` shows the iframe version; `/developers.html` shows
  the snippets used and links to the Streamlit example
- One-liner in `start.sh --demo-site` to run backend + demo site together; a screenshot/GIF in the
  README; also the page we point pilots and the onboarding guide at

**Phasing** — Streamlit example + docs (~1 day) → embed tokens + endpoints + tests (~3 days) →
iframe page (~2 days) → `embed.js` bubble (~2 days) → Share → Embed tab (~2 days) → demo site
(~1 day, alongside the bubble so it's the manual test bed)

**Exit criteria**
- `streamlit run examples/streamlit_chat/app.py` streams answers from a published app, and two
  browser tabs keep separate histories
- The demo site's bubble and iframe chat with the sample app on `localhost:8080`; the same token
  from a non-allowlisted origin gets 403, and a revoked token stops working on the next message
- Nothing in the demo site's page source can call any `/v1` route besides its own app's chat
- Embed runs show up in traces and metrics as `embed:<token_id>` and count against the budget

---

## 4b) Product Features (added 2026-11-03)

Features nothing else in this plan covers. F2 and F5 first (both help the P1 pilot: feedback on
real answers, and extraction over a whole folder of leases), then F1.

### F1. Build a pipeline from a description — remaining
Mostly exists already: the ✨ Describe box in Build (`POST /api/build/generate`, `routers/build.py`)
scaffolds a pipeline, custom tool or MCP server from a sentence, with a fallback scaffold when no
live key is available (guide 02, "AI-assisted building"). Left:
- Follow-up edits by chat ("add a reranker", "swap to Claude") as a diff the builder accepts,
  instead of a new scaffold each time
- Validate the generated graph (`utils/pipelineValidation.ts`) before it lands on the canvas, and
  show what was dropped (node types or tools that don't exist)
- Exit: 10 described pipelines from the docs' examples produce graphs that validate and run with
  the mock provider

### F2. Feedback from end users into evals — remaining
First version built 2026-11-03 (see [done.md](done.md#product-features-plan-md-4b)): 👍 / 👎 in the
Prompt Runner, on chat links and through `/v1`; Evaluate → Feedback with satisfaction per version
and export to eval datasets.
- Not tried in a browser yet (component tests and backend tests only)
- The list has no version filter in the UI (the API takes `version`)
- Satisfaction on the Monitor tiles; alert when a version's 👎 rate crosses a threshold
- Rate from the trace drawer and from Master Agent human-gate edits (an edit = implicit 👎)
- `run_pipeline` over MCP returns no way to rate
- Eval datasets aren't tenant-scoped (existing gap), so exported cases are visible across tenants
- Exit: a 👎 from a chat link shows up in the list with the run's prompt and answer, and becomes
  an eval case; no tenant sees another tenant's feedback — ✅ in CI (`tests/evals/test_feedback.py`)

### F3. Score live runs (online evals)
- Sample N % of production traces per pipeline; an LLM judge scores groundedness, relevance and
  safety as a job (B1 queue); trend per version on the Monitor view; alert on a drop
- Exit: a regression introduced in a new version shows up as a score drop within a day

### F4. Gradual rollout of published versions
- Canary (x % of traffic to the new version) and shadow (run it, don't show it) per pipeline;
  compare cost, latency, F2 ratings and F3 scores; promote or roll back in one click
- Exit: a canary at 10 % routes within ±2 % over 1,000 runs; rollback takes effect on the next run

### F5. Batch runs (one run per row) — remaining
First version built 2026-11-03 (see [done.md](done.md#product-features-plan-md-4b)): Automation →
Batches, file upload, `{column}` prompt template, one job per row with retries, at most N rows of a
batch at once, cancel, retry failed, CSV export.
- Not tried in a browser yet, nor with a real model
- Rows run the *latest* published version: republishing mid-batch switches the rest to the new
  version (each row records its version); pin the version at batch start
- A row's run id is shown, not linked: open its trace from the batch view
- Rows go browser → server as one JSON body (5,000 max); bigger inputs need a server-side upload
- Documents as input built 2026-11-03 (done.md). Open: uploaded files live on the API server's disk
  (`<data dir>/uploads/batches/`), so with workers on other machines the data dir must be a shared
  volume (or move them to S3 / the database); `.xls` and zip uploads aren't read; a document's
  `{document}` text is cut at 100,000 characters (Structured Extract with `{path}` splits long
  documents itself instead); the batch view doesn't link to its review-queue rows yet
- Later: a Map node to fan out inside a pipeline; F8 cost estimate before start
- Exit: 200 rows with the mock provider finish with every row accounted for, after killing the
  worker mid-batch; cancel stops the remaining rows — partly in CI (`tests/runtime/test_batches.py`:
  cancel, retry, a lost queue chain recovered by the sweep, on 4–7 rows); the 200-row kill test is open

### F6. Step-through debugging on the canvas — remaining
First version built 2026-11-03 (see [done.md](done.md#product-features-plan-md-4b)): breakpoints on
LLM / Tool / Toolkit / Retriever nodes with Continue / Step / Stop and an editable input at each
pause; pinned outputs on those nodes and on Child agents; ● / 📌 buttons in each node's header and
a 🐞 Debug strip at the top of its config; 📌 Pin from tool results, answers and child steps.
- Not tried in a browser yet (component tests and backend tests with a scripted model only)
- Pin from the trace drawer (spans now carry `node_id` and `checkpoint_key`;
  `GET /api/agents/runs/{id}/steps/{key}` returns the full output)
- Breakpoints inside Master Agent runs (before a child / synthesis); pause on Memory and Output
  Parser nodes; conditional breakpoints ("pause when the tool returns nothing")
- A paused run is only resumable from the page that started it (the request with its keys lives
  in the browser), like Resume today
- Child-agent pins are matched to their node by label (step traces carry no node id)
- Pins are saved in the flow, so they travel with exports and published versions (ignored there);
  a warning on publish ("3 nodes have pinned outputs") would help
- Exit: with breakpoints on a tool and the LLM node, a run pauses before each, an edited tool
  argument reaches the tool, Continue finishes without repeating a model call; a pinned LLM output
  costs nothing and still runs the output parser / response guardrails; a published run of the
  same flow ignores pins — ✅ in CI (`tests/runtime/test_debug_runs.py`)

### F7. Semantic cache
- Cache node mode `semantic`: hit when a new prompt's embedding is within a threshold of a cached
  one; per-scope threshold, hit rate in the Cache stats panel

### F8. Cost estimate before a run or publish
- From past traces and token counts: "≈ $0.04 per run, ≈ $120 / month at this schedule", shown on
  publish, schedules and F5 batches; warn against the budget

### F9. Canvas comments and presence
- Comments pinned to nodes, who else is editing; for pilots with more than one builder

### F10. Red-team report as a product feature
- "Attack my pipeline": run the adversarial suite (A3) against a published pipeline, get a report
  of what got through

---

## 5) Desktop App (Tauri)

M0–M2 are done (see [done.md](done.md)). Remaining:

### Shell (M3)
- Bundle the backend as a real sidecar (`bundle.externalBin`) instead of starting it from
  `backend/.venv` / `PIPESETS_BACKEND_BIN`
- Restart the backend if it crashes
- Single-instance lock (second launch focuses the existing window)
- Native menu, window size / position memory

### Local models
- Detect running local servers (Ollama `:11434`, Jan, llama.cpp) on startup and offer them in
  Settings
- Later: bundle a llama.cpp server as a second sidecar for a fully offline install

### Packaging, signing, updates (M4, M5)
- macOS: Developer ID signing + notarization (sidecar signed too); universal or per-arch builds
- Windows: NSIS / MSI installer; code signing (optional at first)
- Linux: AppImage + `.deb`
- Tauri updater with signed manifests on GitHub Releases
- CI matrix (macOS arm64 / x64, Windows, Linux) building backend + shell per target

### Polish (after first release)
- System tray: show / hide, backend status, quit
- Launch at login (optional)
- "Open data folder" and "Export logs" in Settings
- Deep links (`pipesets://`) for opening shared pipelines
- Docling as an optional "Advanced document parsing" download
- Master key in the OS keychain

### Open questions
- Keep multi-user auth / IAM in desktop mode, or auto-login a single local user?
- Should the desktop app also connect to a remote Pipesets server instead of its own sidecar?

| # | Milestone | Done when |
|---|---|---|
| M3 | Desktop build | `npm run tauri build` app starts its bundled sidecar and runs a pipeline end to end |
| M4 | Unsigned installers | Installers built in CI for all three OSes |
| M5 | Signed release + updater | Notarized macOS build installs cleanly and auto-updates |

---

## 6) Phase D — MVP Verification, Docs & Pilot

### Verify end to end (built, never tested against the criterion)
- Middleware: harmful prompt blocked before the LLM with a clear reason; cost visible after every
  run; rate limiter throttles at threshold
- RAG: upload a PDF → ask → grounded answer with cited chunks; grounded-answer rate on an eval set
- Observability: every run has a trace with tokens, cost and latency
- Cost estimate within 5% of a real provider invoice
- Real LLM run through `pipesets run` / `pipesets stream` / MCP `run_pipeline`; registration in a
  real MCP client
- Canvas render and streaming latency at 20+ nodes
- Postgres MCP against the Lab's seeded shop database (Lab → Data Seeder), with a real model:
  "Show me all delivered orders with total amount over $500", "Which customer has spent the
  most?", "List the top 5 products by number of orders", "How many orders were placed in the last
  90 days?" answer correctly; "Cancel all pending orders older than 30 days" is refused on a
  read-only connection (was `testing_data.md`)

### MVP leftovers
- Content-safe chatbot starter template
- Middleware nodes in the exporters (none of `exporters/` handle middleware)
- Backend graph validation endpoint `POST /api/apps/{id}/validate` (optional; client-side exists)
- Edge colour coding by type — verify or build

### Synthetic Data node — remaining (first version shipped 2026-11-01, see done.md)
- ✅ 2026-11-01: full generation, download, save to an eval dataset and backend tests (done.md).
  **Not tested against a real model** — checked with the mock provider and a stubbed OpenAI
  backend only. Try a real run of a few hundred rows and check batch-to-batch variety
- Over 1,000 rows: run as a background job (B1 queue) with the file kept server-side, instead of
  one streamed request holding every row in the browser
- The seed only makes the mock provider repeatable; with a real model it's passed in the prompt,
  which models don't honour exactly
- Dataset routing in the Prompt Runner is frontend-only keyword scoring — move it server-side so
  `/v1` runs and schedules see synthetic datasets too

### Docs
- Quickstart (first app in 10 minutes)
- Node reference generated from node schemas
- `/v1` API reference from OpenAPI
- Org onboarding guide: getting a key, calling the API, Python / curl / Node examples
- RAG setup, middleware configuration and troubleshooting guides

### Usage view
- Per-tenant cost, run volume, error rate, active builders — built on budgets + traces

### Refactors (only files touched in the same PR)
- Split `PromptRunner.tsx` (~2,000 lines), `App.tsx` (~1,800), `lab.py` (~1,500)

### Pilot
- Onboard 2 design partners, weekly feedback review, bug bash, go/no-go (§8)

---

## 7) KPI Targets

| Area | KPI | Target |
|---|---|---|
| Reliability | Run success rate (happy path) | ≥ 99% |
| Reliability | Lost runs on pod restart | 0 |
| Reliability | Alert delivery (incl. retries) | ≥ 99.5% |
| Security | Plaintext secrets at rest | 0 |
| Security | Adversarial suite pass rate / moderation block rate on known harmful prompts | 100% |
| Quality | Grounded answer rate on RAG eval set | ≥ 80% |
| Quality | Long-term memory recall eval | ≥ 90% |
| Performance | `/v1` p95 time-to-first-token (non-RAG) | < 2s |
| Cost | Cost estimate vs actual invoice | within 5% |
| Cost | Cache hit rate on repeated queries | ≥ 25% |
| Engineering | Backend test coverage (routers + services) | ≥ 60% |
| Adoption | Time to first working workflow | < 30 min |
| Adoption | Design partners running in production | ≥ 2 |

---

## 8) Go/No-Go Checklist

- [ ] All secrets encrypted at rest; masked in API responses and logs
- [ ] CI runs backend, frontend, migration and adversarial suites on every PR
- [ ] Only `/v1/*` reachable externally, over TLS; invalid key → 403, rate limit → 429
- [ ] All custom tools execute in an isolated sandbox; nothing pip-installs into the backend
- [ ] All LLM calls go through our gateway; LiteLLM removed; every provider passes the contract suite
- [ ] Multi-replica soak: schedules fire exactly once; no lost runs on pod kill
- [ ] Alerts retry and dead-letter; Human Gate timeouts enforced in the background
- [ ] OpenTelemetry traces visible in an external backend
- [ ] Middleware, RAG and observability verified end to end (§6)
- [ ] Store node + long-term memory pass recall eval
- [ ] UI vector store list matches backend support
- [x] Every run type resumable from checkpoint
- [ ] Remote MCP server works from a real MCP client with an API key
- [ ] Tool built, tested and deployed end to end with `pipesets tool` — no UI
- [ ] Pipeline change goes PR → CI → merge → staging → prod via `pipesets apply`
- [ ] Quickstart + node reference + API reference published
- [ ] 2+ design partners running published apps; zero Sev-1 at launch gate

---

## 9) Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Secret migration corrupts existing rows | Back up DB first; idempotent migration verified by decrypt round-trip before commit |
| Master key lost | Document key backup; KMS so the key never lives only in env |
| Redis adds ops burden | Postgres `SKIP LOCKED` queue as the zero-new-infra option |
| Queue migration breaks run semantics | `PIPESETS_QUEUE` flag; run both modes in CI |
| Long-term memory stores sensitive data | Per-tenant opt-in, inspector with delete, PII middleware before storing |
| Sandboxing breaks existing custom tools | Network allowlist + declared requirements; dry-run every existing tool before switching |
| Canvas and Git diverge | One mode per project; Git-managed projects read-only on canvas; `pipesets plan` flags drift |
| Secrets committed to Git | Serializer refuses raw secrets; CI secret scan on the repo template |
| SDK and UI versions of a tool diverge | SDK tools read-only in the UI; "fork to UI" makes a copy |
| Content moderation false positives | Warn mode before block mode; user override |
| Cost tracker inaccuracy across tokenizers | tiktoken for OpenAI, character fallback, shown as an estimate |
| Refactors stall feature work | Refactor only files changed in the same PR |
| Own gateway falls behind provider API changes | We follow only the 21 providers we ship; contract tests flag drift; LiteLLM backend kept as a fallback until removal |
| "OpenAI-compatible" providers differ (tool-call deltas, stream usage, errors) | Per-provider flags in `openai_compat`; a provider moves off LiteLLM only after its contract tests pass |
| Prices go stale | Price table updated whenever a model is added; unknown model logs a warning instead of costing $0 silently |
| Webview differences (e.g. `@xyflow/react` on WebKitGTK) | Electron stays the fallback shell |

---

## 10) API Conventions

- `/v1/` routes never change shape — additive changes only; breaking changes go to `/v2/`
- Deprecate with a `Sunset` header 90 days before removal
- Internal `/api/...` routes are never exposed to orgs
- Keys in headers (`Authorization: Bearer` / `X-API-Key`), never query params; never logged
- Apps are `/v1/apps` (not `/v1/workflows`, which clashes with wf_step workflows)

---

## 11) Later

- Connector nodes: Slack, Jira, Notion, Snowflake, BigQuery — on the custom-MCP path (MCP config
  + encrypted credentials), OAuth for Slack / Jira / Notion
- MongoDB short- and long-term memory nodes
- Git integration for GitLab / Bitbucket beyond the first GitHub App
- API gateway — Option B (AWS API Gateway + ECS / GCP Cloud Endpoints + Cloud Run / Azure APIM,
  20–200 orgs: usage plans, WAF, metering) then Option C (Kong / Tyk / Traefik on k8s, 200+ orgs
  or on-prem)
- Developer portal: self-service keys, per-org usage dashboards
- Hosted SaaS: per-org data isolation, usage billing
- Enterprise SSO (OIDC / SAML) and SCIM — when a partner requires it
- LangGraph-compatible export (stateful graph JSON)
- Agent-to-agent protocol (A2A) for external agents
- Fine-tuning management (non-goal for now)
- **Phone layout (mobile web)** — decided 2026-10-31: responsive web, not Flutter (a Flutter app
  would rewrite every panel in Dart, has no React Flow equivalent for the canvas, and doubles every
  future UI change; nobody builds pipelines on a phone anyway). Seen via ngrok
  (Settings → Share via ngrok): top-nav items overlap, the sidebar and config panel stack, the
  run bar floats over content, Monitor tiles run off-screen. Steps, each checked on a phone:
  1. Top nav collapses to a menu below ~768px (workspace switcher, tabs, account)
  2. Builder on small screens: a short "open on a computer to edit" view instead of the
     squeezed canvas / sidebar / config panel
  3. Phone shell with a bottom tab bar: Run (published pipelines' chat / prompt runner),
     Monitor (Metrics, Runs, Traces in one column), Approvals (pending Human Gates)
  4. PWA: manifest + service worker, so it installs to the home screen and opens full-screen;
     web push for failed runs, budget alerts and pending approvals
  5. Only if a store app is needed: wrap the same web app with Capacitor (native push, App
     Store / Play) — not a second codebase
