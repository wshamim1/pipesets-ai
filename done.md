# Pipesets AI — Done

> Everything shipped so far, merged from `90_day_mvp_plan.md`, `next_90_days_plan.md` and
> `desktop_app_plan.md` (2026-10-28). Checked against the code, not by end-to-end testing,
> unless a line says "verified". Open work and known gaps live in [plan.md](plan.md).

---

## Canvas & Builder

- Visual drag-and-drop canvas (React + TypeScript + React Flow + Zustand): connect, configure,
  save, export
- 24 node types: LLM, Tool, Toolkit, Connection, Memory, Cache, Middleware, Doc Loader, Text
  Splitter, Embedding, Vector Store, Retriever, Reranker, Knowledge Base, Output Parser, Skill,
  Workflow Step, Start, Stop, Gateway, Human Gate, Master Agent, Child Agent, Synthetic Data
- Client-side graph validation with errors and warnings (`utils/pipelineValidation.ts`)
- Versioning: draft / published with version bump (`/publish`, `/edit` in `apps.py`);
  `app_versions` snapshots
- Starter templates in one click (`AppsHubView.tsx`): RAG assistant, multi-agent research crew,
  tool-equipped assistant
- Blueprints and marketplace (`services/marketplace.py`)
- Export (`routers/export.py`, `exporters/`): native JSON, OpenAPI, LangChain, CrewAI, AutoGen,
  Docker Compose, notebook, Agent Skill (2026-11-03: `SKILL.md` + stdlib `run.py` zip that runs the
  published app via `/v1`; the script verified against a live server in `tests/apps/test_skill_export.py`)
- Exports and skills scoped to the caller's tenant / project (2026-11-03): export needed no ACL and
  read any app by id; skills could be listed, read, edited and deleted across tenants. Built-in
  skills now live in code, read-only (migration `0029`)

## Models

- LLM node: 19 providers through our own gateway (`backend/llm/`); model catalog in `llm/catalog.py`
- Own adapters for every chat provider (2026-11-01; was LiteLLM): `openai_compat` (OpenAI, Groq,
  Mistral, Together, Fireworks, Hugging Face, DeepSeek, xAI, Cerebras, Perplexity, Cohere, Azure,
  NVIDIA, Ollama, llama.cpp), `anthropic`, `gemini`, `bedrock`, `watsonx`. `auto` picks them; LiteLLM
  is an optional fallback serving only TypeSafe. Live-checked: OpenAI and local servers only — the
  rest are covered by unit tests (see plan.md A5)
- Native adapters for Mistral, Cohere (v2) and Ollama (`/api/chat`), opt-in per provider in
  Settings → Model backends (2026-11-01). **Not tested against the real APIs** — unit tests only
  (`tests/gateway/test_llm_native.py`); `auto` still uses `openai_compat` for these three
- Settings → Model backends: **Migrate LiteLLM overrides** moves saved `litellm` rows to `auto`
  (`POST /api/llm-settings/migrate-litellm`, dry-run) (2026-11-01)
- CI fails if a listed paid model has no price (2026-10-28)
- Local models: Ollama, llama.cpp and Jan over HTTP (`services/llm_runner.py`)
- Streaming prompt runner with tool-call trace

## Tools & MCP

- 10 built-in tools (2026-11-04), offline tests against fake APIs (`test_research_devops_tools.py`):
  - Research & Knowledge: Semantic Scholar (key optional), Crossref DOI lookup / search, SEC EDGAR
    filings (ticker or CIK; the SEC requires a contact `user_agent`)
  - APIs & Integrations: GitLab (gitlab.com or self-managed; project, issues, MRs, pipelines,
    commits), Sentry issues (search, or one issue with its latest stack trace), Prometheus
    (PromQL instant query, or min / max / last over a `lookback`)
  - Business Apps: ClickUp (list / read / create tasks). Communication: Pushover
  - Everyday Utilities: cron expression helper (explains each field, next runs in a timezone).
    Data & Files: XML ↔ JSON converter (refuses DOCTYPE / ENTITY declarations)
  - None are in `tool_packages.DEFAULTS`; workspaces install them from Tools & MCP packages
