"""Website health check — built-in tool `website_health_check`."""

import asyncio
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="website_health_check",
    name="Website Health Check",
    icon="🩺",
    category="APIs & Integrations",
    description="Checks one or more URLs: status code, response time, redirect chain and TLS certificate expiry. Input is a URL (or several, comma-separated).",
    default_config={"timeout": 10, "expected_status": 200, "cert_warning_days": 21},
    order=80,
    parameters=params({"urls": {"type": "string", "description": "A URL, or several comma-separated"}}),
    input_param="urls",
)


def _cert_expiry(host: str, port: int) -> datetime:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=8) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            not_after = tls.getpeercert()["notAfter"]
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=timezone.utc)


async def _check(client: httpx.AsyncClient, url: str, cfg: Dict[str, Any]) -> str:
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    expected = int(cfg.get("expected_status", 200))
    started = time.monotonic()
    try:
        resp = await client.get(url)
    except httpx.TimeoutException:
        return f"✗ {url}\n    DOWN — no response within {cfg.get('timeout', 10)}s"
    except Exception as e:
        return f"✗ {url}\n    DOWN — {type(e).__name__}: {e}"
    ms = int((time.monotonic() - started) * 1000)
    ok = resp.status_code == expected
    lines = [f"{'✓' if ok else '✗'} {url}", f"    HTTP {resp.status_code} in {ms} ms" + ("" if ok else f" (expected {expected})")]
    if resp.history:
        chain = " → ".join([str(r.url) for r in resp.history] + [str(resp.url)])
        lines.append(f"    redirects: {chain}")
    final = urlparse(str(resp.url))
    if final.scheme == "https":
        try:
            expiry = await asyncio.to_thread(_cert_expiry, final.hostname, final.port or 443)
            days = (expiry - datetime.now(timezone.utc)).days
            warn = days <= int(cfg.get("cert_warning_days", 21))
            lines.append(f"    TLS certificate expires {expiry:%Y-%m-%d} ({days} days){'  ⚠ renew soon' if warn else ''}")
        except Exception as e:
            lines.append(f"    TLS certificate check failed: {e}")
    else:
        lines.append("    ⚠ not served over HTTPS")
    return "\n".join(lines)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    urls = [u.strip() for u in inp.replace("\n", ",").split(",") if u.strip()][:10]
    if not urls:
        return "[Health check] Provide a URL, e.g. 'https://example.com'."
    async with httpx.AsyncClient(timeout=float(cfg.get("timeout", 10)), follow_redirects=True,
                                 headers={"User-Agent": "PipesetsAI-HealthCheck/1.0"}) as client:
        results = await asyncio.gather(*(_check(client, u, cfg) for u in urls))
    return "[Website health check]\n" + "\n".join(results)
