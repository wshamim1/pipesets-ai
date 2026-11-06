# Security model

## Tenancy

Every resource belongs to a **tenant** and a **project**. Users can belong to several tenants and
switch projects. Each `/api` request carries `x-tenant-id` and `x-project-id`, and
`services/request_context.py` checks that the signed-in user is a member before building the
`RequestContext`. Handlers filter every query by the context's tenant and project. A resource in
another tenant returns 404, not 403, so its existence isn't revealed.

## Who the caller is

| Caller | Credential | Where checked |
|---|---|---|
| UI user | Session token `uas_…` in `Authorization: Bearer` or `X-Session-Token` | `services/auth.py` |
| Code, CLI, MCP client | API key `ps_…` with scopes, rate limit and expiry | `services/api_keys.py` |
| Webhook caller | Secret URL token, plus an optional HMAC-SHA256 signature of the body | `services/webhooks.py` |
| Chat-link visitor | The link token, with per-link rate limits | `services/chat_links.py` |

- Passwords are hashed with scrypt and a per-user salt. Repeated failed logins lock the account
  for a while.
- Session tokens, API keys, webhook tokens and chat-link tokens are all stored as SHA-256 hashes,
  so the plaintext exists only on the client.
- Sessions expire after `AUTH_SESSION_TTL_HOURS` (7 days by default). They end immediately on
  logout, on a password change, or when the user is disabled.
- API keys only work on `/v1` and are never accepted as sessions. A key acts as the user who
  created it.
- `AUTH_MODE=headers` is a legacy development mode that trusts `x-user-id`. Never use it on a
  shared server.

## Access control

`services/acl.py` checks `require_access(ctx, resource, action)`. The caller must be a member of
the tenant. Tenant owners have every permission. Everyone else gets permissions from tenant
roles, groups and per-resource ACLs. MCP and `/v1` scopes (`apps:read`, `apps:run`, `apps:write`,
`apps:publish`) limit an API key further.

## Secrets

The vault is [services/secret_store.py](../../backend/services/secret_store.py).

- **Encryption.** Values are encrypted with Fernet (AES-128-CBC with HMAC-SHA256) under a master
  key from `PIPESETS_MASTER_KEY`, AWS KMS or HashiCorp Vault (`services/master_key.py`). Several
  keys are accepted: the first one encrypts and all of them decrypt, so you rotate by putting a new
  key first and running `manage.py rotate-secrets`. With none configured, a key is generated into
  `<data dir>/.secrets_master_key`, which is fine for development only.
- **Write-only.** The API lists a secret's name and last 4 characters, never its value.
- **References, not values.** Nodes hold `secret://<id>`, and the value is substituted on the
  server just before the tool or model runs. It never appears in a saved flow, an export or the
  browser. Connection credentials, webhook signing secrets and notification URLs are stored
  sealed inline (`enc://…`).
- **Refused saves.** `PUT /api/apps/{id}` rejects a flow with a plaintext credential in a known
  key field.
- **Kinds.** An `llm` secret can reach only model and embedding calls, and a `tool` secret can
  reach only tools. A pipeline can't route an OpenAI key into an HTTP tool's headers.
- **Scope.** A secret belongs to one project or to every project in its tenant, and can be a
  project's default key for a provider.

## Guardrails and budgets

Guardrail middleware nodes (`routers/middleware.py`, `services/guardrail_judge.py`) run before and
after the model. They cover content moderation, PII detection and redaction, prompt-injection
detection, grounding, custom LLM-judged rules, token caps and rate limits. They apply to
streaming runs too, and can retract a response mid-stream. Budgets (`services/budget.py`) block or
warn when spending reaches a limit, globally or per app.

## Audit log

`services/audit.py` records admin actions to an append-only `audit_log` table:

- `AuditMiddleware` records every request to a route listed in `AUDITED`: who, which tenant and
  project, the action name, the target id, and the outcome (`success` or `denied`). Recording
  happens at the route level, so a handler can't forget to do it.
- `tests/security/test_audit_log.py` fails when a mutating route under an audited prefix is in
  neither `AUDITED` nor `NOT_AUDITED`.
- Request bodies are never read, so secrets can't end up in the log.
- There's no route to change or delete entries. Retention (`AUDIT_RETENTION_DAYS`, 365 by
  default) is set by the operator, and each purge and export is itself logged.
- `GET /api/audit-log` lets you filter by action, user, outcome and date, and export to CSV or
  JSON Lines. It needs `audit:read`.

## Transport and browser protections

- Security headers (CSP, frame denial, `nosniff`, HSTS) on every response.
- No cookies, so no CSRF surface, and CORS is off by default.
- An optional `ALLOWED_HOSTS` allow-list against DNS rebinding.
- `MCP_ALLOWED_ORIGINS` for browser origins on `/v1/mcp`.
- Logs mask known key patterns (`services/log_redaction.py`).
- In Kubernetes, a NetworkPolicy stops other pods from reaching `/api`, and only the sandbox pod
  is privileged ([deployment](deployment.md)).

Report vulnerabilities as described in [SECURITY.md](../../SECURITY.md).
