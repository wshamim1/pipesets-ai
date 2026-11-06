# Pipesets AI

Pipesets AI is a self-hostable platform for building, evaluating and operating LLM agent
pipelines. You design a pipeline visually on a canvas (models, tools, memory, retrieval,
guardrails, multi-agent orchestration), test it against eval datasets, publish a version, and run
it from the UI, on a cron schedule, from an inbound webhook, through a versioned public REST API,
from any MCP client, or share it as a chat link anyone can open on a phone or laptop.

![A 70-second tour of Pipesets AI: the Apps hub and starter blueprints, a multi-agent pipeline on the Build canvas, an eval dataset, Monitor runs, traces and costs, Automation, Settings (the tools & MCP package manager, built-in agents, the secrets vault and the audit log), the Lab, the Help menu, sharing a published pipeline as a chat link (QR code and the public chat page), calling that pipeline from another one with a Call Pipeline node, and the desktop app starting up and showing the same Build canvas](docs/media/pipesets-tour.webp)

<sub>The tour runs on a demo workspace with sample data and ends with the desktop app, which has the same features. [Watch it as an MP4](docs/media/pipesets-tour.mp4).</sub>

Version **0.7.0**. The core platform is feature-complete for a pilot. See
[Known limitations](#known-limitations) before running it with production data.

---

## Contents

- [Core concepts](#core-concepts)
- [Features](#features)
- [Canvas node reference](#canvas-node-reference)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Authentication and access control](#authentication-and-access-control)
- [Running pipelines from outside the UI](#running-pipelines-from-outside-the-ui)
- [Exporting pipelines](#exporting-pipelines)
- [Database](#database)
- [Testing](#testing)
- [Deployment](#deployment)
- [Known limitations](#known-limitations)
- [Further documentation](#further-documentation)
- [License](#license)

---

## Core concepts

| Concept | What it is |
|---|---|
| **Tenant / Project** | Every resource belongs to a tenant and a project. Users can belong to several tenants and switch between projects. |
| **App** | A saved canvas flow. Apps start as **drafts**. **Publishing** freezes an immutable numbered version, and only published versions can run outside the editor. Editing a published app creates a new draft. |
| **Pipeline** | A published app run as a unit. Pipelines can call other pipelines, which is how larger systems are composed. |
| **Master / Child agents** | Multi-agent orchestration. A Master Agent plans and delegates to Child Agents (LLMs, pipelines or external agents). Master Agent runs can pause at a **Human Gate** for approval. |
| **Workflow** | A conversational, pausable flow built from Workflow Step nodes. It asks the user questions, collects variables and branches. Each run pins the flow version it started with. |
| **Skill** | A reusable package of instructions or SOPs plus the tools and MCP servers to activate with them. Bound to an LLM node, or selected automatically from its trigger description. |
| **Toolkit** | A user-built bundle of tools that a node can use as a single unit. |
| **Connection** | Saved credentials for an external system (Postgres, MySQL, MongoDB, Redis, Snowflake, S3, SQLite or a custom REST API) that tool nodes reference by name. |

## Features

The UI has seven areas: **Apps, Build, Evaluate, Monitor, Automation, Marketplace and Lab**.

**Build**
- Drag-and-drop canvas (React Flow) with live graph validation. Run the unsaved canvas directly
  from the side panel with streaming output.
- 19 LLM providers and 73 models through our own LLM gateway (`backend/llm/`): OpenAI,
  Anthropic, Gemini, Mistral, Groq, DeepSeek, xAI, Together, Fireworks, Azure, Bedrock, NVIDIA NIM,
  IBM watsonx.ai, Ollama, llama.cpp and others. Covered providers use built-in adapters first;
  LiteLLM remains available as an optional backend and as a fallback for providers without an adapter
  (for example TypeSafe) in
  **Settings → Model backends**.
- AI-assisted building: generate a pipeline from a plain-language description, write custom
  Python tools from a prompt, or convert existing LangChain / CrewAI / AutoGen code into a
  blueprint.
- Tools: a built-in catalog of about 145 tools (web search, Python, REST, SQL, GitHub, Slack, Notion,
  Linear, Kafka and more) and 74 MCP servers, plus custom Python tools, custom MCP servers, toolkits
  and skills.
- **Tools & MCP packages** (Settings): the sidebar offers only the tools and MCP servers a workspace
  has installed — a starter set plus whatever its pipelines use. Browse and install the rest from
  the package manager. Uninstalling hides a tool from the sidebar; pipelines that use it keep running.
- **Databricks and Snowflake:** REST tools for jobs, runs, clusters, SQL warehouses, Unity Catalog,
  volumes, model serving, vector search, Genie and pipelines (Databricks), and SQL without a driver,
  warehouses, catalog, query history, tasks, Snowpipe, COPY history, stages and Cortex Complete /
  Search / Analyst (Snowflake), with token auth. MCP servers for both: the community servers,
  Snowflake's official server (read-only by default) and each platform's managed MCP servers.
- Custom tools are typed functions (`@tool`): their parameters become the function the model calls,
  with real arguments. Every change is a version (pin one per node, roll back); write, test and
  deploy them from code with `pipesets tool` and a CI recipe (see [sdk/README.md](sdk/README.md)).
- Custom Python code runs in a container sandbox (podman or docker). There is a local fallback
  that can be disabled.
- RAG: over 100 document loader types, six text splitters, nine embedding providers, local or
  pgvector vector stores, similarity / MMR / BM25 retrievers, a reranker, and knowledge bases.
- Guardrail middleware: content moderation with PII detection, prompt-injection detection,
  per-run token caps and rate limiting. Applied to normal and streaming runs, including mid-stream
  retraction.
- Memory (sliding window, summarize, last-k) with an inspector, response caching with three
  scopes, and output parsers. Conversation history is kept per tenant / project.
- **Long-term memory** (opt-in per workspace): facts each end user states — preferences, profile,
  goals — are learned after each answer (PII removed) and recalled in their later sessions. The end
  user is the signed-in user on the canvas and the `user` field on `/v1` and MCP runs. Monitor →
  Sessions → Long-term lists, deletes and forgets what is remembered.
- **Model provider keys in Settings:** default per-project keys for OpenAI, Anthropic, Groq,
  Gemini, Mistral, Together, Hugging Face, Fireworks, DeepSeek, xAI, Cerebras, Perplexity,
  Cohere, Azure OpenAI, NVIDIA NIM, IBM watsonx.ai and TypeSafe.

**Evaluate**
- Eval datasets and test cases, with Excel import/export, LLM-generated cases, and cases created
  from real traces.
- **Synthetic data support:** generate synthetic eval test cases from your app (and optionally
  dataset instructions), then review and save them into a dataset before running evals.
- Scorers and run comparison. Pipeline evals record the cost of every model call a run makes,
  nested pipelines included.
- **Optimize models** (Evaluate → ⚡ Optimize): finds the cheapest (or fastest) model for each LLM
  node that keeps the dataset's pass rate within a tolerance you set. Every option runs the whole
  pipeline, so a cheap model that makes later steps work harder is charged for that. It starts from
  the saved models, tries each candidate on each node (optionally screened on the first few cases),
  then combines the winners and measures each combination again. It runs as a background job with
  live progress, and its results can be applied to the pipeline's draft. Past optimizations are kept
  and can be reopened, re-run, or edited and re-run. Each option is a real, billed run of the dataset.
- **Eval-gated publishing:** an app can require a dataset to pass a threshold, or not regress
  against the previous version, before it can be published (block or warn mode, admin override).

**Monitor**
- Runs, traces (per-step detail), global logs, sessions, costs and budgets (block or warn).
- Optional mirroring of every trace to Langfuse, with a redaction mode.

**Automation**
- Schedules, webhooks and alerts. Alerts go to Slack or a JSON webhook when a run fails, a Human
  Gate pauses a run or its review times out, or a schedule auto-pauses.
- Jobs: the background queue that runs them, retried with backoff. Jobs that fail every retry can
  be retried again or discarded.

**Share**
- Chat links: give a published pipeline a URL (`/c/pc_…`) that opens a phone-friendly chat page.
  Anyone with the link can chat, no account needed; each visitor gets their own conversation.
  The page can show what the pipeline is (description, model, tools, MCP servers, agents) and
  sample prompts to tap. Per-link limits, QR code and instant revoke.

**Marketplace**
- Publish pipelines as listings that are public or limited to your tenant. Others can browse,
  try a listing without importing it, and import a version into their project as a draft. Imports
  show when a newer version is available.

**Lab**
- One-click service containers (Postgres, MySQL, MariaDB, MongoDB, ClickHouse, Chroma and more)
  seeded with sample datasets, for trying out pipelines against real databases.

**Platform**
- Multi-tenant IAM with users, groups, projects, per-resource ACLs and tenant roles.
- App versioning with history and generated pipeline documentation.
- Public `/v1` API with scoped, rate-limited, expiring API keys.
- Python SDK, CLI and MCP server.

## Canvas node reference

| Group | Nodes |
|---|---|
| Models | LLM, Output Parser |
| Tools | Tool, MCP server, Toolkit, Skill, Connection |
| Guardrails | Middleware (content moderation, cost tracker, rate limiter, prompt injection) |
| State | Memory, Cache |
| Retrieval | Doc Loader, Text Splitter, Embedding, Vector Store, Retriever, Reranker, Knowledge Base |
| Orchestration | Start, Stop, Master Agent, Child Agent, Gateway (routing), Human Gate |
| Workflows | Workflow Step |

## Architecture

```
 Browser ──► frontend (React + Vite; nginx in containers)
                │  /api/*  (session cookie / bearer token)
                ▼
 External ──► backend (FastAPI)
 callers       ├─ /api/*        internal API — signed-in users only
   │           ├─ /v1/*         public API — API keys (ps_…)
   ├──────────►├─ /v1/hooks/*   inbound webhooks — secret URL token (+ optional HMAC)
   └──────────►├─ /v1/chat/*    chat links — secret URL token (page: frontend /c/<token>)
               │
               ├─ pipeline runner ── LLM gateway (llm/) ── built-in adapters + optional LiteLLM backend ──► LLM providers
               ├─ tool executor ──── sandbox (podman/docker) · MCP servers · connections
               ├─ RAG ────────────── local store (app DB) or pgvector
               ├─ scheduler (in-process cron) · webhook workers · notifier
               └─ SQLAlchemy ──► SQLite (default) | Postgres | SQL Server | MySQL
                                      └─ optional trace export ──► Langfuse
```

| Layer | Stack |
|---|---|
| Frontend | React 19, TypeScript, Vite, React Flow (`@xyflow/react`) |
| Backend | Python 3.12, FastAPI, Uvicorn, SQLAlchemy, Alembic, own LLM gateway (built-in adapters where available; LiteLLM optional/fallback) |
| Storage | SQLite by default, or any SQLAlchemy database. pgvector for vectors. |
| Packaging | Docker/Podman images, Compose, Kubernetes (Kustomize) |

For how each part works inside, see [docs/architecture](docs/architecture/README.md).

## Repository layout

```
pipesets-ai/
├── backend/
│   ├── main.py              FastAPI app: router registration, auth dependency, scheduler lifecycle
│   ├── routers/             one module per API area (apps, run, stream, v1, webhooks, eval, iam, …)
│   ├── services/            pipeline runner, LLM runner, workflow engine, sandbox, scheduler,
│   │                        webhooks, notifier, vector store, auth, API keys, ACLs, budgets
│   ├── exporters/           LangChain, CrewAI, AutoGen, notebook, Docker and native exporters
│   ├── data/                built-in tool catalog and custom-tool templates
│   ├── migrations/          Alembic migrations
│   ├── tests/               pytest suite (conftest.py: per-module temp DB, helpers)
│   ├── db.py · models.py    database engine, schema bootstrap, demo seed · default LLM config
│   └── manage.py            admin CLI (API keys, passwords, schema)
├── frontend/src/
│   ├── App.tsx              top-level views and canvas
│   ├── components/          views and panels (Build, Monitor, Eval, Marketplace, Lab, IAM, …)
│   └── types.ts             node data types; API_BASE
├── sdk/                     `pipesets` Python SDK, CLI and MCP server
├── deploy/
│   ├── compose/             Docker/Podman Compose
│   └── k8s/                 Kustomize manifests
├── start.sh · stop.sh       local development launcher
└── DEPLOYMENT.md            container and Kubernetes deployment guide
```

## Getting started

### Prerequisites

- Python 3.12+
- Node.js 20.19+ or 22.12+ (required by Vite 8)
- Optional: **podman or docker**. Used to sandbox custom Python tools and to run Lab service
  containers. Without it, tools run in a local subprocess unless `SANDBOX_REQUIRE_ISOLATION=1`.

### Run locally

```bash
cp backend/.env.example backend/.env    # add at least one provider key, or set DEFAULT_LLM_PROVIDER=mock
./start.sh
```

`start.sh` creates `backend/.venv`, installs the Python dependencies (again only when
`requirements.txt` changes), runs `npm install` on first start, and launches both services in the
background.

| | URL / file |
|---|---|
| UI | http://localhost:5173 |
| API + interactive docs | http://localhost:8000/docs |
| Logs | `backend.log`, `frontend.log` in the repo root |
| Stop | `./stop.sh` |

Use `BACKEND_PORT` and `FRONTEND_PORT` to change the ports. If the backend is not on
`localhost:8000`, set `VITE_API_BASE` for the frontend.

To run the services in the foreground instead:

```bash
cd backend  && source .venv/bin/activate && uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```

### First sign-in

On first start the backend creates the schema and seeds a **Demo Tenant**. It contains the users
`admin@demo.local` and `analyst@demo.local`, who have no passwords. Either:

- **Sign up** from the login screen (enabled by default with `AUTH_ALLOW_SIGNUP=1`), or
- set a password for a seeded user:

  ```bash
  cd backend && .venv/bin/python manage.py set-password admin@demo.local
  ```

### Build your first pipeline

1. **Build:** drag an **LLM** node onto the canvas and choose a provider and model. Optionally add
   Memory, Tools or a Knowledge Base.
2. Try it in the run panel. Provider keys come from the node, from **Settings**, or from the
   server environment.
3. **Publish** the app. Only published versions can be called by schedules, webhooks, `/v1` or
   other pipelines.
4. **Monitor:** inspect the run's trace, cost and logs.

## Configuration

All backend settings are environment variables, read from `backend/.env`. See
[backend/.env.example](backend/.env.example) for the annotated defaults.

**Models**

| Variable | Default | Purpose |
|---|---|---|
| `DEFAULT_LLM_PROVIDER` | `openai` | `openai`, `anthropic`, `ollama` or `mock` |
| `DEFAULT_LLM_MODEL` | `gpt-4` | Default model for new LLM nodes |
| `DEFAULT_LLM_TEMPERATURE` / `_MAX_TOKENS` / `_TOP_P` | `0.7` / `1024` / `1.0` | Default sampling settings |
| `LLM_BASE_URL`, `OLLAMA_API_BASE` | | Custom endpoint (Ollama, vLLM, a proxy) |
| `WATSONX_URL`, `WATSONX_PROJECT_ID` | `https://us-south.ml.cloud.ibm.com` | IBM watsonx.ai region URL and the project every watsonx call runs in (the region URL can also be set in Settings → Model backends) |
| `NVIDIA_NIM_API_BASE` | `https://integrate.api.nvidia.com/v1` | NVIDIA's hosted API, or your self-hosted NIM |
| `LLM_BACKEND`, `LLM_BACKEND_<PROVIDER>` | `auto` | Which gateway backend sends model calls: `auto`, `openai_compat`, `anthropic`, `gemini`, `bedrock`, `watsonx` or (if installed) `litellm`. `auto` prefers built-in adapters for covered providers and falls back to LiteLLM for uncovered ones. Settings → Model backends overrides these per project or workspace. |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`, `COHERE_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `CEREBRAS_API_KEY`, `PERPLEXITY_API_KEY`, `HF_TOKEN`/`HUGGINGFACE_API_KEY`, `AZURE_API_KEY`/`AZURE_OPENAI_API_KEY`, `TOGETHERAI_API_KEY`, `FIREWORKS_AI_API_KEY`, `NVIDIA_NIM_API_KEY`, `WATSONX_APIKEY`/`WATSONX_API_KEY` | | Server-wide provider keys. Node-level keys and keys sent with a request take precedence. |

**Database and storage**

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | empty | Any SQLAlchemy URL. Empty means SQLite. |
| `SQLITE_DB_PATH` | `backend/pipesets.db` | SQLite file location when `DATABASE_URL` is empty |
| `PGVECTOR_URL` | | Fallback DSN for pgvector stores. A Vector Store node can set its own DSN. |

**Authentication**

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_MODE` | `session` | `session`: every `/api` route requires sign-in. `headers`: legacy dev mode that trusts `x-user-id` / `x-tenant-id`. |
| `AUTH_ALLOW_SIGNUP` | `1` | `0` turns off self-service sign-up, so admins add users from IAM |
| `AUTH_SESSION_TTL_HOURS` | `168` | Session lifetime |

**Runtime**

| Variable | Default | Purpose |
|---|---|---|
| `SCHEDULER_ENABLED` | `true` | Runs cron schedules in this process. Set it to `true` on only one replica. |
| `SCHEDULER_POLL_SECONDS` / `_MAX_CONCURRENT` / `_MIN_INTERVAL_SECONDS` | `30` / `3` / `300` | Scheduler tuning |
| `WEBHOOK_MAX_INFLIGHT` / `WEBHOOK_MAX_BODY_BYTES` | `5` / `262144` | Per-webhook concurrency (more calls get 429) and body size limit |
| `SANDBOX_REQUIRE_ISOLATION` | `0` | `1` means custom tools fail instead of running unsandboxed when no container engine is available |
| `EXTERNAL_AGENT_ALLOW_PRIVATE` / `EXTERNAL_AGENT_ALLOWED_HOSTS` | `0` / empty | SSRF guard for external child agents and remote MCP servers |
| `PIPESETS_PUBLIC_URL` | the request's own URL | Public base URL of the backend, e.g. `https://pipesets.example.com`. MCP OAuth sign-in redirects back to `<it>/api/custom-mcp/oauth/callback`; set it behind a proxy |
| `MARKETPLACE_TRY_SERVER_KEYS` | | Allows "try" runs in the Marketplace to use the server's provider keys |

**Observability and alerts**

| Variable | Purpose |
|---|---|
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Mirror every run trace to Langfuse |
| `LANGFUSE_REDACT` | `1` sends only model, tokens, cost and latency (no prompt or output text) |
| `SLACK_WEBHOOK_URL`, `SMTP_PASSWORD` | Defaults for the notification and email tools |

**Built-in tool credentials (optional).** Set these to enable the matching catalog tools and MCP
servers: `TAVILY_API_KEY`, `BRAVE_API_KEY`, `FIRECRAWL_API_KEY`, `OPENWEATHERMAP_API_KEY`,
`GITHUB_TOKEN` / `GITHUB_PERSONAL_ACCESS_TOKEN`, `GITLAB_PERSONAL_ACCESS_TOKEN` / `GITLAB_API_URL`,
`NOTION_TOKEN`, `LINEAR_API_KEY`, `SENTRY_AUTH_TOKEN`, `GDRIVE_CREDENTIALS_FILE`,
`SLACK_BOT_TOKEN` / `SLACK_TEAM_ID` / `SLACK_CHANNEL_IDS`, `TRELLO_API_KEY` / `TRELLO_TOKEN`,
`ASANA_ACCESS_TOKEN` / `ASANA_MCP_DEFAULT_WORKSPACE` / `ASANA_MCP_WRITE_MODE`,
`GOOGLE_MAPS_API_KEY`, `BEDROCK_KB_ID`,
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION`, `KAFKA_BOOTSTRAP_SERVERS`,
`CONFLUENT_CLOUD_API_KEY` / `_SECRET`, `REDIS_URL`, `SQL_CONNECTION_STRING`, `OPENAPI_SPEC_URL`.
The Databricks and Snowflake MCP servers also read `DATABRICKS_HOST` / `DATABRICKS_TOKEN` /
`DATABRICKS_WAREHOUSE_ID` and `SNOWFLAKE_ACCOUNT` / `SNOWFLAKE_USER` / `SNOWFLAKE_PASSWORD` /
`SNOWFLAKE_ROLE` / `SNOWFLAKE_WAREHOUSE` / `SNOWFLAKE_TOKEN`; the Databricks and Snowflake REST tools
take their host or account and token from the node (use a secret).

**Frontend**

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE` | `http://localhost:8000` | Backend base URL, set at build time. Container builds use `/api`, which nginx proxies. |

## Authentication and access control

| Surface | Credential | Notes |
|---|---|---|
| `/api/*` (UI and internal) | Session token from `/api/auth/login` | Brute-force throttled. Changing a password ends all of that user's sessions. |
| `/v1/*` (public API) | `Authorization: Bearer ps_…` API key | Scopes `apps:read` and `apps:run`. Per-key rate limit (default 60 rpm) and optional expiry. Only the SHA-256 hash is stored. |
| `/v1/hooks/{token}` | Secret URL token, optional HMAC | Token is shown once and stored hashed. Signature header is `X-Hub-Signature-256` or `X-Pipesets-Signature`. |
| `/v1/chat/{token}` | Secret URL token (the chat link) | Public: anyone with the link. Stored hashed, plus an encrypted copy so the builder can copy the link again. Runs act as the link's creator. Passcode and sign-in links are planned. |

- **Tenant roles:** `owner`, `editor`, `viewer`. Groups and per-resource ACLs narrow access
  within a tenant.
- API keys act as the user who created them, so ACLs, budgets and middleware still apply.
- API keys are never accepted as UI sessions, and session tokens are never accepted on `/v1`.

Manage API keys from **Settings → API Keys** in the UI, or with the CLI:

```bash
cd backend
.venv/bin/python manage.py create-key --name "My app" [--scope apps:run] [--rpm 120] [--expires-days 90]
.venv/bin/python manage.py list-keys
.venv/bin/python manage.py revoke-key <key_id>
```

The plaintext key is printed once and cannot be recovered.

## Running pipelines from outside the UI

### Public REST API (`/v1`)

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/v1/health` | none | Liveness |
| GET | `/v1/apps` | `apps:read` | Published apps visible to the key |
| GET | `/v1/apps/{app_id}` | `apps:read` | One app's summary (flow data is never returned) |
| POST | `/v1/apps/{app_id}/run` | `apps:run` | Run a published app, returning SSE or JSON |
| POST | `/v1/runs/{run_id}/resume` | `apps:run` | Continue a paused, interrupted or failed run |

```bash
curl -N http://localhost:8000/v1/apps/$APP_ID/run \
  -H "Authorization: Bearer $PIPESETS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarise this ticket", "session_id": "user-42", "stream": true}'
```

Request fields:

| Field | Default | Purpose |
|---|---|---|
| `prompt` | required | Input text |
| `session_id` | | Gives each end user their own Memory history |
| `stream` | `true` | `true` returns SSE, `false` returns JSON |
| `timeout_ms` | `120000` | Run timeout |
| `provider_keys` | | Bring-your-own provider keys, e.g. `{"openai": "sk-…"}` |

The stream emits these events: `run` (LLM apps, first: the run's id), `token`, `meta`, `paused` (a
Human Gate is waiting; resume with a `gate_decision` of `approve`, `reject` or `edit`), `error` and
`done`. Every run is checkpointed: an interrupted or failed one continues with
`POST /v1/runs/{run_id}/resume`, reusing its finished model and tool calls. The `/v1` contract only
changes additively. Breaking changes will go to `/v2`.

### Webhooks

Create a webhook in **Automation → Webhooks** (or from the Build sidebar) for a published app.
External systems `POST /v1/hooks/{token}`. The call is accepted with `202` and the run happens in
the background. The run's prompt comes from the webhook's template:

```
{{body}}                    whole body (pretty-printed JSON)
{{body.commits.0.message}}  a field of a JSON body
{{query.repo}}              a query-string parameter
```

If a signing secret is set, each call must include `sha256=<hex HMAC-SHA256 of raw body>` in
`X-Hub-Signature-256` (works directly with GitHub) or `X-Pipesets-Signature`.

### Chat links

Open a published pipeline in **Build** and click **Chat link** in the toolbar, then **+ New chat
link**. You get a URL like `https://<host>/c/pc_…` and a QR code. Anyone who opens it can chat with
the pipeline's latest published version. No account is needed.

- The page shows the pipeline's description and the names of its models, tools, MCP servers and
  agents. It never shows system prompts, connection details, document collections or keys. Untick
  **Show pipeline details** to hide them. A collapsed **Pipeline info** section has the pipeline ID,
  its published version and an **Open in Pipesets** link (`/?pipeline=<id>`), which opens the
  pipeline in Build for anyone signed in with access to its project.
- Add up to 6 **sample prompts** visitors can tap to start, or click **✨ Generate from pipeline** to
  have the pipeline's model draft them.
- Each visitor gets their own conversation, kept across page reloads. It's remembered even if the
  pipeline has no Memory node.
- Visitors only see the answer, never traces, costs or run IDs.
- Runs act as the user who created the link, so their ACLs, budgets and middleware apply.
- Limits per link (editable): 10 messages a minute per visitor, 50 per conversation, 500 a day
  across all visitors, 4,000 characters per message.
- **Turn off** stops the link on the next message. Creating, editing and turning off links is
  recorded in the audit log.
- While the pipeline is being edited, the link answers "unavailable" until you publish again.

A link made on `localhost` only opens on that computer. To try it on a phone during development,
use **Settings → Share via ngrok** and open the builder through the ngrok address. Behind the edge
proxy, chat links are served on the public host (see [DEPLOYMENT.md](DEPLOYMENT.md)).

**Embed on a website.** In the Chat link dialog, **Embed on a website** gives copy-paste HTML for
a floating chat button or an inline `<iframe>` (the chat page with `?embed=1`), and **Download
sample page** gives a page with both and your link filled in. See
[examples/chat-embed](examples/chat-embed/). Any site can embed a link, just as anyone can open it;
turning the link off stops it everywhere.

The page calls two public endpoints: `POST /v1/chat/{token}/session` and
`POST /v1/chat/{token}/message` (SSE).

### Schedules

**Automation → Schedules** runs a published app on a cron expression, at most once every
`SCHEDULER_MIN_INTERVAL_SECONDS`. A schedule auto-pauses after repeated failures and sends an
alert.

### SDK, CLI and MCP server

```bash
pip install -e sdk
export PIPESETS_URL=http://localhost:8000 PIPESETS_API_KEY=ps_...
pipesets v1 apps
pipesets v1 run <app_id> "Summarise this ticket" --stream
```

```python
from pipesets import PipesetsClient

with PipesetsClient("http://localhost:8000", api_key="ps_...") as c:
    print(c.v1_run(app_id, "Hello", stream=False))
```

**Remote MCP server.** The backend serves the `/v1` API as an MCP server at `/v1/mcp`
(Streamable HTTP), authenticated by the same API keys. Tools: `list_apps` and `get_app`
(`apps:read`), `run_app` and `resume_run` (`apps:run`). A key only sees the tools its scopes allow.
Two opt-in scopes let a client build apps: `apps:write` (`create_app`, `update_app`, `list_drafts`,
`get_flow`) changes drafts only, never what is live; `apps:publish` (`publish_app`) puts a draft live
through its eval gate, with no override. Each write is in the audit log under the key's owner and name.
Add it to Claude Code with:

```bash
claude mcp add --transport http pipesets https://api.example.com/v1/mcp \
  --header "Authorization: Bearer ps_..."
```

Other clients take the same URL and header. Provider keys go in headers
(`X-Provider-Key-Openai: sk-...`), never in tool arguments; without them, runs use the
project's default keys or the server's. A run that pauses at a Human Gate is reported to the
client, but a person approves it in Pipesets: the model can't approve its own gate. A browser
`Origin` is refused unless listed in `MCP_ALLOWED_ORIGINS`.

`pipesets-mcp` (in the SDK) is the older stdio server. It signs in as a user and has more tools
(drafts, traces, export). See [sdk/README.md](sdk/README.md) for its configuration.

## Exporting pipelines

From the Export dialog (or `pipesets export <app_id> --format …`):

| Format | Output |
|---|---|
| Pipesets JSON | Raw flow, re-importable into any Pipesets AI instance |
| LangChain / CrewAI / AutoGen | Standalone Python code |
| Notebook | Jupyter notebook |
| Docker Compose | Containerised runnable bundle |
| OpenAPI | Spec for the app's API |

## Database

- **SQLite** (default): `backend/pipesets.db`, or `/data/pipesets.db` in the container image.
  This is fine for development and single-instance deployments.
- **Postgres, SQL Server, MySQL**: set `DATABASE_URL`, for example
  `postgresql+psycopg2://user:pass@host:5432/pipesets`. SQL Server also needs `pyodbc` and an
  ODBC driver.

The schema is created and upgraded automatically at startup through Alembic. To manage it
explicitly:

```bash
cd backend
.venv/bin/python manage.py db setup   # create/upgrade the schema and seed the demo tenant
.venv/bin/python manage.py db sql     # print the migration SQL without applying it (for DBA review)
```

## Testing

Backend tests use pytest. Every test module gets its own fresh, migrated SQLite database in a
temp folder, so your real database and master key are never touched, and none of them call an LLM
(they use the `mock` provider or stub the model call). Shared setup is in `tests/conftest.py`.

```bash
cd backend
.venv/bin/python -m pip install -r requirements-dev.txt   # once
.venv/bin/python -m pytest                               # or: pytest tests/security/test_secrets.py -k rotation
```

Frontend:

```bash
cd frontend
npm run lint          # oxlint
npm run build         # tsc -b, then vite build
```

CI (`.github/workflows/ci.yml`) runs all of this on every push and pull request, and checks that
the migrations run up and back down. It installs the backend from `requirements.lock`: exact
versions with hashes, generated from `requirements.txt` for Linux (CI and the container image),
with the CPU build of torch — installing it needs the PyTorch CPU index (`--torch-backend cpu`
with uv, `--extra-index-url https://download.pytorch.org/whl/cpu` with pip). After changing `requirements.txt`, regenerate the lock with the command in its header (needs
[uv](https://docs.astral.sh/uv/)). CI fails if the lock no longer satisfies `requirements.txt`.

## Deployment

Two images, `pipesets-ai-backend` (FastAPI on `:8000`) and `pipesets-ai-frontend` (nginx on
`:8080`, which serves the UI and proxies `/api` to the backend):

```bash
cd deploy/compose
cp .env.example .env
docker compose up -d --build     # or: podman compose up -d --build
```

[DEPLOYMENT.md](DEPLOYMENT.md) covers Podman pods, Kubernetes (Kustomize), image registries, secrets and container-specific limitations.

## Known limitations

- **Secrets at rest:** saved secrets and connection credentials are encrypted under
  `PIPESETS_MASTER_KEY` (or a key held in AWS KMS / Vault — see `backend/.env.example`), as are
  webhook signing secrets and notification channel URLs. Pipelines can't be saved with a key typed
  into a node — pick it from Secrets. Logs mask known key patterns (`sk-…`, bearer tokens,
  `enc://…`). Restrict access to the database and its backups anyway.
- **Single-process state:** the API-key rate limiter, webhook concurrency limits and scheduler
  live in process memory. With several replicas, enable the scheduler on only one of them. Rate
  limits apply per replica.
- **Vector stores:** only `local` (brute-force cosine in the app DB, suitable for a few thousand
  chunks) and `pgvector` are implemented. Other store types shown in the UI fall back to `local`.
- **Checkpointing:** Master Agent and LLM-node runs are checkpointed and resumable. Runs of a
  pipeline nested inside another run are not (the outer run is).
- **Publish gate:** the eval runs inside the publish request, so large datasets make publishing slow.
- **Optimize models:** results are only as good as the dataset. If the saved models pass no cases,
  the optimization stops instead of recommending anything. Expected outputs that describe an action
  ("Update successful") reward a model that only claims it. Each option runs once, so on a small
  dataset one unlucky answer can reject a good model; set a tolerance. Nodes inside called pipelines
  are tried but not changed by **Apply to draft**: edit and re-publish those pipelines.
- **Alerts:** delivered on a best-effort basis to Slack or a JSON webhook, without retries. There
  is no email alert channel yet.
- **CORS:** only the origins in `CORS_ORIGINS` may call the backend from a browser (default: the
  Vite dev server). The deployed UI goes through the frontend proxy and needs no CORS. Set
  `ALLOWED_HOSTS` to restrict the accepted `Host` header.

## Further documentation

| Document | Contents |
|---|---|
| [DEPLOYMENT.md](DEPLOYMENT.md) | Container, Compose and Kubernetes deployment |
| [docs/architecture](docs/architecture/README.md) | How the system is built: backend, run engine, LLM gateway, tools and RAG, security model, background jobs, storage, observability, frontend, deployment topologies |
| [sdk/README.md](sdk/README.md) | SDK, CLI and MCP server reference |
| [docs/guide](docs/guide/README.md) | User guide: building pipelines, tools, MCP, custom tools, agents, workflows, skills, RAG, guardrails, evals, monitoring, automation, sharing, settings, document extraction. Also in the app: **Docs** in the top bar |

## License

Apache License 2.0. Copyright 2026 Shamim and the Pipesets AI contributors. See
[LICENSE](LICENSE) and [NOTICE](NOTICE).

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md), and report security issues as
described in [SECURITY.md](SECURITY.md).
