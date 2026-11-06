"""SSL certificate check — built-in tool `ssl_certificate_check` (TLS handshake; no key).

Connects to host:port (443 by default; a URL works too), validates the certificate chain and host
name the way a browser would, and reports the subject, issuer, alternative names and days until
expiry. A certificate that fails validation (expired, self-signed, wrong host) is reported as such.
"""

import asyncio
import re
import ssl
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from tools.base import ToolSpec, params

LABEL = "[SSL Check]"
_HOST = re.compile(r"^[A-Za-z0-9.-]+$")

TOOL = ToolSpec(
    id="ssl_certificate_check",
    name="SSL Certificate Check",
    icon="🔐",
    category="APIs & Integrations",
    description="Checks a site's TLS certificate: valid or not, issuer, names it covers, and days until it expires. Input: a host, host:port or URL.",
    default_config={"warn_days": 30, "timeout": 10},
    order=98,
    parameters=params({"host": {"type": "string", "description": "Host name, host:port or https URL"}}),
    input_param="host",
)


def _target(inp: str):
    text = inp.strip().strip("'\"")
    if "://" in text:
        parsed = urlparse(text)
        return parsed.hostname or "", parsed.port or 443
    host, _, port = text.partition(":")
    return host.strip().strip("/"), int(port) if port.isdigit() else 443


def _names(pairs) -> str:
    return ", ".join(f"{k}={v}" for rdn in pairs or () for k, v in rdn if k in ("commonName", "organizationName"))


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    host, port = _target(inp)
    if not host or not _HOST.match(host) or not (0 < port < 65536):
        return f"{LABEL} Provide a host like example.com, example.com:8443 or https://example.com."
    timeout = float(cfg.get("timeout") or 10)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl.create_default_context(), server_hostname=host), timeout)
    except ssl.SSLCertVerificationError as e:
        return f"{LABEL} {host}:{port} — INVALID certificate: {e.verify_message or e.reason}"
    except asyncio.TimeoutError:
        return f"{LABEL} {host}:{port} didn't complete a TLS handshake within {timeout:g}s."
    except (ssl.SSLError, OSError) as e:
        return f"{LABEL} Couldn't complete a TLS handshake with {host}:{port}: {e or type(e).__name__}"
    try:
        cert = writer.get_extra_info("peercert") or {}
        tls = writer.get_extra_info("ssl_object")
        protocol = tls.version() if tls else "?"
    finally:
        writer.close()
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), timezone.utc)
    issued = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notBefore"]), timezone.utc)
    days = (expires - datetime.now(timezone.utc)).days
    warn = int(cfg.get("warn_days") or 30)
    verdict = "VALID" if days > warn else f"VALID but expires in {days} day(s) (warning at {warn})"
    sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    return (f"{LABEL} {host}:{port} — {verdict}\n"
            f"  Subject  : {_names(cert.get('subject'))}\n"
            f"  Issuer   : {_names(cert.get('issuer'))}\n"
            f"  Valid    : {issued:%Y-%m-%d} → {expires:%Y-%m-%d} ({days} days left)\n"
            f"  Names    : {', '.join(sans[:20])}{' …' if len(sans) > 20 else ''}\n"
            f"  Protocol : {protocol}")
