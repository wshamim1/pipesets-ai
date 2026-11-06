"""
desktop_main.py — backend entry point for the desktop app (desktop/).

    python desktop_main.py --port 58088 [--import-from /path/to/old/backend]

The desktop shell sets PIPESETS_DATA_DIR to its app-data folder before starting this.
It then:
  1. starts a watchdog that exits when the desktop app's process goes away, so a crash or
     force-quit doesn't leave the backend running;
  2. on first launch (no DB in the data folder yet), copies the DB, the secrets master key
     and uploads from --import-from, so existing pipelines, logins and saved secrets carry
     over — copied, never moved, so the web setup keeps working;
  3. serves the API on 127.0.0.1 only, to the app's own webview (CORS_ORIGINS / ALLOWED_HOSTS).
"""

import argparse
import os
import shutil
import sqlite3
import sys
import threading
import time


def _watch_parent() -> None:
    parent = os.getppid()

    def watchdog() -> None:
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(0)

    threading.Thread(target=watchdog, daemon=True, name="parent-watchdog").start()


def _import_existing_data(src_dir: str, data_dir: str) -> None:
    """First launch only: copy DB, master key and uploads from an older install."""
    dst_db = os.path.join(data_dir, "pipesets.db")
    src_db = os.path.join(src_dir, "pipesets.db")
    if os.path.exists(dst_db) or not os.path.exists(src_db):
        return
    print(f"[desktop] First launch: importing data from {src_dir}", flush=True)

    # sqlite backup API: a consistent copy even if the web backend is using the DB right now
    src, dst = sqlite3.connect(src_db), sqlite3.connect(dst_db)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()

    # Without the same key, secrets sealed in the copied DB couldn't be decrypted
    src_key = os.path.join(src_dir, ".secrets_master_key")
    dst_key = os.path.join(data_dir, ".secrets_master_key")
    if os.path.exists(src_key) and not os.path.exists(dst_key):
        shutil.copy2(src_key, dst_key)
        os.chmod(dst_key, 0o600)

    src_uploads = os.path.join(src_dir, "uploads")
    if os.path.isdir(src_uploads):
        shutil.copytree(src_uploads, os.path.join(data_dir, "uploads"), dirs_exist_ok=True)


def main() -> None:
    # The frozen build has no `python -c`; services/sandbox.py runs this binary with
    # --sandbox-exec <cpu> <mem_mb> to execute sandboxed code from stdin instead.
    if len(sys.argv) > 1 and sys.argv[1] == "--sandbox-exec":
        from services.sandbox import _LOCAL_BOOTSTRAP
        sys.argv = ["sandbox", *sys.argv[2:]]
        exec(compile(_LOCAL_BOOTSTRAP, "<sandbox-bootstrap>", "exec"), {"__name__": "__main__"})
        return

    parser = argparse.ArgumentParser(description="Pipesets backend for the desktop app")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--import-from", default="", help="backend folder to copy data from on first launch")
    args = parser.parse_args()

    if not os.getenv("PIPESETS_DATA_DIR"):
        sys.exit("PIPESETS_DATA_DIR must be set (the desktop app sets it).")
    _watch_parent()

    from paths import CODE_DIR, DATA_DIR  # after the env check: creates DATA_DIR
    if args.import_from and os.path.abspath(args.import_from) != DATA_DIR:
        _import_existing_data(os.path.abspath(args.import_from), DATA_DIR)

    # Only the app's own webview may call the API, and only via a loopback Host header,
    # so a web page open in the user's browser can't read from (or DNS-rebind onto) it.
    # A bundled build serves the UI from tauri://localhost (macOS/Linux) or
    # http(s)://tauri.localhost (Windows), but `tauri dev` serves it from
    # http://127.0.0.1:<random port> — a different origin on every launch, so the
    # loopback regex covers that (any loopback dev server, as the Vite default already is).
    os.environ.setdefault("CORS_ORIGINS", "tauri://localhost,http://tauri.localhost,https://tauri.localhost")
    os.environ.setdefault("CORS_ORIGIN_REGEX", r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$")
    os.environ.setdefault("ALLOWED_HOSTS", "127.0.0.1,localhost")

    os.chdir(CODE_DIR)
    sys.path.insert(0, CODE_DIR)
    print(f"[desktop] data folder: {DATA_DIR}", flush=True)

    # Imported directly (not as "main:app") so PyInstaller bundles the whole app
    import uvicorn
    from main import app
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
