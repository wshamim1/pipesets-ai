# 4. MCP servers

[MCP (Model Context Protocol)](https://modelcontextprotocol.io) is a standard way to offer tools to
a model. An MCP server exposes a set of tools: GitHub, Postgres, a filesystem, a browser. Pipesets
can **use** MCP servers in pipelines and can **be** an MCP server for other clients.

## Use a built-in MCP server

1. In Build, open **Tools & integrations → MCP Servers**. It lists the servers installed in your
   workspace; install others in **Settings → Tools & MCP packages** (or **📦 Browse N more MCP
   servers** in that section). See [Install more tools](03-tools.md#install-more-tools).
2. Drag a server onto the canvas and connect it to the LLM node.
3. Fill in what it needs, usually a token as a **secret** (e.g. the GitHub personal access token).
   A missing required key is named before anything starts.
4. Optionally pick **which of its tools** the model may use. Fewer tools means better choices and
   a smaller prompt.

### Built-in servers

Every stdio server runs a **pinned** package version, so a new release can't change what runs
without an update to Pipesets. **Read-only** is the default where a server offers it.

| Category | Servers |
|---|---|
| Web & Browser | Brave Search (Brave's own), Tavily, Exa, Perplexity, Fetch, Firecrawl, Playwright, Browserbase, Apify, PDF, Google Maps¹, remote HTTP / SSE |
| Databases & Data | Postgres and SQL databases (through a Connection), SQLite, MySQL, MongoDB, ClickHouse, BigQuery, Elasticsearch, Neon, MotherDuck, DynamoDB, Snowflake (community, official and managed), Databricks (community and managed), Redis (Redis's own), Kafka (Confluent), Supabase, Qdrant, Chroma, Neo4j, Pinecone |
| Developer Tools | GitHub (GitHub's own remote server), GitLab, Git, Filesystem, Docker, Podman, Kubernetes, Sentry, Stripe, OpenAPI, AWS Documentation, Netlify, Postman |
| DevOps & Observability | Datadog (Datadog's own), PostHog, Grafana, Prometheus |
| Productivity | Jira and Confluence (mcp-atlassian), Linear (Linear's own remote server), Notion, Asana, Trello, HubSpot, Airtable, Salesforce, Figma, Discord, Todoist, Slack¹, Google Drive¹ |
| AI & Memory | AWS Bedrock Knowledge Bases (AWS's own), Hugging Face (Hugging Face's own), Context7, Time, Memory, Sequential Thinking, Everything |

¹ The upstream reference server is deprecated and has no maintained replacement yet. It's pinned
to its last release and still runs. Puppeteer is hidden from the list (use Playwright); pipelines
that already use it keep working.

GitHub and Linear run on the vendor's own remote server with your token in the `Authorization`
header, so nothing is installed. Their read-only setting uses GitHub's `X-MCP-Readonly` header and
Linear's `/mcp/readonly` endpoint.

### Databricks and Snowflake servers

| Server | What it is | Set |
|---|---|---|
| **Databricks** | Community server (`databricks-mcp-server`): clusters, jobs, notebooks, DBFS, repos, libraries, SQL, Unity Catalog. With input it runs the input as SQL; without, it lists clusters. | Host, token, optionally a SQL warehouse ID |
| **Databricks Managed** | The MCP servers your Databricks workspace hosts: **Databricks SQL**, a **Genie space**, the **Unity Catalog functions** of a schema, or **Vector Search** indexes of a schema | Host, token, the server type, and the Genie space ID or catalog and schema |
| **Snowflake** | Community server (`mcp-server-snowflake`): query, list and describe tables | Account, user, password, database |
| **Snowflake (official)** | Snowflake-Labs' server: SQL, Cortex Search, Cortex Analyst, semantic views, object management | Account, user, password or programmatic access token; optionally a Cortex Search service (`DB.SCHEMA.SERVICE`) and a semantic view or model for Analyst |
| **Snowflake Managed** | An MCP server object created in your Snowflake account (`CREATE MCP SERVER`) | Account, token, and the server as `DB.SCHEMA.NAME` |

The **managed** servers' tools depend on your workspace or account, so they have no default tool:
open the node, list the server's tools and pick one. **Snowflake (official)** is read-only by default:
only SELECT and DESCRIBE run, and its create / alter / drop tools are off until you choose **Read and
write**.

## Add your own MCP server

**Tools & integrations → MCP Servers → + Add Custom MCP Server.** Start from a template (Postgres,
Filesystem, Git, SQLite, GitHub, GitLab, Docker, Kubernetes, Playwright, Fetch, Brave Search,
Firecrawl, Notion, Linear, Jira, Remote) or fill it in yourself. Templates use pinned versions;
GitHub and Linear fill in the vendor's remote URL and a token header to complete.

| Transport | Use for | Fill in |
|---|---|---|
| **stdio** | A server started as a program on the Pipesets server | **Executable** (e.g. `npx`, `uvx`), **Arguments** (e.g. `-y some-mcp-server@1.2.3 --read-only`), environment variables as JSON |
| **HTTP** (Streamable HTTP) | A remote server at a URL (the current standard) | **Server URL**, and headers as JSON (e.g. `{"Authorization": "Bearer …"}`) |
| **SSE** | Older remote servers (HTTP + SSE) | Server URL and headers |

Then:

1. **Test / discover** to list the server's tools and check it responds.
2. **Save.** It appears in the MCP Servers list and can be dragged into any pipeline.

### Remote servers that need sign-in (OAuth)

Some remote servers ask you to sign in instead of taking a token. Save the server, then click
**OAuth → Connect**. A sign-in window opens; once you approve, the server shows **✅ Connected** and
Pipesets refreshes the token itself. **Reconnect** if access is revoked, and disconnect to remove
the stored token. Behind a proxy, set `PIPESETS_PUBLIC_URL` so the sign-in can return to Pipesets.

### Safety

- stdio servers run programs on your server. Only add packages you trust, and pin versions
  (`npx -y some-server@1.2.3`).
- Remote servers can't reach private network addresses unless the server allows it
  (`EXTERNAL_AGENT_ALLOW_PRIVATE`, `EXTERNAL_AGENT_ALLOWED_HOSTS`).
- Put tokens in **Secrets**, not in arguments.

## Use Pipesets as an MCP server

Your published pipelines can be called from Claude Code, Claude Desktop, Cursor or any MCP client.
The server is at `/v1/mcp` (Streamable HTTP), signed in with a Pipesets API key.

1. **Settings → API keys → New key.** Scopes: `apps:read` and `apps:run` to list and run apps.
   Optional: `apps:write` (edit drafts) and `apps:publish` (publish through the eval gate).
2. Add the server to your client, e.g. Claude Code:

   ```bash
   claude mcp add --transport http pipesets https://<your-host>/v1/mcp \
     --header "Authorization: Bearer ps_..."
   ```

3. The client gets tools such as `list_apps`, `get_app`, `run_app` and `resume_run`, plus
   `create_app`, `update_app` and `publish_app` with the write scopes.

Notes:

- Provider keys go in headers (`X-Provider-Key-Openai: sk-…`); without them, runs use the
  project's or server's keys.
- A run that stops at a Human Gate is reported to the client, but **a person approves it in
  Pipesets**. The model can't approve its own gate.
- Every write is in the audit log under the key's owner.
- `pipesets-mcp` in the SDK is an older stdio server with more tools (drafts, traces, export);
  see [sdk/README.md](../../sdk/README.md).
