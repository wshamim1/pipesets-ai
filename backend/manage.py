"""
manage.py — operator CLI for the backend (run from the backend directory).

  python manage.py create-key --name "Acme prod" [--tenant T --project P --user U]
                              [--scope apps:read --scope apps:run] [--rpm 60] [--expires-days 90]
  python manage.py list-keys [--tenant T] [--project P]
  python manage.py revoke-key KEY_ID [--tenant T]
  python manage.py set-password EMAIL        (prompts; or pipe the password on stdin)
  python manage.py server-admin EMAIL [--revoke] | --list
                                             who may manage the server itself (Settings → Database)
  python manage.py db setup                  create/upgrade the schema in DATABASE_URL and seed demo data
  python manage.py db sql                    print the DDL for DATABASE_URL's database instead of running it
  python manage.py db copy --to URL [--overwrite] [--skip-orphans]
                                             copy every row from DATABASE_URL's database into URL's
                                             (e.g. SQLite → Postgres); then point DATABASE_URL at it
  python manage.py rotate-secrets            re-encrypt every secret under the primary master key
  python manage.py kms-wrap-key --key-id K [--wrap-current]
                                             print a KMS-encrypted master key for PIPESETS_MASTER_KEY_KMS
  python manage.py worker [--concurrency N] [--once]
                                             work the job queue (scheduled / webhook runs, notifications)
                                             and take turns at the periodic loops (scheduler tick, sweeps);
                                             run with PIPESETS_WORKER=external on the API processes

Keys act as --user inside --tenant/--project (defaults: the seeded demo ids), so
that user's ACLs decide what the key can reach. The plaintext key is printed once.
"""

import argparse
import getpass
import os
import sys

from dotenv import load_dotenv

load_dotenv()  # DATABASE_URL etc. from backend/.env, before db reads them

