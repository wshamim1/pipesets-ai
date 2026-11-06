"""Google Contacts — built-in tool `google_contacts` (People API v1, read-only).

Actions: ``list`` (a page of contacts, alphabetical) and ``search`` (query matches on names,
emails, phone numbers etc.). Auth is an OAuth access token with the
https://www.googleapis.com/auth/contacts.readonly scope (+ refresh token / client id / secret
when present) in the node config, resolved from a ``secret://`` ref.
"""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, enum, params
from tools.productivity._google_auth import call as google_call
from tools.productivity._google_auth import http_error

LABEL = "[Google Contacts]"
PEOPLE_API = "https://people.googleapis.com/v1"
_READ_MASK = "names,emailAddresses,phoneNumbers,biographies"  # noqa: RUF012


def _first(items: Any) -> str:
    """The first value entry for a contact field (e.g. primary display name)."""
    try:
        return str((list(items) or [None])[0].get("value") or "").strip()
    except AttributeError:
        return ""


def _who(person: Dict[str, Any]) -> str:
    """One line: display name — emails — phones (title case like the API sends)."""
    name = _first(person.get("names") or {}) or "(no name)"
    emails = [str(e.get("value") or "").strip() for e in person.get("emailAddresses") or []]
    phones = [str(p.get("value") or "").strip() for p in person.get("phoneNumbers") or []]
    parts = " — ".join(p for p in [name,
                                   ", ".join(filter(None, emails)),
                                   ", ".join(filter(None, phones))] if p)
    return f"  {parts}"


TOOL = ToolSpec(
    id="google_contacts",
    name="Google Contacts",
    icon="👥",
    category="Productivity",
    description="Lists or searches the user's Google Contacts (names, emails, phones, notes) via the People API.",
    default_config={"access_token": "", "max_results": 25},
    order=50,
    required=("access_token",),
    parameters=params(
        {"action": enum(["list", "search"], "list = a page of contacts, search = contacts matching a query")},
        {
            "query": {"type": "string", "description": "Search text: name, email, phone… (search)"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Most contacts to return (list)"},
        },
    ),
    input_param="action",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide an OAuth access token (or a secret:// ref) "
                "with the contacts.readonly scope.")
    action = str(inp or "").strip().lower()
    if action not in ("list", "search"):
        return f'{LABEL} Action is "list" or "search" — got "{inp}".'

    max_results = min(max(int(cfg.get("max_results", 25) or 25), 1), 100)
    query = str(cfg.get("query") or "").strip()
    if action == "search":
        if not query:
            return f"{LABEL} search needs a query — text to match against names, emails or phones."
        resp = await google_call(cfg, "GET", f"{PEOPLE_API}/people:searchContacts", query={
            "query": query, "pageSize": max_results, "readMask": _READ_MASK})
    else:
        resp = await google_call(cfg, "GET", f"{PEOPLE_API}/people:listContacts", query={
            "pageSize": max_results, "readMask": _READ_MASK})
    if resp.status_code != 200:
        return http_error(LABEL, resp)
    people = resp.json().get("people") or []
    if not people:
        target = f' matching "{query}"' if action == "search" else ""
        return f"{LABEL} No contacts{target}."

    header = (f"{LABEL} {len(people)} contact(s)"
              + (f' matching "{query}"' if action == "search" else ""))
    return "\n".join([header, ""] + [_who(p) for p in people])
