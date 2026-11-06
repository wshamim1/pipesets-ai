"""
middleware.py — Middleware guardrail node management.

Supported middleware types:
- content_moderation : keyword / regex blocklist + PII detection
- cost_tracker       : per-run token budget with hard cap and alerts
- rate_limiter       : requests-per-minute sliding window per session, caller or app
- prompt_injection   : detect prompt-injection / jailbreak attempts
- grounding          : stop hallucinated answers — grounding instruction, empty-tool
                       short-circuit, and a fact check against tool output / documents
- custom_pattern     : user-defined words / regexes on the prompt, the answer or both
- custom_rule        : plain-English rule checked by a judge model (services/guardrail_judge.py)

The UI calls these "Guardrails"; the node type stays `middleware` so saved pipelines load.

Endpoints:
- GET    /api/middleware              — List all middleware configs
- POST   /api/middleware              — Create a middleware config
- GET    /api/middleware/{id}         — Get single config
- PUT    /api/middleware/{id}         — Update config
- DELETE /api/middleware/{id}         — Delete config
- POST   /api/middleware/evaluate     — Evaluate a prompt/response against a config (ad-hoc)
"""

import functools
import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import get_db_connection
from services import shared_state
from services.pipeline_runner import current_scope

logger = logging.getLogger("pipesets-ai-backend")

router = APIRouter(prefix="/api/middleware", tags=["middleware"])


# ── Pydantic Models ───────────────────────────────────────────────────────────

class MiddlewareCreate(BaseModel):
    name: str
    type: str  # content_moderation | cost_tracker | rate_limiter | prompt_injection
    icon: str = "🛡️"
    description: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class MiddlewareUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class MiddlewareEvaluateRequest(BaseModel):
    middleware_id: Optional[str] = None
    type: Optional[str] = None
    config: Optional[Dict[str, Any]] = Field(default_factory=dict)
    prompt: str = ""
    response: str = ""
    session_id: Optional[str] = None
    token_count: int = 0
    cost_usd: float = 0.0
    # custom_rule tests: the connected LLM node's settings, used as the judge when the
    # guardrail doesn't name its own judge model
    llm_config: Optional[Dict[str, Any]] = None


class MiddlewareEvaluateResult(BaseModel):
    passed: bool
    action: str = "allow"  # allow | block | flag | throttle
    reason: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)


# ── DB Helpers ────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row)
    if isinstance(d.get("config"), str):
        try:
            d["config"] = json.loads(d["config"])
        except Exception:
            d["config"] = {}
    d["enabled"] = bool(d.get("enabled", 1))
    return d


def _get_by_id(mw_id: str) -> Optional[Dict[str, Any]]:
    db = get_db_connection()
    row = db.execute("SELECT * FROM middleware WHERE id = ?", (mw_id,)).fetchone()
    db.close()
    return _row_to_dict(row) if row else None


# ── Evaluation Engine ─────────────────────────────────────────────────────────

# Rate limiter windows live in services/shared_state.py (shared by every replica; in memory
# they're capped, so a flood of fresh session ids can't grow them without bound).

DEFAULT_BLOCKED_PATTERNS = [
    r"\b(bomb|explosive|weapon)s?\b",
    r"\b(hack|crack|exploit)\s+(?:[\w'’]+\s+){0,3}?(password|account|system|wi-?fi|network)s?\b",
    r"\b(ssn|social.?security|credit.?card)\s*:?\s*\d",
]


# ── Text normalization ────────────────────────────────────────────────────────
# Pattern guards match on the raw text and on a normalized copy, so look-alike tricks don't
# slip past them: fullwidth / compatibility forms (NFKC), invisible format characters
# (zero-width space, soft hyphen, word joiner, bidi overrides), combining accents, and
# Cyrillic / Greek letters that look Latin. Whitespace runs become one space.

_CONFUSABLES = str.maketrans({
    # Cyrillic
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
    "т": "t", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
    "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S",
    # Greek
    "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
    "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
})


@functools.lru_cache(maxsize=64)   # each guard runs ~30 patterns over the same text
def normalize_for_matching(text: str) -> str:
    """The text a pattern guard should see — never shown to anyone or sent to a model."""
    t = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text))
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("Cf", "Mn"))
    t = unicodedata.normalize("NFC", t).translate(_CONFUSABLES)
    return re.sub(r"\s+", " ", t)


