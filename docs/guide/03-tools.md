# 3. Tools

A tool is something the model can do besides writing text: search the web, query a database, post
to Slack, run Python. You attach tools to an LLM node (or an agent). The model decides when to
call them, with which arguments, and uses the result in its answer.

## Add a built-in tool

1. In Build, open **Tools & integrations** in the sidebar. It lists the tools **installed** in your
   workspace, in groups: Data & Files, Productivity, Research & Knowledge, Communication, Business
   Apps, Code & Compute, Web Search, Everyday Utilities, APIs & Integrations, DevOps & Observability.
   Don't see the one you need? Install it first ([below](#install-more-tools)).
2. Drag the tool onto the canvas and **connect it to the LLM node** that should use it.
3. Click the tool and fill in its settings:
   - **Description for LLM Agent:** when the model should use it. The default is usually fine; make
     it specific if the model calls the wrong tool.
   - **Credentials:** pick a **secret** for keys and tokens (e.g. GitHub token, Brave API key). A
     red warning lists any setting the tool can't run without.
   - **Data Source Connection:** for database and storage tools, pick a Connection node.
4. In the LLM's system prompt, say when to use it: "Use Web Search for anything after 2025."

Some tools work with no setup (Calculator, Wikipedia, DuckDuckGo Search). Others need
a key in Secrets or an environment variable on the server (`TAVILY_API_KEY`, `GITHUB_TOKEN`,
`NOTION_TOKEN`, `SLACK_BOT_TOKEN`, …).

**Typed tools.** Many tools take real arguments (e.g. a query and a result count) rather than one
text input. The model sees them as a function signature, which makes calls more reliable.

## Install more tools

There are about 145 built-in tools. To keep the sidebar short, only the ones your workspace has
**installed** appear there; the rest wait in the package manager.

1. Open **Settings → Tools & MCP packages**, or click **📦 Browse N more tools** at the bottom of
   the sidebar's Tools section.
2. Pick **Tools** or **MCP servers**, then search or filter by category. **Not installed** shows
   what you can add.
3. Click **Install** on a card (or **Install all N matching** after a search, e.g. "snowflake"). The
   tool appears in the sidebar straight away.

What's installed to begin with: a starter set (web search, scraping, Wikipedia, calculator, Python,
REST, file / CSV / PDF readers, SQL, summarise, extract, email, Slack, weather, translation), plus
every tool a pipeline in the workspace already uses.

- **Uninstall** only hides a tool from the sidebar. Pipelines that use it keep running, and their
  nodes still open and configure as before.
- The choice is for the **whole workspace**. Installing needs write access to tools; anyone can
  browse. Each change is in the audit log. **Reset to defaults** forgets every choice.
- Custom tools, custom MCP servers and frameworks are always shown; they aren't packages.

## Databricks and Snowflake tools

Install them in **Settings → Tools & MCP packages** (search "databricks" or "snowflake").

**Databricks** tools call the workspace REST API. Set **host** (the workspace URL, e.g.
`adb-123.azuredatabricks.net`) and **token** (a personal access token or service principal token, as
a secret) on each node. The model passes the job, run, cluster or pipeline ID per call.