from db import BACKEND_DIR, get_db_connection, init_db, safe_database_url  # noqa: E402
from services import api_keys, auth, secret_store
from services.request_context import RequestContext


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="manage.py", description="Backend operator commands")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-key", help="Issue an API key for the /v1 API")
    create.add_argument("--name", required=True)
    create.add_argument("--tenant", default="tenant_demo")
    create.add_argument("--project", default="proj_research")
    create.add_argument("--user", default="user_admin", help="User the key acts as")
    create.add_argument("--scope", action="append", choices=api_keys.SCOPES,
                        help="Repeatable; default: all scopes")
    create.add_argument("--rpm", type=int, default=60, help="Requests per minute (0 = unlimited)")
    create.add_argument("--expires-days", type=int)

    ls = sub.add_parser("list-keys", help="List API keys (never shows secrets)")
    ls.add_argument("--tenant", default="tenant_demo")
    ls.add_argument("--project")

    revoke = sub.add_parser("revoke-key", help="Revoke an API key immediately")
    revoke.add_argument("key_id")
    revoke.add_argument("--tenant", default="tenant_demo")

    setpw = sub.add_parser("set-password", help="Set a user's login password (ends their sessions)")
    setpw.add_argument("email")

    sadmin = sub.add_parser("server-admin", help="Grant, revoke or list server admins")
    sadmin.add_argument("email", nargs="?")
    sadmin.add_argument("--revoke", action="store_true")
    sadmin.add_argument("--list", action="store_true")
    sub.add_parser("rotate-secrets", help="Re-encrypt all secrets with the primary master key")

    kms = sub.add_parser("kms-wrap-key", help="Print a KMS-encrypted master key for PIPESETS_MASTER_KEY_KMS")
    kms.add_argument("--key-id", required=True, help="KMS key ARN, id or alias (e.g. alias/pipesets)")
    kms.add_argument("--wrap-current", action="store_true",
                     help="Encrypt the key in PIPESETS_MASTER_KEY instead of generating a new one")

    worker = sub.add_parser("worker", help="Work the background job queue until stopped")
    worker.add_argument("--concurrency", type=int, help="Jobs at once (default WORKER_CONCURRENCY or 4)")
    worker.add_argument("--once", action="store_true", help="Run what is due now, then exit")

    dbcmd = sub.add_parser("db", help="Database schema commands")
    dbcmd.add_argument("action", choices=["setup", "sql", "copy"])
    dbcmd.add_argument("--to", help="copy: the target database URL (any SQLAlchemy URL)")
    dbcmd.add_argument("--overwrite", action="store_true", help="copy: replace data already in the target")
    dbcmd.add_argument("--skip-orphans", action="store_true",
                       help="copy: leave out rows whose parent row no longer exists")

    args = parser.parse_args(argv)

    if args.command == "db":
        if args.action == "copy":
            return db_copy(args.to, args.overwrite, args.skip_orphans)
        return db_command(args.action)
    if args.command == "kms-wrap-key":
        return kms_wrap_key(args.key_id, args.wrap_current)

    init_db()

    if args.command == "worker":
        return run_worker(args.concurrency, args.once)
    if args.command == "create-key":
        ctx = RequestContext(tenant_id=args.tenant, project_id=args.project, user_id=args.user)
        plaintext, rec = api_keys.create_key(ctx, args.name, args.scope, args.rpm, args.expires_days)
        print(f"Created {rec['id']} ({rec['name']}) for {rec['tenant_id']}/{rec['project_id']} as {rec['created_by']}")
        print(f"Scopes: {', '.join(rec['scopes'])} · {rec['rate_limit_rpm']} req/min"
              + (f" · expires {rec['expires_at']}" if rec["expires_at"] else ""))
        print(f"\n  {plaintext}\n\nStore this key now — it will not be shown again.")
        return 0

    if args.command == "list-keys":
        keys = api_keys.list_keys(args.tenant, args.project)
        if not keys:
            print("No API keys.")
        for k in keys:
            state = "active" if k["active"] else ("revoked" if k["revoked_at"] else "expired")
            print(f"{k['id']}  {k['key_prefix']}…  {state:8} {k['project_id']:16} {k['name']}"
                  f"  ({k['request_count']} req, last used {k['last_used_at'] or 'never'})")
        return 0

    if args.command == "revoke-key":
        if api_keys.revoke_key(args.key_id, args.tenant):
            print(f"Revoked {args.key_id}")
            return 0
        print(f"No active key {args.key_id} in tenant {args.tenant}", file=sys.stderr)
        return 1
    if args.command == "server-admin":
        if args.list or not args.email:
            admins = auth.list_server_admins()
            for a in admins:
                note = "" if a["has_password"] else "  (no password — can't sign in)"
                print(f"{a['email']:32} {a['id']:16} {a['status']:8} via {a['source']}{note}")
            if not admins:
                print("No server admins. The next account to sign up becomes one.")
            return 0
        user_id = auth.set_server_admin(args.email, not args.revoke)
        if not user_id:
            print(f"No user with email {args.email}", file=sys.stderr)
            return 1
        print(f"{'Revoked' if args.revoke else 'Granted'} server admin: {args.email} ({user_id})")
        return 0
    if args.command == "rotate-secrets":
        print(f"Re-encrypted {secret_store.rotate_all()} secret(s) with the primary master key.")
        return 0
    if args.command == "set-password":
        conn = get_db_connection()
        row = conn.execute("SELECT id FROM users WHERE email = ?", (args.email.strip().lower(),)).fetchone()
        conn.close()
        if not row:
            print(f"No user with email {args.email}", file=sys.stderr)
            return 1
        if sys.stdin.isatty():
            password = getpass.getpass("New password: ")
            if password != getpass.getpass("Repeat: "):
                print("Passwords do not match", file=sys.stderr)
                return 1
        else:
            password = sys.stdin.readline().rstrip("\n")
        if len(password) < auth.MIN_PASSWORD_LENGTH:
            print(f"Password must be at least {auth.MIN_PASSWORD_LENGTH} characters", file=sys.stderr)
            return 1
        auth.set_password(row["id"], password)
        print(f"Password set for {args.email} ({row['id']})")
        return 0
    return 2


