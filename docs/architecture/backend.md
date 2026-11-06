# Backend

The backend is one FastAPI app ([backend/main.py](../../backend/main.py)) on Python 3.12. It
serves the internal API for the UI, the public `/v1` API, and runs background work in the same
process unless workers are split out.

## Startup

`main.py` does these steps in order when the module loads:

1. Loads `.env`, then `<data dir>/.env` (the desktop app keeps its settings there). Variables
   already set are never overridden.
2. Installs log redaction (`services/log_redaction.py`), so API keys, bearer tokens and sealed
   values are masked in every log line.
3. Runs `init_db()`: applies pending Alembic migrations and seeds the demo tenant.
4. Seals any connection credentials an older version saved in plaintext.
5. Builds the default LLM config from the environment.

The FastAPI `lifespan` then starts the background loops and, unless `PIPESETS_WORKER` is
`external` or `off`, an embedded job worker. See [Background work](background-jobs.md).

## Middleware

Applied to every request, outermost first:

| Middleware | Purpose |
|---|---|
| `TrustedHostMiddleware` | Optional `ALLOWED_HOSTS` allow-list. Blocks DNS rebinding against a localhost backend; the desktop app sets it to loopback names. |
| `AuditMiddleware` | Records admin actions to the audit log after the response is sent ([security](security.md#audit-log)). |
| `SecurityHeadersMiddleware` | CSP, `X-Frame-Options`, `nosniff`, and HSTS on HTTPS. |
| `CORSMiddleware` | By default allows only the Vite dev server. The deployed UI goes through the frontend's proxy on the same origin, so it needs no CORS. Credentialed CORS is never used: sessions travel in a header, not a cookie. |

## Routers and authentication

Routers live in [backend/routers/](../../backend/routers/), one module per area. They fall into
two groups, and the group decides how a caller authenticates.

**Public routers** carry their own credential:

| Prefix | Router | Credential |
|---|---|---|
| `/api/auth` | `auth.py` | None (sign-up, login) |
| `/v1` | `v1.py` | API key (`ps_…`) with scopes |
| `/v1/mcp` | `v1_mcp.py` | API key, same scopes as `/v1` |
| `/v1/tools` | `v1_tools.py` | API key (custom tools as code) |
| `/v1/hooks/{token}` | `webhooks.py` | The secret URL token, plus optional HMAC |
| `/v1/chat/{token}` | `chat_links.py` | The chat-link token |

**Every other router** is mounted with two dependencies: `get_current_user` (a valid session,
or 401) and `bind_secret_scope` (binds the caller's tenant and project for secret lookups). These
are the `/api/*` routes the UI uses.

Inside a handler, `get_request_context(request)` returns the `RequestContext` (`tenant_id`,
`project_id`, `user_id`), and `require_access(ctx, resource, action)` checks the ACL. Every SQL
query filters by the context's tenant and project.

Other endpoints:

- `GET /health`: liveness, and which database is in use (credentials masked).
- `GET /metrics`: Prometheus metrics. Not under `/api` or `/v1`, so neither proxy serves it;
  scrape the backend directly. Optional `METRICS_TOKEN`.

## Services layer

Routers stay thin and call into [backend/services/](../../backend/services/). The main ones:

| Area | Modules |
|---|---|
| Running | `llm_runner.py` (single-LLM runs and the tool loop), `pipeline_runner.py` (published pipelines and nesting), `workflow_engine.py`, `checkpoint.py`, `skills_runtime.py`, `child_tool_loop.py`, `external_agent.py`, `debug_run.py` |
| Models | `llm_auth.py` (key resolution), `llm_settings.py` (which backend serves a provider) |
| Tools | `sandbox.py`, `tool_store.py`, `tool_packages.py`, `tool_signature.py`, `mcp_oauth.py` |
| Retrieval and memory | `vector_store.py`, `long_term_memory.py`, `kv_store.py`, `extraction.py` |
| Safety | `guardrail_judge.py`, `budget.py`, `publish_gate.py`, `gates.py` (Human Gate timeouts) |
| Security | `auth.py`, `acl.py`, `api_keys.py`, `request_context.py`, `secret_store.py`, `master_key.py`, `audit.py`, `security_headers.py`, `log_redaction.py` |
| Background | `jobs.py`, `scheduler.py`, `webhooks.py`, `notifier.py`, `batches.py` |
| Platform | `marketplace.py`, `chat_links.py`, `pipeline_docs.py`, `release_notes.py`, `db_setup.py`, `db_copy.py`, `shared_state.py`, `telemetry.py`, `langfuse_export.py` |

## Command-line management

[backend/manage.py](../../backend/manage.py) handles operator tasks: `db setup` and `db sql`
(apply or print migrations), `worker` (run a standalone job worker), `create-key`, and
`rotate-secrets`.

## Adding an endpoint

1. Add the route to the router for its area, or a new module in `routers/` registered in `main.py`.
2. Get the context with `get_request_context`, check access with `require_access`, and filter
   every query by tenant and project.
3. If it changes admin state (keys, secrets, IAM, publishing, config), add it to `AUDITED` in
   `services/audit.py`, or to `NOT_AUDITED` with a reason. `tests/security/test_audit_log.py`
   fails for unlisted routes under audited prefixes.
4. A `/v1` route must stay backward compatible.
5. Add tests under `backend/tests/<area>/`.
