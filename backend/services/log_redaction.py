"""
log_redaction.py — keep credentials out of the logs.

``install()`` wraps the log-record factory, so every record from every logger (ours, uvicorn's
access log, httpx, LiteLLM, …) is checked once, after the level check and before any handler
sees it. A message containing a known key pattern is rewritten with the secret part replaced
by ``[REDACTED]`` (the recognisable prefix stays, e.g. ``sk-[REDACTED]``); tracebacks are
redacted too. Records without a match are left untouched.
"""

import logging
import re
from typing import Any

MASK = "[REDACTED]"

# Each pattern's first group is kept; the rest of the match is masked. Generic patterns run
# first, so "api_key: sk-…" becomes "api_key: [REDACTED]" rather than being masked twice.
_PATTERNS = [
    re.compile(r"(?i)\b((?:bearer|basic)\s+)[A-Za-z0-9._~+/=\-]{8,}"),
    # key=value / "key": "value" pairs
    re.compile(r"(?i)\b((?:api[_-]?key|x-api-key|access[_-]?token|auth[_-]?token|refresh[_-]?token|client[_-]?secret|"
               r"secret[_-]?access[_-]?key|password|passwd)[\"']?\s*[=:]\s*[\"']?)[^\s\"'&,;})\[\]]{4,}"),
    # Provider and service keys with a recognisable prefix
    re.compile(r"\b(sk-|gsk_|xai-|pplx-|fc-|sntrys_|lin_api_|ntn_|glpat-|github_pat_|gh[pousr]_|xox[abprs]-)"
               r"[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\b(AIza)[A-Za-z0-9_\-]{30,}"),                   # Google API keys
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),                   # AWS access key ids
    re.compile(r"\b(ps_|uas_|whk_)[A-Za-z0-9_\-]{16,}"),          # our API keys, sessions, webhook tokens
    re.compile(r"(enc://)[A-Za-z0-9_\-=]+"),                      # sealed values
    re.compile(r"(hooks\.slack\.com/services/)[A-Za-z0-9/_\-]+"),  # Slack incoming-webhook URLs
]


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + MASK, text)
    return text


def _redact_arg(arg: Any) -> Any:
    return redact(arg) if isinstance(arg, str) else arg


def _clean(record: logging.LogRecord) -> None:
    try:
        message = record.getMessage()
    except Exception:  # a broken format string — leave it for logging's own error report
        return
    clean = redact(message)
    if clean != message:
        if record.name.startswith("uvicorn.access") and isinstance(record.args, tuple):
            # uvicorn's access formatter unpacks args, so keep their shape
            record.args = tuple(_redact_arg(a) for a in record.args)
        else:
            record.msg, record.args = clean, ()
    if record.exc_info and not record.exc_text:
        record.exc_text = redact(logging.Formatter().formatException(record.exc_info))


def install() -> None:
    """Redact every log record created from now on. Safe to call more than once."""
    base = logging.getLogRecordFactory()
    if getattr(base, "_pipesets_redacting", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base(*args, **kwargs)
        _clean(record)
        return record

    factory._pipesets_redacting = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
