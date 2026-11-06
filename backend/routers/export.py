"""
Export router — converts a saved App (flow_data) into various portable formats.

Supported formats:
  native_json    — raw Pipesets JSON (re-importable)
  openapi        — OpenAPI 3.1 YAML spec
  langchain      — Ready-to-run LangChain agent script
  crewai         — CrewAI multi-agent script
  autogen        — Microsoft AutoGen script
  docker_compose — docker-compose.yml deployment stub
  notebook       — Jupyter Notebook (.ipynb)
  readme         — the pipeline's Markdown docs (a fact-only template when none are written yet)
  skill          — an Agent Skill (SKILL.md + run script, zipped) that runs the published app via /v1

Exports need ``apps:read`` and only see apps in the caller's tenant / project.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from exporters.helpers import load_app
from exporters.native_exporter import to_native_json, to_openapi
from exporters.langchain_exporter import to_langchain
from exporters.crewai_exporter import to_crewai
from exporters.autogen_exporter import to_autogen
from exporters.docker_exporter import to_docker_compose
from exporters.notebook_exporter import to_notebook
from exporters.skill_exporter import skill_slug, to_skill_md, to_skill_zip
from services import pipeline_docs, secret_store
from services.acl import require_access
from services.request_context import get_request_context

router = APIRouter(prefix="/api/export", tags=["export"])


def to_readme(app) -> str:
    if (app.get("docs") or "").strip():
        return app["docs"]
    flow = app["flow_data"]
    visited = [{"source": "this pipeline", "flow": flow}]
    return pipeline_docs.template_docs(app["name"], app.get("description") or "", visited, pipeline_docs.collect_facts(flow))


SUPPORTED_FORMATS = ["native_json", "openapi", "langchain", "crewai", "autogen", "docker_compose", "notebook", "readme",
                     "skill"]

CONTENT_TYPES = {
    "native_json": "application/json",
    "openapi": "text/yaml",
    "langchain": "text/x-python",
    "crewai": "text/x-python",
    "autogen": "text/x-python",
    "docker_compose": "text/yaml",
    "notebook": "application/json",
    "readme": "text/markdown",
    "skill": "text/markdown",   # preview: the SKILL.md; the download is a zip
}

FILE_NAMES = {
    "native_json": "app_export.json",
    "openapi": "openapi.yaml",
    "langchain": "langchain_agent.py",
    "crewai": "crewai_agent.py",
    "autogen": "autogen_agent.py",
    "docker_compose": "docker-compose.yml",
    "notebook": "agent_notebook.ipynb",
    "readme": "README.md",
    "skill": "SKILL.md",
}

FORMATTERS = {
    "native_json": to_native_json,
    "openapi": to_openapi,
    "langchain": to_langchain,
    "crewai": to_crewai,
    "autogen": to_autogen,
    "docker_compose": to_docker_compose,
    "notebook": to_notebook,
    "readme": to_readme,
    "skill": to_skill_md,
}


def _strip_secret_refs(app, format: str):
    """Vault refs and sealed values can't be resolved outside this server, so code exports get blanks
    (the generated code reads keys from environment variables instead). Native JSON keeps
    them: re-imported into this workspace they still work, elsewhere the picker flags them."""
    if format == "native_json":
        return app
    def strip(value):
        if secret_store.is_protected(value):
            return ""
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items()}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    app["flow_data"] = strip(app["flow_data"])
    return app


def _load(app_id: str, format: str, request: Request):
    if format not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{format}'. Choose from: {', '.join(SUPPORTED_FORMATS)}",
        )
    ctx = get_request_context(request)
    require_access(ctx, "apps", "read")
    app = load_app(app_id, ctx.tenant_id, ctx.project_id)
    if format == "skill" and app["status"] != "published":
        raise HTTPException(status_code=409, detail="Publish the pipeline first: the skill runs its published version.")
    return _strip_secret_refs(app, format)


@router.get("/{app_id}")
def export_app(
    app_id: str,
    request: Request,
    format: str = Query(default="native_json", description=f"One of: {', '.join(SUPPORTED_FORMATS)}"),
):
    app = _load(app_id, format, request)
    if format == "skill":
        return Response(
            content=to_skill_zip(app, str(request.base_url)),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{skill_slug(app["name"])}.zip"'},
        )
    return PlainTextResponse(
        content=FORMATTERS[format](app),
        media_type=CONTENT_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{FILE_NAMES[format]}"'},
    )


@router.get("/{app_id}/preview", response_class=PlainTextResponse)
def preview_export(
    app_id: str,
    request: Request,
    format: str = Query(default="native_json"),
):
    """Same as export but returns inline (no download header) for in-app preview."""
    app = _load(app_id, format, request)
    return PlainTextResponse(
        content=FORMATTERS[format](app),
        media_type=CONTENT_TYPES[format],
    )