def _search(pattern: str, text: str, flags: int = 0) -> bool:
    """re.search on the raw text or its normalized form. Raises re.error for a bad pattern."""
    return bool(re.search(pattern, text, flags) or re.search(pattern, normalize_for_matching(text), flags))


# ── PII ───────────────────────────────────────────────────────────────────────

def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _is_card(match: str) -> bool:
    digits = re.sub(r"\D", "", match)
    return 13 <= len(digits) <= 19 and _luhn_ok(digits)


# (kind, pattern, check on the matched text or None)
_PII: List[Tuple[str, "re.Pattern[str]", Any]] = [
    ("ssn", re.compile(r"(?<!\d)\d{3}[-\s]\d{2}[-\s]\d{4}(?!\d)"), None),
    ("card", re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)"), _is_card),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    ("phone", re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\d-])"), None),
]


def _pii_spans(text: str) -> List[Tuple[str, int, int]]:
    spans = []
    for kind, pattern, check in _PII:
        for m in pattern.finditer(text):
            if check is None or check(m.group()):
                spans.append((kind, m.start(), m.end()))
    return spans


def find_pii(text: str) -> List[str]:
    """Kinds of PII in the text (ssn, card, email, phone), each listed once — never the values."""
    found = {kind for kind, _, _ in _pii_spans(text)} | {kind for kind, _, _ in _pii_spans(normalize_for_matching(text))}
    return [kind for kind, _, _ in _PII if kind in found]


def redact_pii(text: str) -> str:
    """The text with each PII value replaced by [PII:kind], for traces of blocked prompts.
    Normalizes first, so a value hidden with zero-width characters is caught too."""
    if not find_pii(text):
        return text
    text = normalize_for_matching(text)
    for kind, start, end in sorted(_pii_spans(text), key=lambda s: s[1], reverse=True):
        text = text[:start] + f"[PII:{kind}]" + text[end:]
    return text


def _evaluate_content_moderation(
    config: Dict[str, Any],
    prompt: str,
    response: str,
) -> MiddlewareEvaluateResult:
    blocked_patterns: List[str] = config.get("blocked_patterns", DEFAULT_BLOCKED_PATTERNS)
    pii_detection: bool = config.get("pii_detection", True)
    block_on_pii: bool = config.get("block_on_pii", False)
    action_on_block: str = config.get("action_on_block", "block")
    check_response: bool = config.get("check_response", False)

    text_to_check = prompt + (" " + response if check_response and response else "")

    # Blocked pattern check
    for pat in blocked_patterns:
        try:
            if _search(pat, text_to_check, re.IGNORECASE):
                return MiddlewareEvaluateResult(
                    passed=False,
                    action=action_on_block,
                    reason=f"Blocked pattern matched: `{pat}`",
                    details={"pattern": pat, "text_length": len(text_to_check)},
                )
        except re.error:
            pass

    # PII check
    if pii_detection:
        pii_found = find_pii(text_to_check)
        if pii_found:
            if block_on_pii:
                return MiddlewareEvaluateResult(
                    passed=False,
                    action=action_on_block,
                    reason=f"PII detected in input ({', '.join(pii_found)})",
                    details={"pii_types": pii_found},
                )
            else:
                return MiddlewareEvaluateResult(
                    passed=True,
                    action="flag",
                    reason=f"PII detected — flagged but allowed ({', '.join(pii_found)})",
                    details={"pii_types": pii_found},
                )

    return MiddlewareEvaluateResult(passed=True, action="allow", reason="Content check passed")


