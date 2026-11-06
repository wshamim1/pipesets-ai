"""
pipeline_docs.py — draft a Markdown README for a pipeline.

Facts that must be right (models, required setup, output schema, workflow inputs) are read
from the flow itself; an LLM only writes the prose around them. Without a usable model the
same facts are laid out as a plain template, so a draft is always available.
"""

import json
import re
from typing import Any, Dict, List, Optional

from services.flow_summary import describe_flows

# Config fields that are credentials or targets the user must supply. A bare tool `api_key` is
# optional in the catalog (Weather -> Open-Meteo, Web Search -> DuckDuckGo), so it is not listed.
_SETUP_FIELD = re.compile(r"(?<!^api)_key$|token|secret|password|webhook|connection_string|username|address|_url$", re.I)
_KEYLESS_PROVIDERS = {"mock", "ollama", "llamacpp", "jan", "local"}


def _model_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        n.get("data", {}) or {} for n in nodes
        if n.get("type") in ("llm", "master_agent")
        or (n.get("type") == "child_agent" and ((n.get("data") or {}).get("kind") or "llm") == "llm")
    ]


def collect_facts(flow: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the README states as fact, read straight from the flow."""
    nodes = flow.get("nodes", []) or []
    models = sorted({f"{d.get('provider')}/{d.get('model')}" for d in _model_nodes(nodes) if d.get("model")})

    setup: List[str] = []
    for provider in sorted({d.get("provider") for d in _model_nodes(nodes) if d.get("provider")} - _KEYLESS_PROVIDERS):
        setup.append(f"An API key for **{provider}** (Settings → API keys, or on the model node).")
    for n in nodes:
        t, d = n.get("type"), n.get("data", {}) or {}
        label = d.get("label") or t
        if t == "tool":
            cfg = d.get("config") or {}
            fields = [k for k, v in {**cfg, **(cfg.get("env_vars") or {})}.items()
                      if v == "" and _SETUP_FIELD.search(k)]
            if fields:
                setup.append(f"**{label}** tool: set {', '.join(f'`{f}`' for f in fields)}.")
        elif t == "doc_loader":
            src = d.get("source") or ""
            where = "a source path" if not src or src.startswith("/path/to/") else f"`{src}`"
            setup.append(f"Ingest documents with **{label}** from {where} (Run panel → Ingest Document).")
        elif t == "connection":
            setup.append(f"The **{label}** connection ({d.get('connection_type', 'data source')}) must be reachable.")
        elif t == "child_agent" and d.get("kind") == "pipeline":
            setup.append(f"Access to the published pipeline **{d.get('app_name') or label}**.")
        elif t == "human_gate":
            setup.append(f"Someone to answer the **{label}** approval step during runs.")

    parser = next((n.get("data", {}) or {} for n in nodes if n.get("type") == "output_parser"), None)
    output = None
    if parser:
        output = {"type": parser.get("parser_type", "json"), "schema": (parser.get("schema_json") or "").strip()}

    inputs = [
        {"variable": (n.get("data") or {}).get("variable", ""), "prompt": (n.get("data") or {}).get("prompt", "")}
        for n in nodes if n.get("type") == "wf_step" and (n.get("data") or {}).get("step_type") in ("ask", "choice", "confirm")
    ]
    return {"models": models, "setup": setup, "output": output, "workflow_inputs": inputs}


def template_docs(name: str, description: str, visited: List[Dict[str, Any]], facts: Dict[str, Any]) -> str:
    """A README built only from facts — used when no model is available to write prose."""
    parts = [f"# {name or 'Pipeline'}", "", "## Overview", "", description.strip() or "_Describe what this pipeline is for._", ""]
    parts += ["## How it works", "", describe_flows(visited), ""]
    if facts["models"]:
        parts += ["**Models:** " + ", ".join(f"`{m}`" for m in facts["models"]), ""]
    parts += ["## Inputs", ""]
    if facts["workflow_inputs"]:
        parts += [f"- `{i['variable']}` — {i['prompt']}" for i in facts["workflow_inputs"]] + [""]
    else:
        parts += ["A natural-language request in the Run panel.", ""]
    parts += ["## Output", ""]
    if facts["output"]:
        parts += [f"Structured {facts['output']['type'].upper()}:", "", "```json", facts["output"]["schema"] or "{}", "```", ""]
    else:
        parts += ["A text answer.", ""]
    parts += ["## Setup", ""]
    parts += [f"- {s}" for s in facts["setup"]] if facts["setup"] else ["Nothing — it runs as is."]
    return "\n".join(parts).rstrip() + "\n"


def docs_prompt(name: str, description: str, visited: List[Dict[str, Any]], facts: Dict[str, Any],
                example_prompts: Optional[List[str]] = None) -> str:
    examples = "\n".join(f"- {p}" for p in (example_prompts or []))
    return f"""You are a technical writer documenting an AI pipeline for the team that will use and maintain it.

Pipeline name: {name or "(untitled)"}
Owner's description: {description.strip() or "(none)"}

How it is built:
{describe_flows(visited)}

Facts read from the configuration (state these accurately; do not add requirements that are not listed):
{json.dumps(facts, indent=2)}
{f"{chr(10)}Example prompts already suggested for it:{chr(10)}{examples}{chr(10)}" if examples else ""}
Write a concise README in GitHub Markdown with exactly these sections:
# {name or "Pipeline"}
## Overview — 2-3 sentences: what it does and who it is for.
## How it works — numbered steps following the flow; name each agent/tool and its role.
## Inputs — what a good request looks like (list workflow inputs if there are any).
## Output — what comes back; include the JSON schema in a code block if there is one.
## Setup — a bullet list built from the setup facts (or "Nothing — it runs as is.").
## Example prompts — 3 realistic prompts specific to this pipeline.
## Limitations — 2-4 honest caveats (e.g. live data, hallucination risk, tool rate limits).

Return only the Markdown, no preamble and no surrounding code fence."""


def strip_fence(text: str) -> str:
    """Models sometimes wrap the whole answer in ```markdown fences."""
    t = text.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```$", t, re.S)
    return (m.group(1) if m else t).strip() + "\n"
