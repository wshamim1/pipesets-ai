# Frontend

The frontend is a React 19 and TypeScript app built with Vite. The canvas uses React Flow
(`@xyflow/react`). It has two entry points:

| Entry | File | What it is |
|---|---|---|
| Builder | `index.html` → `src/main.tsx` → `App.tsx` | The signed-in app: Apps, Build, Evaluate, Monitor, Automation, Marketplace, Lab, Settings |
| Chat page | `chat.html` → `src/chat/main.tsx` | The public chat-link page (`/c/<token>`). It's small and loads none of the builder. |

## Structure

| Folder | Contents |
|---|---|
| `App.tsx` | Top-level views, the canvas, and the wiring between hooks and panels |
| `components/` | Views and panels. Subfolders: `config/` (one settings panel per node type), `eval/`, `ops/` (Monitor and admin), `settings/`, `marketplace/`, `docs/` |
| `nodes/` | One React Flow component per canvas node type, registered in `nodes/index.ts` |
| `hooks/` | `useFlowManager` (nodes, edges, selection), `useFlowHistory` (undo and redo), `useAppManager` (load, save, publish, rename, delete), `useCatalogData` (tools, models, published apps), `useSidebarState` |
| `context/` | `AuthContext` (session), `TenantContext` (tenant and project), `CredentialsContext` (browser-held provider keys), `ExecutionContext` (live run state) |
| `utils/` | API helpers, pipeline validation, secrets, run logs, exports |
| `blueprints/` | Starter blueprints shown in the Apps hub |

## Talking to the backend

- The base URL is `API_BASE` (in `types.ts`), set from `VITE_API_BASE`. Behind nginx, the UI
  calls `/api` on its own origin, and nginx proxies it to the backend.
- Every request carries the session token in a header, plus `x-tenant-id` and `x-project-id`.
- Runs stream as server-sent events. `PromptRunner.tsx` reads them from `/api/run/stream` and
  draws tokens, tool calls, steps and cost as they arrive.

## The canvas and runs

The flow lives in `useFlowManager` as React Flow nodes and edges. `utils/pipelineValidation.ts`
checks the graph as you edit it. For a canvas run, the browser works out what is attached to the
LLM node and sends it as one request, so unsaved changes can run. Saving sends the whole flow to
`PUT /api/apps/{id}`. The server rejects plaintext credentials, so key fields use secret pickers
(`ToolSecretFields`, `SecretModal`).

## Adding a node type

1. Add a component in `nodes/` and register it in `nodes/index.ts`.
2. Add its settings panel in `components/config/`.
3. Add it to the sidebar (`Sidebar.tsx`) and to validation.
4. Teach the backend about it: wiring resolution in `pipeline_runner.py`, and the runner that
   executes it.
5. Add tests next to the component (`*.test.tsx`, Vitest).

Run the checks with `npm run lint`, `npm test` and `npm run build`.
