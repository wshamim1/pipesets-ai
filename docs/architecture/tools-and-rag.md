# Tools, MCP and RAG

## Tool registry

Built-in tools live in [backend/tools/](../../backend/tools/), grouped by category (`search`,
`data`, `communication`, `integrations`, `compute`, …). Any module, at any depth, that defines
`TOOL` (or `TOOLS` for several ids) and an async `run()` is registered automatically. Adding a
tool means adding one file.

```python
TOOL = ToolSpec(id="web_search", name="Web Search", category="search", ...)

async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> str:
    ...
```

The `ToolSpec` is the single source of truth. The `GET /api/tools` catalog, the Tool panel's
dropdowns (`selects`), missing-key checks (`required`) and the function schema offered to the
model (`parameters`) are all generated from it. Only declared parameters can reach `cfg`, so a
model can't override credentials or base URLs.

`tools.execute()` is the single entry point for running any tool, whether built-in, MCP or
custom. It decrypts `secret://` references and sealed values, so tools receive real values and
never decrypt anything themselves. It also enforces that only secrets of kind `tool` reach
tools, dispatches by id, and applies fallbacks.

`reload()` picks up added, edited or deleted tool modules without a restart. Runs already in
progress finish on the code they started with.

**Packages.** Each workspace installs the tools and MCP servers it wants
(`services/tool_packages.py`). The sidebar shows only installed ones. Uninstalling hides a tool,
but pipelines that already use it keep working.

## MCP servers

There are two kinds of MCP server:

- **Built-in servers** (`tools/mcp/<category>/<id>.py`) are launched over stdio by
  `tools/mcp/_stdio.py`. Each module declares its launch command and a `prepare()` that maps node
  config to arguments, environment variables and the MCP tool call. `discover()` lists the
  server's tools (`tools/list`), and each tool is offered to the model as a separate function.
- **Custom servers** (`routers/custom_mcp.py`) are added by users over stdio or HTTP, with OAuth
  support (`services/mcp_oauth.py`).

Going the other way, Pipesets also serves its own `/v1` API as an MCP server at `/v1/mcp`.

## Custom tools and the sandbox

Users can write Python tools by hand or generate them from a prompt. They can also be deployed as
code with the SDK (`pipesets tool`, `/v1/tools`). The code runs in `services/sandbox.py`:

| Backend | Isolation |
|---|---|
| `container` | podman or docker. No network by default, read-only root filesystem, dropped capabilities, memory, CPU and process limits, non-root user. |
| `remote` | The sandbox runner service (`sandbox_runner.py`) at `SANDBOX_URL`, which has its own podman. The backend needs no container engine, and the runner holds no secrets. |
| `local` | A hardened subprocess with a scrubbed environment. **Not real isolation.** Turn it off with `SANDBOX_REQUIRE_ISOLATION=1`. |
| `auto` | `remote` if `SANDBOX_URL` is set, otherwise `container` if a runtime is available, otherwise `local`. |

A tool's pip requirements are installed into a separate environment for that tool (a cached
image or venv keyed by a hash of the requirements), never into the backend's own environment.

## RAG

| Stage | Where |
|---|---|
| Document loaders (100+ types) | [backend/loaders/](../../backend/loaders/): `files`, `web`, `storage`, `databases`, `research` |
| Text splitters, embeddings | `routers/retrieval.py` |
| Vector stores | `services/vector_store.py` |
| Retrievers and rerankers | `routers/retrieval.py`, used by `llm_runner` |
| Knowledge bases | `routers/knowledge_base.py` |

**Loaders** use the same registry pattern as tools: a module with `LOADER = LoaderSpec(...)` and
`async def load(source, cfg)`. File-format loaders also define `EXTENSIONS` and a synchronous
`parse()`, so the Directory and S3 loaders can reuse them. Loaders that haven't been built yet
are listed in `loaders/_planned.py` and shown as "Soon".

**Vector stores.** Each collection lives in exactly one backend:

- `local`: chunks stored as JSON in the app database's `rag_chunks` table, with brute-force
  cosine search. Needs no setup and is fine up to a few thousand chunks.
- `pgvector`: one Postgres table per collection with an HNSW cosine index, registered in
  `pipesets_rag_collections` in that Postgres database.

Readers only need the collection name, because the backend is looked up from it. Retrieval
supports similarity, MMR and BM25, followed by an optional reranker.
