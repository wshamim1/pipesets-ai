# Contributing to Pipesets AI

Thanks for helping. Bug reports, fixes, new tools, document loaders, LLM provider adapters and
docs are all welcome.

## Before you start

- **Small fixes** (typos, clear bugs): open a pull request directly.
- **Larger changes** (new nodes, API changes, schema migrations): open an issue first so we can
  agree on the approach before you spend time on it.
- **Security issues:** don't open a public issue. Follow [SECURITY.md](SECURITY.md).

## Set up

You need Python 3.12+ and Node.js 20.19+ or 22.12+. podman or docker is optional (sandboxed
custom tools).

```bash
git clone https://github.com/wshamim1/pipesets-ai.git
cd pipesets-ai
cp backend/.env.example backend/.env   # set DEFAULT_LLM_PROVIDER=mock to run without API keys
./start.sh                             # UI on :5173, API on :8000
```

See [Getting started](README.md#getting-started) for running the services in the foreground.

## Run the checks

CI runs these on every pull request. Run them locally first.

```bash
# Backend
cd backend
.venv/bin/python -m pip install -r requirements-dev.txt   # once
.venv/bin/python -m pytest

# Frontend
cd frontend
npm run lint
npm test
npm run build
```

Tests never call a real LLM: use the `mock` provider or stub the model call. Each backend test
module gets its own fresh database, so you can't break your local data.

## Where things go

| Adding | Where | Notes |
|---|---|---|
| A built-in tool | `backend/tools/` | One module per tool |
| A document loader | `backend/loaders/` | Placeholders live in `_planned.py` |
| An LLM provider | `backend/llm/` | Our own gateway; add a contract cassette in `backend/tests/gateway/llm_contract/` |
| A DB change | `backend/migrations/versions/` | Alembic; must upgrade and downgrade cleanly |
| An API route | `backend/routers/` | `/v1/*` is public: additive changes only |
| A backend test | `backend/tests/<area>/` | `apps`, `evals`, `gateway`, `knowledge`, `mcp_servers`, `observability`, `runtime`, `security`, `storage`, `tooling`; shared setup in `tests/conftest.py` and `tests/helpers.py`. Test file names must be unique across folders |

## Pull requests

- Keep each PR to one change, and add or update tests for it.
- Match the style of the code around you.
- Update the README or docs if behaviour visible to users changes.
- Never commit secrets, `.env` files, databases or logs (`.gitignore` covers them).
- Describe what changed and how you tested it.

## License

Pipesets AI is licensed under the [Apache License 2.0](LICENSE). By submitting a contribution
you agree it is licensed under the same terms (Apache-2.0, section 5), and that you have the
right to submit it.
