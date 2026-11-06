"""
llm_auth.py — per-call credentials for model calls.

The LLM gateway (``llm/``) resolves each request's key here and passes it to the backend
per call instead of writing it to os.environ: the process environment is shared by every
concurrent request, so an env-based key could leak into another user's call (and a call
without a key would silently use whichever key was set last).

A node's key may be plaintext, a "secret://" vault ref or a sealed value; an empty key
falls back to the project's default key for the provider from the vault, and finally to
"" — the backend then uses the server's own env vars.
"""

from typing import Optional

from services import secret_store


def resolve_api_key(provider: str, api_key: Optional[str]) -> str:
    key = (api_key or "").strip() or secret_store.default_ref(provider)
    return secret_store.reveal_value(key, purpose="llm") if key else ""
