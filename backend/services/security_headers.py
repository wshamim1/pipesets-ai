"""
security_headers.py — browser hardening headers on every backend response.

A plain ASGI middleware (not ``BaseHTTPMiddleware``), so SSE streams pass through untouched.
The backend only serves JSON, files and streams, so the CSP forbids everything and the
response can't be framed. The Swagger / ReDoc pages load scripts from a CDN and get a relaxed
policy instead. HSTS is sent only on HTTPS requests (directly or behind a proxy that sets
``X-Forwarded-Proto``), so a plain-HTTP localhost or desktop backend never pins the browser.
A header the route already set is left as it is.
"""

import os

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; "
            "worker-src 'self' blob:; frame-ancestors 'none'")
DOCS_PATHS = ("/docs", "/redoc")

_COMMON = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


def _hsts_value() -> bytes:
    max_age = os.getenv("HSTS_MAX_AGE", "31536000")
    return f"max-age={max_age}; includeSubDomains".encode()


def _is_https(scope) -> bool:
    if scope.get("scheme") == "https":
        return True
    for name, value in scope.get("headers") or []:
        if name == b"x-forwarded-proto":
            return value.split(b",")[0].strip().lower() == b"https"
    return False


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        csp = DOCS_CSP if path.startswith(DOCS_PATHS) else API_CSP
        extra = _COMMON + [(b"content-security-policy", csp.encode())]
        if _is_https(scope) and os.getenv("HSTS_ENABLED", "true").lower() not in ("0", "false", "no"):
            extra.append((b"strict-transport-security", _hsts_value()))

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}
                headers.extend((name, value) for name, value in extra if name not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
