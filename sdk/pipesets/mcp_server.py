"""MCP server exposing Pipesets AI to MCP clients (stdio).

Scope is deliberately small: read-only tools plus run_pipeline. There are no
create / update / delete / publish tools — the backend has no API-key auth yet,
so an AI client should not be able to modify workflows.

Config (environment):
  PIPESETS_URL, PIPESETS_TENANT_ID, PIPESETS_PROJECT_ID   same as the CLI
  PIPESETS_SESSION_TOKEN    login session (from `pipesets login`); required unless the
                       backend runs in AUTH_MODE=headers (then PIPESETS_USER_ID)
  PIPESETS_KEY_<PROVIDER>   e.g. PIPESETS_KEY_OPENAI, PIPESETS_KEY_ANTHROPIC — forwarded to
                       run_pipeline. Never accepted as tool arguments, because
                       tool arguments are visible in the MCP client's logs.

Logging goes to stderr; stdout is the MCP protocol channel.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .client import EXPORT_FORMATS, PipesetsClient, PipesetsError

mcp = MCPServer(
    "pipesets-ai",
    instructions=(
        "Tools for Pipesets AI. Use list_pipelines to find "
        "published pipelines, then run_pipeline to execute one. run_pipeline makes "
        "real LLM calls and can incur cost."
    ),
)

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
_RUN = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)


def _client() -> PipesetsClient:
    return PipesetsClient()


def _provider_keys() -> Dict[str, str]:
    prefix = "PIPESETS_KEY_"
    return {k[len(prefix):].lower(): v for k, v in os.environ.items() if k.startswith(prefix) and v}


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _fail(exc: PipesetsError) -> None:
    # ToolError reaches the model verbatim; any other exception is masked as a crash.
    raise ToolError(str(exc)) from exc


@mcp.tool(annotations=_READ_ONLY)
def list_pipelines() -> str:
    """List published pipelines (id, name, version, node_count, runnable). Only these can be run."""
    try:
        with _client() as c:
            return _dump(c.list_pipelines())
    except PipesetsError as exc:
        _fail(exc)


@mcp.tool(annotations=_RUN)
def run_pipeline(app_id: str, prompt: str, timeout_ms: int = 120000) -> str:
    """Run a published pipeline once with a prompt and return its output.

    This makes real LLM calls and may incur cost against the configured provider
    and any spend budget. Use list_pipelines first to get a valid app_id.
    """
    try:
        with _client() as c:
            result = c.run_pipeline(app_id, prompt, timeout_ms, _provider_keys())
    except PipesetsError as exc:
        _fail(exc)
    if not result.get("ok"):
        raise ToolError(result.get("error") or "Pipeline run failed")
    return result["output"]


@mcp.tool(annotations=_READ_ONLY)
def list_apps() -> str:
    """List saved apps (workflows), including drafts. Drafts cannot be run."""
    try:
        with _client() as c:
            apps = c.list_apps()
    except PipesetsError as exc:
        _fail(exc)
    slim: List[Dict[str, Any]] = [
        {k: a.get(k) for k in ("id", "name", "description", "status", "version", "updated_at")} for a in apps
    ]
    return _dump(slim)


@mcp.tool(annotations=_READ_ONLY)
def get_app(app_id: str) -> str:
    """Get one saved app including its full flow_data (nodes and edges)."""
    try:
        with _client() as c:
            return _dump(c.get_app(app_id))
    except PipesetsError as exc:
        _fail(exc)


@mcp.tool(annotations=_READ_ONLY)
def get_traces(run_id: Optional[str] = None, limit: int = 20, app_id: Optional[str] = None) -> str:
    """Get recent run traces (newest first), or every span of one run when run_id is given."""
    try:
        with _client() as c:
            return _dump(c.get_run_traces(run_id) if run_id else c.list_traces(limit, app_id))
    except PipesetsError as exc:
        _fail(exc)


@mcp.tool(annotations=_READ_ONLY)
def export_app(app_id: str, format: str = "native_json") -> str:
    """Export an app as code or config.

    format is one of: native_json, openapi, langchain, crewai, autogen, docker_compose, notebook.
    """
    if format not in EXPORT_FORMATS:
        raise ToolError(f"format must be one of: {', '.join(EXPORT_FORMATS)}")
    try:
        with _client() as c:
            return c.export_app(app_id, format)
    except PipesetsError as exc:
        _fail(exc)


def main() -> None:
    print("pipesets-mcp running on stdio", file=sys.stderr)
    mcp.run("stdio")


if __name__ == "__main__":
    main()
