"""Agent skill exporter — a published app as a SKILL.md folder that Claude Code, Claude Desktop and other
agents that read Agent Skills can load.

The pipeline keeps running on Pipesets: the skill tells the agent when to use it, and its script calls
``POST /v1/apps/{id}/run`` with the caller's own API key (``PIPESETS_API_KEY``, never written into the
files). Zip layout::

    <slug>/SKILL.md          name + description (what the agent sees first), then how to run it
    <slug>/scripts/run.py    stdlib-only client for /v1 run and resume
    <slug>/reference.md      the pipeline's README, when it has one
"""

import io
import json
import re
import zipfile
from typing import Dict

from exporters.helpers import nodes_by_type

NAME_MAX = 64            # Agent Skills limits
DESCRIPTION_MAX = 1024


def skill_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:NAME_MAX].strip("-")
    return slug or "pipesets-pipeline"


def _has_gate(flow: Dict) -> bool:
    return any(n.get("type") == "human_gate" for n in flow.get("nodes", []))


def _has_memory(flow: Dict) -> bool:
    return bool(nodes_by_type(flow)["memory"])


def _description(app: Dict) -> str:
    what = (app.get("description") or "").strip().rstrip(".")
    text = (f"{what}. Runs the \"{app['name']}\" pipeline on Pipesets." if what
            else f"Runs the \"{app['name']}\" pipeline on Pipesets.")
    text += f" Use when the user asks for what the {app['name']} pipeline does."
    return " ".join(text.split())[:DESCRIPTION_MAX]


def _yaml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)   # a JSON string is a valid YAML scalar


def to_skill_md(app: Dict) -> str:
    flow = app["flow_data"]
    lines = [
        "---",
        f"name: {skill_slug(app['name'])}",
        f"description: {_yaml_str(_description(app))}",
        "---",
        "",
        f"# {app['name']}",
        "",
        f"This skill runs the published Pipesets pipeline **{app['name']}** (app `{app['id']}`). "
        "The pipeline does the work on the Pipesets server; you send it the request and relay its answer.",
        "",
        "## Setup",
        "",
        "- `PIPESETS_API_KEY`: a Pipesets API key with the `apps:run` scope for this project",
        "- `PIPESETS_BASE_URL` (optional): the Pipesets server, if it isn't the one in `scripts/run.py`",
        "",
        "If the key is missing, tell the user to create one under Settings → API keys and set it; don't guess one.",
        "",
        "## Run it",
        "",
        "Put the whole request in the prompt, with any details the pipeline needs:",
        "",
        "```bash",
        "python scripts/run.py \"<the user's request>\"",
        "```",
        "",
        "The script prints the pipeline's answer. With `--json` it prints the full result "
        "(`status`, `run_id`, `output`, `error`, `pending_gate`). A non-zero exit means the run failed; "
        "show the error to the user.",
    ]
    if _has_memory(flow):
        lines += [
            "",
            "The pipeline keeps conversation history. Pass the same `--session <id>` on follow-up requests "
            "in one conversation, and a new one for a new conversation.",
        ]
    if _has_gate(flow):
        lines += [
            "",
            "## Human approval",
            "",
            "Some steps wait for a person to approve them. Then the script exits with code 3 and prints the "
            "step waiting for approval and the `run_id`. Show it to the user and ask what to do. Never approve "
            "on their behalf. Then continue with their decision:",
            "",
            "```bash",
            "python scripts/run.py --resume <run_id> --decision approve",
            "python scripts/run.py --resume <run_id> --decision reject --comment \"why\"",
            "python scripts/run.py --resume <run_id> --decision edit --edited-output \"corrected text\"",
            "```",
        ]
    lines += [
        "",
        "## Failures",
        "",
        "A run that failed or timed out is saved at its last step. Retry it with "
        "`python scripts/run.py --resume <run_id>`, which reuses the steps that finished.",
    ]
    if (app.get("docs") or "").strip():
        lines += ["", "What the pipeline does in detail, its inputs and outputs: [reference.md](reference.md)."]
    return "\n".join(lines) + "\n"


