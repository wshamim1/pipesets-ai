"""tool_packages.py — Settings → Tools & MCP packages: which built-in tools and MCP servers a workspace
has installed. Only installed ones are offered as nodes in the builder's sidebar; the rest wait in
the package manager. Installing is a visibility choice, not a download — every tool stays runnable,
so pipelines that use an uninstalled tool keep working (and still open and configure normally).

A tool is installed when, most specific first:

    the workspace's row for it says so (install / uninstall in the package manager)
    → it is in DEFAULTS (a small essentials set)
    → a pipeline in the workspace already uses it (so nothing disappears from existing users)

Frameworks, custom tools and custom MCP servers aren't packages; they're always shown.
Effective sets are cached per workspace for a few seconds so the catalog request doesn't scan
every pipeline; writes in this process clear the cache.
"""

import re
import time
from datetime import datetime
from typing import Dict, Iterable, List, Set, Tuple

from db import get_db_connection

SECTIONS = ("agentic_tools", "mcp_servers")
CACHE_TTL_S = 10.0

DEFAULTS: Set[str] = {
    # tools
    "duckduckgo_search", "url_scraper", "wikipedia", "calculator", "python_interpreter", "datetime_tool",
    "rest_api_caller", "file_reader", "file_writer", "csv_reader", "pdf_reader", "json_transformer",
    "sql_database", "text_summarizer", "structured_extract", "email_sender", "slack_webhook", "weather",
    "translation",
    # MCP servers
    "mcp_database", "mcp_filesystem", "mcp_fetch", "mcp_github", "mcp_remote_http", "mcp_memory", "mcp_time",
    "mcp_sequential_thinking",
}

_TOOL_ID = re.compile(r'"toolId"\s*:\s*"([^"]+)"')


class PackageStore:
    """Install state for one kind of package, one row per workspace choice in ``table``. Also used
    for built-in agents (services/agent_packages.py). ``used`` finds the ids a pipeline uses in its
    flow JSON; ``defaults`` are installed until a workspace uninstalls them."""

    def __init__(self, table: str, id_col: str, used: "re.Pattern[str]", defaults: Set[str]):
        self.table, self.id_col, self.used_re, self.defaults = table, id_col, used, defaults
        # tenant_id → (expires_at, explicit {id: installed}, ids used by pipelines)
        self._cache: Dict[str, Tuple[float, Dict[str, bool], Set[str]]] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def _state(self, tenant_id: str) -> Tuple[Dict[str, bool], Set[str]]:
        hit = self._cache.get(tenant_id)
        if hit and hit[0] > time.monotonic():
            return hit[1], hit[2]
        conn = get_db_connection()
        try:
            explicit = {r[self.id_col]: bool(r["installed"]) for r in conn.execute(
                f"SELECT {self.id_col}, installed FROM {self.table} WHERE tenant_id = ?", (tenant_id,)).fetchall()}
            used: Set[str] = set()
            for r in conn.execute("SELECT flow_data FROM apps WHERE tenant_id = ?", (tenant_id,)).fetchall():
                used.update(self.used_re.findall(r["flow_data"] or ""))
        finally:
            conn.close()
        self._cache[tenant_id] = (time.monotonic() + CACHE_TTL_S, explicit, used)
        return explicit, used

    def installed_ids(self, tenant_id: str) -> Set[str]:
        """Ids installed in this workspace (ids without a row resolve through the defaults)."""
        explicit, used = self._state(tenant_id)
        default_on = (self.defaults | used) - {i for i, on in explicit.items() if not on}
        return default_on | {i for i, on in explicit.items() if on}

    def describe(self, tenant_id: str, package_ids: Iterable[str]) -> List[Dict[str, object]]:
        """Per package: installed, why (``choice`` | ``default`` | ``in_use`` | None) and whether a pipeline uses it."""
        explicit, used = self._state(tenant_id)
        out = []
        for pid in package_ids:
            if pid in explicit:
                installed, source = explicit[pid], "choice"
            elif pid in self.defaults:
                installed, source = True, "default"
            elif pid in used:
                installed, source = True, "in_use"
            else:
                installed, source = False, None
            out.append({"id": pid, "installed": installed, "source": source, "in_use": pid in used,
                        "default": pid in self.defaults})
        return out

    def set_installed(self, tenant_id: str, user_id: str, ids: Iterable[str], installed: bool) -> None:
        now = datetime.utcnow().isoformat()
        conn = get_db_connection()
        try:
            for pid in ids:
                conn.execute(f"DELETE FROM {self.table} WHERE tenant_id = ? AND {self.id_col} = ?", (tenant_id, pid))
                conn.execute(f"INSERT INTO {self.table} (tenant_id, {self.id_col}, installed, updated_by, updated_at) "
                             "VALUES (?, ?, ?, ?, ?)", (tenant_id, pid, installed, user_id, now))
            conn.commit()
        finally:
            conn.close()
        self.clear_cache()

    def reset(self, tenant_id: str) -> None:
        """Forget every install / uninstall choice: back to the defaults plus what pipelines use."""
        conn = get_db_connection()
        try:
            conn.execute(f"DELETE FROM {self.table} WHERE tenant_id = ?", (tenant_id,))
            conn.commit()
        finally:
            conn.close()
        self.clear_cache()


STORE = PackageStore("tool_packages", "tool_id", _TOOL_ID, DEFAULTS)
clear_cache = STORE.clear_cache
installed_ids = STORE.installed_ids
describe = STORE.describe
set_installed = STORE.set_installed
reset = STORE.reset
