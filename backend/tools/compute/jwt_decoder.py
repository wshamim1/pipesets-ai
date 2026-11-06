"""JWT decoder — built-in tool `jwt_decoder` (offline).

Decodes a JSON Web Token's header and claims, turns exp / iat / nbf into dates and says whether it
has expired. With ``hmac_secret`` set, HS256 / HS384 / HS512 signatures are verified; otherwise the
signature is not checked and the output says so. The token is never sent anywhere.
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

LABEL = "[JWT]"
HASHES = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}
TIME_CLAIMS = ("exp", "iat", "nbf", "auth_time")

TOOL = ToolSpec(
    id="jwt_decoder",
    name="JWT Decoder",
    icon="🪪",
    category="Code & Compute",
    description="Decodes a JWT's header and claims, shows expiry as a date, and verifies HS256/384/512 signatures when a secret is configured. Offline.",
    default_config={"hmac_secret": ""},
    order=110,
    parameters=params({"jwt": {"type": "string", "description": "The JWT (header.payload.signature); a 'Bearer ' prefix is fine"}}),
    input_param="jwt",
)


def _b64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _when(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        return "not a timestamp"


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = inp.strip().strip("'\"")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    parts = token.split(".")
    if len(parts) != 3:
        return f"{LABEL} A JWT has three dot-separated parts; this has {len(parts)}." + (
            " (Five parts means an encrypted JWE, which can't be read without its key.)" if len(parts) == 5 else "")
    try:
        header = json.loads(_b64(parts[0]))
        claims = json.loads(_b64(parts[1]))
    except (ValueError, UnicodeDecodeError) as e:
        return f"{LABEL} Not a valid JWT: {e}"
    if not isinstance(header, dict) or not isinstance(claims, dict):
        return f"{LABEL} Not a valid JWT: header and payload must be JSON objects."

    alg = str(header.get("alg", ""))
    secret = cfg.get("hmac_secret") or ""
    if alg.lower() == "none":
        signature = "NONE — the token is unsigned (alg: none); don't trust it"
    elif not secret:
        signature = "not verified (set hmac_secret to check HS256/384/512)"
    elif alg not in HASHES:
        signature = f"not verified ({alg} needs a public key; only HMAC algorithms are checked)"
    else:
        expected = hmac.new(secret.encode(), f"{parts[0]}.{parts[1]}".encode(), HASHES[alg]).digest()
        try:
            ok = hmac.compare_digest(expected, _b64(parts[2]))
        except ValueError:
            ok = False
        signature = "VALID" if ok else "INVALID — the signature doesn't match hmac_secret"

    now = datetime.now(timezone.utc).timestamp()
    status = []
    if isinstance(claims.get("exp"), (int, float)):
        left = claims["exp"] - now
        status.append(f"EXPIRED {_ago(-left)} ago" if left < 0 else f"expires in {_ago(left)}")
    if isinstance(claims.get("nbf"), (int, float)) and claims["nbf"] > now:
        status.append(f"not valid for another {_ago(claims['nbf'] - now)}")
    dates = [f"  {k}: {claims[k]} → {_when(claims[k])}" for k in TIME_CLAIMS if k in claims]
    return "\n".join([
        f"{LABEL} {alg or '?'} token · signature {signature}" + (f" · {'; '.join(status)}" if status else ""),
        "", "Header:", json.dumps(header, indent=2), "", "Claims:", json.dumps(claims, indent=2, ensure_ascii=False),
        *(["", "Dates:", *dates] if dates else []),
    ])


def _ago(seconds: float) -> str:
    seconds = int(seconds)
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"
