"""
flow_summary.py — read a flow (plus the pipelines it calls) the way an LLM prompt needs it.

Shared by the AI generators: eval test cases, Run-panel starter prompts and pipeline docs.
"""

from typing import Any, Dict, List

from routers.run import get_current_config
from services.pipeline_runner import _resolve_key


def pick_generator_llm(visited: List[Dict[str, Any]], provider_keys: Dict[str, str]):
    """First real model (with a usable key) found in the pipeline or its sub-pipelines;
    falls back to a mock model, then to the global config."""
    from models import LLMConfig
    candidates = []
    for v in visited:
        for n in v["flow"].get("nodes", []):
            d = n.get("data", {}) or {}
            if n.get("type") in ("llm", "master_agent") or (
                n.get("type") == "child_agent" and (d.get("kind") or "llm") == "llm"
            ):
                if d.get("provider") and d.get("model"):
                    candidates.append(d)
    for d in candidates:
        key = _resolve_key(d["provider"], d.get("api_key") or "", provider_keys)
        if d["provider"] != "mock" and (key or d["provider"] in ("ollama", "llamacpp", "jan", "local")):
            return LLMConfig(provider=d["provider"], model=d["model"], api_key=key or None,
                             base_url=d.get("base_url") or None, max_tokens=4096)
    if candidates:
        d = candidates[0]
        return LLMConfig(provider=d["provider"], model=d["model"], max_tokens=4096)
    cfg = get_current_config()
    if not cfg.api_key:
        cfg = cfg.model_copy(update={"api_key": _resolve_key(cfg.provider, "", provider_keys) or None})
    return cfg


def describe_flows(visited: List[Dict[str, Any]]) -> str:
    blocks = []
    for v in visited:
        lines = []
        for n in v["flow"].get("nodes", []):
            t, d = n.get("type"), n.get("data", {}) or {}
            if t in ("llm", "master_agent") or (t == "child_agent" and (d.get("kind") or "llm") == "llm"):
                sp = (d.get("system_prompt") or "").strip().replace("\n", " ")
                role = f" role={d.get('role')}" if t == "child_agent" else ""
                lines.append(f"- {t} {d.get('provider', '')}/{d.get('model', '')}{role}"
                             + (f' — system prompt: "{sp[:400]}"' if sp else ""))
            elif t == "tool":
                lines.append(f"- tool {d.get('label') or d.get('toolId')}: {(d.get('description') or '')[:200]}")
            elif t == "toolkit":
                for st in d.get("subTools") or []:
                    if isinstance(st, dict):
                        lines.append(f"- tool {st.get('label') or st.get('name') or st.get('id')}: "
                                     f"{(st.get('description') or '')[:200]}")
            elif t == "child_agent" and d.get("kind") == "pipeline":
                lines.append(f"- calls sub-pipeline '{d.get('app_name') or d.get('label')}' "
                             f"v{d.get('app_version') or 'latest'}")
            elif t == "wf_step":
                lines.append(f"- workflow step {d.get('step_type', '')}: {d.get('label', '')}")
            elif t in ("retriever", "vector_store", "knowledge_base"):
                lines.append(f"- {t} (answers from documents: {d.get('label') or d.get('collection_name') or ''})")
            elif t in ("memory", "cache", "connection", "human_gate", "middleware"):
                lines.append(f"- {t} {d.get('label', '')}")
            elif t == "checkpointer":
                saving = "saves each step" if d.get("save_steps", True) is not False else "saves no step output"
                resume = "resumes after the last finished step" if d.get("restore_on_resume", True) is not False \
                    else "a resume starts over"
                lines.append(f"- checkpointer: {saving}; {resume}")
        header = "Main pipeline" if v["source"] == "this pipeline" else (
            f"Sub-pipeline {v['source']} (called from {v['called_from']})")
        blocks.append(f"{header}:\n" + ("\n".join(lines) if lines else "- (no notable nodes)"))
    return "\n\n".join(blocks)