RUN_SCRIPT = '''#!/usr/bin/env python3
"""Run the "{name}" Pipesets pipeline. Standard library only.

    python run.py "request"                          run it, print the answer
    python run.py --resume RUN_ID [--decision ...]   continue a paused or failed run

Env: PIPESETS_API_KEY (required), PIPESETS_BASE_URL (default {base_url}).
Exit codes: 0 done, 1 failed, 2 usage / setup error, 3 waiting for human approval.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

APP_ID = {app_id}
BASE_URL = os.environ.get("PIPESETS_BASE_URL", {base_url}).rstrip("/")


def call(path, body, timeout_ms):
    key = os.environ.get("PIPESETS_API_KEY", "").strip()
    if not key:
        sys.exit("PIPESETS_API_KEY is not set: create a key with the apps:run scope in Pipesets → Settings → API keys")
    req = urllib.request.Request(BASE_URL + path, data=json.dumps(body).encode(), method="POST",
                                 headers={{"Authorization": "Bearer " + key, "Content-Type": "application/json"}})
    try:
        with urllib.request.urlopen(req, timeout=timeout_ms / 1000 + 15) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        return {{"ok": False, "status": "failed", "error": f"HTTP {{e.code}}: {{detail}}"}}
    except urllib.error.URLError as e:
        return {{"ok": False, "status": "failed", "error": f"Can't reach {{BASE_URL}}: {{e.reason}}"}}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("prompt", nargs="?", help="the request for the pipeline")
    p.add_argument("--session", help="conversation id, to keep history across calls")
    p.add_argument("--resume", metavar="RUN_ID", help="continue this paused or failed run")
    p.add_argument("--decision", choices=["approve", "reject", "edit"], help="answer to a human approval step")
    p.add_argument("--comment", default="")
    p.add_argument("--edited-output", default="")
    p.add_argument("--timeout-ms", type=int, default=120000)
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    a = p.parse_args()

    if a.resume:
        body = {{"timeout_ms": a.timeout_ms}}
        if a.decision:
            body["gate_decision"] = {{"action": a.decision, "comment": a.comment, "edited_output": a.edited_output}}
        res = call(f"/v1/runs/{{a.resume}}/resume", body, a.timeout_ms)
    elif a.prompt:
        body = {{"prompt": a.prompt, "stream": False, "timeout_ms": a.timeout_ms}}
        if a.session:
            body["session_id"] = a.session
        res = call(f"/v1/apps/{{APP_ID}}/run", body, a.timeout_ms)
    else:
        p.print_usage(sys.stderr)
        sys.exit(2)

    status = res.get("status")
    if a.json:
        print(json.dumps(res, indent=2))
    elif status == "paused":
        print("Waiting for human approval (run_id " + str(res.get("run_id")) + "):")
        print(json.dumps(res.get("pending_gate"), indent=2))
    elif status == "completed":
        print(res.get("output", ""))
    else:
        print("Run failed" + (" (run_id " + str(res["run_id"]) + ")" if res.get("run_id") else "") + ": "
              + str(res.get("error")), file=sys.stderr)
    sys.exit({{"completed": 0, "paused": 3}}.get(status, 1))


if __name__ == "__main__":
    main()
'''


def to_run_script(app: Dict, base_url: str) -> str:
    return RUN_SCRIPT.format(name=app["name"].replace('"', "'").replace("\\", "/"), app_id=json.dumps(app["id"]),
                             base_url=json.dumps(base_url.rstrip("/")))


def to_skill_zip(app: Dict, base_url: str) -> bytes:
    slug = skill_slug(app["name"])
    files = {"SKILL.md": to_skill_md(app), "scripts/run.py": to_run_script(app, base_url)}
    if (app.get("docs") or "").strip():
        files["reference.md"] = app["docs"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in files.items():
            info = zipfile.ZipInfo(f"{slug}/{path}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.endswith(".py") else 0o644) << 16
            z.writestr(info, text)
    return buf.getvalue()
