"""
guardrail_judge.py — "custom_rule" guardrails: plain-English rules checked by a judge model.

After the answer is generated, each enabled custom_rule middleware asks a model whether
the answer breaks any of its rules ("Never give medical advice", "Don't mention
competitors") — all of a guardrail's rules go to the judge in one call.
The judge is the pipeline's own LLM unless the guardrail names another provider/model;
keys come from the vault (llm_auth), so the guardrail itself stores none.

Kept apart from routers/middleware.py because it is async and needs an LLM call; the
runners await check_custom_rules after the synchronous check_response_middleware pass.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import llm
from models import LLMConfig
from routers.middleware import MiddlewareEvaluateResult

logger = logging.getLogger("pipesets-ai-backend")

_JUDGE_PROMPT = """You check an AI assistant's answer against a list of rules.

RULES:
{rules}

USER PROMPT:
{prompt}

ASSISTANT ANSWER:
{answer}

First explain in one short sentence whether the answer breaks any rule, then list the numbers
of the rules it breaks (an empty list if it breaks none).
Reply with ONLY a JSON object, no markdown:
{{"reason": "<one short sentence>", "broken_rules": [<rule numbers>]}}"""


# The judge reads the answer in overlapping windows, so padding can't push the part that breaks a
# rule past what it sees. An answer longer than the windows cover follows on_judge_error.
_WINDOW, _OVERLAP, _MAX_WINDOWS = 8000, 400, 4


def answer_windows(answer: str) -> List[str]:
    step = _WINDOW - _OVERLAP
    return [answer[i:i + _WINDOW] for i in range(0, max(len(answer) - _OVERLAP, 1), step)]


def guardrail_rules(config: Dict[str, Any]) -> List[str]:
    """The guardrail's rules: the `rules` list, plus a single `rule` saved by older versions."""
    rules = [str(r).strip() for r in (config.get("rules") or []) if str(r).strip()]
    legacy = (config.get("rule") or "").strip()
    if legacy and legacy not in rules:
        rules.insert(0, legacy)
    return rules


def judge_config(config: Dict[str, Any], node_cfg: Optional[LLMConfig]) -> Optional[LLMConfig]:
    """The guardrail's own judge model if set, else the pipeline's LLM."""
    provider = (config.get("judge_provider") or "").strip()
    model = (config.get("judge_model") or "").strip()
    if provider and model:
        return LLMConfig(provider=provider, model=model, base_url=(config.get("judge_base_url") or None),
                         temperature=0.0, max_tokens=200)
    if node_cfg is None:
        return None
    return node_cfg.model_copy(update={"temperature": 0.0, "max_tokens": 200})


def _parse_verdict(raw: str, rule_count: int) -> Optional[Dict[str, Any]]:
    """{"reason": str, "broken": [1-based rule numbers]} or None when unreadable."""
    start, end = raw.find("{"), raw.rfind("}") + 1
    if not 0 <= start < end:
        return None
    try:
        verdict = json.loads(raw[start:end])
    except json.JSONDecodeError:
        return None
    if not isinstance(verdict, dict):
        return None
    if isinstance(verdict.get("broken_rules"), list):
        broken = []
        for n in verdict["broken_rules"]:
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= rule_count and n not in broken:
                broken.append(n)
    elif "violates" in verdict:  # some models answer in the older single-rule shape
        broken = [1] if str(verdict["violates"]).lower() == "true" and rule_count == 1 else []
    else:
        return None
    return {"reason": str(verdict.get("reason") or "").strip(), "broken": broken}


async def evaluate_custom_rule(config: Dict[str, Any], prompt: str, response: str,
                               node_cfg: Optional[LLMConfig]) -> MiddlewareEvaluateResult:
    rules = guardrail_rules(config)
    if not rules:
        return MiddlewareEvaluateResult(passed=True, action="allow", reason="No rules set")
    action = config.get("action_on_fail", "block")
    # A judge that can't answer either lets the response through (default) or blocks it
    on_error = config.get("on_judge_error", "allow")

    jcfg = judge_config(config, node_cfg)
    if jcfg is None or jcfg.provider == "mock":
        return MiddlewareEvaluateResult(passed=True, action="flag",
                                        reason="Custom rules skipped — no judge model available")

    numbered = "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1))
    windows = answer_windows(response)
    verdict, err = None, "the judge did not return a verdict"
    for window in windows[:_MAX_WINDOWS]:
        try:
            completion = await llm.complete(llm.request_from_config(
                jcfg,
                [{"role": "user", "content": _JUDGE_PROMPT.format(
                    rules=numbered, prompt=prompt[:4000], answer=window)}],
                temperature=0.0,
                max_tokens=200,
                timeout_s=max(1, int(jcfg.timeout_ms or 45000)) / 1000.0,
            ))
            verdict = _parse_verdict(completion.text, len(rules))
        except Exception as e:  # noqa: BLE001 — any judge failure follows on_judge_error
            logger.warning("custom_rule judge failed (%s/%s): %s", jcfg.provider, jcfg.model, e)
            verdict, err = None, str(e)
        if verdict is None or verdict["broken"]:
            break
    else:
        if len(windows) > _MAX_WINDOWS:
            verdict, err = None, f"the answer is too long to check in full ({len(response):,} characters)"

    judge = f"{jcfg.provider}/{jcfg.model}"
    if verdict is None:
        return MiddlewareEvaluateResult(
            passed=on_error != "block", action="block" if on_error == "block" else "flag",
            reason=f"Couldn't check {len(rules)} rule(s) — {err[:200]}", details={"judge": judge},
        )
    reason = verdict["reason"]
    if verdict["broken"]:
        names = "; ".join(f'"{rules[n - 1][:80]}"' for n in verdict["broken"])
        return MiddlewareEvaluateResult(
            passed=False, action=action,
            reason=f"Breaks rule {names}" + (f" — {reason}" if reason else ""),
            details={"judge": judge, "broken_rules": [rules[n - 1] for n in verdict["broken"]]},
        )
    return MiddlewareEvaluateResult(passed=True, action="allow",
                                    reason=reason or f"The answer follows all {len(rules)} rule(s)",
                                    details={"judge": judge})


async def check_custom_rules(middleware_configs: Optional[List[Dict[str, Any]]], prompt: str, response: str,
                             node_cfg: Optional[LLMConfig]) -> Tuple[Optional[str], List[str]]:
    """Post-response pass for custom_rule guardrails. Returns (block message or None, flag messages)."""
    flags: List[str] = []
    if not response:
        return None, flags
    for mw_cfg in middleware_configs or []:
        if not mw_cfg.get("enabled", True) or (mw_cfg.get("type") or "").lower() != "custom_rule":
            continue
        result = await evaluate_custom_rule(mw_cfg.get("config") or {}, prompt, response, node_cfg)
        if not result.passed and result.action == "block":
            return f"[Guardrail: custom rule] Response blocked — {result.reason}", flags
        if result.action != "allow":
            flags.append(f"[Guardrail: custom rule] {result.reason}")
    return None, flags