def _evaluate_cost_tracker(
    config: Dict[str, Any],
    session_id: Optional[str],
    token_count: int,
    cost_usd: float,
) -> MiddlewareEvaluateResult:
    max_tokens_per_run: int = int(config.get("max_tokens_per_run", 0))
    max_cost_per_run: float = float(config.get("max_cost_per_run", 0.0))
    alert_threshold: float = float(config.get("alert_threshold_usd", 0.0))
    action_on_exceed: str = config.get("action_on_exceed", "block")

    details: Dict[str, Any] = {
        "token_count": token_count,
        "cost_usd": cost_usd,
        "max_tokens_per_run": max_tokens_per_run,
        "max_cost_per_run": max_cost_per_run,
    }

    if max_tokens_per_run > 0 and token_count > max_tokens_per_run:
        return MiddlewareEvaluateResult(
            passed=False,
            action=action_on_exceed,
            reason=f"Token budget exceeded: {token_count} > {max_tokens_per_run} tokens",
            details=details,
        )

    if max_cost_per_run > 0 and cost_usd > max_cost_per_run:
        return MiddlewareEvaluateResult(
            passed=False,
            action=action_on_exceed,
            reason=f"Cost budget exceeded: ${cost_usd:.5f} > ${max_cost_per_run:.5f}",
            details=details,
        )

    if alert_threshold > 0 and cost_usd >= alert_threshold:
        return MiddlewareEvaluateResult(
            passed=True,
            action="flag",
            reason=f"Cost alert: ${cost_usd:.5f} reached alert threshold ${alert_threshold:.5f}",
            details=details,
        )

    return MiddlewareEvaluateResult(
        passed=True, action="allow",
        reason=f"Cost within budget (${cost_usd:.5f} / {token_count} tokens)",
        details=details,
    )


def _rate_key(per: str, session_id: Optional[str]) -> str:
    """Which window a request counts against. Always inside the run's tenant / project, so
    equal session ids elsewhere never share one. per="session" (default) counts each
    conversation — the caller picks the session id, so rotating it gets a fresh window;
    "caller" counts per API key (or user) and "app" across every caller of the app."""
    scope = current_scope.get()
    where = f"{scope.tenant_id}/{scope.project_id}" if scope else "-"
    caller = (scope.caller or f"user:{scope.user_id}") if scope else "anonymous"
    if per == "app" and scope and scope.chain:
        return f"{where}:app:{scope.chain[-1]}"
    if per in ("caller", "app") or not session_id:
        return f"{where}:caller:{caller}"
    return f"{where}:session:{session_id}"


def _evaluate_rate_limiter(
    config: Dict[str, Any],
    session_id: Optional[str],
) -> MiddlewareEvaluateResult:
    max_rpm: int = int(config.get("max_rpm", 20))
    window_seconds: int = int(config.get("window_seconds", 60))
    action_on_exceed: str = config.get("action_on_exceed", "throttle")
    per = config.get("per", "session")
    key = _rate_key(per, session_id)

    current_rpm = shared_state.add(f"rl:mw:{key}", window_seconds).count   # every request counts, refused or not
    details = {"per": per, "requests_in_window": current_rpm, "max_rpm": max_rpm, "window_seconds": window_seconds}

    if current_rpm > max_rpm:
        return MiddlewareEvaluateResult(
            passed=False,
            action=action_on_exceed,
            reason=f"Rate limit exceeded: {current_rpm} requests in {window_seconds}s (max {max_rpm})",
            details=details,
        )

    return MiddlewareEvaluateResult(
        passed=True, action="allow",
        reason=f"Rate OK: {current_rpm}/{max_rpm} requests in window",
        details=details,
    )


# ── Prompt Injection Detection ────────────────────────────────────────────────
#
# Heuristic pattern library covering the most common injection / jailbreak
# categories.  Intentionally broad — each pattern is short to avoid false
# negatives.  An LLM-backed scorer can be added later as a separate strategy.

