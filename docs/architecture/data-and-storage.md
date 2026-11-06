# Data and storage

## App database

[backend/db.py](../../backend/db.py) connects to any SQLAlchemy database chosen by
`DATABASE_URL`:

| Database | Use |
|---|---|
| SQLite (default) | `backend/pipesets.db`, or `/data/pipesets.db` in the container. Fine for development, one-box installs and the desktop app. |
| PostgreSQL | Recommended for production and required for more than one replica. Also provides pgvector. |
| MySQL, SQL Server | Supported. SQL Server needs `pyodbc` and an ODBC driver. |

`get_db_connection()` returns a sqlite3-style connection on every database: `conn.execute` with
`?` placeholders, and rows readable as `row["col"]`. Code is written once and runs everywhere.

The tables, grouped by area:

| Area | Tables |
|---|---|
| Apps | `apps` (current draft or published flow), `app_versions` (published snapshots), `publish_gates` |
| Runs | `traces`, `agent_runs` (Master Agent runs, steps and pending gates), `workflow_runs`, `batch_runs`, `batch_items`, `run_feedback` |
| Identity | `users`, `tenants`, `projects`, `tenant_memberships`, `groups`, `group_memberships`, `acl_entries`, `auth_sessions`, `api_keys`, `tenant_features` |
| Secrets and connections | `secrets` (encrypted values), `connections` (sealed credentials), `llm_settings` |
| Building blocks | `custom_tools`, `custom_tool_versions`, `custom_mcp_servers`, `tool_packages`, `skills`, `skill_versions`, `saved_agents`, `saved_agent_versions`, `agent_packages`, `middleware` |
| State | `memories`, `memory_messages`, `cache_entries`, `kv_entries` |
| Automation | `jobs`, `schedules`, `schedule_runs`, `webhooks`, `webhook_runs`, `notification_channels`, `leases` |
| Evaluate | `eval_datasets`, `eval_cases`, `eval_runs`, `eval_results`, `model_optimizations`, `model_optimization_cases`, `budgets` |
| RAG and extraction | `rag_chunks` (local vector store), `knowledge_bases`, `extraction_reviews`, `extraction_review_pages` |
| Platform | `audit_log`, `marketplace_listings`, `marketplace_versions`, `marketplace_imports`, `chat_links`, `shared_hits`, `shared_flags` |

## Migrations

The schema lives in Alembic migrations in
[backend/migrations/versions/](../../backend/migrations/versions/). `init_db()` applies pending
migrations at startup. Operators can also run them by hand:

```bash
python manage.py db setup   # create or upgrade, and seed the demo tenant
python manage.py db sql     # print the SQL for DBA review, without applying it
```

Each migration must upgrade and downgrade cleanly on every supported database.
[DEPLOYMENT.md](../../DEPLOYMENT.md) covers moving from SQLite to PostgreSQL
(`services/db_copy.py`).

## Data folder

[backend/paths.py](../../backend/paths.py) sets `DATA_DIR`. It's `backend/` by default, or
`PIPESETS_DATA_DIR` if set. The desktop app uses an OS data folder instead. The folder holds:

- the SQLite database
- `.secrets_master_key` (only when no master key is configured)
- uploads
- per-tool Python environments (`tool-envs/`)
- an optional `.env`

## Vector storage

Collections live in the app database (`local`) or in pgvector. See
[Tools, MCP and RAG](tools-and-rag.md#rag).

## Shared state

Some state has to be the same across every replica: rate-limit counters, login lockouts and
cancel signals. [services/shared_state.py](../../backend/services/shared_state.py) has three
backends, chosen with `PIPESETS_SHARED_STATE`:

| Backend | Use |
|---|---|
| `memory` | One process. With N replicas, each one counts separately and allows N times the limit. |
| `database` | Rows in the app database. Needs nothing beyond a shared `DATABASE_URL`. |
| `redis` | `REDIS_URL`. Atomic sliding windows, so a limit is never exceeded. |
