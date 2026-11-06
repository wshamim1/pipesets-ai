"""Guardrails AI — input/output validation — built-in tool `guardrails`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec

TOOL = ToolSpec(
    id="guardrails",
    name="Guardrails AI",
    icon="🛡️",
    group="frameworks",
    description="Validate and fix LLM inputs and outputs. Detect PII, toxic content, off-topic responses, and format violations. Can auto-correct or block non-compliant outputs.",
    default_config={
        "mode": "output",
        "checks": "detect_pii,toxic_language",
        "action": "warn",
        "pii_entities": "PERSON,EMAIL,PHONE_NUMBER,LOCATION",
        "toxicity_threshold": 0.5,
    },
    order=40,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text_input = inp.strip()
    mode = (cfg.get("mode") or "output").lower()        # input | output | both
    checks_raw = cfg.get("checks", "detect_pii,toxic_language")
    action = (cfg.get("action") or "warn").lower()      # warn | block | redact
    pii_entities = cfg.get("pii_entities", "PERSON,EMAIL,PHONE_NUMBER,LOCATION")
    toxicity_threshold = float(cfg.get("toxicity_threshold", 0.5))

    if not text_input:
        return "[Guardrails AI] No input text provided."

    checks = [c.strip() for c in str(checks_raw).split(",") if c.strip()]

    violations: list[str] = []
    redacted = text_input

    # ── PII detection (regex-based, no external dep required) ─────────────
    if "detect_pii" in checks:
        import re as _re
        pii_patterns = {
            "EMAIL":        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
            "PHONE_NUMBER": r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            "LOCATION":     r"\b\d{1,5}\s+\w[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Place|Pl)\b",
        }
        requested = {e.strip().upper() for e in pii_entities.split(",")}
        for entity, pattern in pii_patterns.items():
            if entity in requested:
                matches = _re.findall(pattern, text_input, _re.IGNORECASE)
                if matches:
                    violations.append(f"PII detected — {entity}: {matches}")
                    if action == "redact":
                        redacted = _re.sub(pattern, f"[{entity} REDACTED]", redacted, flags=_re.IGNORECASE)

    # ── Toxic language detection (keyword heuristic fallback) ─────────────
    if "toxic_language" in checks:
        try:
            from detoxify import Detoxify as _Detoxify
            scores = _Detoxify("original").predict(text_input)
            for label, score in scores.items():
                if score >= toxicity_threshold:
                    violations.append(f"Toxicity — {label}: {score:.2f} (threshold {toxicity_threshold})")
        except ImportError:
            # Fallback: simple blocklist heuristic
            _TOXIC_WORDS = {"hate", "kill", "abuse", "slur", "racist", "sexist"}
            words = set(text_input.lower().split())
            found = words & _TOXIC_WORDS
            if found:
                violations.append(f"Toxicity heuristic — flagged words: {sorted(found)}")

    # ── Off-topic / format checks ─────────────────────────────────────────
    if "no_profanity" in checks:
        _PROFANITY = {"fuck", "shit", "asshole", "bitch", "damn", "crap"}
        found = set(text_input.lower().split()) & _PROFANITY
        if found:
            violations.append(f"Profanity detected: {sorted(found)}")
            if action == "redact":
                for w in found:
                    redacted = redacted.replace(w, "*" * len(w))

    # ── Build result ──────────────────────────────────────────────────────
    passed = len(violations) == 0
    status = "✅ PASSED" if passed else ("⚠ WARNED" if action == "warn" else ("❌ BLOCKED" if action == "block" else "✏ REDACTED"))

    lines = [
        f"[Guardrails AI]\nMode: {mode}  Action: {action}  Status: {status}",
        f"Checks run: {', '.join(checks)}",
    ]
    if violations:
        lines.append("\nViolations found:")
        for v in violations:
            lines.append(f"  • {v}")
    else:
        lines.append("No violations detected.")

    if action == "block" and not passed:
        lines.append("\n❌ OUTPUT BLOCKED — content did not pass guardrails.")
        return "\n".join(lines)

    output_text = redacted if action == "redact" else text_input
    lines.append(f"\nOutput text:\n{output_text}")
    return "\n".join(lines)
