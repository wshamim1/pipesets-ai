# Deployment

Three ways to run the framework. All use the same two images:

| Image | Source | Serves |
|---|---|---|
| `pipesets-ai-backend` | `backend/Dockerfile` | FastAPI on `:8000` |
| `pipesets-ai-frontend` | `frontend/Dockerfile` | nginx on `:8080`; static UI + reverse proxy `/api/*` → backend |

The UI is built with `VITE_API_BASE=/api`, so the browser only talks to the frontend origin. No CORS or
public backend URL is needed. SSE streaming is supported (proxy buffering is off).

## Docker / Podman (Compose)

```bash
cd deploy/compose
cp .env.example .env          # add OPENAI_API_KEY etc.
docker compose up -d --build  # or: podman compose up -d --build
```

- UI: http://localhost:8080 — API docs: http://localhost:8000/docs
- Data (SQLite DB + uploads) lives in the `backend-data` volume.
- Stop: `docker compose down` (add `-v` to delete data).
- Background jobs run inside the backend container. With PostgreSQL (`DATABASE_URL`) they can run in
  their own container: `PIPESETS_WORKER=external docker compose --profile worker up -d`, and
  `--scale worker=N` for more. Jobs, and failed ones to retry, show in **Automation → Jobs**.

### Exposing it: TLS and the edge proxy

`compose.yaml` publishes the UI and the backend on plain HTTP — fine on a laptop, not on the internet.
For a server, add the edge overlay:

```bash
# .env: PUBLIC_HOST=api.example.com  UI_HOST=app.example.com  LETSENCRYPT_EMAIL=ops@example.com
# both DNS names point at this host; ports 80 and 443 open
docker compose -f compose.yaml -f compose.edge.yaml up -d --build
```

- `https://$PUBLIC_HOST/v1/*` — the public API and webhooks (`/v1/hooks/*`), and nothing else: `/api`,
  `/docs` and `/health` are 404 there. Callers use API keys / webhook tokens.
- Chat links (`https://$PUBLIC_HOST/c/pc_…`, Build toolbar → Chat link): the public host also serves the chat page
  (`/c/*` and the static `/assets/*` it loads) and `/v1/chat/*`, so visitors outside your network can
  open them while the UI host stays restricted. Nothing else from the UI is reachable there. The chat
  page's "Open in Pipesets" link points at `VITE_UI_URL` (set to `https://$UI_HOST` by the edge overlay).
- `https://$UI_HOST/` — the UI and the `/api` it calls. To limit it to an office or VPN, list the ranges in
  `deploy/edge/ui-allow.conf` and run `docker compose exec edge nginx -s reload`.
- The backend and frontend publish no ports, so nothing gets around the edge. Other hostnames, and the
  bare IP, get no TLS handshake.
- Certificates come from Let's Encrypt (the `certbot` container; HTTP-01 on port 80) and renew on their own.
  Until the first one is issued the edge serves a self-signed stand-in. Try it with
  `LETSENCRYPT_STAGING=1` first, since Let's Encrypt rate-limits failed attempts.
- The UI is built with `VITE_PUBLIC_API_URL=https://$PUBLIC_HOST`, so the API-key curl example and
  webhook URLs it shows point at the public host.
- `deploy/edge/test/test.sh` checks these rules against stand-in upstreams; CI runs it.

Podman without compose, using a pod:

```bash
# from the repo root (pipesets-ai/)
podman build -t pipesets-ai-backend  ./backend
podman build -t pipesets-ai-frontend --build-context docs=./docs/guide ./frontend
podman pod create --name pipesets-ai -p 8080:8080 -p 8000:8000
podman run -d --pod pipesets-ai --name backend  --env-file deploy/compose/.env -v pipesets-ai-data:/data pipesets-ai-backend
podman run -d --pod pipesets-ai --name frontend -e BACKEND_URL=http://127.0.0.1:8000 pipesets-ai-frontend
```

(Inside a pod, containers share localhost, hence `BACKEND_URL=http://127.0.0.1:8000`.)

The frontend image bundles the user guide (`docs/guide/`, shown under **Docs** in the app), which is
outside `frontend/`, so its build needs the extra build context `docs` as above (`--build-context`
needs BuildKit / Docker 23+ or Podman 4.2+; Compose passes it through `additional_contexts`). Without
it the build stops at `COPY --from=docs`.

## Kubernetes

Manifests are in `deploy/k8s/` (Kustomize).

