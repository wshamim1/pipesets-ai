"""`pipesets` command line interface. Wraps PipesetsClient; no dependencies beyond httpx."""

import argparse
import getpass
import json
import sys
from typing import Any, List, Optional

from .client import EXPORT_FORMATS, PipesetsClient, PipesetsError


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def _table(rows: List[dict], columns: List[str]) -> None:
    if not rows:
        print("(none)")
        return
    widths = [max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns]
    print("  ".join(c.upper().ljust(w) for c, w in zip(columns, widths)))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(w) for c, w in zip(columns, widths)))


def _parse_keys(pairs: Optional[List[str]]) -> dict:
    keys = {}
    for pair in pairs or []:
        provider, sep, key = pair.partition("=")
        if not sep or not key:
            raise PipesetsError(f"--provider-key expects PROVIDER=KEY, got '{pair}'")
        keys[provider.strip().lower()] = key.strip()
    return keys


# ── command handlers ──────────────────────────────────────────────────────────

def cmd_health(c: PipesetsClient, a: argparse.Namespace) -> int:
    _print_json(c.health())
    return 0


def cmd_login(c: PipesetsClient, a: argparse.Namespace) -> int:
    password = getpass.getpass("Password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
    data = c.login(a.email, password)
    tenants = ", ".join(f"{t['name']} ({t['role']})" for t in data["tenants"]) or "none"
    print(f"Signed in as {data['user']['email']} · tenants: {tenants}", file=sys.stderr)
    print(f"Session expires {data['expires_at']}. To use it:", file=sys.stderr)
    print(f"export PIPESETS_SESSION_TOKEN={data['token']}")
    return 0


def cmd_whoami(c: PipesetsClient, a: argparse.Namespace) -> int:
    _print_json(c.me())
    return 0


def cmd_apps(c: PipesetsClient, a: argparse.Namespace) -> int:
    if a.action == "list":
        apps = c.list_apps()
        if a.json:
            _print_json(apps)
        else:
            _table(apps, ["id", "name", "status", "version", "updated_at"])
    elif a.action == "get":
        _print_json(c.get_app(a.app_id))
    elif a.action == "publish":
        app = c.publish_app(a.app_id)
        print(f"Published '{app['name']}' as v{app['version']}")
    elif a.action == "delete":
        c.delete_app(a.app_id)
        print(f"Deleted {a.app_id}")
    return 0


def cmd_pipelines(c: PipesetsClient, a: argparse.Namespace) -> int:
    pipelines = c.list_pipelines()
    if a.json:
        _print_json(pipelines)
    else:
        _table(pipelines, ["id", "name", "version", "node_count", "runnable"])
    return 0


def cmd_run(c: PipesetsClient, a: argparse.Namespace) -> int:
    result = c.run_pipeline(a.app_id, a.prompt, a.timeout_ms, _parse_keys(a.provider_key))
    if a.json:
        _print_json(result)
    elif result.get("ok"):
        print(result["output"])
    else:
        print(result.get("error") or "Run failed", file=sys.stderr)
    return 0 if result.get("ok") else 1


def cmd_stream(c: PipesetsClient, a: argparse.Namespace) -> int:
    fields = {}
    if a.app_id:
        fields["app_id"] = a.app_id
    if a.session_id:
        fields["session_id"] = a.session_id
    for event in c.stream(a.prompt, **fields):
        if a.json:
            print(json.dumps(event))
        elif not _print_event(event):
            return 1
    if not a.json:
        print()
    return 0


def _print_event(event: dict) -> bool:
    """Print one SSE event human-readably. Returns False on an error event."""
    kind = event.get("type")
    if kind == "token":
        print(event.get("text", ""), end="", flush=True)
    elif kind == "tool_call":
        print(f"\n[tool_call] {event.get('name')}: {event.get('input')}", file=sys.stderr)
    elif kind == "tool":
        print(f"[tool] {event.get('name')} -> {event.get('output')}", file=sys.stderr)
    elif kind == "meta":
        print(f"\n[meta] {event.get('provider')}/{event.get('model')} "
              f"cost=${event.get('cost_usd')} steps={event.get('steps')}", file=sys.stderr)
    elif kind == "error":
        print(f"\n[error] {event.get('message')}", file=sys.stderr)
        return False
    return True


def cmd_v1(c: PipesetsClient, a: argparse.Namespace) -> int:
    if a.action == "apps":
        apps = c.v1_list_apps()
        if a.json:
            _print_json(apps)
        else:
            _table(apps, ["id", "name", "version", "runnable", "updated_at"])
        return 0
    if a.action == "get":
        _print_json(c.v1_get_app(a.app_id))
        return 0
    keys = _parse_keys(a.provider_key)
    if a.stream:
        for event in c.v1_stream(a.app_id, a.prompt, a.session_id, a.timeout_ms, keys):
            if a.json:
                print(json.dumps(event))
            elif not _print_event(event):
                return 1
        if not a.json:
            print()
        return 0
    result = c.v1_run(a.app_id, a.prompt, a.session_id, a.timeout_ms, keys)
    if a.json:
        _print_json(result)
    elif result.get("ok"):
        print(result["output"])
    else:
        print(result.get("error") or "Run failed", file=sys.stderr)
    return 0 if result.get("ok") else 1


def cmd_export(c: PipesetsClient, a: argparse.Namespace) -> int:
    content = c.export_app(a.app_id, a.format)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"Wrote {a.output}")
    else:
        print(content)
    return 0