def run_worker(concurrency, once: bool) -> int:
    """Work the queue and run the periodic loops (they take turns with the API processes');
    SIGTERM / SIGINT stop claiming and give running jobs time to finish."""
    import asyncio
    import signal

    from services import jobs

    async def go() -> None:
        kinds = jobs.load_handlers()
        w = jobs.Worker(concurrency=concurrency)
        if once:
            await w.drain()
            return
        loop = asyncio.get_running_loop()
        stopping = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stopping.set)
        print(f"Worker {w.id} on {safe_database_url()} — kinds: {', '.join(kinds) or 'none'}", flush=True)
        print(f"Periodic loops: {', '.join(jobs.start_periodic()) or 'none'}", flush=True)
        if port := int(os.getenv("WORKER_METRICS_PORT", "0") or 0):
            from prometheus_client import start_http_server
            from services import telemetry
            start_http_server(port, registry=telemetry.REGISTRY)   # GET :<port>/metrics for Prometheus
            print(f"Metrics on :{port}/metrics", flush=True)
        task = asyncio.create_task(w.run())
        await stopping.wait()
        print("Stopping: waiting for running jobs…", flush=True)
        await jobs.stop_periodic()
        await w.stop(grace_seconds=float(os.getenv("WORKER_GRACE_SECONDS", "30")))
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        from services import telemetry
        telemetry.shutdown()

    asyncio.run(go())
    return 0


def db_command(action: str) -> int:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.exc import SQLAlchemyError

    if action == "sql":
        cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
        command.upgrade(cfg, "head", sql=True)
        return 0

    print(f"Database: {safe_database_url()}")
    try:
        init_db()
    except ModuleNotFoundError as e:
        print(f"Database driver not installed: {e.name} (see requirements.txt)", file=sys.stderr)
        return 1
    except SQLAlchemyError as e:
        print(f"Could not set up the database: {e}", file=sys.stderr)
        return 1
    print("Schema is up to date; demo tenant seeded.")
    return 0


def db_copy(target: str, overwrite: bool, skip_orphans: bool) -> int:
    from sqlalchemy.exc import SQLAlchemyError

    from db import DATABASE_URL
    from services.db_copy import CopyError, copy_database

    if not target:
        print("Give the target with --to, e.g. --to postgresql+psycopg2://user:pass@host:5432/pipesets",
              file=sys.stderr)
        return 2
    print(f"From: {safe_database_url()}")
    try:
        report = copy_database(DATABASE_URL, target, overwrite=overwrite, skip_orphans=skip_orphans, progress=print)
    except CopyError as e:
        print(f"Not copied: {e}", file=sys.stderr)
        return 1
    except ModuleNotFoundError as e:
        print(f"Database driver not installed: {e.name} (see requirements.txt)", file=sys.stderr)
        return 1
    except SQLAlchemyError as e:
        print(f"Not copied — the target was left unchanged: {e}", file=sys.stderr)
        return 1
    print(f"\nCopied {report.total} rows in {len(report.rows)} tables; row counts match.")
    if report.created:
        print(f"Created from the source: {', '.join(report.created)}")
    if report.orphans:
        print(f"Left out (parent row missing): {', '.join(f'{t} {n}' for t, n in report.orphans.items())}")
    print("\nNext:\n  1. Set DATABASE_URL to the new database and restart the backend.\n"
          "  2. Keep the same PIPESETS_MASTER_KEY (or KMS / Vault setting) — secrets are copied still encrypted.\n"
          "  3. Uploaded files are in the data directory, not the database: move it too if the server changes.")
    return 0


def kms_wrap_key(key_id: str, wrap_current: bool) -> int:
    from services import master_key

    current = ""
    if wrap_current:
        current = os.getenv("PIPESETS_MASTER_KEY", "").split(",")[0].strip()
        if not current:
            print("PIPESETS_MASTER_KEY is not set — nothing to wrap.", file=sys.stderr)
            return 1
    blob = master_key.kms_wrap(key_id, current or None)
    print(f"PIPESETS_MASTER_KEY_KMS={blob}")
    if not wrap_current:
        print("\nThis is a new key. To move existing secrets to it, set PIPESETS_MASTER_KEY_KMS to the new "
              "blob followed by a comma and a blob made with --wrap-current, then run rotate-secrets.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
