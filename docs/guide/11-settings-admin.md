# 11. Settings and admin

Open **Settings** with the ⚙ gear in the top bar.

| Tab | Use it to |
|---|---|
| **Members & access** | Invite users, set roles, manage groups and access rules |
| **Workspaces & projects** | Create workspaces (tenants) and projects; switch between them in the top bar |
| **API keys** | Keys for `/v1`, MCP and the SDK ([Share](10-share-integrate.md#rest-api-v1)) |
| **Audit log** | Who changed what: keys, secrets, members, publishing, chat links, review decisions; export it |
| **Tools & MCP packages** | Install the built-in tools and MCP servers the builder's sidebar offers |
| **Model provider keys** | A default key per model provider for the project |
| **Model backends** | Which gateway engine sends calls for each provider, and its base URL |
| **Secrets** | Named, encrypted keys and tokens that nodes pick by name |
| **Database** | Which database Pipesets runs on, migration status, moving to PostgreSQL |
| **Share via ngrok** | A temporary public address for testing chat links and webhooks from outside |
| **Status & data** | Server status and the data stored for the workspace |
| **Danger zone** | Actions that can't be undone; read each one before clicking |

## Workspaces, projects and access

- A **workspace** (tenant) is an organisation or team. A **project** groups related apps, datasets,
  secrets and keys. Everything you create is in the current project.
- **Roles** per workspace:

  | Role | Can |
  |---|---|
  | Owner | Everything, including members and settings |
  | Editor | Build and change apps and other resources |
  | Viewer | See, not change |

  What each role may do exactly comes from the workspace's access rules (below).

- **Groups and access rules** narrow access further: allow or deny a user or group a resource
  (apps, tools, secrets…) and action (read, write…), in one project or the whole workspace. A deny
  beats any allow.
- New users: self sign-up is on by default (`AUTH_ALLOW_SIGNUP=0` turns it off so only admins add
  users). Changing a password ends that user's sessions.

## Tools & MCP packages

The builder's sidebar shows only the tools and MCP servers **installed** in the workspace. Here you
browse all of them, by type, category and install state, and install or uninstall them. A new
workspace starts with a starter set plus whatever its pipelines already use.

Uninstalling only hides a package from the sidebar: pipelines that use it keep working. Changes
apply to the whole workspace, need write access to tools, and are recorded in the audit log.
**Reset to defaults** forgets every choice. Details: [Install more tools](03-tools.md#install-more-tools).

**Reload from disk** (server admins only) picks up tool and MCP modules added, edited or deleted in
`backend/tools/`, with no backend restart. Runs already in progress finish on the old code. A file
that fails to import is listed, and the tool keeps its last working version. With `./start.sh`,
changes are also picked up by themselves (`TOOLS_AUTO_RELOAD=1`; set it to `0` to turn this off).
With several backend workers, the button reloads only the worker that serves the request, so use
`TOOLS_AUTO_RELOAD` there. A new pip dependency, or a change to `backend/tools/__init__.py`, still
needs a restart. The desktop app gets new tools only by updating.

## Keys and secrets

- **Model provider keys** are the easiest way to give a project its models.
- **Secrets** are for everything else: tool tokens, database passwords, per-node model keys.
  Values are encrypted with the server's master key and never shown again in full.
- **API keys** let programs call Pipesets. Each acts as the user who made it, is shown once, and
  can be limited by scope, rate and expiry. Revoke a leaked key at once.

## Model backends

Pipesets sends model calls through its own gateway. **Auto** (default) uses the built-in adapter
for each provider. Here you can, per project or workspace:

- pick a different engine for a provider (e.g. route OpenAI-compatible calls through a proxy);
- set a provider's base URL (e.g. a regional endpoint, a self-hosted NIM or vLLM).

Leave it on Auto unless you have a reason.

## Database

Pipesets uses SQLite by default, which is fine for one server. For production, **Database → Use
PostgreSQL** walks you through moving: create an empty PostgreSQL database, point Pipesets at it,
restart. The old database is left untouched. Schema migrations apply on start. See
[DEPLOYMENT.md](../../DEPLOYMENT.md).

## Lab

**Lab** spins up things to test against, on your machine (needs podman or docker):

- **Services:** one-click databases and stores (Postgres, MySQL, MariaDB, MongoDB, ClickHouse,
  Chroma…), seeded with sample data, ready to use as Connections.
- **Seeder:** load sample datasets (e-commerce, HR, CRM, or your own SQL) into them.
- **Ollama / llama.cpp:** run local models for offline or private use.

Lab is for development. Don't point production pipelines at Lab containers.
