"""
child_tool_loop.py — the tool loop a Master Agent's child agents run (plan.md C11, step 1).

A child agent with Tool / Toolkit / MCP server nodes or Skill nodes wired to it gets the same loop
an LLM node runs, minus streaming: the model sees the attached tools (and ``use_skill`` when skills
load on demand), its calls are executed with ``execute_tool_real``, the results go back, and the
loop ends when the model answers or after ``MAX_AGENT_STEPS`` turns. Tool schemas, MCP functions,
typed signatures and skill gating all come from ``llm_runner`` / ``skills_runtime``, so a tool
behaves the same under a child as under an LLM node.

Not here (yet): per-tool checkpoints (a child is one checkpointed step of the master run, so an
interrupted child re-runs whole), editor pins and breakpoints on a child's tool nodes, grounding and
output parsers.
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from models import LLMConfig
from services import skills_runtime
from services import llm_runner as lr

PREVIEW_CHARS = 400


async def _collect(response: Any, timeout_ms: int) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """Read one streamed turn: (text, tool calls in OpenAI format, thinking blocks, finish reason)."""
    text, calls, thinking, finish = "", [], [], "stop"
    deadline = time.monotonic() + max(1000, int(timeout_ms or 45000)) / 1000.0
    async for chunk in response:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Timed out after {int(timeout_ms or 45000)} ms")
        text += chunk.text or ""
        for d in chunk.tool_calls:
            while len(calls) <= d.index:
                calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if d.id:
                calls[d.index]["id"] = d.id
            calls[d.index]["function"]["name"] += d.name
            calls[d.index]["function"]["arguments"] += d.arguments
        thinking.extend(chunk.thinking_blocks)
        if chunk.finish_reason:
            finish = chunk.finish_reason
    return text, calls, thinking, finish


def can_use_tools(cfg: LLMConfig) -> bool:
    """Native function calling with a key (or a keyless local server) for the primary model."""
    return cfg.provider in lr.TOOL_CALL_PROVIDERS and lr._can_attempt_real_call(cfg)


async def run(cfg: LLMConfig, system: str, user_content: str, attached_tools: List[Dict[str, Any]],
              skillset: skills_runtime.SkillSet) -> Tuple[str, Dict[str, Any]]:
    """Run the loop; returns (final text, telemetry). Telemetry has the reliability fields the
    master's step trace reads, plus ``tool_calls`` (one record per call) and ``skills_used``."""
    typed = await asyncio.to_thread(lr._typed_tools, attached_tools) if attached_tools else {}
    mcp = await asyncio.to_thread(lr._mcp_functions, attached_tools) if attached_tools else {}

    def schemas() -> List[Dict[str, Any]]:
        visible = skillset.visible_tools(attached_tools)
        mcp_visible = {k: v for k, v in mcp.items() if skillset.tool_visible(v["tool_id"])}
        return (lr._tool_schemas(visible, typed, mcp_visible) if visible else []) + skillset.schemas()

    messages: List[Dict[str, Any]] = [{"role": "system", "content": system + skillset.prompt_section()},
                                      {"role": "user", "content": user_content}]
    final, cost, total_tokens = "", 0.0, 0
    calls_made: List[Dict[str, Any]] = []
    active, attempt_count, used_fallback = cfg, 1, False

    for _step in range(1, lr.MAX_AGENT_STEPS + 1):
        offered = schemas()
        response, active, attempt_count, used_fallback = await lr._start_stream_with_policy(
            cfg, messages, tools=offered or None, tool_choice="auto" if offered else None)
        text, tool_calls, thinking, finish = await _collect(response, active.timeout_ms)
        cost += getattr(response, "cost_usd", 0.0) or 0.0
        if getattr(response, "usage", None):
            total_tokens += response.usage.total_tokens
        final += text
        if finish == "stop" or not tool_calls:
            break

        messages.append({
            "role": "assistant", "content": text or None,
            "tool_calls": [{"id": tc["id"], "type": "function", "function": dict(tc["function"])} for tc in tool_calls],
            **({"thinking_blocks": thinking} if thinking else {}),
        })
        for tc in tool_calls:
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": await _call_tool(tc, attached_tools, typed, mcp, skillset, user_content, calls_made)})

    return final, {
        "attempt_count": attempt_count, "used_fallback": used_fallback,
        "effective_provider": active.provider, "effective_model": active.model,
        "total_tokens": total_tokens, "cost_usd": cost,
        "tool_calls": calls_made, "skills_used": skillset.used,
    }


async def _call_tool(tc: Dict[str, Any], attached_tools: List[Dict[str, Any]], typed: Dict[str, Any],
                     mcp: Dict[str, Dict[str, Any]], skillset: skills_runtime.SkillSet, user_content: str,
                     calls_made: List[Dict[str, Any]]) -> str:
    """Run one tool call (or use_skill) and return what goes back to the model."""
    name = tc["function"]["name"]
    try:
        args = json.loads(tc["function"]["arguments"] or "{}")
    except json.JSONDecodeError:
        args = {}
    t0 = time.monotonic()

    if skillset.on_demand and name == skills_runtime.USE_SKILL:
        out, loaded = skillset.load(str(args.get("name") or ""), attached_tools, lr._tool_func_name)
        calls_made.append({"name": name, "tool_id": skills_runtime.USE_SKILL, "input": str(args.get("name") or ""),
                           "output": out[:PREVIEW_CHARS], "latency_ms": 0, "status": "success" if loaded else "error"})
        return out

    # Same argument handling as the LLM node: typed tools get the model's arguments, the rest one string
    sig = typed.get(name)
    legacy_call = sig is not None and set(args) == {"input"} and "input" not in sig.parameters.get("properties", {})
    tool_args = args if sig is not None and not legacy_call else None
    tool_input = json.dumps(args, ensure_ascii=False) if tool_args is not None else args.get("input", user_content)
    tool_id = lr._tool_id_for_name(name, attached_tools)
    tool_cfg = lr._tool_config_for_id(tool_id or name, attached_tools)
    if (mcp_fn := mcp.get(name)):
        tool_id, tool_args, tool_input = mcp_fn["tool_id"], None, json.dumps(args, ensure_ascii=False)
        tool_cfg = {**lr._tool_config_for_id(tool_id, attached_tools), "tool_name": mcp_fn["tool_name"], "arguments": args}
    if (needs := skillset.blocked_by(tool_id)):
        return f"'{name}' isn't available yet: load the skill '{needs}' with use_skill first."

    try:
        out = await lr.execute_tool_real(tool_id or name, tool_input, tool_cfg, tool_args)
        status = "success"
    except Exception as e:   # the model sees the failure and can try something else
        out, status = f"Tool '{name}' failed: {e}", "error"
    calls_made.append({"name": name, "tool_id": tool_id or name, "input": str(tool_input)[:200],
                       "output": out[:PREVIEW_CHARS], "latency_ms": int((time.monotonic() - t0) * 1000),
                       "status": status})
    return out
