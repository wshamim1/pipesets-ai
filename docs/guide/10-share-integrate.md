# 10. Share and integrate

Every way to use a published pipeline outside the editor. All of them run the **latest published
version** and act as a real user, so that user's access rights, budgets and guardrails apply.

| Way | For |
|---|---|
| [`/v1` REST API](#rest-api-v1) | Your own apps and services |
| [SDK and CLI](#sdk-and-cli) | Python code, scripts, CI |
| [Chat links](#chat-links) | Anyone with a link, on phone or laptop, no account; or embedded in a website |
| [MCP server](04-mcp.md#use-pipesets-as-an-mcp-server) | Claude Code, Claude Desktop, Cursor and other MCP clients |
| [Webhooks and schedules](09-monitor-automate.md#automate) | Other systems and timetables |
| [Export](#export) | Taking the pipeline out as code |
| [Marketplace](#marketplace) | Sharing with other teams or tenants |

## REST API (`/v1`)

1. **Settings → API keys → New key.** Give it a name, scopes (`apps:read` to list, `apps:run` to
   run), and optionally a rate limit (default 60 a minute) and an expiry. **Copy the key now**: it's
   shown once (`ps_…`). The key acts as you.
2. Call it:

   ```bash
   curl -N https://<host>/v1/apps/$APP_ID/run \
     -H "Authorization: Bearer $PIPESETS_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Summarise this ticket", "session_id": "user-42", "stream": true}'
   ```

| Field | Default | Meaning |
|---|---|---|
| `prompt` | required | The input |
| `session_id` | — | Gives each end user their own conversation memory |
| `user` | — | The end user, for long-term memory |
| `stream` | `true` | `true`: server-sent events; `false`: one JSON answer |
| `timeout_ms` | 120000 | Run timeout |
| `provider_keys` | — | Bring your own model keys, e.g. `{"openai": "sk-…"}` |

Stream events: `run` (the run id), `token`, `meta`, `paused` (Human Gate waiting), `error`, `done`.
Continue a paused, interrupted or failed run with `POST /v1/runs/{run_id}/resume` (with
`gate_decision` for a gate). Other endpoints: `GET /v1/apps`, `GET /v1/apps/{id}`, `GET /v1/health`.
Interactive docs are at `/docs` on the backend.

`/v1` only changes in backward-compatible ways; breaking changes would go to `/v2`.

## SDK and CLI

```bash
pip install -e sdk
export PIPESETS_URL=https://<host> PIPESETS_API_KEY=ps_...
pipesets v1 apps
pipesets v1 run <app_id> "Summarise this ticket" --stream
```

```python
from pipesets import PipesetsClient

with PipesetsClient("https://<host>", api_key="ps_...") as c:
    print(c.v1_run(app_id, "What is RAG?", session_id="user-42")["output"])
    for event in c.v1_stream(app_id, "What is RAG?"):
        if event["type"] == "token":
            print(event["text"], end="")
```

The CLI also publishes apps, exports them, lists traces, and manages custom tools as code
([Tools](03-tools.md#as-code-with-the-sdk)). Full reference: [sdk/README.md](../../sdk/README.md).

## Chat links

A link anyone can open to chat with a pipeline, with no account.

1. Open the published pipeline in **Build → Chat link → + New chat link**.
2. Set a title, a greeting, and up to 6 **sample prompts** (or **✨ Generate from pipeline**).
   **Show pipeline details** shows the description and the names of its models, tools and agents,
   never prompts, keys or data.
3. Adjust the limits: messages a minute per visitor (10), per conversation (50), per day across
   everyone (500), characters per message (4,000).
4. Share the URL (`/c/pc_…`) or the QR code.

- Each visitor gets their own conversation, kept across reloads.
- Visitors see only answers, never traces, costs or run ids.
- **Turn off** stops the link at the next message. Creating, editing and turning off links is in
  the audit log.
- While the pipeline is being edited (a draft after publishing), the link answers "unavailable"
  until you publish again. Edit and publish outside busy hours.
- **Embed on a website** gives HTML for a floating chat button or an inline iframe; see
  [examples/chat-embed](../../examples/chat-embed/).
- A link made on `localhost` only works on that computer. To test on a phone, use **Settings →
  Share via ngrok**.

A public link is public: add **Prompt Injection**, **Rate Limiter** and **Cost Tracker** guardrails
first ([Guardrails](07-guardrails-budgets.md)).

## Export

**Export App** (in Build) or `pipesets export <app_id> --format …`:

| Format | You get |
|---|---|
| Pipesets JSON | The flow, re-importable into any Pipesets |
| LangChain / CrewAI / AutoGen | Standalone Python |
| Notebook | A Jupyter notebook |
| Docker Compose | A runnable container bundle |
| OpenAPI | An API spec for the app |
| Agent Skill | A skill folder (zip) for Claude Code and other agents that read `SKILL.md` |

Exports don't include guardrail (middleware) nodes yet.

### As an Agent Skill

Turns a **published** pipeline into a skill another agent can use. The pipeline keeps running on
Pipesets; the skill tells the agent when to use it and how to call it.

1. Publish the pipeline, then **Export App → Agent Skill → Download**.
2. Unzip it into `.claude/skills/` (one project) or `~/.claude/skills/` (all your projects).
3. Create an API key with the `apps:run` scope and set `PIPESETS_API_KEY`. Set
   `PIPESETS_BASE_URL` if the agent reaches Pipesets at a different address than the one the
   export was made from.

The zip holds `SKILL.md` (the name and description come from the pipeline's name and
description, so write the description as *when* to use it), `scripts/run.py` (Python standard
library only), and `reference.md` when the pipeline has docs. The key is never written into the
files. If the pipeline has a Human Gate, the agent is told to show the step to the user and pass
on their decision, never to approve on its own.

## Marketplace

Share pipelines as listings.

- **Publish a listing:** from a published pipeline, set a summary, description, category and tags,
  and the **Visibility**: public (every user), tenant only, or unlisted. **What you'll need** tells
  importers which keys or connections to provide.
- **Browse:** filter by category; sort by most imported or recently updated. **Try it** runs a
  listing without importing it.
- **Import:** copies a version into your project as a draft. You're told when a newer version is
  out.