_INJECTION_PATTERNS: List[str] = [
    # Role/persona override
    r"\b(ignore|disregard|forget|override|bypass)\s+(?:(?:all|any|every|the|your|my|of|these|those|prior|previous|"
    r"above|earlier|preceding|original|initial|system|safety)\s+)*(instructions?|rules|guidelines|directions|"
    r"directives|prompts?|guardrails|restrictions|constraints|programming)\b",
    r"\b(ignore|disregard|forget)\s+(everything|anything|all)\s+(above|before|prior|previous|earlier|"
    r"(you\s+(were|have\s+been)\s+told))",
    r"you\s+are\s+now\s+(a|an|the)\s+\w",
    r"act\s+as\s+(if\s+you\s+are\s+)?(a|an|the)\s+\w",
    r"pretend\s+(you\s+are|to\s+be)\s+",
    r"roleplay\s+as\s+",
    r"your\s+new\s+(role|persona|instructions?)\s+(is|are)\b",
    # Jailbreak / DAN patterns
    r"\bDAN\b.*mode",
    r"do\s+anything\s+now",
    r"jailbreak",
    r"developer\s+mode",
    r"unrestricted\s+mode",
    r"bypass\s+(your\s+)?(safety|filter|guardrail|restriction)",
    r"disable\s+(your\s+)?(safety|filter|guardrail|restriction)",
    # Instruction smuggling
    r"<\s*(system|inst|SYS|INST)\s*>",      # LLaMA / Mistral special tokens
    r"\[INST\]",
    r"\[\[SYSTEM\]\]",
    r"<\|im_start\|>",                      # ChatML tokens
    r"<!--.*instructions.*-->",
    # Prompt leaking
    r"repeat\s+(the\s+)?(above|everything|your\s+instructions?)",
    r"print\s+(the\s+)?(above|your\s+system\s+prompt)",
    r"reveal\s+(your\s+)?(system\s+prompt|instructions?|guidelines?)",
    r"what\s+(is|are)\s+your\s+(system\s+prompt|instructions?|guidelines?)",
    # Goal hijacking
    r"new\s+task\s*:",
    r"new\s+instructions?\s*:",
    r"override\s*:",
]


def _evaluate_prompt_injection(
    config: Dict[str, Any],
    prompt: str,
    response: str,
) -> MiddlewareEvaluateResult:
    action_on_detect: str = config.get("action_on_detect", "block")
    sensitivity: str = config.get("sensitivity", "medium")   # low | medium | high
    check_response: bool = config.get("check_response", False)
    extra_patterns: List[str] = config.get("extra_patterns", [])

    # sensitivity controls which subset of patterns to run
    # low   → only the most unambiguous patterns (first 8)
    # medium → all built-in patterns (default)
    # high  → built-in + extra
    if sensitivity == "low":
        active_patterns = _INJECTION_PATTERNS[:8]
    else:
        active_patterns = list(_INJECTION_PATTERNS)

    if sensitivity == "high" or extra_patterns:
        active_patterns += extra_patterns

    text_to_check = prompt + (" " + response if check_response and response else "")

    matched: List[str] = []
    for pat in active_patterns:
        try:
            if _search(pat, text_to_check, re.IGNORECASE | re.DOTALL):
                matched.append(pat)
        except re.error:
            pass

    if matched:
        return MiddlewareEvaluateResult(
            passed=False,
            action=action_on_detect,
            reason=f"Prompt injection pattern detected ({len(matched)} match{'es' if len(matched) > 1 else ''})",
            details={
                "matched_patterns": matched[:5],   # cap to avoid bloated traces
                "match_count": len(matched),
                "sensitivity": sensitivity,
            },
        )

    return MiddlewareEvaluateResult(
        passed=True,
        action="allow",
        reason=f"No injection patterns detected (sensitivity={sensitivity})",
        details={"patterns_checked": len(active_patterns)},
    )


# ── Grounding (hallucination guard) ──────────────────────────────────────────
# Small local models happily invent IDs, dates and names when a tool returns
# nothing. This guard works in three layers, all deterministic (no judge LLM):
#   1. inject_instruction — tell the model to use only tool / document data
#   2. on_empty_tools     — when every tool returned nothing, answer with a fixed
#                           message ("answer") or warn the model ("instruct")
#   3. check_facts        — after the response, every ID / number / date / email /
#                           URL in it must appear in the prompt, tool output or
#                           documents; otherwise block or flag

GROUNDING_INSTRUCTION = (
    "Grounding rules: answer ONLY from the tool results, documents and conversation above. "
    "Never invent IDs, names, numbers, dates, URLs or other facts. If the tool results are empty "
    "or do not contain the answer, say so plainly instead of guessing."
)
GROUNDING_EMPTY_INSTRUCTION = (
    "All tool results are EMPTY. Tell the user that nothing was found. Do not make up any data."
)
DEFAULT_EMPTY_MESSAGE = "The tool returned no results, so there is nothing to report."

_EMPTY_TEXT = {"", "[]", "{}", "null", "none", "no results", "no results found", "no data", "not found", "0 results"}

