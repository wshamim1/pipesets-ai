# pipesets — Python SDK and CLI

Thin client over the Pipesets AI REST API. Only dependency: `httpx`.

```bash
cd pipesets-ai/sdk
pip install -e .
```

## CLI

```bash
pipesets health
pipesets apps list
pipesets apps publish <app_id>
pipesets pipelines                                   # published, runnable pipelines
pipesets run <app_id> "Summarise this ticket" --provider-key openai=sk-...
pipesets stream "Hello" --app-id <app_id>            # live tokens; --json for raw SSE events
pipesets export <app_id> --format langchain -o agent.py
pipesets traces --limit 10
pipesets traces <run_id>
```

Public API (`/v1`, API-key authenticated — the key fixes tenant, project and user):

```bash
export PIPESETS_API_KEY=ps_...                      # issue one: python backend/manage.py create-key --name "My app"
pipesets v1 apps                                     # published apps the key can see
pipesets v1 run <app_id> "Summarise this ticket" --session-id user-42
pipesets v1 run <app_id> "Summarise this ticket" --stream
```

Global options (or env vars): `--url` / `PIPESETS_URL` (default `http://localhost:8000`),
`--api-key` / `PIPESETS_API_KEY` (for `v1` commands),
`--tenant` / `PIPESETS_TENANT_ID`, `--project` / `PIPESETS_PROJECT_ID`, `--user` / `PIPESETS_USER_ID`.

Exit codes: `0` success, `1` error or failed run, `2` bad arguments.

## SDK

```python
from pipesets import PipesetsClient

with PipesetsClient("http://localhost:8000") as c:
    result = c.run_pipeline("app-123", "What is RAG?", provider_keys={"openai": "sk-..."})
    print(result["output"])

    for event in c.stream("Hello", app_id="app-123"):
        if event["type"] == "token":
            print(event["text"], end="")

# Public /v1 API with an API key
with PipesetsClient("https://api.example.com", api_key="ps_...") as c:
    print(c.v1_run("app-123", "What is RAG?", session_id="user-42")["output"])
    for event in c.v1_stream("app-123", "What is RAG?"):
        if event["type"] == "token":
            print(event["text"], end="")
```

## Tools as code

Write custom tools as typed Python functions, test them locally, and deploy them by name. The
parameters become the function the model calls, with real arguments (not one input string).

```bash
pip install -e "sdk[test]"
pipesets tool init jira_lookup && cd jira_lookup   # tool.py, pipesets.toml, requirements.txt, tests/
pipesets tool test                                 # pytest, no backend needed
pipesets tool run --args '{"query": "OPS-1"}'      # run locally
export PIPESETS_API_KEY=ps_...                     # a key with tools:write (+ tools:execute for --remote)
pipesets tool deploy --note "$(git rev-parse --short HEAD)"   # new version, or "unchanged"
pipesets tool run --remote --args '{"query": "OPS-1"}'        # in the server's sandbox
pipesets tool versions && pipesets tool rollback 2
```

```python
# tool.py
from typing import Literal
from pipesets import tool

@tool(description="Look up a Jira issue by key", secrets=["jira_token"], requirements=["requests>=2.31"])
def jira_lookup(issue_key: str, include_comments: bool = False, mode: Literal["brief", "full"] = "brief",
                *, config) -> str:
    """Look up a Jira issue.

    Args:
        issue_key: The issue key, e.g. OPS-1
    """
    token = config["jira_token"]   # the node's config, secrets decrypted; never shown to the model
    ...
```

- Each parameter's type, default, required-ness and description (from the docstring's Args section
  or `Annotated[str, "…"]`) form the schema. Understood: `str`, `int`, `float`, `bool`, `list[X]`,
  `dict`, `Optional[X]`, `Literal[...]`, `Annotated[X, "…"]`. Returning a dict or list sends JSON.
- `secrets` become the tool's config keys (fields on the canvas node); `requirements` are installed
  into the tool's own sandbox. Arguments to `@tool` must be literals: the server reads them from the
  code without running it.
- Every content change is a new version; deploying the same code again is a no-op. Canvas nodes use
  the latest unless they pin a version. Tools deployed this way are read-only in the UI (fork to edit).
- `pipesets.testing.call(fn, args, config=...)` checks the arguments against the schema, as the
  server does, then calls the tool.

### CI recipe

Test on every pull request, deploy on merge, with an API key that has `tools:write`:

```yaml
# .github/workflows/tools.yml
name: tools
on:
  pull_request:
  push:
    branches: [main]
jobs:
  jira_lookup:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: tools/jira_lookup
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "pipesets-sdk[test] @ git+https://github.com/<you>/pipesets-ai#subdirectory=sdk"
      - run: pip install -r requirements.txt
      - run: pipesets tool test
      - if: github.event_name == 'push'
        run: pipesets tool deploy --note "${GITHUB_SHA::12}"
        env:
          PIPESETS_URL: ${{ vars.PIPESETS_URL }}
          PIPESETS_API_KEY: ${{ secrets.PIPESETS_TOOLS_KEY }}
```

## MCP server

> For most clients, use the backend's **remote MCP server** at `<backend>/v1/mcp` instead: no
> install, authenticated by a `/v1` API key (see the main README). This stdio server is for
> local use with a login session, and has more tools (drafts, traces, export).

Exposes the framework to MCP clients (Claude Desktop, Cursor, Bob, ...) over stdio.
Requires Python 3.10+ and the `mcp` extra:

```bash
pip install -e ".[mcp]"
```

| Tool | Notes |
|---|---|
| `list_pipelines` | read-only |
| `run_pipeline(app_id, prompt, timeout_ms)` | **makes real LLM calls; may cost money** |
| `list_apps`, `get_app` | read-only |
| `get_traces(run_id?, limit, app_id?)` | read-only |
| `export_app(app_id, format)` | read-only |

There are deliberately no create / update / delete / publish tools.

Provider keys for `run_pipeline` come from the server's environment as `PIPESETS_KEY_<PROVIDER>`
(e.g. `PIPESETS_KEY_OPENAI`) and are never accepted as tool arguments, since arguments appear in the
client's logs. Example client config:

```json
{
  "mcpServers": {
    "pipesets": {
      "command": "pipesets-mcp",
      "env": {
        "PIPESETS_URL": "http://localhost:8000",
        "PIPESETS_KEY_OPENAI": "${env:OPENAI_API_KEY}"
      }
    }
  }
}
```

If `pipesets-mcp` is not on the client's PATH, use the absolute path to the installed script.

## Limits

Only the `/v1` routes accept API keys. The internal `/api/...` routes (everything except `v1`
commands) need a login session: run `eval "$(pipesets login you@example.com)"` to set
`PIPESETS_SESSION_TOKEN`, then pick the scope with `--tenant` / `--project`. `--user` / `PIPESETS_USER_ID`
only apply to a backend started with `AUTH_MODE=headers` (local development). The stdio MCP
server uses the internal routes, so give it `PIPESETS_SESSION_TOKEN` too; the remote one at
`/v1/mcp` takes an API key.