- 7 more built-in tools (2026-11-05), offline tests against fake vendor APIs in `test_more_tools.py`:
  - Research & Knowledge: FRED (St. Louis Fed, free key; a series id or short name like
    `unemployment` / `10y_treasury` reads the latest observations, else searches series by popularity)
  - Code & Compute: OSV vulnerabilities (OSV.dev, no key; `ecosystem:package@version` lists the
    advisories with severity, CVE aliases and fixed versions for that package; npm scopes handled; an
    advisory id reads it)
  - Business Apps: Pipedrive (API v2, read-only: open deals, one deal with contact and organization,
    item search)
  - APIs & Integrations: HCP Terraform (read-only: workspaces with their latest run, errored first; a
    workspace's runs; one run's plan changes and the errored plan / apply log, fetched without the token
    from the pre-signed URL; `hostname` for Terraform Enterprise), Vercel deployments (failed by
    default, per project; one deployment's error and build log tail; `team_id`)
  - Productivity: Dropbox (read-only: list a folder, read a text file, search; refresh token + app
    key / secret, since access tokens expire after 4 hours)
  - Communication: WhatsApp (Cloud API; recipient only in config; text inside the 24-hour window,
    else `template_name` with the input as {{1}}; error 131047 explained). Request shapes from the
    vendors' docs, not yet run against the real APIs
- 4 more MCP servers (2026-11-05), each checked against its downloaded source, not launched
  (`tests/mcp_servers/test_mcp_more_servers.py`):
  - Productivity: Mailgun (`@mailgun/mcp-server` 2.1.3, official; `MAILGUN_API_KEY` /
    `MAILGUN_API_REGION`, a `--tags` dropdown per product, no delete tools; default `get-v4-domains`,
    a domain as input → `get_metrics_summary`), Contentful (`@contentful/mcp-server` 1.24.4, official;
    `CONTENTFUL_MANAGEMENT_ACCESS_TOKEN` / `SPACE_ID` / `ENVIRONMENT_ID` / `CONTENTFUL_HOST`; input →
    `search_entries`, else `list_content_types`; no read-only mode, the description says so)
  - DevOps & Observability: AWS Cost Explorer (`awslabs.cost-explorer-mcp-server` 0.0.21; read-only,
    standard AWS env vars; default month-to-date cost by service; $0.01 per API request, said in the
    description)
  - Developer Tools: GitMCP (hosted gitmcp.io, no key; tool names from a live `tools/list`;
    `owner/repo: question` searches the docs, `owner/repo` reads them, a URL reads the page, a bare
    library name maps it to its repo)
  - Not added: Heroku (`@heroku/mcp-server` needs the Heroku CLI installed and has no read-only mode,
    incl. `pg_psql` and deploys), Twilio (`@twilio-alpha/mcp` is a proof of concept and takes the API
    secret as a command-line argument), CoinGecko's remote server (code-execution only), AWS Billing
    and Cost Management (tools registered through sub-servers, names not checkable from the package)
  - None are in `tool_packages.DEFAULTS`; workspaces install them from Tools & MCP packages
- Jobs & Careers tools (2026-11-04), offline tests in `test_job_tools.py`: LinkedIn, Indeed and Naukri have
  no public job-search API and forbid scraping, so: Google Jobs (SerpApi `google_jobs` engine; results
  say where they were posted — LinkedIn, Indeed, Naukri… — with apply links), Adzuna (free key; India,
  UK, US, Europe…), Jooble (free key; 60+ countries; request shape from Jooble's sample code, not yet
  run against the real API), Company Jobs (public Greenhouse / Lever / Ashby boards, no key; checked
  live) and LinkedIn Post (official Posts API, member token with `w_member_social`, version 202610).
  New agent: Job Search Assistant. Not added: scraper MCP servers for LinkedIn / Indeed / Naukri (break
  their terms), Remotive (asks for ~4 calls a day and no redistribution), Indeed's hosted MCP
  (`mcp.indeed.com`, OAuth, not documented on indeed.com — try it as a custom MCP server)
- Observability batch (2026-11-04), offline tests against fake APIs in `test_observability_tools.py`:
  - Built-in tools: Grafana (firing / pending alert rules, dashboard search, annotations, data
    sources), Loki (LogQL `query_range`: lines newest first, or a metric query's latest values;
    Grafana Cloud basic auth, tenant header), Tempo (TraceQL search slowest first; a trace id reads
    services, slowest spans and errors, v2 API then v1), Alertmanager (API v2: active alerts most
    severe first, silences), Datadog (monitors not OK, v2 log search, events; site dropdown), Splunk
    (SPL one-shot export, v2 then v1 endpoint) and Elasticsearch Ops (cluster health with the
    unassigned-shard explanation, indices by size, ES|QL as a table). Shared Grafana-stack auth in
    `tools/integrations/_grafana_stack.py`
  - MCP: OpenSearch (`opensearch-mcp-server-py` 0.12.0, official; checked against source; writes off,
    no-auth when no credentials) and Elastic Agent Builder (Kibana's own endpoint
    `/api/agent_builder/mcp`, `ApiKey` header; default `platform.core.list_indices` from Elastic's
    docs, the exposed tool list not confirmed). `mcp_elasticsearch` is now hidden: Elastic deprecated
    the package and server (security fixes only)
  - Not added: Logfire (`logfire-mcp` now only prints "use the remote server", which needs OAuth),
    Splunk MCP (only an individual's package)
  - Agents: Incident Responder reads Datadog / Grafana / Loki / Splunk and optionally Alertmanager and
    Tempo; new Log Investigator and Alert Triage
- 7 more built-in tools (2026-11-04, third batch), offline tests against fake vendor APIs in
  `test_platform_ops_tools.py`: dbt Cloud (Administrative API v2: jobs, runs, one run's steps with the
  failed step's log, trigger), Fivetran (`/v1/connections`: list with broken / failing first, one
  connection's state, tasks and warnings), Airbyte (Airbyte API: connections, a connection's jobs),
  Prefect (REST: flow runs filtered by state, one run with its state message and last logs),
  Kubernetes (API server with a bearer token, read-only: pods unready first, warning events, pod logs
  incl. the previous instance, deployments), GitHub Actions (runs, one run's jobs, failed steps and
  log tail) and Service Status (public Statuspage pages, no key; known providers checked live —
  Databricks and Datadog removed, they don't serve Statuspage JSON). Agents: CI Build Doctor can use
  GitHub Actions; Incident Responder gains Service Status and Kubernetes; new ELT Pipeline Doctor and
  Kubernetes Troubleshooter
- 9 more built-in tools (2026-11-04, second batch), offline tests in `test_social_ops_tools.py`:
  - Communication: Bluesky post (app password; link facets with UTF-8 byte offsets), Mastodon
    post (any instance, visibility dropdown)
  - APIs & Integrations: Jenkins (last build, console tail, start a build, list jobs; folder
    paths), SSL certificate check (validates the chain and host name, days to expiry)
  - Research & Knowledge: World Bank indicators (short names like `gdp` / `inflation`, several
    countries, year ranges), Wikidata (search, item by Q-id with the `mul` label fallback, SPARQL)
  - Business Apps: Freshdesk (list / search / read / create tickets)
  - Code & Compute: JWT decoder (offline; verifies HS256/384/512 with `hmac_secret`, flags
    `alg: none`). Data & Files: CSV SQL (SQLite in memory; an authorizer allows only reads, so
    ATTACH / PRAGMA / writes / `load_extension` are refused, and a progress handler stops runaway
    queries)
- Databricks and Snowflake REST tools (2026-11-03), offline tests against fake APIs
  (`test_databricks_tools.py`, `test_snowflake_tools.py`):
  - 12 Databricks tools on a shared `tools/data/_databricks.py`: list / run / cancel jobs,
    clusters list / control, SQL warehouses, Unity Catalog browser, volume files, model serving,
    vector search, Genie (polls the conversation), Lakeflow / DLT pipelines
  - Fix for 9 existing Databricks tools: the model's argument (job_id, cluster_id, path…) never
    reached them, because they only read node config. They now take the argument first, and
    those keys are no longer required in config. `databricks_sql` also accepts an `https://` host
  - 12 Snowflake tools on `tools/data/_snowflake.py`: SQL API with polling for statements still
    running, PAT / OAuth / key-pair JWT tokens, no driver needed. SQL (REST), warehouses and
    warehouse control, catalog browser, query history, tasks, pipe status, COPY history, stage
    files, Cortex Complete / Search / Analyst
  - Identifiers are validated before they go into SQL or URLs; only read statements run,
    including Analyst's generated SQL

- Tool contract test (`tests/tooling/test_tool_contract.py`, offline): every built-in tool returns a
  string and never raises on hostile input; a missing required key is named and refused before
  any network call (2026-10-28)
- Built-in tool registry (C8, merged 2026-10-26): 98 tool specs in `backend/tools/`, one module
  per tool; `routers/tools.py` 2,926 → 58 lines; catalog, UI dropdowns and required keys are
  generated from the specs and served by `/api/tools` (generated catalog verified identical to
  the old one)
- Toolkit node (user-built container that flattens sub-tools)
- MCP node: built-in servers (filesystem, GitHub, Slack, …), split by category; custom MCP
  servers (`custom_mcp.py`)
- Remote MCP client (2026-10-30): custom servers with transport `http` speak Streamable HTTP
  (`tools/mcp/_http.py`: session id, protocol-version header, JSON or SSE replies, `tools/list`
  paging), falling back to legacy HTTP+SSE when the POST is refused; `sse` is legacy only. URLs
  pass the outbound SSRF guard, headers may hold `secret://` refs, a 401 raises
  `MCPAuthRequired`. Custom stdio servers now use the shared runner (`_stdio.py`), and
  `/api/custom-mcp/test` needs `mcp:write`. `tests/mcp_servers/test_mcp_remote.py` runs a real local server
  and our own `/v1/mcp`
- MCP OAuth (2026-10-30): remote custom servers sign in with OAuth 2.1 (`services/mcp_oauth.py`,
  MCP authorization spec 2025-06-18): discovery from the 401's `resource_metadata` (RFC 9728) →
  authorization-server metadata (RFC 8414 / OIDC), dynamic client registration (RFC 7591) or the
  user's own client id, PKCE S256, `resource` indicator (RFC 8707). Public callback
  `/api/custom-mcp/oauth/callback` matches a single-use 10-minute `state`. Tokens are sealed in
  `custom_mcp_servers.oauth` (migration 0021, included in key rotation), never returned
  (`oauth_status` instead), refreshed before expiry and once on a 401, and dropped when the URL
  changes. "Connect with OAuth" in the MCP modal polls for completion. `PIPESETS_PUBLIC_URL` sets
  the redirect base behind a proxy. `tests/mcp_servers/test_mcp_oauth.py` (fake AS over real HTTP)
- Custom tools (UI): upload / write Python tools
- Custom tools run in the sandbox (2026-10-27): saved, ad-hoc and in-pipeline custom tools go
  through `services/sandbox.run_tool` in a separate process — local subprocess by default
  (scrubbed env, throwaway cwd, timeout) or podman/docker with `CUSTOM_TOOL_SANDBOX=container|auto`
  / `SANDBOX_REQUIRE_ISOLATION=1`
- ACL on every custom-tool route; `/execute-code` needs `tools:execute`, `/install` needs
  `tools:install` and is refused when isolation is required or in the frozen build
- Python sandbox (`services/sandbox.py`): podman/docker with local fallback (pulled forward
  from post-MVP)
- Docling integration as a custom tool template (`backend/data/custom_tool_templates/docling_parser_tool.py`,
  upload under Tools → Build your own); since 2026-11-02 Docling is also a built-in loader and
  OCR engine (guide 12, Document extraction)
- Translation tool (2026-10-30): `backend/tools/utilities/translation.py` — `translation` (🌐): text → translation via DeepL (API key) or the free LibreTranslate; source / target language selects, model gets typed arguments (`text`, `source`, `target`)
- Google Calendar tool (2026-10-30): `backend/tools/productivity/google_calendar.py` — `google_calendar`: list upcoming events in a window, create and delete events via the Google Calendar API; OAuth access token in the node config with refresh (client id / secret)
- SaaS tools (2026-10-30), typed (`action` + the main text), destinations (channel, list, team,
  base / table) config-only: `slack` (bot token: post / thread reply, channel or thread history),
  `airtable` (search records by field formula or across fields, create), `trello` (search, list
  cards, create), `hubspot` (search contacts / companies / deals, create), `stripe` (read-only:
  customers, payments, invoices, subscriptions, balance), `linear` (GraphQL: search, read with
  comments, create). `tests/tooling/test_saas_tools.py` against fakes of each documented API
- Microsoft 365 tools (2026-10-30), all read/side-effect actions through Microsoft Graph with a
  delegated OAuth access token (+ refresh flow, shared `productivity/_ms_auth.py`):
  `outlook_mail` (search / list messages, read one — HTML un-tagged, send plain text to
  recipients), `outlook_calendar` (list a window via /me/calendarview in UTC, create with
  attendees / location, delete), `onedrive` (free-text search, recent items, read a text file by
  id or OneDrive path — folders list their children; .xlsx hands off to Excel), `teams_messages`
  (teams → channels, channel posts and thread replies, oldest first; posting stays with
  `teams_webhook`), `excel_workbook` (sheet names in order, one sheet's used range as a markdown
  table, values only — drive item id or path in config). `tests/tooling/test_microsoft_tools.py` against
  a fake Graph, including the 401 → refresh_token → retry flow
- Data tools (2026-10-31): `bigquery_reader` (BigQuery REST v2: one read SELECT/EXPLAIN/SHOW/WITH
  via /projects/{p}/queries, Standard SQL, polls a still-running job via its jobReference,
  Google OAuth access token + refresh shared with `_google_auth`), `gcs_reader`
  (GCS JSON API: list under a prefix with delimiter folders, read `alt=media`; same auth),
  `elasticsearch_search` (httpx REST: free text / Lucene as `query_string` or a JSON DSL body,
  ApiKey or basic auth, index + base_url in config), `azure_blob_reader` (Blob REST with a read
  SAS token: folder-style list over the XML List Blobs answer — namespace-agnostic parse — and
  blob reads), `snowflake_reader` (optional `snowflake-connector-python`, account/user/password
  + warehouse/database/schema/role, run in a thread, read-only statement guard),
  `mongodb_reader` (optional `pymongo`: JSON filter for find with $sort/$skip/$limit/$project,
  a JSON array runs as aggregate; uri/database/collection in config). Optional drivers give a
  `pip install …` message; requirements.txt gained commented `snowflake-connector-python` /
  `pymongo` lines. `tests/tooling/test_data_tools.py` against fakes of each API (incl. both Google
  refresh flows) + the SDK-offline paths. (also: `_google_auth.http_error` now strips an
  already-bracketed label — `[[Gmail]] ...` becomes `[Gmail] ...` in the existing Google tools)
- Built-in MCP servers (2026-10-31): `mcp_playwright` (`@playwright/mcp`, Web & Browser — browser
  select, headless flag appended as --browser/--headless, bare input becomes the navigate URL),
  `mcp_stripe` (`@stripe/mcp`, Developer Tools — STRIPE_SECRET_KEY env (secret:// ref), the bare
  input is a doc search; the create_* tools come via stored tools), `mcp_kubernetes`
  (mcp-server-kubernetes, Developer Tools — KUBECONFIG from the config, default tool
  list_namespaces). All three are plain `prepare()` + `stdio_server` modules like the existing
  servers. `tests/mcp_servers/test_mcp_builtin_servers.py` covers config → launch arg / env mapping and
  catalog registration. Postgres MCP already existed (`mcp_postgres`)

## Memory, Cache, Middleware

- Memory node (short-term): sliding window, summarize, last-k; SQLite sessions
- Cache node: prompt / model / strict scopes; SQLite TTL cache
- Middleware node + config panel (`routers/middleware.py`): content moderation + PII, cost
  tracker, rate limiter, prompt injection
- Middleware enforced on `run.py`, the streaming path (`services/llm_runner.run_stream`:
  pre-flight before the LLM, response guard retracts streamed text on block) and Master / Child
  agents
- Guardrails and an LLM guardrail judge (`services/guardrail_judge.py`)
- Budgets with block / warn (`budgets.py`, `services/budget.py`)

## Retrieval (RAG)

- Nodes: Document Loader, Text Splitter, Embedding, Vector Store, Retriever, Reranker, Knowledge
  Base (`knowledge_base.py`)
- Document loader registry: `backend/loaders/` — 22 real loaders, the rest shown as "Soon"
  (`_planned.py`); ingest by upload, file, path, URL and database (Postgres / MySQL / SQLite)
- Recursive / token / markdown splitting
- Embeddings: OpenAI, Cohere, Google, Mistral, Voyage, Nomic, Ollama, Bedrock, local
  sentence-transformers
- Vector stores: `local` (SQLite `rag_chunks`) and `pgvector` (`services/vector_store.py`)
- Retrieval modes: similarity, MMR, BM25 hybrid; score threshold and rerank
- Source citations: `rag_sources` SSE event shown as "Retrieved Sources" in the Prompt Runner

## Document Extraction (plan.md P1)

Shipped 2026-11-02. Tested with stubbed models and a stubbed Docling converter only — **not yet
run against a real model or real scanned documents** (see plan.md P1).

- **Docling loader** (`loaders/files/docling.py`, shared code in `loaders/_docling.py`): scanned PDFs,
  images, DOCX and PPTX with OCR and tables, one document per page with its page number
- **OCR engines** (`loaders/_ocr.py`), picked with `ocr_engine`: `auto` (first installed of
  OCRmyPDF → Tesseract → Docling), `tesseract`, `ocrmypdf`, `docling`, `vision` (a vision model through
  the LLM gateway, one call per page, never picked by `auto`) or `off`. Settings: `ocr_language`,
  `ocr_dpi`, `ocr_max_pages` (200; vision 50), `ocr_provider` / `ocr_model` for vision
- **PDF loader OCR fallback**: only pages without a text layer are OCR'd (tagged `parser: ocr:<engine>`);
  pages OCR couldn't read are listed in `pages_without_text` with `ocr_error`, not dropped silently.
  Old `ocr_fallback: false` still turns it off. **Tesseract verified** on a generated scan (PDF and PNG)
- **Image (OCR) loader** (`loaders/files/image.py`, was "Soon"): PNG, JPG, TIFF, BMP, WebP; Directory
  and S3 pick them up
- Doc Loader node: "Scanned pages (OCR)" card (engine, language, vision provider / model) for the PDF,
  Image, Directory, S3 and Email loaders; Structured Extract has the same setting and uses its own
  model for vision OCR. Backend Docker image installs `tesseract-ocr`
- **Email loader** (`loaders/files/email.py`, was "Soon"): `.eml` (stdlib) and `.msg` (needs the
  optional `extract-msg`); attachments are parsed by their file loader and tagged with the message.
  Directory and S3 now pick up `.eml` / `.msg`
- **Yardi Report Export loader** (`loaders/files/yardi_export.py`): rent roll / lease expiration
  exports (CSV or XLSX); finds the header under the report title, carries the property from group
  headings, skips totals and repeated headers, and copies known columns to standard metadata
  (`property`, `unit`, `tenant`, `lease_from`, `lease_to`, `monthly_rent`, …). Built from common
  Yardi layouts, not yet checked against a real export
- **Structured Extract tool** (`tools/data/structured_extract.py`, `services/extraction.py`): fields
  listed as `name: description` lines or JSON; the model returns value, page, exact quote and
  confidence per field; each quote is checked against the cited page (moved to the right page if
  found elsewhere; confidence capped at 0.3 when not found)
- **Review queue** (`services/extraction_reviews.py`, `routers/reviews.py`, migration 0026,
  Evaluate → 🧾 Review): every extracted field filed as pending with its citation; approve, correct
  (typed value) or reject; decisions audited (`review.decide`, `review.export`); reviewed documents
  export to an eval dataset (input = document path, expected = reviewed fields as JSON)
- **Long documents** (2026-11-02, `services/extraction.py`): over `max_chars` a document is split into
  parts at page boundaries (preferring article / section / exhibit starts; an oversized page is cut
  at paragraphs and keeps its number), up to 20 parts, 3 calls at once. Results merged per field:
  verified quote, then confidence, then earlier page; other values kept as `alternatives`, and a
  verified disagreement sets `conflict` and caps confidence at 0.5. Was: refused over `max_chars`
- **Review queue, faster** (2026-11-02, migration 0027): cited pages' text saved at filing
  (`extraction_review_pages`) and shown with the quote highlighted (📄 Page, also for alternatives);
  "Use this value" on an alternative; bulk approve verified, non-conflicting fields at or above a
  threshold (preview count, `bulk` flag, audited `review.bulk_approve`); accuracy report per model,
  prompt version (`prompt_version` hash of prompt + fields + instructions) and field, from human
  decisions only. Tested with a stubbed model, on SQLite and Postgres 16
- **Docling on the Intel Mac dev venv** (2026-11-02): `numpy<2` / `transformers<5` markers for macOS
  x86_64 (torch stops at 2.2.2 there), pypdfium2 PDF backend there because docling-parse's macOS
  x86_64 build segfaults on scanned PDFs. **Verified for real** on generated text and scanned PDFs
  and a PNG (Docling text, Docling OCR, Tesseract)

## Built-in MCP servers (2026-11-02)

- 14 new: Tavily, Exa, Perplexity, Context7, Time, AWS Documentation, Supabase (read-only default),
  Qdrant, Chroma, Neo4j (read-only default), Pinecone, HubSpot, Airtable, Confluence (mcp-atlassian,
  read-only default). Credentials are top-level secret-style keys, so the generic panel shows a
  secret picker; `required` keys are named before launch (`stdio_server(..., required)`)
- Fixed: Jira (`@sooperset/mcp-atlassian` never existed on npm → `uvx mcp-atlassian`), OpenAPI
  (`@modelcontextprotocol/server-openapi` never existed → `@ivotoby/openapi-mcp-server`, dynamic mode)
- Replaced deprecated or unvetted packages: Brave (Brave's own), AWS KB (awslabs), Redis (Redis's
  own; URL split into env vars so the password isn't on the command line), GitLab (zereight),
  Trello (delorenj), Docker / Podman (mcp-server-docker; Podman's default no longer hard-codes a
  developer's home path), GitHub and Linear (vendors' remote servers with a token header,
  `remote_server()` in `tools/mcp/_http.py`, read-only option)
- Every stdio package pinned; Puppeteer hidden (Playwright covers it, old pipelines still run);
  custom MCP templates pinned and updated the same way (GitHub / Linear templates fill URL + header)
- Checked against package source and docs, not launched (see plan.md C5)
- 12 more (2026-11-02), every package pinned and checked against source / docs:
  - Databases & Data: MongoDB (`mongodb-mcp-server`, connection string kept in
    `MDB_MCP_CONNECTION_STRING`), ClickHouse (`mcp-clickhouse`), MySQL
    (`@benborla29/mcp-server-mysql`), Snowflake (`mcp-server-snowflake`), BigQuery
    (`@ergut/mcp-bigquery-server`), Elasticsearch (`@elastic/mcp-server-elasticsearch`).
    Read-only defaults where the server supports it; credentials go in env vars, not argv
  - DevOps & Observability (new catalog category): Grafana (`mcp-grafana`, read-only via
    `--disable-write`), Prometheus (`prometheus-mcp-server`), Datadog (managed remote server,
    `DD-API-KEY` / `DD-APPLICATION-KEY` headers, regional site dropdown)
  - Productivity: Salesforce (`@salesforce/mcp`; the org must already be authorized with
    `sf org login web`), Figma (`figma-developer-mcp`, file URL / key and node id parsed from the
    input), Discord (`discord-mcp`)
  - MongoDB is now a plain built-in server with a secret-style config key rather than a separate
    Connection node; `CATEGORY_ORDER["mcp_servers"]` lists DevOps & Observability between
    Developer Tools and Web & Browser
- 10 more (2026-11-02), every package pinned and checked against source / docs:
  - Databases & Data: Neon (managed remote server, API key header), MotherDuck / DuckDB
    (`mcp-server-motherduck`; token in `MOTHERDUCK_TOKEN`, `--db-path` + read-only default),
    DynamoDB (`awslabs.dynamodb-mcp-server`; AWS Labs data-modeling server, region / profile /
    keys in standard AWS env vars)
  - Developer Tools: Netlify (`@netlify/mcp`; PAT in `NETLIFY_PERSONAL_ACCESS_TOKEN`, default
    tool lists projects), Postman (managed remote server, minimal endpoint, API key header,
    US / EU region dropdown)
  - DevOps & Observability: PostHog (managed remote server; URL pins `mode=tools` so each tool
    is exposed, default `execute-sql`, US / EU region dropdown)
  - Web & Browser: Apify (`@apify/actors-mcp-server`; `APIFY_TOKEN`), Browserbase
    (`@browserbasehq/mcp`; API key + project id, Gemini key for Stagehand)
  - Productivity: Todoist (`@doist/todoist-mcp`; `TODOIST_API_KEY`, default tool searches tasks)
  - AI & Memory: Hugging Face (managed remote server; `HF_TOKEN`, model / dataset / Space search)
  - Added regression coverage for launch args, env vars, default tools / arguments, remote
    headers and regions, missing required keys, and catalog registration
- 10 more (2026-11-03), every package pinned and checked against source / docs:
  - Databases & Data: Redshift (`awslabs.redshift-mcp-server`; AWS region / profile / keys in
    standard env vars, read-only unless switched, default `list_clusters`), DBHub
    (`@bytebase/dbhub`; one DSN for PostgreSQL / MySQL / MariaDB / SQL Server / Oracle / SQLite,
    connection string in `DSN`, default `execute_sql`)
  - Developer Tools: Cloudflare (managed remote server, code-mode `docs` / `search` / `execute`
    tools plus `whoami`; API token header), Render (managed remote server, API key header, default
    `list_services`)
  - DevOps & Observability: New Relic (managed remote server, user API key in the `api-key`
    header, US / EU / JP region dropdown, default lists accounts or runs NRQL when an account id
    is configured), Honeycomb (managed remote server, `Bearer <KEY_ID>:<SECRET_KEY>`, US / EU
    region dropdown, default `get_workspace_context`)
  - Productivity: monday.com (hosted Platform MCP server, personal API token as a Bearer token;
    input searches boards, no input returns the user context)
  - Web & Browser: Jina AI (managed remote server; search tools, `read_url` for URL input, `primer`
    when empty), Hyperbrowser (`hyperbrowser-mcp`; `HYPERBROWSER_API_KEY` / `HB_API_KEY`, default
    scrapes the input URL to markdown)
  - AI & Memory: E2B (`@e2b/mcp-server`; `E2B_API_KEY`, single `run_code` sandbox tool)
  - Read-only defaults where the server supports it (Redshift). New Relic API keys cannot use its
    OAuth-only tools; Cloudflare tokens with Client IP Address Filtering are unsupported; DBHub
    needs Node.js 22.5 or newer and configures read-only in `dbhub.toml`, not a flag
- Databricks and Snowflake (2026-11-03), packages checked against their source; not run against a
  real workspace or account:
  - Databricks (`databricks-mcp-server` 0.4.4): ~40 tools, host / token / warehouse in
    `DATABRICKS_*` env vars. Input runs as `execute_sql`; with no input it lists clusters
  - Databricks Managed (remote): the workspace's own `/api/2.0/mcp/{sql | genie/<space> |
    functions/<catalog>/<schema> | vector-search/<catalog>/<schema>}`, bearer token. It has no
    default tool: the user lists the tools and picks one
  - Snowflake (official, `snowflake-labs-mcp` 1.4.2): the service-config file is generated from
    the node into the temp dir (no secrets in it; passed in `SERVICE_CONFIG_FILE`). Read-only by
    default (SELECT / DESCRIBE only, object manager off); optional Cortex Search service and
    Analyst semantic model
  - Snowflake Managed (remote): `/api/v2/databases/<db>/schemas/<schema>/mcp-servers/<name>`,
    bearer token. No default tool, as with Databricks Managed
- 8 more (2026-11-04), every package pinned; tool names checked against each package's source or
  a live `tools/list` (DeepWiki's tools are `ask_wiki_question` / `read_wiki_*`):
  - Developer Tools: Microsoft Learn (hosted remote server, no key; URL input reads the page, else
    `microsoft_docs_search`), DeepWiki (hosted remote server, no key; `owner/repo: question` asks,
    `owner/repo` alone lists the wiki's topics), Shopify Dev (`@shopify/dev-mcp`, no key; docs
    search and GraphQL / Liquid / extension validation)
  - DevOps & Observability: CircleCI (`@circleci/mcp-server-circleci`; `CIRCLECI_TOKEN`, optional
    `CIRCLECI_BASE_URL`, telemetry off, default `list_followed_projects`)
  - Web & Browser: Mapbox (`@mapbox/mcp-server`; `MAPBOX_ACCESS_TOKEN`, input geocodes),
    DuckDuckGo (`duckduckgo-mcp-server`, no key; URL input → `fetch_content`, safe-search
    dropdown), arXiv (`arxiv-mcp-server`, no key; an arXiv id reads the abstract, else search;
    optional `--storage-path`)
  - AI & Memory: ElevenLabs (`elevenlabs-mcp`; audio goes to `output_dir`, default a temp folder,
    not the server's `~/Desktop`; no input lists voices)
  - Not added: AWS API MCP server (upstream says it's at end of development), PayPal (takes only
    a hand-made, short-lived access token)
- 6 more (2026-11-04, second batch), checked the same way:
  - Developer Tools: AWS Knowledge (hosted remote server, no key; docs search, URL input reads the
    page, no input lists regions), Azure DevOps (`@azure-devops/mcp` 2.10.0, the last release that
    isn't a nightly; `--authentication pat` with the PAT base64-encoded in `PERSONAL_ACCESS_TOKEN`,
    organization as the only argument, a tool-group dropdown for `--domains`)
  - Web & Browser: Kagi (`kagimcp`; `KAGI_API_KEY`, URL input → `kagi_extract`), Wikipedia
    (`wikipedia-mcp`, no key; `--language` dropdown)
  - Databases & Data: Upstash (`@upstash/mcp-server`; email / API key in `UPSTASH_*` env vars,
    telemetry off, default lists Redis databases)
  - AI & Memory: Chart (`@antv/mcp-server-chart`, no key; a JSON list input becomes the chosen
    chart's `data`). It renders on AntV's public service (antv-studio.alipay.com); the description
    says so
  - Not added: MarkItDown (its convert tool reads `file:` URIs, so the model could read files on
    the host), Semgrep and Globalping remote servers (OAuth only), postgres-mcp (no release since
    2025-05)
- 4 more MCP servers (2026-11-04, third batch), each checked against its downloaded source, not launched
  (`tests/mcp_servers/test_mcp_ops_servers.py`):
  - DevOps & Observability: Argo CD (`argocd-mcp` 0.9.0, argoproj-labs; `ARGOCD_BASE_URL` /
    `ARGOCD_API_TOKEN`, read-only by default via `MCP_READ_ONLY`, input searches applications),
    PagerDuty (`pagerduty-mcp` 1.1.0, official; `PAGERDUTY_USER_API_KEY`, optional
    `PAGERDUTY_API_HOST` for EU, write tools only with `--enable-write-tools`, default lists open
    incidents; needs Python 3.12, so `uvx --python 3.12`), CloudWatch
    (`awslabs.cloudwatch-mcp-server` 0.3.1; read-only, standard AWS env vars, default
    `get_active_alarms`)
  - Databases & Data: dbt (`dbt-mcp` 2.10.1, dbt Labs; `DBT_HOST` / `DBT_TOKEN` / `DBT_ACCOUNT_ID` /
    `DBT_PROD_ENV_ID`, local CLI / LSP / codegen toolsets off, read-only by default via
    `DISABLE_TOOLS=trigger_job_run,cancel_job_run,retry_job_run`, telemetry off)
  - Not added: Dynatrace (npm package marked "no longer supported"), Pulumi (`@pulumi/mcp-server`
    last released 2025-09), Azure (`@azure/mcp` ships its tools in a .NET binary, so names can't be
    checked from the package, and it authenticates through Azure Identity / `az login`)
- Tools & MCP packages (2026-11-03): Settings → Builder → Tools & MCP packages. The builder sidebar
  lists only installed built-in tools and MCP servers:
  - What counts as installed (`services/tool_packages.py`, table `tool_packages`, migration 0028),
    in order: the workspace's own choice, then a starter set (`DEFAULTS`), then any tool a
    workspace pipeline already uses
  - API: `GET /api/tools` marks each package `installed`. `GET`, `PUT` and `DELETE`
    `/api/tools/packages` list, install / uninstall and reset (`tools:write`, audited as
    `tool_package.update` / `tool_package.reset`)
  - Uninstalling only hides a package; pipelines that use it still run. Frameworks, custom tools
    and custom MCP servers are always shown
  - UI: the panel has Tools / MCP tabs, an install-state filter, search, a category filter, and
    bulk install of the packages matching the filters, collapsible categories. The sidebar's Tools and MCP sections link to it
    ("📦 Browse N more…")
  - Tests: `tests/tooling/test_tool_packages.py` and `ToolPackagesPanel.test.tsx`
- Tool hot reload (2026-11-04): adding or editing a tool / MCP module no longer needs a backend
  restart. `tools.reload()` re-scans the package by file mtime and imports new and edited modules;
  when a helper (`_x.py`, `base.py`) changes it re-imports every module, helpers first. Deleted
  modules drop out. The new tables are swapped in all at once, so runs in progress keep their code
  - Broken files: a syntax error is caught by compiling before the live module is touched. A
    module that fails keeps its last working version (a new one is skipped) and is retried after
    its next edit. Duplicate ids are reported and the first one is kept
  - Triggers: `POST /api/tools/reload` (server admins, audited as `tool_registry.reload`), the
    **Reload from disk** button in Tools & MCP packages (`can_reload` on the listing), and
    `TOOLS_AUTO_RELOAD=1` (on in `start.sh`) checks at most once a second on `GET /api/tools` and
    on each tool run. It reloads only its own process; the desktop build skips it
  - Still needs a restart: `tools/__init__.py` itself, new pip dependencies
  - Tests: `tests/tooling/test_tool_reload.py` (temp modules on the package path) and
    `ToolPackagesPanel.test.tsx`

## Multi-Agent & Workflow

- Master / Child Agent, Start, Stop, Gateway, Human Gate nodes (`agents.py`,
  `services/pipeline_runner.py`, `services/workflow_engine.py`)
- External agents (`services/external_agent.py`)
- Human Gate pauses Master Agent runs: approve / edit / reject card in the runner
- Checkpointing for Master Agent runs (`services/checkpoint.py`): step memoization in
  `agent_runs.checkpoint`, resume via `resume_from` / `POST /v1/runs/{id}/resume`; startup marks
  cut-off runs `interrupted`. LLM-node runs too since C3 (see Platform & Deployment)

## Operations

- Traces UI, Global Logs panel, run log list; `routers/traces.py` (list, per-run, cost summary,
  clear); optional Langfuse export (`services/langfuse_export.py`)
- Evals (Lab view, `eval.py`): datasets, cases, runs, generate from pipeline / traces, Excel
  import / export
- Synthetic Data node (2026-11-01; `SyntheticDataNode.tsx`, `SyntheticDataConfigPanel.tsx`):
  dataset name, row count, output format, locale, seed, edge cases, strict schema; schema as manual
  columns (string, integer, number, boolean, date, datetime, email, uuid, category, with min / max)
  or a JSON Schema; upload a CSV sample to infer columns (`utils/syntheticCsv.ts`). Preview up to
  50 rows from the connected LLM via `POST /api/eval/synthetic-preview` (mock provider returns
  placeholder rows). In the Prompt Runner, connected synthetic datasets are picked by matching the
  prompt against dataset / column names (strict routing = best one only)
- Synthetic data, full dataset (2026-11-01; card 5 of the node panel): **Generate All N Rows**
  (`POST /api/eval/synthetic-generate`, up to 1,000 rows) in batches of 25, 4 at a time, streamed
  as NDJSON progress; with strict schema, rows missing a required column are dropped, rows repeating
  a unique column are always dropped, and up to 3 rounds make up the shortfall; a failed batch is
  skipped and reported. Mock provider rows are typed, within min / max / category values and
  repeatable per seed. **Download** in the node's format (JSON / JSONL / CSV,
  `utils/syntheticExport.ts`). **Save as eval cases** (`POST /api/eval/synthetic-save`) into a new
  or existing dataset: pick the prompt column (or the whole row as JSON) and an expected-output
  column (guessed from names like question / answer); cases are `source=ai`, tag `synthetic`,
  duplicates skipped. Preview or CSV-sample rows can be downloaded / saved too.
  Tests: `tests/evals/test_eval_synthetic.py` (12), `SyntheticDataConfigPanel.test.tsx`,
  `syntheticExport.test.ts`. Not tested against a real model yet
- Optimize models (2026-11-01; Evaluate → ⚡ Optimize, `services/model_routing.py`,
  `eval/ModelOptimizer.tsx`): cheapest / fastest model per LLM node (LLM node, Master Agent, LLM
  children, in nested pipelines too) that keeps the eval pass rate within a tolerance. Baseline →
  single swaps (optional screen on the first N cases) → greedy combination, each measured end to
  end; config budget. Run-time overrides (`pipeline_runner.model_overrides`) never touch saved flows.
  Job `eval.optimize_models`, table `model_optimizations` (migration 0022), browser keys sealed and
  vault refs kept as refs. Stops when the baseline errors or passes 0%. API
  `POST /api/eval/optimize-models[/slots]`, `GET /api/eval/optimizations[/{id}]`,
  `POST /api/eval/optimizations/{id}/apply` (writes the draft). UI: live per-case progress, configs
  table, apply, history with re-run and edit & re-run. `llm.metered()` prices whole runs, which also
  fixed pipeline evals recording $0. Tests: `tests/evals/test_model_routing.py` (16),
  `ModelOptimizer.test.tsx` (6). Verified against OpenAI on a 10-case dataset (gpt-4o vs
  gpt-5.4-mini / -nano / gpt-4o-mini)
- Eval-gated publishing (`services/publish_gate.py`): dataset, scorer, threshold,
  no-regression, block / warn, dry-run check; 409 on failure unless forced; outcome stored on
  `app_versions`
- Scheduled runs (`services/scheduler.py`): cron, auto-pause after N failures; Schedules panel
- Webhook triggers (`POST /v1/hooks/{token}`): hashed URL tokens, optional HMAC signing, prompt
  templates from the body; create, test, rotate URL, history
- Run alerts (`services/notifier.py`): Slack / JSON webhook on run failed, Human Gate pause,
  schedule auto-pause

## Security & Access

- IAM / RBAC: tenants, users, groups, projects, ACLs (`iam.py`, `services/acl.py`); IAM Admin
  Panel (pulled forward from post-MVP)
- Secrets vault (`services/secret_store.py`, migrations 0005–0007): Fernet encryption under
  `PIPESETS_MASTER_KEY` (multi-key, rotation with `python manage.py rotate-secrets`);
  write-only over the API (name + last 4 chars); `secret://<id>` refs resolved server-side just
  before use, so keys never live in flows, exports or the browser; tenant / project scoping;
  per-project default provider keys; `llm` vs `tool` kinds enforced on decrypt; secrets moved to
  the Settings page
- Connection credentials sealed inline as `enc://<ciphertext>` (`routers/connections.py`)
- A1 secrets at rest finished (2026-10-28): webhook signing secrets and notification channel URLs
  stored sealed; saving a flow with a typed credential is refused (422 naming node + field) — only
  `secret://` refs or sealed values; migration `0009_seal_credentials` seals existing rows and
  flows (idempotent); `rotate-secrets` also covers flows, webhooks and channels; log-record
  factory redacts key patterns from every logger incl. tracebacks and uvicorn access lines
  (`services/log_redaction.py`); master key from env, AWS KMS (`PIPESETS_MASTER_KEY_KMS`,
  `manage.py kms-wrap-key`) or Vault KV (`services/master_key.py`). Checks in
  `tests/security/test_secrets.py`
- CORS origins from `CORS_ORIGINS` (default: the Vite dev server), credentialed CORS off;
  optional `ALLOWED_HOSTS` Host allow-list against DNS rebinding (2026-10-27)
- Security headers on every backend response (2026-10-28, `services/security_headers.py`, plain
  ASGI so SSE is untouched): CSP `default-src 'none'` (relaxed only for `/docs` / `/redoc`),
  X-Frame-Options DENY, nosniff, Referrer-Policy, COOP, Permissions-Policy; HSTS only on HTTPS
  (`X-Forwarded-Proto` honoured; `HSTS_ENABLED`, `HSTS_MAX_AGE`)
- MCP stdio servers (built-in and custom) start with an allow-listed environment plus their own
  configured vars (`services/child_env.py`) — no master key, provider keys or `DATABASE_URL`
  (2026-10-28). Checks in `tests/security/test_security_hardening.py`
- Backend `.dockerignore` keeps `.secrets_master_key`, `.env*`, DBs and the PyInstaller `build/` /
  `dist/` out of images built from a dev checkout (2026-10-28)
- Audit log of admin actions (2026-10-28): `audit_log` table (migration `0010_audit_log`), written by
  `services/audit.AuditMiddleware` for 58 routes — API keys, secrets, IAM, publish / publish gates,
  model backends, webhooks, channels, connections, custom tools / MCP servers, marketplace,
  budgets, middleware, schedules, app deletes. Records actor, tenant, project, action, target id,
  outcome (`success`, or `denied` for 403), status, path, client IP; never request bodies.
  `GET /api/audit-log` (`audit:read`, newest first, filters, paging); no route edits or deletes
  entries. `tests/security/test_audit_log.py` fails when a new mutating admin route is neither audited nor
  listed as exempt
- Custom tool `requirements` (2026-10-28, migration `0011_custom_tool_requirements`): pip specs saved
  with the tool and installed into its own sandbox environment on first run — a cached image
  `FROM` the base image (container, exec-form `RUN`) or a cached venv under `<data dir>/tool-envs/`
  (local), keyed by a hash of the specs; failed installs are cleaned up. Specs are validated
  (`packaging`): no URLs, paths or pip options, at most 30. `/api/custom-tools/install` (pip into the
  backend) removed; the tool editor's Packages tab saves requirements instead. Bundled marketplace
  tools carry them. Live-checked locally (venv install 3.8 s, cached 0.1 s); container build path
  tested with a faked engine only. `tests/tooling/test_custom_tool_requirements.py`
- Sandbox runner service (2026-10-28): `backend/sandbox_runner.py` + `Dockerfile.sandbox` (podman image,
  stdlib HTTP server, reuses `services/sandbox.py`); the backend's `remote` sandbox backend
  (`SANDBOX_URL`, `SANDBOX_TOKEN`) sends code there, `auto` / `container` use it when set, custom tools
  default to it, and the runner never forwards or runs code in its own process. Caps timeout
  (300 s) and memory (4 GB). In compose (own network, no published port, `/dev/fuse`, not privileged)
  and k8s (`deploy/k8s/sandbox.yaml`, privileged pod + backend-only NetworkPolicy);
  `SANDBOX_REQUIRE_ISOLATION=1` by default in both. CI builds the image.
  `tests/tooling/test_sandbox_runner.py` (real runner on a local port, stand-in engine)
- Audit log page and policy (2026-10-29): **Settings → Audit log** (`ops/AuditLogPanel.tsx`) — filter
  by action group / action, user, outcome and date range, page back, export CSV or JSON Lines with the
  same filters. Backend: `outcome` / `since` / `until` filters; `GET /api/audit-log/export` streams every
  match (keyset paging on created_at + id, spreadsheet formulas neutralised) and is itself logged as
  `audit.export`; `GET /api/audit-log/policy`. Retention: `AUDIT_RETENTION_DAYS` (default 365, 0 = keep),
  operator-only, purged at startup and daily with an `audit.purge` marker per tenant; migration
  `0012_audit_log_time_index`
- Adversarial suite (2026-10-29): `tests/security/test_adversarial.py` + corpus in `tests/security/adversarial/*.yaml`
  (injection, moderation, PII — attacks and look-alikes that must pass), marked `adversarial`, own
  CI step. First run found 39 bypasses; all fixed in `routers/middleware.py`: pattern guards also
  match a normalized copy (NFKC, zero-width / bidi / soft hyphen removed, accents stripped,
  Cyrillic / Greek look-alikes mapped); wider injection and moderation wording; PII by kind (SSN
  with spaces, any card number with spaces / dashes by Luhn, phone numbers), never echoing the
  value; traces of blocked prompts keep `[PII:kind]` instead. Rate limiter: windows scoped to the
  tenant / project (was one global bucket for runs without a session), new `per` setting —
  session (default) / caller (API key or user; `/v1` runs carry `RunScope.caller`) / app — so
  rotating session ids or keys can't escape it; window table capped at 10k keys
- Adversarial suite, second part (2026-10-29): a master-agent run no longer writes its goal before
  the guardrail check — the row is claimed with an empty goal and the goal stored once it passes,
  `[PII:kind]`-redacted if blocked, so a blocked goal never reaches the DB (nor Postgres dead tuples
  / the SQLite WAL). Judge cases (`tests/security/adversarial/judge.yaml`): leetspeak, spaced-out, Spanish /
  German and paraphrased injection and weapon prompts the regex guards miss (checked), with the
  answer they got, run through the `custom_rule` judge on replies in `judge_recorded.json` —
  hand-written so far; `PIPESETS_RECORD_JUDGE=<provider>/<model>` records them from a model. Bypass
  found: the judge read only `answer[:8000]`, so padding hid a leak; it now judges overlapping 8k
  windows (up to 4) and a longer answer follows `on_judge_error`
- A4 edge + network isolation (2026-10-29): `deploy/edge/` nginx with Let's Encrypt
  (`compose.edge.yaml` adds the edge and a certbot container; self-signed stand-in until the first
  certificate, reload every 6 h picks up renewals). Two hostnames: `PUBLIC_HOST` serves `/v1/*`
  (incl. `/v1/hooks/*`) only, `UI_HOST` the UI and its `/api`, narrowed by `ui-allow.conf`; unknown
  hosts get no TLS handshake; backend and frontend publish no ports; `X-Forwarded-For` replaced, not
  appended (backend trusts it via `FORWARDED_ALLOW_IPS`); HSTS. k8s: `ingress.yaml` (cert-manager
  ClusterIssuer, public ingress routes `/v1/` only, UI ingress with optional
  `whitelist-source-range`) and `networkpolicy.yaml` (default deny; controller → frontend / backend,
  frontend → backend). UI shows `VITE_PUBLIC_API_URL` for `/v1` and webhook URLs. Verified with
  `deploy/edge/test/test.sh` (22 checks incl. path-traversal encodings, against stub upstreams;
  own CI job); not yet run against real Let's Encrypt or a cluster
- LLM contract suite (2026-10-29): `tests/gateway/test_llm_contract.py` replays each cassette in
  `tests/gateway/llm_contract/` (Chat Completions and Messages wire formats: text, length, parallel tool
  calls, thinking, prompt-cache usage, HTTP and mid-stream errors) under every backend that speaks
  it, through `llm.complete` / `llm.stream`, with a fake transport under httpx and httpx2 and real
  sockets blocked; same text, tool calls, finish reason, usage, cost and `LLMError` required.
  Found and fixed in the LiteLLM backend (today's `auto`): streams never asked for usage, so
  every streamed Anthropic (and llama.cpp) call was priced at $0; its exceptions are now
  `LLMError` with status / retryable and the provider's message. Remaining LiteLLM gaps listed in
  `LITELLM_GAPS` (529 reported as 500; no stream usage for Jan)
- Postgres compatibility (2026-10-29): the suite's first Postgres run failed on SQLite-only SQL —
  `INSERT OR REPLACE` / `INSERT OR IGNORE` in 9 places (publishing a version, memberships, cache,
  eval cases, RAG chunks / collections) and a `PRAGMA` in the marketplace delete, so publishing
  broke on Postgres. Replaced with `db.upsert` / `db.insert_ignore` (`ON CONFLICT` on SQLite and
  Postgres, lookup-then-write elsewhere); `tests/storage/test_db_portability.py` fails on SQLite-only SQL
  in app code
- Database info and move (2026-10-29): **Settings → Database** (`DatabasePanel.tsx`,
  `GET /api/system/database`, `iam:admin`): type, host / file, server version, size, schema revision
  and pending migrations — read-only, never the password. `python manage.py db copy --to URL`
  (`services/db_copy.py`): schema from the migrations (no demo seed), every row parents-first in one
  transaction, run-time tables (`rag_chunks` / `rag_collections`) created portably, row counts
  compared; refuses a target with data (`--overwrite`), a source behind on migrations, and orphan
  rows (`--skip-orphans`). Checked on a copy of a real install: SQLite → Postgres 16, 161 rows /
  40 tables, backend served from it, secrets decrypt. Tests run both ways (SQLite and Postgres legs).
  Fixed on the way: the Status page called `/api/health` (doesn't exist), so it always said
  "Unreachable"
- Server admins (2026-10-29): `users.server_admin` (migration `0013_server_admin`), above any
  workspace — the first sign-up on a server nobody can administer (desktop, fresh install), the
  oldest passworded account on upgrade, `PIPESETS_SERVER_ADMINS`, or `manage.py server-admin EMAIL`.
  Guards `/api/system/*`; `server_admin` on `/api/iam/context` and `/api/auth/me`; Settings → Database
  shown to server admins only
- Workspace / project delete (2026-10-29): SQLite now enforces foreign keys (they were declared but
  off), so memberships, groups, projects and ACLs cascade like on Postgres; migrations run with them off
  (`db.migration_connection`). Deleting a workspace or project also removes its rows from every table
  with no foreign key (apps, versions, secrets, API keys, schedules, webhooks, … — found from the
  schema), keeping the audit log; the UI asks first and reports what was removed. Fixed on the way:
  `except db.IntegrityError` never matched (CPython ignores a metaclass `__subclasscheck__` there), so
  a duplicate agent `run_id` was a 500 — the connection wrapper now raises a real `db.IntegrityError`
- Ollama and llama.cpp on our adapter (2026-10-29): `auto` prefers `openai_compat` for them
  (`llm.backends.ADAPTER_FIRST` / `auto_order`); re-checked live (qwen3, gemma-3-1b) against LiteLLM on
  the same requests — same results
- Database setup on a fresh install (2026-10-29): Settings → Database → **Use PostgreSQL** — test a
  connection, then copy this database into it (`services/db_setup.py`, on `db copy`) and write
  `DATABASE_URL` to the data dir's `.env` (600); used after a restart. Only while no pipelines or runs
  exist and `DATABASE_URL` isn't set by the environment; audited as `database.configure`. Checked end to
  end: fresh SQLite install → sign-up → switch → restart on Postgres → same account signs in

## Public API & Clients

- `/v1` API (`routers/v1.py`): `POST /v1/apps/{id}/run` (SSE or `stream:false` JSON),
  `GET /v1/apps`, `GET /v1/apps/{id}`, `GET /v1/health` (no auth)
- API keys (`services/api_keys.py`): SHA-256 hashes only, scopes, expiry, per-key rate limit
  (60 req/min default, 429 + `Retry-After`); `Authorization: Bearer` or `X-API-Key`
- Key management: Operations → 🔑 API Keys panel (create / reveal-once / revoke) and
  `python manage.py create-key | list-keys | revoke-key`
- Python SDK `pipesets.PipesetsClient` (apps, pipelines, streaming run, export, traces;
  `v1_list_apps`, `v1_run`, `v1_stream`; `PIPESETS_API_KEY`)
- CLI `pipesets` (health, apps, pipelines, run, stream, export, traces; `pipesets v1 apps|get|run`)
  — verified against the live backend
- MCP server `pipesets-mcp` over stdio: `list_pipelines`, `run_pipeline`, `list_apps`, `get_app`,
  `get_traces`, `export_app` — verified through a real MCP stdio client
- C4 remote MCP server (2026-10-29): `POST /v1/mcp` (`routers/v1_mcp.py`), Streamable HTTP,
  stateless (no session, GET/DELETE 405), protocol 2025-11-25 / 2025-06-18 / 2025-03-26 (batches).
  `/v1` API keys on every request (rate limited); `tools/list` filtered by the key's scopes:
  `list_apps`, `get_app` (apps:read), `run_app`, `resume_run` (apps:run), built on the `/v1` route
  functions. Human Gates reported, not approvable by the model. Provider keys from
  `X-Provider-Key-*` headers. Browser `Origin` refused unless in `MCP_ALLOWED_ORIGINS`. API keys
  panel shows a `claude mcp add` command. `tests/test_v1_mcp.py`; verified with the official MCP
  Python SDK (v2) client against a running backend
- C4 write tools (2026-10-29): opt-in scopes `apps:write` (`list_drafts`, `get_flow`, `create_app`,
  `update_app`: drafts only) and `apps:publish` (`publish_app`: eval gate, no override); not in the
  default scopes. Built on the app routes as the key's owner (plaintext credentials refused, owner's
  ACLs). Writes audited as `app.create` / `app.update` / `app.publish` (gate refusals as denied) with
  the key in `path`. API keys panel lists both scopes, unticked by default
- C9 chat links, "anyone with the link" (2026-11-01): a published pipeline gets a URL
  (`/c/pc_…`) that opens a phone-first chat page — no account. `services/chat_links.py`,
  `routers/chat_links.py`, migration 0024. Builder: **Chat link** button in the Build toolbar
  (create, copy, QR code, open, edit title / greeting / limits, turn off; usage per link). Public API: `POST
  /v1/chat/{token}/session` (server-made, encrypted session per visitor) and `POST
  /v1/chat/{token}/message` (SSE; visitors only get `token` / `error` / `done`, never traces, costs or
  run ids). Runs act as the link's creator (ACLs, budgets, middleware apply; `caller = link:<id>`);
  each conversation is remembered even without a Memory node (sliding window, 4k tokens). Limits per
  link through shared state: messages/min per IP (10), per conversation (50), per day for everyone
  (500), message length (4,000). Token stored as hash + sealed copy (rotated with `rotate-secrets`);
  create / update / revoke audited. Page is its own bundle (`frontend/chat.html`, ~75 KB gzip).
  Edge + ingress serve `/c/*`, `/assets/*` and `/v1/chat/*` on the public host (edge test covers it).
  `tests/apps/test_chat_links.py`, `src/chat/ChatPage.test.tsx`; verified end to end on a dev server
  (page, streaming, memory across turns) and at phone width
- Chat link page details (2026-11-01, migration 0025): per link, **Show pipeline details** (on by
  default) puts an About card on the page — the app's description and the names of its models (with
  provider), agents, tools, MCP servers and sub-pipelines, plus "answers from documents"; read from
  the published flow, never system prompts, connections, collections or keys (tested). Up to 6
  **sample prompts** shown as taps on an empty chat, typed or drafted with ✨ Generate from pipeline
  (the Run panel's generator). Once chatting, both step aside; **About** in the header brings the
  details back
- Chat page redesign + Pipeline info (2026-11-01): card layout on desktop, full screen on phones,
  avatar header with the model, welcome screen with prompt cards, typing dots, pill composer with
  send / stop; JSON answers shown readably (a lone `{"error": …}` as its text). A collapsed
  **Pipeline info** section (with details on) shows the pipeline ID (copy), published version and
  **Open in Pipesets** → builder `/?pipeline=<id>`, which opens that pipeline in Build when it's in
  the signed-in user's current project. Builder host from `VITE_UI_URL` (edge compose sets it to
  `https://$UI_HOST`), else the page's own origin
- Chat links on websites (2026-11-01): `?embed=1` embed mode (no page chrome, compact welcome);
  Chat link dialog → **Embed on a website**: copy-paste **Chat button** (floating button that opens
  the chat in a panel and turns into ✕; iframe loaded on first click; full-screen panel on phones;
  Esc closes) or **Inline** iframe, and **Download sample page** with the link filled in
  (`frontend/src/utils/chatEmbed.ts`). `examples/chat-embed/` (index.html generated from the same
  code, a test keeps them equal). Verified from another origin (sample site on :8090 framing the
  chat page) on desktop and phone width

## Platform & Deployment

- FastAPI backend, SQLite with a Postgres path; Alembic migrations 0001–0007
- Docker Compose and Kubernetes manifests (`deploy/compose`, `deploy/k8s`); `DEPLOYMENT.md`
- `start.sh` / `stop.sh` / `start-desktop.sh`
- A2 test harness + CI, first part (2026-10-28): the 18 `check_*.py` scripts converted to a
  pytest suite (`backend/tests/`, 127 tests, ~16 s); `conftest.py` gives every module a fresh
  migrated SQLite DB, a temp data dir and master key, clean in-process caches, and turns off the
  mock model's typing delay. `.github/workflows/ci.yml`: hash-checked install from
  `requirements.lock` (uv, Linux), lock-drift check, `alembic upgrade head && downgrade base`,
  pytest, `oxlint`, `tsc -b` + vite build. Dockerfile installs from the lock with
  `--require-hashes`. Fixed the 4 `tsc` errors and the one `oxlint` error so CI starts green
- Vitest for hooks and config panels (2026-10-29): jsdom + Testing Library (`src/test/setup.ts`,
  `src/test/fetchStub.ts` for routed `fetch` stubs). Hooks: `useFlowHistory` (settle window, drag /
  selection ignored, 100-step cap, reset), `useFlowManager` (delete, copy / paste ids, offsets,
  internal edges), `useAppManager` (connection refresh, server save errors, eval gate block /
  override / error), `useSubPipelineSummary`, `useCatalogData`. `configPanels.test.tsx` runs every
  node config panel (24 variants) on App's drop defaults: label edit → `onUpdate`, Save / Delete
  call back, and read-only leaves no enabled field or action. 90 frontend tests
- CPU-only lock (2026-10-29): `requirements.lock` compiled with `--torch-backend cpu` —
  `torch==2.15.0+cpu` / `torchvision+cpu`, and 19 CUDA packages (`triton`, `cuda-*`, `nvidia-*`)
  gone. CI installs with `uv … --torch-backend cpu`, the lock check compiles the same way, the
  Dockerfile adds the PyTorch CPU index to pip (hashes still pin every file). Backend image
  2.2 GB, built and smoke-tested (`/health`, `torch.version.cuda` is `None`). CI `push` /
  `pull_request` triggers restored
- B1 durable job queue (2026-10-29), verified on SQLite and Postgres 16 in tests:
  - Step 1: `jobs` + `leases` tables (migration `0014_jobs`), `services/jobs.py`; a claim is a
    conditional UPDATE fenced on `attempts`, so one worker wins on every database without
    `SKIP LOCKED`; leases renewed by heartbeat; retries ×4 backoff → `dead`.
    `python manage.py worker`; embedded worker in the API unless `PIPESETS_WORKER=external|off`
  - Step 2: schedule runs, webhook runs and notification deliveries are jobs; failed / crashed
    runs retry per the schedule's / webhook's **Retries** (0–10, -1 = until success); overlap and
    in-flight limits counted from the queue (migration `0015_run_retries`)
  - Step 3: periodic work (`@jobs.periodic`) — scheduler tick, orphaned-run sweep, audit purge,
    Human Gate sweep, job purge — takes turns through `leases`, so one process runs each per
    period, in API processes and workers alike. Human Gate timeouts enforced in the background
    (`services/gates.py`): reject → run rejected + `run.failed`; approve → published-app runs
    resumed by an `agent.resume` job; escalate → new `gate.escalated` event, sent once.
    Agent runs heartbeat `updated_at`; only runs silent for `AGENT_RUN_STALE_SECONDS` (120) are
    marked interrupted, replacing the startup sweep that assumed one process. Done jobs purged
    after `JOB_KEEP_DONE_DAYS` (7), dead after `JOB_KEEP_DEAD_DAYS` (30). **Automation → Jobs** (new
    top-menu area that also holds Schedules, Webhooks and Alerts, moved from Monitor; jobs by status,
    failed first; retry / discard failed ones): `GET /api/jobs`, retry / discard
    audited as `job.retry` / `job.discard`. Opt-in `worker` service in compose (`--profile worker`) and
    `deploy/k8s/worker.yaml` (Postgres only). `tests/runtime/test_background.py`, `JobsPanel.test.tsx`
- B2 shared state (2026-10-29): `services/shared_state.py` — sliding windows and expiring flags on
  `PIPESETS_SHARED_STATE` = memory | database (`shared_hits` / `shared_flags`, migration `0016`) |
  redis (`REDIS_URL`; atomic Lua check, `redis==8.1.0` in the lock) | auto (redis when `REDIS_URL`
  is set, else memory). API-key and middleware rate limits and the login lockout use it, so limits
  hold across replicas. Cancel signals: `POST /api/jobs/{id}/cancel` (queued → dead at once; running
  → its worker stops it within `CANCEL_POLL_SECONDS`, `on_dead` records "Cancelled"; audited
  `job.cancel`; Cancel button in Automation → Jobs), `POST /api/agents/runs/{id}/cancel` and
  `POST /v1/runs/{id}/cancel` for running Master Agent runs (status `cancelled`), MCP `cancel_run`.
  Optional `redis` service in compose (`--profile redis`). `tests/storage/test_shared_state.py` runs the same
  contract on each backend; CI runs Redis, and the postgres leg uses the database backend.
  Verified: full suite on memory, database and redis; touched modules on Postgres 16
- B3 observability (2026-10-29): `services/telemetry.py`. Prometheus `GET /metrics` (optional
  `METRICS_TOKEN`) and `WORKER_METRICS_PORT` on workers: runs by kind / app / status with a duration
  histogram, model calls, tokens and spend by provider / model, tool calls, job outcomes, and queue
  depth / oldest wait read from the DB at scrape time. OpenTelemetry over OTLP/HTTP when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set: one trace per run (`pipesets.run` → `chat <model>` /
  `execute_tool <name>` at recorded offsets, or `agent <name>` per Master Agent step), trace id = run
  id, GenAI semantic-convention attributes, content only with `OTEL_CAPTURE_CONTENT=1`; live
  `job <kind>` spans that runs link to. LLM steps record `start_ms`, local-model runs now record
  spans too, and the stream sends `{"type": "trace", ...}` per finished call (runner logs model-call
  time). New deps `prometheus-client`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`.
  Compose / k8s config, scrape annotations, a commented NetworkPolicy for Prometheus, DEPLOYMENT.md
  Observability section. `tests/observability/test_telemetry.py`; verified exporting to a real Jaeger 1.62
  - Settings → Share via ngrok (2026-10-31, dev only): server admins start / stop an ngrok tunnel to the
    dev UI, optionally on a static domain so the URL never changes (`routers/dev_tunnel.py`; off unless
    `PIPESETS_DEV_TUNNEL=1`, which start.sh sets). The Vite dev server accepts ngrok hosts and proxies
    `/api`, `/v1`, `/health`; opened from another host the UI calls the API on its own origin
  - Monitor → Metrics (2026-10-31): `GET /api/metrics/overview` (`routers/metrics.py`) computes runs,
    error rate, p50 / p95 latency, spend, tokens, a time series, breakdowns by model / tool / run phase,
    Master Agent run statuses and the job queue from the app DB (no Prometheus needed; history survives
    restarts), scoped to the project; `MetricsPanel` shows tiles, a runs chart (succeeded / failed),
    a p95 latency chart and tables, for 1 h to 30 days and per pipeline
  - Grafana dashboard (2026-10-31): `deploy/grafana/pipesets-dashboard.json` (23 panels: overview,
    runs, models, tools, run phases, jobs; data source picker and app filter); documented in
    DEPLOYMENT.md; `test_telemetry.py` checks every metric it queries is exported
  - Middleware, retrieval and embedding spans (2026-10-31): LLM runs record `middleware`
    (prompt / response checks, blocked ones as errors), `retrieval` (collection, chunks) and
    `embedding` (query embedding, inside retrieval) spans next to model and tool spans; exported to
    OTLP (`embeddings <model>` per GenAI conventions) and Langfuse, timed in
    `pipesets_phase_duration_seconds{phase}`, shown in the trace drawer
  - Simulated runs traced (2026-10-31): mock / no-key runs write a trace row (`metadata.simulated`,
    tool spans for the tools that really ran) and so reach Traces, metrics, OTLP and Langfuse; they
    count as runs and tool calls but not as LLM calls, tokens or cost; root span
    `pipesets.simulated`; "sim" tag in the canvas and Monitor trace lists
  - Agent step start times (2026-10-31): Master Agent steps record `started_at`, so their spans
    sit at their real starts and parallel strategies overlap (`pipesets.timing: recorded`);
    steps restored from older checkpoints follow the previous step (`sequential`)
- C1 long-term memory (2026-10-29), `services/long_term_memory.py`, migration `0017`:
  - Conversation memory scoped by tenant / project: `memory_sessions` (keyed by session id alone, so
    equal ids in two tenants shared a history; no primary key, so deleting a message used SQLite's
    `rowid`) became `memory_messages`; rows moved to the project of the app whose Memory node names
    the session. Memory inspector, runs and eval generate-from-traces are scoped and ACL-checked
  - Long-term memory: per-workspace opt-in (`tenant_features`, workspace owners); Memory node option
    "Remember facts about the user across sessions" (+ facts recalled, learn on / off). After each
    answer a `memory.extract` job reads the turn with the run's model when a server-side key exists
    (refs / sealed / project default / env; browser-typed keys never stored), else rules; facts
    PII-redacted, deduplicated by a unique index, capped at 200 per user. Recall: all up to
    `recall_k`, else by shared words. End user = signed-in user on the canvas, `user` on `/v1`, MCP
    `run_app` and the SDK; none for schedules / webhooks. Inspector: Monitor → Sessions →
    Long-term (switch, users, facts, add, delete, forget user); writes audited as `memory.*`
  - Memory node Session TTL enforced (2026-10-31): runs load only turns newer than
    `session_ttl_hours` (`ltm.load_messages(max_age_hours=…)`, both the streaming runner and
    `routers/run.py`); older turns stay stored and visible in the inspector. Unset / 0 keeps all
  - Key-value store (2026-10-30), `services/kv_store.py`, migration `0019`, built-in tool
    `key_value_store` (Data & Files): typed `action` get / set / delete / list with `key`, any JSON
    `value`, `ttl_seconds`, `prefix`. Node settings: namespace, scope (per end user — default — or
    shared across the project; runs with no end user can only use shared), default TTL, read only.
    Limits: 200-char keys, 64 KB values, 1,000 keys per namespace and user. Expired entries never
    returned, purged hourly (`kv_store.purge`); forgetting a user in the inspector deletes their
    entries. Inspector: Monitor → Sessions → Store (shared + users, namespace filter, edit as JSON
    keeping the expiry, add, delete; `/api/memory/store/*`, audited as `memory.store_put` /
    `memory.store_delete`). Exported code (LangChain, AutoGen, CrewAI, notebook) gets a working
    stdlib version on a local SQLite file (`KV_STORE_PATH`, `KV_STORE_USER`) instead of a stub.
    `tests/knowledge/test_kv_store.py` (incl. an agent storing a value in one run and reading it in the next,
    and the exported function run as-is), `KeyValueStorePanel.test.tsx`; on SQLite and Postgres 16
  - `tests/knowledge/test_long_term_memory.py` includes the exit criterion (a preference from an earlier
    session is recalled, only for that user); tested on SQLite and Postgres 16
- C6 tools as code (2026-10-30):
  - Typed custom tools: `services/tool_signature.py` reads the entry point and parameter JSON schema
    from the code's syntax tree (never runs it): `@tool(...)` function or `run` with typed params;
    types, defaults, required, docstring / `Annotated` descriptions, `Literal` enums; `config`
    reserved for the node's config. Legacy `run(input_text, config)` unchanged. The model gets the
    schema as a real function definition and the sandbox calls `fn(**args, config=)` (a stand-in
    `pipesets` module there); arguments validated first; non-string results returned as JSON
  - Versions (`custom_tool_versions`, migration `0018`): every content change a version, same content a
    no-op, rollback = new version; nodes pin `tool_version`. Custom tools looked up in the run's tenant
    / project only (they were fetched by id alone)
  - `/v1/tools` (list, get, idempotent `PUT` deploy by name, versions, rollback, sandbox run) with
    opt-in `tools:read|write|execute` scopes; deploys / rollbacks audited
  - SDK 0.2.0: `@tool`, `pipesets.testing` (`load`, `call`, `output`), `pipesets tool init | test | run
    [--remote] | deploy | list | versions | rollback`, `pipesets.toml` (3.9+ without tomllib), CI recipe
  - UI: schema preview while editing, typed test arguments, Versions tab (view, roll back), SDK tools
    read-only with "Deployed from SDK" and Fork, node version picker, tool scopes on API keys
  - Tests: `test_typed_tools.py`, `test_sdk_tools.py` (SDK and server read the same schema),
    `CustomToolModal.test.tsx`; CLI workflow verified against a running backend
  - Built-in tools with typed parameters (2026-10-30): `ToolSpec.parameters` (+ `input_param` or
    `to_input`; helpers `params`, `query_params`, `enum`) for 25 tools — the 8 web searches, arXiv,
    PubMed, news, Hacker News, Stack Overflow, OpenAlex, Wikipedia, calculator, Python, URL scraper,
    weather, currency / unit / timezone / date-time, SQL, GitHub. One argument is the tool's input;
    the other declared ones override the node config key of the same name for that call (never
    credentials or endpoints — a test checks every schema). Arguments validated incl. numeric bounds;
    the old `{"input": …}` call still works; schemas in the catalog. `test_builtin_tool_schemas.py`
  - Every other built-in tool typed too (75 in all; `json_input` / `json_value` / `config_args` for
    tools that read JSON). Recipients, destinations, credentials and sandbox settings are never model
    arguments (the test lists them). MCP servers: `POST /api/tools/discover` runs `tools/list` on a
    built-in server (or a custom one's discovered tools); the node stores the picked tools
    (`mcp_tools`) and each is offered as its own function `<node>__<tool>` with the server's input
    schema, arguments going straight to `tools/call` (custom servers use their discovered tools
    unless the node picks one). Custom MCP servers looked up in the run's project only (were by id).
    MCP processes are reaped after each call. Toolkits get their sub-tools' schemas. UI: "The model
    calls it with" on tool nodes, "Discover tools" + pick list on MCP nodes.
    `test_mcp_typed.py` (a real MCP server over stdio), `ToolParameters.test.tsx`
- C3 checkpointing for every run (2026-10-30):
  - Single-LLM runs (`services/llm_checkpoint.py`, migration `0020` adds `agent_runs.kind`): a run
    with a `run_id` saves retrieval, the parsed document, loaded memory, every model turn and every
    tool result; `resume_from` replays saved steps (the answer streams complete) and continues from
    the first unfinished one, so no finished model call is paid for twice and no tool runs twice.
    Same lifecycle as Master Agent runs (heartbeat, cancel from any replica, caller gone →
    `interrupted`); lifecycle helpers moved to `services/checkpoint.py`
  - Editor runs send a run id and show Resume on failed / interrupted turns; `/v1` LLM runs are
    checkpointed and `POST /v1/runs/{id}/resume` (and MCP `resume_run`) handles them; a failed `/v1`
    run reports its id; scheduled / webhook retries resume the previous attempt's run
  - Checkpointer node: Save steps (off: only the run's status is kept) and Restore on resume (off:
    a resume starts over); a flow with a Human Gate always saves and restores. Checkpoints live in
    the app database (SQLite or Postgres)
  - Time travel: spans record their `checkpoint_key`; `POST /api/agents/runs/{id}/rerun` forks a run
    from a step (earlier steps reused, the rest run against the app's current flow, optionally with
    an edited tool result), writing nothing to the session's memory or the cache. Trace drawer:
    "Re-run from here" / "Edit result" per span. LLM-node runs only (Master Agent runs write no
    trace rows)
  - `tests/runtime/test_llm_checkpoint.py` (resume after failure / disconnect, cancel, fingerprint, `/v1`,
    retried automation, Checkpointer node, re-runs). Fixed on the way: a Memory node saved without
    `token_budget` crashed `/v1` runs
- Vitest (2026-10-28): `npm test`, run in CI; `utils/pipelineValidation.test.ts` covers every
  rule (13 tests). Fixed on the way: LLM nodes on keyless providers (mock / Ollama / llama.cpp /
  Jan) skipped the timeout, retry and fallback checks

## Product features (plan.md §4b)

- **Feedback on runs** (F2, 2026-11-03; `services/feedback.py`, `routers/feedback.py`, migration 0030
  `run_feedback`): 👍 / 👎 plus a comment and an optional correction, one per run per rater (rating
  again replaces it), stored with the pipeline version; prompt and answer read from `agent_runs`.
  Raters: builders in the Prompt Runner (`RunRating.tsx`, LLM and Master Agent turns), chat-link
  visitors (the answer's `done` event carries a sealed token bound to the link and session;
  `POST /v1/chat/{token}/feedback`), API callers (`POST /v1/runs/{run_id}/feedback`, scope `apps:run`,
  per end `user`). Evaluate → Feedback (`eval/FeedbackPanel.tsx`): satisfaction per pipeline and
  version, filters, export to an eval dataset (expected = correction, else the answer for a 👍).
  Tests: `tests/evals/test_feedback.py`, `FeedbackPanel.test.tsx`, `ChatPage.test.tsx`
- **Batch runs** (F5, 2026-11-03; `services/batches.py`, `routers/batches.py`, migration 0031
  `batch_runs` / `batch_items`): a published pipeline once per row of a CSV / TSV / JSONL / JSON /
  Excel / text file, `{column}` prompt template, up to 5,000 rows. Each row is a `batch.run` job
  through `scheduler.run_attempt` (checkpointed under the row id, retried, dead-lettered); at most
  `concurrency` rows of a batch queued at once, topped up as rows finish and by a periodic sweep
  (`batch.top_up`). Cancel, retry failed, delete, CSV export. Automation → Batches
  (`ops/BatchesPanel.tsx`). Tests: `tests/runtime/test_batches.py`, `BatchesPanel.test.tsx`

- **Agent skills on demand** (C10 step 1, 2026-11-03; `services/skills_runtime.py`,
  `routers/skills.py`, migration 0033): skills have a version (`skill_versions` snapshot per save,
  `GET /api/skills/{id}/versions[/{v}]`), `when_to_use` (≤ 300 chars) and `required_tools` /
  `required_connections`; a Skill node runs the library copy (or a pinned `skill_version`), old
  inline-only nodes keep their copy. LLM node `skill_mode`: on demand (default) lists skills as
  `name — when to use` with a `use_skill` tool; tools a skill needs stay hidden until it loads (a
  hidden tool called early isn't run); at most `max_active_skills` (3) per request; unknown and
  repeated loads answered; a resumed run replays its `use_skill` calls and gets the same tools.
  `always` = the old behaviour, also used by the mock provider, local servers and Child agents.
  `skill_loaded` stream event, a "Loaded skill" trace span (version, tools switched on),
  `skills_used` in run metadata, 🧩 badges in the Prompt Runner. Four starter skills (Airflow DAG
  triage, Databricks job triage, Snowflake slow / costly query review, Kafka consumer lag) replace
  the generic built-ins in the list (those still load), `available` once their tools are installed.
  UI: Skills setting on the LLM node, "When to use" with a counter and "Tools it needs" in the
  catalog, library skills read-only with a version picker in the Skill node's config. Guide 05
  rewritten. Tests: `tests/runtime/test_skills_runtime.py` (the step-1 exit criterion),
  `tests/security/test_skills_scoping.py`, `SkillConfigPanel.test.tsx`
- **Skill readiness** (C10 step 3 reframed, 2026-11-03; `skills_runtime.readiness`, `utils/skillReadiness.ts`):
  for each Skill node wired to an LLM node, the required tools not attached to it and the attached
  ones missing a `ToolSpec.required` setting (a linked Connection node counts). Publishing refuses a
  flow with an unready skill (409, `detail.skills`, no override); Validate shows a blocking issue on
  the Skill node; the node shows "✓ Its N tool(s) are attached" or "⚠ Needs: attach …; set … on …".
  Tests: `tests/runtime/test_skill_readiness.py`, `utils/skillReadiness.test.ts`
- **Batch runs over documents** (F5 → P1, 2026-11-03; `services/batches.create_from_documents`,
  `POST /api/batches/documents`, migration 0032 `batch_runs.source`): uploaded files (PDF with OCR,
  images, email, Word, Excel, text; up to 500 × 50 MB) saved under `<data dir>/uploads/batches/<id>/`,
  one row `{filename, path}` each; `{document}` is the file's text, read when the row runs (loader
  by extension, or Docling for PDFs and scans; cut at 100,000 characters); an unreadable file fails
  its row without a run; deleting the batch deletes the files. `RunScope.batch` carries the batch
  name, so Structured Extract (prompt `{path}`) files its fields in the review queue under it.
  UI: Run over → Documents in Automation → Batches (prompt starts as `{path}` for a Structured Extract
  pipeline). Tests: `tests/runtime/test_batch_documents.py`, `BatchesPanel.test.tsx`
- **Step-through debugging** (F6, 2026-11-03; `services/debug_run.py`, request field `debug` on
  `/api/run/stream`): breakpoints on LLM, Tool, Toolkit and Retriever nodes pause a checkpointed
  Prompt Runner run before the node's step (`debug_paused` event, run saved `paused`); Continue /
  Step resume it from the checkpoint with the paused step's edited input (tool input, model
  messages, retrieval query), so no finished model call is repeated. Pinned outputs replace a tool,
  retriever, LLM or Child agent (`ChildAgentConfig.pinned_output`) at no cost; a run with pins
  writes nothing to memory, debug runs skip the cache. Spans carry `node_id`, `pinned`, `edited`;
  `GET /api/agents/runs/{id}/steps/{key}` returns a step's full output for pinning. UI: ● (toggle
  breakpoint) and 📌 (pin editor) buttons in each debuggable node's header beside ✕, visible on hover
  and always once set (`nodes/DebugBadges.tsx`, callbacks injected like `onDelete`); a 🐞 Debug strip
  at the top of the node's config (`NodeDebugSection.tsx`); `DebugPauseCard.tsx` in the Prompt
  Runner (focuses the paused node); 📌 Pin on tool results, answers and child steps. Node data
  `debug_breakpoint` / `debug_pin` are never read by server-built (published) requests. Tests:
  `tests/runtime/test_debug_runs.py`, `DebugPauseCard.test.tsx`, `NodeDebugSection.test.tsx`,
  `DebugBadges.test.tsx`, `utils/debugRun.test.ts`

## Docs (in-app user guide)

Shipped 2026-11-02.

- User guide in `docs/guide/` (12 guides: getting started, building pipelines, tools, MCP, agents /
  workflows / skills, RAG, guardrails and budgets, evaluate, monitor and automate, share and integrate,
  settings and admin, document extraction), linked from the README
- **Docs** button in the top bar opens it in the app (`?view=docs&page=<guide>#<section>`): guide
  list, search across every guide, "On this page", links between guides that stay in the app. Bundled
  at build time from `docs/guide/` (`src/utils/guides.ts`), loaded only when Docs opens. Docker /
  Compose / CI pass the folder as the extra build context `docs`
- "?" help links (`components/docs/HelpLink.tsx`) open the right section from: the OCR card, Guardrail,
  Master Agent, Human Gate, Workflow Step, Toolkit and Skill panels, the custom tool and custom MCP
  dialogs, the webhook prompt and Evaluate → Review
- Tests fail on a broken link between guides or a "?" link to a section that doesn't exist

## Desktop App (Tauri)

- M0 — Dev desktop shell (`desktop/`, 2026-10-27): Tauri window around the React build; starts
  the backend from `backend/.venv` (or the PyInstaller build with `--packaged`) on a free
  `127.0.0.1` port; `loading.html` until `/health` answers; backend stopped on quit, plus a
  watchdog if the app crashes; HTML5 drag-and-drop kept working
- M1 — Location-independent backend (2026-10-27): `PIPESETS_DATA_DIR` for DB, master key,
  uploads and `.env`; `backend/desktop_main.py` (port selection, localhost bind); first-launch
  copy of the web setup's data; web deployment unchanged
- Frontend resolves `API_BASE` at runtime (`window.__PIPESETS_API_BASE__`)
- M2 — Frozen backend (2026-10-27): PyInstaller one-folder build, 217 MB, docling left out;
  smoke-tested (start, migrate, create app, run pipeline, upload document); `--sandbox-exec`
  mode so custom tools and `python_interpreter` work in the frozen binary
- Desktop backend locked to its webview (Tauri origins + loopback hosts)
