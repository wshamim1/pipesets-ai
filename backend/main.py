import logging
import os

from dotenv import load_dotenv

load_dotenv()  # before db reads DATABASE_URL

from paths import data_path  # noqa: E402

# The desktop app keeps settings next to its data; never overrides variables already set
load_dotenv(data_path(".env"))

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from db import init_db
from models import make_default_config
from version import APP_VERSION
from routers import apps, tools, memory, cache, run, export, stream, retrieval, agents, custom_tools, custom_mcp, connections, knowledge_base, traces, eval as eval_router, build, iam, lab, skills, middleware as middleware_router, budgets, pipelines, workflows, api_keys, v1, auth as auth_router, marketplace, schedules, webhooks, notifications, secrets as secrets_router, llm_settings as llm_settings_router, audit_log, system, jobs as jobs_router, metrics as metrics_router, dev_tunnel, v1_mcp, v1_tools, chat_links, reviews, feedback as feedback_router, batches, saved_agents, agent_catalog, release_notes, about, admin
from services import jobs, log_redaction, telemetry
from services.request_context import bind_secret_scope, get_current_user
from services.audit import AuditMiddleware
from services.security_headers import SecurityHeadersMiddleware


logging.basicConfig(level=logging.INFO)
log_redaction.install()  # mask API keys, tokens and sealed values in every log line

# Initialise database tables
init_db()

# Seal connection credentials saved in plaintext by older versions (idempotent)
from routers.connections import seal_plaintext_connections  # noqa: E402
seal_plaintext_connections()

# Seed the shared LLM config from environment
run.set_current_config(make_default_config())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Periodic loops — scheduler tick (SCHEDULER_ENABLED), audit retention, Human Gate timeouts,
    # stale-run and job purges — one process per turn; and a worker on the job queue unless
    # PIPESETS_WORKER=external / off
    jobs.start_background()
    yield
    await jobs.stop_background()
    telemetry.shutdown()   # flush spans still buffered for the OTLP exporter


app = FastAPI(
    lifespan=lifespan,
    title="Pipesets AI Backend",
    version=APP_VERSION,
    description="Backend API for LLM configuration, prompt running, app persistence, tools, memory & cache.",
)

def _env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in (os.getenv(name) or default).split(",") if v.strip()]


# Browser origins allowed to call the API. The deployed UI goes through the frontend
# proxy (same origin, no CORS), so by default only the Vite dev server is allowed;
# CORS_ORIGINS=* restores allow-all. Sessions use the x-session-token header, not
# cookies, so credentialed CORS is never needed. CORS_ORIGIN_REGEX covers origins whose
# port isn't fixed (e.g. `tauri dev` serves the desktop UI from http://127.0.0.1:<random>).
app.add_middleware(
    CORSMiddleware,
    allow_origins=_env_list("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"),
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],   # lets the browser read download filenames
)

# CSP, X-Frame-Options, nosniff etc. on every response; HSTS on HTTPS requests.
app.add_middleware(SecurityHeadersMiddleware)

# Admin actions (keys, secrets, IAM, publishing, config changes) → audit_log table.
app.add_middleware(AuditMiddleware)

# Optional Host header allow-list (blocks DNS rebinding against a localhost backend).
# Unset = any host; the desktop app sets it to the loopback names.
if _allowed_hosts := _env_list("ALLOWED_HOSTS"):
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["health"])
def health_check():
    from db import safe_database_url
    return {"status": "ok", "service": "pipesets-ai-backend", "db": safe_database_url()}

# ── Metrics ───────────────────────────────────────────────────────────────────
# Prometheus text format (services/telemetry.py). Not under /api or /v1, so neither the UI proxy
# nor the public edge serves it: scrape the backend directly. METRICS_TOKEN, when set, must come
# as "Authorization: Bearer <token>".
@app.get("/metrics", tags=["health"], include_in_schema=False)
def metrics(request: Request):
    import hmac
    from fastapi.responses import Response
    from prometheus_client import CONTENT_TYPE_LATEST

    token = os.getenv("METRICS_TOKEN", "")
    sent = request.headers.get("authorization", "")
    if token and not hmac.compare_digest(sent.encode(), f"Bearer {token}".encode()):
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    return Response(telemetry.metrics_text(), media_type=CONTENT_TYPE_LATEST)


# ── Routers ───────────────────────────────────────────────────────────────────
# Public: sign-up/login, /v1 (authenticates with its own API keys) and /v1/hooks (the URL token is the credential)
app.include_router(auth_router.router)
app.include_router(v1.router)
app.include_router(v1_mcp.router)   # /v1/mcp: the same API as a remote MCP server
app.include_router(v1_tools.router)   # /v1/tools: custom tools as code (the SDK's `pipesets tool`)
app.include_router(webhooks.public_router)
app.include_router(chat_links.public_router)   # /v1/chat: public chat links (the URL token is the credential)
app.include_router(custom_mcp.public_router)   # the MCP OAuth callback (its single-use state is the credential)

# Everything else requires a signed-in user (see services/request_context.py)
_login_required = [Depends(get_current_user), Depends(bind_secret_scope)]
for _router in (
    apps,
    tools,
    memory,
    cache,
    run,
    stream,
    export,
    retrieval,
    agents,
    custom_tools,
    custom_mcp,
    connections,
    knowledge_base,
    traces,
    eval_router,
    build,
    iam,
    lab,
    skills,
    saved_agents,
    agent_catalog,
    release_notes,
    about,
    middleware_router,
    budgets,
    pipelines,
    workflows,
    api_keys,
    marketplace,
    schedules,
    webhooks,
    chat_links,
    reviews,
    feedback_router,
    batches,
    notifications,
    secrets_router,
    llm_settings_router,
    audit_log,
    system,
    admin,
    jobs_router,
    metrics_router,
    dev_tunnel,
):
    app.include_router(_router.router, dependencies=_login_required)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