def cmd_traces(c: PipesetsClient, a: argparse.Namespace) -> int:
    if a.run_id:
        _print_json(c.get_run_traces(a.run_id))
        return 0
    traces = c.list_traces(a.limit, a.app_id)
    if a.json:
        _print_json(traces)
    else:
        _table(traces, ["run_id", "app_id", "status", "created_at"])
    return 0


# ── parser ────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipesets", description="Pipesets AI CLI")
    p.add_argument("--url", help="Backend URL (env PIPESETS_URL, default http://localhost:8000)")
    p.add_argument("--tenant", help="Tenant id (env PIPESETS_TENANT_ID)")
    p.add_argument("--project", help="Project id (env PIPESETS_PROJECT_ID)")
    p.add_argument("--user", help="User id — only honoured by servers in AUTH_MODE=headers (env PIPESETS_USER_ID)")
    p.add_argument("--api-key", help="API key for the /v1 commands (env PIPESETS_API_KEY)")
    p.add_argument("--session-token", help="Login session for the other commands (env PIPESETS_SESSION_TOKEN; see `pipesets login`)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="Check backend health").set_defaults(func=cmd_health)

    login = sub.add_parser("login", help="Sign in and print an PIPESETS_SESSION_TOKEN export line")
    login.add_argument("email")
    login.set_defaults(func=cmd_login)
    sub.add_parser("whoami", help="Show the signed-in user and their tenants").set_defaults(func=cmd_whoami)

    apps = sub.add_parser("apps", help="Manage saved apps (workflows)")
    apps.add_argument("action", choices=["list", "get", "publish", "delete"])
    apps.add_argument("app_id", nargs="?")
    apps.add_argument("--json", action="store_true")
    apps.set_defaults(func=cmd_apps)

    pl = sub.add_parser("pipelines", help="List published pipelines")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_pipelines)

    run = sub.add_parser("run", help="Run a published pipeline with a prompt")
    run.add_argument("app_id")
    run.add_argument("prompt")
    run.add_argument("--timeout-ms", type=int, default=120000)
    run.add_argument("--provider-key", action="append", metavar="PROVIDER=KEY",
                     help="API key for a provider; repeatable")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_run)

    st = sub.add_parser("stream", help="Stream a prompt through /api/run/stream")
    st.add_argument("prompt")
    st.add_argument("--app-id")
    st.add_argument("--session-id")
    st.add_argument("--json", action="store_true", help="Print raw SSE events as JSON lines")
    st.set_defaults(func=cmd_stream)

    v1 = sub.add_parser("v1", help="Public API (needs --api-key): list, inspect or run published apps")
    v1.add_argument("action", choices=["apps", "get", "run"])
    v1.add_argument("app_id", nargs="?")
    v1.add_argument("prompt", nargs="?")
    v1.add_argument("--session-id", help="End-user session for apps with a Memory node")
    v1.add_argument("--stream", action="store_true", help="Stream SSE events instead of waiting")
    v1.add_argument("--timeout-ms", type=int, default=120000)
    v1.add_argument("--provider-key", action="append", metavar="PROVIDER=KEY",
                    help="Bring your own provider key; repeatable")
    v1.add_argument("--json", action="store_true")
    v1.set_defaults(func=cmd_v1)

    ex = sub.add_parser("export", help="Export an app as code or config")
    ex.add_argument("app_id")
    ex.add_argument("--format", choices=EXPORT_FORMATS, default="native_json")
    ex.add_argument("-o", "--output", help="Write to file instead of stdout")
    ex.set_defaults(func=cmd_export)

    tr = sub.add_parser("traces", help="List recent traces, or show one run")
    tr.add_argument("run_id", nargs="?")
    tr.add_argument("--limit", type=int, default=20)
    tr.add_argument("--app-id")
    tr.add_argument("--json", action="store_true")
    tr.set_defaults(func=cmd_traces)

    from .tool_cli import add_parser as add_tool_parser
    add_tool_parser(sub)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if getattr(args, "tool_action", None) == "test":
        args.pytest_args = [*extra, *args.pytest_args]   # `pipesets tool test -q -k name` → pytest
    elif extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    if args.command == "apps" and args.action in ("get", "publish", "delete") and not args.app_id:
        parser.error(f"apps {args.action} requires an app_id")
    if args.command == "v1" and args.action in ("get", "run") and not args.app_id:
        parser.error(f"v1 {args.action} requires an app_id")
    if args.command == "v1" and args.action == "run" and not args.prompt:
        parser.error("v1 run requires a prompt")
    try:
        with PipesetsClient(args.url, args.tenant, args.project, args.user, api_key=args.api_key,
                       session_token=args.session_token) as client:
            return args.func(client, args)
    except PipesetsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