The image has no `.git`, so write the "What's new" release notes into it first (they're read from
`backend/release_notes.json`; without it the panel says notes aren't available):

```bash
python backend/scripts/write_release_notes.py
```

```bash
# 1. Build and make the images available to the cluster
docker build -t registry.example.com/pipesets-ai-backend:0.7.0  backend
docker build -t registry.example.com/pipesets-ai-frontend:0.7.0 --build-context docs=docs/guide frontend
docker push registry.example.com/pipesets-ai-backend:0.7.0
docker push registry.example.com/pipesets-ai-frontend:0.7.0
#    then uncomment/edit the `images:` block in deploy/k8s/kustomization.yaml
#    (local kind/minikube: `kind load docker-image ...` / `minikube image load ...`)

# 2. Apply, then create the API-key secret
kubectl apply -k deploy/k8s
kubectl -n pipesets-ai create secret generic backend-secrets \
  --from-literal=OPENAI_API_KEY=sk-... --dry-run=client -o yaml | kubectl apply -f -
kubectl -n pipesets-ai rollout restart deploy/backend

# 3. Access
kubectl -n pipesets-ai port-forward svc/frontend 8080:80       # http://localhost:8080
# or edit deploy/k8s/ingress.yaml and `kubectl apply -f deploy/k8s/ingress.yaml`
```

`ingress.yaml` (needs ingress-nginx and cert-manager) has the same split as the compose edge: a public host
whose only path is `/v1/` → backend, and a UI host → frontend, optionally narrowed with
`nginx.ingress.kubernetes.io/whitelist-source-range`; both get Let's Encrypt certificates from the
`letsencrypt` ClusterIssuer. `networkpolicy.yaml` (applied by the kustomization) denies all ingress in the
namespace except controller → frontend / backend, frontend → backend and backend → sandbox; it matches the
controller by its namespace name, `ingress-nginx`. It needs a CNI that enforces NetworkPolicy.

Notes:
- Non-secret settings: `deploy/k8s/config.yaml`. Secrets: `backend-secrets` (optional reference, see `secret.example.yaml`).
- The backend is **one replica with `Recreate` strategy** because state is SQLite on a ReadWriteOnce PVC.
  Scaling it out requires moving to a shared database first. The frontend is stateless and runs 2 replicas.
- Background jobs (scheduled / webhook runs, notifications, Human Gate timeouts) run inside the backend
  by default. With PostgreSQL, run them in `worker` pods instead (`deploy/k8s/worker.yaml`; its header
  lists the steps): set `PIPESETS_WORKER: external` on the backend and add `worker.yaml` to the
  kustomization. Any number of backend and worker replicas can run: periodic work (the scheduler tick,
  sweeps, purges) takes turns through the database, so each firing and each job runs once.
- With more than one backend or worker pod, set `PIPESETS_SHARED_STATE` to `database` or `redis`
  (with `REDIS_URL`). It holds API-key and middleware rate limits, login lockouts and cancel signals;
  the default (`memory`, without `REDIS_URL`) keeps them per pod, so each pod allows the full limit
  and a cancel only reaches runs on the pod that received it.

## Observability

**Metrics.** `GET /metrics` on the backend (Prometheus text format) and on each worker at
`WORKER_METRICS_PORT` (9100 in compose / k8s). It isn't under `/api` or `/v1`, so neither the UI proxy
nor the public edge serves it: scrape the pods directly (k8s pods carry `prometheus.io/*` annotations;
`networkpolicy.yaml` has a commented rule to let your monitoring namespace in). Set `METRICS_TOKEN` to
require `Authorization: Bearer <token>`. Series: runs (`pipesets_runs_total`,
`pipesets_run_duration_seconds` by kind / app / status), model calls, tokens and spend by provider /
model, tool calls, time in middleware / retrieval / embedding (`pipesets_phase_duration_seconds` by
phase), job outcomes, and queue depth (`pipesets_job_queue`,
`pipesets_job_queue_oldest_seconds`). Counters are per process, so `sum()` them across pods; the queue
gauges are read from the shared database, so take `max()`. Examples:

```promql
# error rate
sum(rate(pipesets_runs_total{status="failed"}[5m])) / sum(rate(pipesets_runs_total[5m]))
# p95 run latency per app
histogram_quantile(0.95, sum by (app, le) (rate(pipesets_run_duration_seconds_bucket[5m])))
# spend per hour by model
sum by (model) (increase(pipesets_llm_cost_usd_total[1h]))
```

**Dashboard.** Import [`deploy/grafana/pipesets-dashboard.json`](deploy/grafana/pipesets-dashboard.json)
into Grafana (Dashboards → New → Import) and pick your Prometheus data source. Rows: overview (run rate,
error rate, p95 latency, 24 h spend, queued jobs, oldest wait), runs, models, tools, run phases and the
job queue, filterable by app. A backend test fails if it queries a metric the backend doesn't export.

**Traces.** Set `OTEL_EXPORTER_OTLP_ENDPOINT` (OTLP over HTTP, e.g. `http://tempo:4318`) and, if the
backend needs auth, `OTEL_EXPORTER_OTLP_HEADERS`. Each run is one trace (`pipesets.run`, with a span
per model call and tool call, or per agent step) whose trace id is the run id without dashes, so a run
id from Pipesets finds it in Tempo / Jaeger / Datadog. Jobs get a `job <kind>` span that the runs
inside them link to. Prompt and output text are left out unless `OTEL_CAPTURE_CONTENT=1`.

## Python sandbox

`python_interpreter` and custom tools never run code inside the backend container. They go to the
**sandbox runner** (`sandbox` service, image from `backend/Dockerfile.sandbox`), which runs each call in a
throwaway container with its own rootless podman: no network unless the tool needs it, read-only root,
dropped capabilities, memory / CPU / pid limits, non-root user. A tool's requirements are installed into a
cached image there, never into the backend. The runner holds no secrets and only the backend can reach it.

- Set `SANDBOX_TOKEN` (shared by both services) in `.env` / `backend-secrets` — both refuse to start
  without it. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- `SANDBOX_REQUIRE_ISOLATION=1` (the default here): if the runner is down, Python tools fail instead of
  running inside the backend.
- **Compose** gives the runner `/dev/fuse` and unconfined seccomp / SELinux labels (what nested rootless
  podman needs), not `--privileged`.
- **Kubernetes** (`deploy/k8s/sandbox.yaml`): plain k8s only grants that to a privileged container, so the
  runner pod — only that pod — is privileged. A NetworkPolicy admits the backend only. With a fuse device
  plugin you can drop `privileged`; with gVisor, set `runtimeClassName: gvisor` on the runner.

## Server admins

A **server admin** manages the server itself (Settings → Database) — a workspace owner isn't one by
default. The first account to sign up on a server nobody can administer becomes one (the desktop app's
user, or whoever sets up a new server); upgrading gives the role to the oldest account with a password.
Grant or revoke it with `python manage.py server-admin EMAIL [--revoke]` (`--list` shows who has it), or
list emails in `PIPESETS_SERVER_ADMINS`.

## Choosing the database on a fresh install

Before anyone builds pipelines, a server admin can switch a new install to PostgreSQL from **Settings →
Database → Use PostgreSQL**: test the connection, then switch. What exists so far (their account and
workspace) is copied into the new database and `DATABASE_URL` is written to the data directory's `.env`
(mode 600); restart the backend — or reopen the desktop app — to use it. This isn't offered once pipelines
or runs exist (use the move below, with the backend stopped), or when `DATABASE_URL` is set by the
environment, as in Docker Compose and Kubernetes — set it there instead.

## Moving from SQLite to PostgreSQL

The database is chosen by `DATABASE_URL` when the backend starts (empty = SQLite); **Settings → Database**
shows which one is in use and whether its schema is current. To move a running SQLite install to Postgres:

1. Create an empty Postgres database and stop the backend (so nothing writes during the copy).
2. From `backend/`, with the current `DATABASE_URL` (or none, for SQLite):
   `python manage.py db copy --to postgresql+psycopg2://user:pass@host:5432/pipesets`
   — it creates the schema, copies every row in one transaction and compares row counts. Nothing is kept
   if it fails. It refuses a target that already has data (`--overwrite` replaces it), and rows whose
   parent no longer exists — SQLite doesn't enforce foreign keys, Postgres does — stop the copy until you
   rerun with `--skip-orphans`.
3. Set `DATABASE_URL` to the new database and start the backend. Keep the **same master key**
   (`PIPESETS_MASTER_KEY`, KMS or Vault setting): secrets are copied still encrypted. Uploaded files live in
   the data directory, not the database — move it too if the server changes.

The old SQLite file is left untouched; keep it until you've checked the new install.

## Audit log retention

Admin actions (keys, secrets, members and access, publishing, settings) and refused attempts are kept in
the `audit_log` table and shown in **Settings → Audit log**, where anyone with `audit:read` can filter them
and export CSV or JSON Lines (each export is logged). `AUDIT_RETENTION_DAYS` (default 365; `0` keeps
everything) is the only way entries are removed: the backend purges older ones at startup and daily, and
leaves an `audit.purge` entry in each tenant it trimmed. It is an operator setting on purpose — a tenant
admin can't shorten their own trail. For longer retention, export on a schedule before the purge.

## Known limitations in containers

- **Lab Postgres / MCP-docker tools** start containers on the host engine and will not work from inside the
  backend container unless you mount a container socket (not done here, as it grants host-level access).
- **Host services** (e.g. Ollama): use `host.docker.internal` / `host.containers.internal` in `LLM_BASE_URL`.
- Expose a server through the edge proxy (compose) or `ingress.yaml` (k8s), not the published ports.
