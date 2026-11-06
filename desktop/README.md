# Pipesets Desktop (v0)

A Tauri window around the existing React UI. On launch it starts the FastAPI backend from
`../backend/.venv` on a free `127.0.0.1` port with its own data folder, shows `loading.html` until `/health` answers,
then loads the app. Quitting the app stops the backend (a watchdog also stops it if the app
crashes or is force-quit).

## Run

Needs Rust (`rustup`), Node and a working `backend/.venv` (run `../start.sh` once).

The easiest way is the script in the repo root, which checks all of that first:

```bash
./start-desktop.sh              # backend from backend/.venv
./start-desktop.sh --packaged   # backend as the PyInstaller build (built if missing)
```

Or by hand:

```bash
cd desktop
npm install
npm run dev
```

`npm run dev` builds the UI into `desktop/dist` (plus `loading.html`) and starts the app.

| What | Where (macOS) |
|---|---|
| Data — DB, secrets key, uploads, optional `.env` | `~/Library/Application Support/ai.pipesets.desktop/` |
| Backend log | `~/Library/Logs/ai.pipesets.desktop/backend.log` |

The backend runs through `backend/desktop_main.py`. On first launch it **copies** the web
setup's `backend/pipesets.db`, `.secrets_master_key` and `uploads/` into the data folder, so
your pipelines, login and saved keys carry over. After that the two are separate: changes in
the desktop app don't show up in the web version, and vice versa. To start fresh, quit the
app and delete the data folder.

## Packaged backend

The installable app will ship the backend as a PyInstaller build instead of `backend/.venv`
(spec: `backend/pipesets-backend.spec`). To build it and run the app on it:

```bash
cd backend && .venv/bin/python -m pip install -r requirements-build.txt && cd ../desktop
npm run build:backend     # ~2 min → backend/dist/pipesets-backend/ (~217 MB)
npm run dev:packaged
```

Docling (and its torch / OCR stack) is left out of the build; the docling tool reports that
the package is missing. The first launch of a fresh build takes ~30 s while macOS scans the
new libraries; after that it starts in ~5 s.

## v0 limits

- Runs from this repo only — no installer yet (`bundle.active` is false).
- The first-launch copy includes your schedules, so running the web backend (`start.sh`) and
  the desktop app at the same time fires each scheduled pipeline twice.
- macOS tested only.