| Tool | Does |
|---|---|
| Databricks SQL | A read-only query on a SQL warehouse (needs the warehouse's HTTP path and `databricks-sql-connector`) |
| List Jobs · Run Job · Cancel Run | Find jobs, start one (with job parameters), cancel a run |
| Job Status · Job Runs · Job Logs | A job's latest state and history, a run's output and errors |
| List Clusters · Cluster Control · Cluster Status / Logs / Events | Clusters by state; start, restart or terminate one; its details, driver logs and events |
| SQL Warehouses | Warehouses with state, size and the HTTP path to connect with |
| Unity Catalog | Browse catalogs → schemas → tables, or describe a table's columns |
| Volume Files · Workspace Files | List or read files under `/Volumes/...`; list workspace paths |
| Notebook Run · Notebook Status | Run a notebook on a cluster; check a notebook exists and its type |
| Model Serving | Query a serving endpoint (text is sent as a chat message, a JSON object as the request body) |
| Vector Search | Similarity search on a Vector Search index (set the index and the columns to return) |
| Genie | Ask an AI/BI Genie space a question; get the answer, its SQL and the result rows |
| Pipeline | A Lakeflow / Delta Live Tables pipeline's state and recent updates, or start an update |

**Snowflake** tools call Snowflake's REST and SQL APIs, so no driver is needed. Set **account**
(e.g. `myorg-myaccount`) and **token**, a programmatic access token by default (switch **Token
type** for OAuth or a key-pair JWT). Warehouse, database, schema and role are optional defaults
for SQL. Names are given fully qualified, e.g. `DB.SCHEMA.TASK`.

| Tool | Does |
|---|---|
| Snowflake SQL (REST) | One read statement (SELECT / SHOW / DESCRIBE / WITH / EXPLAIN) |
| Snowflake | The same, through `snowflake-connector-python` with user and password (install it first) |
| Warehouses · Warehouse Control | List warehouses; resume or suspend one |
| Catalog | Browse databases → schemas → tables, or describe a table |
| Query History | Recent queries, optionally only failed or running ones |
| Task | A task's state, schedule and last runs; or run, resume or suspend it |
| Pipe Status · Copy History · Stage Files | Snowpipe state, recent file loads into a table, files in a stage |
| Cortex Complete | A prompt to an LLM hosted in Snowflake Cortex (set the model) |
| Cortex Search | Search a Cortex Search service (`DB.SCHEMA.SERVICE`) |
| Cortex Analyst | A plain-language question over a semantic view or model; returns the SQL and, if it's a read statement, its rows |

SQL tools refuse anything but read statements. Names that aren't valid identifiers are rejected
before they reach Snowflake.

## Connections

A **Connection** holds credentials for a database or service: Postgres, MySQL, MongoDB, Redis,
Snowflake, S3, SQLite or a custom REST API.

1. **Tools & integrations → + Add Connection** (or drag a Connection node).
2. Pick the type (or a **Quick Preset**), fill in host, database, user and password, and **test** it.
3. Drag the Connection onto the canvas and connect it to the tool or Doc Loader that uses it.

Passwords are encrypted. Lab's test databases (see [Settings and admin](11-settings-admin.md#lab))
are a quick way to try database tools.

## Secrets

Never type a key into a node; a pipeline can't be saved that way. Instead:

1. **Settings → Secrets → New secret.** Name it (e.g. `slack-bot-token`) and paste the value.
2. In the tool's key field, pick the secret by name.

The value is encrypted and only decrypted when the tool runs. Rotating the secret updates every
pipeline that uses it.

## Toolkits

A **Toolkit** bundles several tools into one node, e.g. "CRM toolkit" = Salesforce lookup +
HubSpot lookup + email. Use it when the same set of tools goes into many pipelines.

1. Drag a **Toolkit** node and give it a label and description.
2. Add its **sub-tools**.
3. Choose how they're shown to the agent (**Agent Exposure**), and connect the toolkit to the LLM node.

## Custom tools

Write your own tool in Python when nothing built-in fits: an internal API, a calculation, a lookup.

### In the UI

1. **Tools & integrations → + Create Custom Tool.** Or **↑ Upload .py** to load a file, or describe
   it in the ✨ box to have one written for you.
2. **Code tab.** Define one function with `@tool`. Its typed parameters become what the model calls:

   ```python
   from pipesets import tool


   @tool(description="Look up a tenant's lease end date by unit")
   def lease_end(property_code: str, unit: str, *, config) -> str:
       """Find when a unit's lease ends.

       Args:
           property_code: Yardi property code, e.g. mg01
           unit: Unit or suite number
       """
       # config holds the Config Keys values (secrets decrypted)
       ...
       return "2034-12-31"
   ```

   - Parameter types and the `Args:` docstring become the function the model sees.
   - `config` (keyword-only) holds the tool's settings.
   - Return a string (or something that turns into one).
   - The older form `run(input_text, config)` still works; the model then sends one text string.

3. **Config tab.** Add **Config Keys** (e.g. `api_base`, `api_token`). Each node using the tool fills
   them in, and secrets can be picked.
4. **Packages tab.** List pip packages the code needs (e.g. `requests`). They're installed into the
   tool's sandbox, not the server.
5. **Test tab.** Run it with sample arguments and config before saving.
6. **Save.** The tool appears in the sidebar under custom tools. Every save is a new **version**;
   pin a version per node, or roll back from the **Versions** tab.

### Where custom code runs

Custom tools run in a **container sandbox** (podman or docker) with time and memory limits. With
no container engine, they run in a local subprocess, unless the server sets
`SANDBOX_REQUIRE_ISOLATION=1`, in which case they fail instead. Use the sandbox for anything
customers or other teams can edit.

### As code, with the SDK

For tools you keep in git and deploy from CI:

```bash
pip install -e "sdk[test]"
pipesets tool init lease_lookup && cd lease_lookup   # tool.py, pipesets.toml, requirements.txt, tests/
pipesets tool test                                   # pytest, no server needed
pipesets tool run --args '{"property_code": "mg01", "unit": "100"}'
export PIPESETS_API_KEY=ps_...                       # key with tools:write (+ tools:execute for --remote)
pipesets tool deploy --note "$(git rev-parse --short HEAD)"
pipesets tool versions && pipesets tool rollback 2
```

Tools deployed from the SDK are read-only in the UI: change them in code, or fork them. See
[sdk/README.md](../../sdk/README.md).

## Tips

- **Fewer tools, better calls.** Give an LLM node only the tools it needs; split big jobs across agents.
- **Name and describe tools for the model**, not for people: what it does, when to use it, what it returns.
- **Watch the trace.** **Monitor → Traces** shows every tool call with its arguments and result.
