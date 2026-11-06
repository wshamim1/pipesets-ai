"""`pipesets tool …` — build, test and deploy custom tools from code (pipesets/project.py).

    pipesets tool init jira_lookup              scaffold tool.py, pipesets.toml, requirements.txt, tests/
    pipesets tool test                          pytest the project locally (no backend)
    pipesets tool run --args '{"issue_key": "OPS-1"}'           run locally
    pipesets tool run --remote --args '…'       run the deployed tool in the server sandbox
    pipesets tool deploy [--note <commit>]      upsert by name → new version (or "unchanged")
    pipesets tool list | versions | rollback <v>

deploy / list / versions / rollback / run --remote use the /v1 API: an API key with tools:write
(deploy, rollback), tools:read (list, versions) or tools:execute (run --remote).
"""

import argparse
import json
import os
import subprocess
import sys

from . import project


def _json_arg(value, flag):
    try:
        data = json.loads(value) if value else {}
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: {flag} is not JSON: {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"error: {flag} must be a JSON object")
    return data


def cmd_tool(client, a: argparse.Namespace) -> int:
    action = a.tool_action
    if action == "init":
        root = project.init(a.name, a.dir)
        print(f"Created {os.path.relpath(root)}/ — edit tool.py, then `pipesets tool test` and `pipesets tool deploy`")
        return 0

    proj = project.find(a.path)
    if action == "test":
        return subprocess.call([sys.executable, "-m", "pytest", *a.pytest_args], cwd=proj.root)

    if action == "run":
        args, config = _json_arg(a.args, "--args"), _json_arg(a.config, "--config")
        if a.remote:
            result = client.tool_run(proj.name, args, config, a.version)
            if a.json:
                print(json.dumps(result, indent=2))
            elif result.get("ok"):
                print(result["output"])
            else:
                print(f"error: {result.get('error')}", file=sys.stderr)
            return 0 if result.get("ok") else 1
        from .testing import ToolArgumentError, load, output
        try:
            print(output(load(proj.entry_path), args, config=config))
        except ToolArgumentError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0

    if action == "deploy":
        result = client.tool_deploy(proj.name, proj.bundle(a.note))
        if a.json:
            print(json.dumps(result, indent=2))
        elif not result.get("changed"):
            print(f"{proj.name} unchanged (v{result['version']})")
        else:
            verb = "created" if result.get("created") else "deployed"
            print(f"{proj.name} {verb}: v{result['version']} (id {result['id']})")
        return 0

    if action == "list":
        rows = client.tools_list()
        if a.json:
            print(json.dumps(rows, indent=2))
        else:
            from .cli import _table
            _table(rows, ["name", "version", "source", "description"])
        return 0

    if action == "versions":
        result = client.tool_versions(a.name or proj.name)
        if a.json:
            print(json.dumps(result, indent=2))
        else:
            from .cli import _table
            for row in result["data"]:
                row["current"] = "*" if row["version"] == result["current"] else ""
            _table(result["data"], ["current", "version", "source", "created_at", "created_by", "note"])
        return 0

    if action == "rollback":
        result = client.tool_rollback(a.name or proj.name, a.version)
        print(f"{result['name']} rolled back to v{a.version}'s code as v{result['version']}")
        return 0
    raise SystemExit(f"unknown tool action {action}")


def add_parser(sub) -> None:
    t = sub.add_parser("tool", help="Build, test and deploy custom tools from code")
    t.add_argument("--path", default=".", help="Tool project directory (default: here, or a parent)")
    actions = t.add_subparsers(dest="tool_action", required=True)

    init = actions.add_parser("init", help="Scaffold a tool project")
    init.add_argument("name", help="Tool name, a Python identifier (e.g. jira_lookup)")
    init.add_argument("--dir", help="Directory to create (default: ./<name>)")

    test = actions.add_parser("test", help="Run the project's tests with pytest (extra args go to pytest)")
    test.add_argument("pytest_args", nargs="*")

    run = actions.add_parser("run", help="Run the tool locally, or with --remote in the server sandbox")
    run.add_argument("--args", help='JSON object of arguments, e.g. \'{"issue_key": "OPS-1"}\'')
    run.add_argument("--config", help="JSON object of config / secret values")
    run.add_argument("--remote", action="store_true", help="Run the deployed tool on the server")
    run.add_argument("--version", type=int, help="With --remote: a specific deployed version")
    run.add_argument("--json", action="store_true")

    deploy = actions.add_parser("deploy", help="Upsert the tool by name; a content change is a new version")
    deploy.add_argument("--note", help="Recorded with the version, e.g. the git commit")
    deploy.add_argument("--json", action="store_true")

    ls = actions.add_parser("list", help="Custom tools in the project")
    ls.add_argument("--json", action="store_true")

    versions = actions.add_parser("versions", help="A tool's version history")
    versions.add_argument("name", nargs="?", help="Default: this project's tool")
    versions.add_argument("--json", action="store_true")

    rollback = actions.add_parser("rollback", help="New version with an earlier version's code")
    rollback.add_argument("version", type=int)
    rollback.add_argument("--name", help="Default: this project's tool")

    t.set_defaults(func=cmd_tool)
