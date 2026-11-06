"""
child_env.py — the environment handed to third-party child processes (MCP stdio servers).

The backend's own environment holds the master key, provider API keys and the database URL, so
a child must never inherit it wholesale. ``scrubbed_env()`` copies only what a launcher like
npx / uvx / docker needs to find binaries, caches, locale, proxies and CA certificates, then
adds the server's own configured variables on top.
"""

import os
from typing import Dict, Mapping, Optional

_ALLOWED = {
    # binaries, user, shell, locale, temp dirs
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TERM", "TZ",
    "TMPDIR", "TEMP", "TMP",
    # outbound proxies and corporate CA bundles
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    # node / python launchers
    "NVM_DIR", "NVM_BIN", "VOLTA_HOME", "PNPM_HOME", "UV_CACHE_DIR", "UV_TOOL_DIR", "PIPX_HOME",
    "DOCKER_HOST", "DOCKER_CONFIG",
    # Windows: without these, spawning node / python fails
    "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA",
    "USERPROFILE", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH",
}
_ALLOWED_PREFIXES = ("LC_", "XDG_")


def scrubbed_env(extra: Optional[Mapping[str, str]] = None,
                 base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Allow-listed variables from ``base`` (default ``os.environ``), plus ``extra``."""
    source = os.environ if base is None else base
    env = {k: v for k, v in source.items() if k in _ALLOWED or k.startswith(_ALLOWED_PREFIXES)}
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env