_FACT_PATTERNS = [
    r"https?://[^\s)\]>\"'`]+",                                  # URL
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",        # email
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b",      # ISO date / datetime
    r"\b[A-Za-z]*\d[\w-]*\d[\w-]*\b",                             # IDs and numbers (≥2 digits; min_digits filters further)
]


def _is_empty_value(v: Any) -> bool:
    if v is None or v is False or v == 0 or v == "":
        return True
    if isinstance(v, (list, tuple)):
        return all(_is_empty_value(x) for x in v)
    if isinstance(v, dict):
        return all(_is_empty_value(x) for x in v.values())
    return False


def is_empty_tool_output(text: Optional[str]) -> bool:
    """True for "[]", "{}", "no results", {"jobs": [], "has_more": false} and similar."""
    s = (text or "").strip()
    if s.lower().rstrip(".") in _EMPTY_TEXT:
        return True
    if s[:1] in "[{":
        try:
            return _is_empty_value(json.loads(s))
        except (json.JSONDecodeError, ValueError):
            return False
    return False


def get_grounding_config(middleware_configs: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """Config of the first enabled grounding middleware, or None."""
    for mw_cfg in middleware_configs or []:
        if mw_cfg.get("enabled", True) and (mw_cfg.get("type") or "").lower() == "grounding":
            return mw_cfg.get("config") or {}
    return None


def extract_facts(text: str, min_digits: int = 3) -> List[str]:
    """Checkable facts in a response: URLs, emails, ISO dates, and tokens with ≥ min_digits digits."""
    found: List[str] = []
    for pat in _FACT_PATTERNS:
        for m in re.findall(pat, text or ""):
            fact = m.rstrip(".,;:")
            if pat == _FACT_PATTERNS[-1] and sum(c.isdigit() for c in fact) < min_digits:
                continue
            if fact not in found and not any(fact in f for f in found):
                found.append(fact)
    return found


def _norm(text: str) -> str:
    return re.sub(r"[,\s]", "", text.lower())


def _evaluate_grounding(config: Dict[str, Any], response: str, context: str) -> MiddlewareEvaluateResult:
    if config.get("check_facts", True) is False:
        return MiddlewareEvaluateResult(passed=True, action="allow", reason="Fact check off")
    action_on_fail: str = config.get("action_on_fail", "block")
    min_digits = max(1, int(config.get("min_digits", 3)))
    max_ungrounded = max(0, int(config.get("max_ungrounded", 0)))

    facts = extract_facts(response, min_digits)
    ctx = _norm(context)
    ungrounded = [f for f in facts if _norm(f) not in ctx]
    if len(ungrounded) > max_ungrounded:
        shown = ", ".join(ungrounded[:5]) + ("…" if len(ungrounded) > 5 else "")
        return MiddlewareEvaluateResult(
            passed=False,
            action=action_on_fail,
            reason=f"{len(ungrounded)} fact(s) not found in the tool output or documents: {shown}",
            details={"ungrounded": ungrounded[:20], "facts_checked": len(facts)},
        )
    return MiddlewareEvaluateResult(
        passed=True, action="allow",
        reason=f"All {len(facts)} fact(s) found in the tool output or documents",
        details={"facts_checked": len(facts)},
    )


# ── Custom pattern ────────────────────────────────────────────────────────────
# User-defined words or regexes, checked on the prompt, the answer or both.
# custom_rule (plain-English rule checked by a judge model) needs an LLM call,
# so it lives in services/guardrail_judge.py and is awaited by the runners.

def _pattern_applies(config: Dict[str, Any], phase: str) -> bool:
    return config.get("apply_to", "both") in (phase, "both")


def _evaluate_custom_pattern(config: Dict[str, Any], prompt: str, response: str) -> MiddlewareEvaluateResult:
    entries = [p for p in (config.get("patterns") or []) if str(p).strip()]
    if not entries:
        return MiddlewareEvaluateResult(passed=True, action="allow", reason="No patterns set")
    mode = config.get("mode", "words")
    flags = 0 if config.get("case_sensitive") else re.IGNORECASE
    texts = []
    if prompt and _pattern_applies(config, "prompt"):
        texts.append(("prompt", prompt))
    if response and _pattern_applies(config, "response"):
        texts.append(("answer", response))

    for where, text in texts:
        for entry in entries:
            pat = str(entry).strip() if mode == "regex" else rf"(?<!\w){re.escape(str(entry).strip())}(?!\w)"
            try:
                if _search(pat, text, flags):
                    message = (config.get("message") or "").strip()
                    return MiddlewareEvaluateResult(
                        passed=False,
                        action=config.get("action_on_match", "block"),
                        reason=message or f"The {where} matched `{entry}`",
                        details={"pattern": entry, "where": where},
                    )
            except re.error as e:
                logger.warning("custom_pattern: invalid regex %r: %s", entry, e)
    return MiddlewareEvaluateResult(passed=True, action="allow", reason="No custom pattern matched")


def evaluate_middleware(
    mw_type: str,
    config: Dict[str, Any],
    prompt: str = "",
    response: str = "",
    session_id: Optional[str] = None,
    token_count: int = 0,
    cost_usd: float = 0.0,
    context: Optional[str] = None,
) -> MiddlewareEvaluateResult:
    """Main evaluation dispatcher — called from run.py."""
    mw_type = mw_type.lower()
    if mw_type == "custom_pattern":
        return _evaluate_custom_pattern(config, prompt, response)
    if mw_type == "custom_rule":
        # Needs an LLM call — handled by services/guardrail_judge.check_custom_rules.
        return MiddlewareEvaluateResult(passed=True, action="allow", reason="Checked by the judge model")
    if mw_type == "grounding":
        # Pre-flight has no response to check; ad-hoc tests pass the context as the prompt.
        if not response:
            return MiddlewareEvaluateResult(passed=True, action="allow", reason="Grounding checks responses only")
        return _evaluate_grounding(config, response, context if context is not None else prompt)
    if mw_type == "content_moderation":
        return _evaluate_content_moderation(config, prompt, response)
    elif mw_type == "cost_tracker":
        return _evaluate_cost_tracker(config, session_id, token_count, cost_usd)
    elif mw_type == "rate_limiter":
        return _evaluate_rate_limiter(config, session_id)
    elif mw_type == "prompt_injection":
        return _evaluate_prompt_injection(config, prompt, response)
    return MiddlewareEvaluateResult(passed=True, action="allow", reason=f"Unknown middleware type: {mw_type}")


def check_prompt_middleware(
    middleware_configs: Optional[List[Dict[str, Any]]],
    prompt: str,
    session_id: Optional[str] = None,
) -> Tuple[Optional[str], bool, List[str]]:
    """Pre-flight pass — called before RAG, tools, cache and the LLM.

    Returns (block message or None, throttled, flag messages); throttled is True
    when the block came from a throttle action (callers map it to HTTP 429).
    """
    flags: List[str] = []
    for mw_cfg in middleware_configs or []:
        if not mw_cfg.get("enabled", True):
            continue
        mw_type = mw_cfg.get("type", "")
        result = evaluate_middleware(
            mw_type=mw_type,
            config=mw_cfg.get("config") or {},
            prompt=prompt,
            session_id=session_id,
        )
        if not result.passed and result.action in ("block", "throttle"):
            return f"[Guardrail: {mw_type}] {result.reason}", result.action == "throttle", flags
        if result.action != "allow":
            flags.append(f"[Guardrail: {mw_type}] {result.reason}")
    return None, False, flags


def check_response_middleware(
    middleware_configs: Optional[List[Dict[str, Any]]],
    response: str,
    session_id: Optional[str] = None,
    token_count: int = 0,
    cost_usd: float = 0.0,
    context: Optional[str] = None,
) -> Tuple[Optional[str], List[str]]:
    """Post-response pass — called once the full LLM output and spend are known.

    Runs content_moderation / prompt_injection (only when check_response is on)
    and cost_tracker. rate_limiter is pre-flight only so each run counts once.
    grounding runs only when the caller passes `context` (prompt + tool output +
    documents) — without it every fact would look invented.
    Returns (block message or None, flag messages).
    """
    flags: List[str] = []
    for mw_cfg in middleware_configs or []:
        if not mw_cfg.get("enabled", True):
            continue
        mw_type = (mw_cfg.get("type") or "").lower()
        config = mw_cfg.get("config") or {}
        if mw_type in ("content_moderation", "prompt_injection") and config.get("check_response"):
            result = evaluate_middleware(mw_type, config, response=response)
        elif mw_type == "grounding" and context is not None and response:
            result = evaluate_middleware(mw_type, config, response=response, context=context)
        elif mw_type == "custom_pattern" and _pattern_applies(config, "response"):
            result = evaluate_middleware(mw_type, config, response=response)
        elif mw_type == "cost_tracker":
            result = evaluate_middleware(mw_type, config, session_id=session_id,
                                         token_count=token_count, cost_usd=cost_usd)
        else:
            continue
        if not result.passed and result.action in ("block", "throttle"):
            return f"[Guardrail: {mw_type}] Response blocked — {result.reason}", flags
        if result.action != "allow":
            flags.append(f"[Guardrail: {mw_type}] {result.reason}")
    return None, flags


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
def list_middleware():
    db = get_db_connection()
    rows = db.execute("SELECT * FROM middleware ORDER BY created_at ASC").fetchall()
    db.close()
    return [_row_to_dict(r) for r in rows]


@router.post("")
def create_middleware(req: MiddlewareCreate):
    mw_id = f"mw_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow().isoformat()
    db = get_db_connection()
    db.execute(
        """
        INSERT INTO middleware (id, name, type, icon, description, config, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (mw_id, req.name, req.type, req.icon, req.description, json.dumps(req.config), 1 if req.enabled else 0, now, now),
    )
    db.commit()
    db.close()
    return _get_by_id(mw_id)


@router.get("/{mw_id}")
def get_middleware(mw_id: str):
    mw = _get_by_id(mw_id)
    if not mw:
        raise HTTPException(status_code=404, detail="Middleware not found")
    return mw


@router.put("/{mw_id}")
def update_middleware(mw_id: str, req: MiddlewareUpdate):
    existing = _get_by_id(mw_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Middleware not found")
    name = req.name if req.name is not None else existing["name"]
    icon = req.icon if req.icon is not None else existing["icon"]
    description = req.description if req.description is not None else existing["description"]
    config = req.config if req.config is not None else existing["config"]
    enabled = req.enabled if req.enabled is not None else existing["enabled"]
    now = datetime.utcnow().isoformat()
    db = get_db_connection()
    db.execute(
        "UPDATE middleware SET name=?, icon=?, description=?, config=?, enabled=?, updated_at=? WHERE id=?",
        (name, icon, description, json.dumps(config), 1 if enabled else 0, now, mw_id),
    )
    db.commit()
    db.close()
    return _get_by_id(mw_id)


@router.delete("/{mw_id}")
def delete_middleware(mw_id: str):
    db = get_db_connection()
    cur = db.execute("DELETE FROM middleware WHERE id=?", (mw_id,))
    db.commit()
    deleted = cur.rowcount > 0
    db.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Middleware not found")
    return {"deleted": True, "id": mw_id}


@router.post("/evaluate")
async def evaluate_adhoc(req: MiddlewareEvaluateRequest):
    """Evaluate ad-hoc (from node config panel test button)."""
    mw_type = req.type
    config = req.config or {}

    # If an ID was given, load from DB
    if req.middleware_id:
        mw = _get_by_id(req.middleware_id)
        if mw:
            mw_type = mw_type or mw["type"]
            config = {**mw["config"], **config}

    if not mw_type:
        raise HTTPException(status_code=400, detail="middleware type required")

    if mw_type.lower() == "custom_rule":
        from models import LLMConfig
        from services.guardrail_judge import evaluate_custom_rule
        node_cfg = None
        if req.llm_config and req.llm_config.get("provider") and req.llm_config.get("model"):
            node_cfg = LLMConfig(**{k: v for k, v in req.llm_config.items()
                                    if k in ("provider", "model", "api_key", "base_url") and v})
        return await evaluate_custom_rule(config, req.prompt, req.response, node_cfg)

    result = evaluate_middleware(
        mw_type=mw_type,
        config=config,
        prompt=req.prompt,
        response=req.response,
        session_id=req.session_id,
        token_count=req.token_count,
        cost_usd=req.cost_usd,
    )
    return result
