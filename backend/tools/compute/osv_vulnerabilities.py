"""OSV vulnerabilities — built-in tool `osv_vulnerabilities` (OSV.dev API; free, no key).

Input: ``<ecosystem>:<package>@<version>`` (``PyPI:requests@2.19.0``, ``npm:lodash@4.17.15``,
``Maven:org.apache.logging.log4j:log4j-core@2.14.1``) lists the known vulnerabilities affecting
that version, with severity, aliases (CVE ids) and the versions that fix them. Without ``@version``
every advisory for the package is listed. A vulnerability id (``GHSA-…``, ``CVE-…``, ``PYSEC-…``)
reads that advisory.
"""

import re
from typing import Any, Dict, List, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[OSV]"
API = "https://api.osv.dev/v1"
ECOSYSTEMS = {e.lower(): e for e in (
    "PyPI", "npm", "Maven", "Go", "crates.io", "RubyGems", "NuGet", "Packagist", "Pub", "Hex", "Hackage",
    "CRAN", "SwiftURL", "Debian", "Ubuntu", "Alpine", "GitHub Actions", "Bitnami", "Linux")}
ECOSYSTEMS.update({"pip": "PyPI", "python": "PyPI", "node": "npm", "cargo": "crates.io", "rust": "crates.io",
                   "gem": "RubyGems", "ruby": "RubyGems", "golang": "Go", "composer": "Packagist", "dart": "Pub"})
_VULN_ID = re.compile(r"^[A-Z][A-Z0-9]*-[A-Za-z0-9._:-]+$")

TOOL = ToolSpec(
    id="osv_vulnerabilities",
    name="OSV Vulnerabilities",
    icon="🛡️",
    category="Code & Compute",
    description="Known security vulnerabilities in an open-source package version (PyPI, npm, Maven, Go, crates.io, RubyGems, NuGet…) from OSV.dev, with severity and fixed versions; or one advisory by id. Free, no key.",
    default_config={"max_results": 20},
    order=105,
    parameters=params({"package": {"type": "string", "description": "ecosystem:package@version (e.g. PyPI:requests@2.19.0, npm:lodash@4.17.15), or an advisory id like GHSA-… or CVE-…"}}),
    input_param="package",
    is_new=True,
)


def _severity(v: Dict[str, Any]) -> str:
    sev = (v.get("database_specific") or {}).get("severity")
    if not sev:
        for a in v.get("affected") or []:
            sev = (a.get("database_specific") or a.get("ecosystem_specific") or {}).get("severity")
            if sev:
                break
    vectors = [s.get("score") for s in v.get("severity") or [] if s.get("score")]
    return " · ".join(str(x) for x in (sev, vectors[0] if vectors else None) if x) or "severity not given"


def _fixed(v: Dict[str, Any], package: str) -> List[str]:
    out: List[str] = []
    for a in v.get("affected") or []:
        if package and (a.get("package") or {}).get("name", "").lower() != package.lower():
            continue
        for r in a.get("ranges") or []:
            out += [e["fixed"] for e in r.get("events") or [] if e.get("fixed") and e["fixed"] not in out]
    return out


def _line(v: Dict[str, Any], package: str = "") -> str:
    aliases = [a for a in v.get("aliases") or [] if a != v.get("id")]
    fixed = _fixed(v, package)
    return (f"- {v.get('id')}{' (' + ', '.join(aliases[:3]) + ')' if aliases else ''} · {_severity(v)}\n"
            f"    {(v.get('summary') or (v.get('details') or '').split(chr(10))[0])[:200]}\n"
            f"    Fixed in: {', '.join(fixed[:6]) if fixed else 'no fixed version listed'}"
            f" · https://osv.dev/vulnerability/{v.get('id')}")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text = inp.strip().strip("'\"")
    limit = max(1, min(int(cfg.get("max_results") or 20), 100))
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if _VULN_ID.match(text) and ":" not in text:
                resp = await client.get(f"{API}/vulns/{text}")
                if resp.status_code == 404:
                    return f"{LABEL} No advisory {text} in OSV."
                if resp.status_code >= 400:
                    return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
                v = resp.json()
                return (f"{LABEL} {v.get('id')}: {v.get('summary') or ''}\n{_line(v)}\n"
                        f"  Affects: {', '.join(sorted({(a.get('package') or {}).get('ecosystem', '') + ':' + (a.get('package') or {}).get('name', '') for a in v.get('affected') or []})) or '?'}"
                        f"\n  Published {(v.get('published') or '')[:10]} · modified {(v.get('modified') or '')[:10]}\n\n"
                        + (v.get("details") or "")[:3000])
            eco, sep, rest = text.partition(":")
            if not sep or not rest:
                return f"{LABEL} Input is ecosystem:package@version (e.g. PyPI:requests@2.19.0), or an advisory id."
            ecosystem = ECOSYSTEMS.get(eco.strip().lower())
            if not ecosystem:
                return f"{LABEL} Unknown ecosystem '{eco}'. Use one of: PyPI, npm, Maven, Go, crates.io, RubyGems, NuGet, Packagist, Pub, Hex."
            rest = rest.strip()  # an npm scope's leading @ isn't the version separator
            name, _, version = rest.rpartition("@") if "@" in rest.lstrip("@") else (rest, "", "")
            body: Dict[str, Any] = {"package": {"name": name, "ecosystem": ecosystem}}
            if version:
                body["version"] = version
            resp = await client.post(f"{API}/query", json=body)
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach OSV.dev: {e}"
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    vulns = data.get("vulns") or []
    what = f"{ecosystem} {name}" + (f" {version}" if version else "")
    if not vulns:
        return f"{LABEL} No known vulnerabilities for {what}."
    more = " (more on the next page)" if data.get("next_page_token") else ""
    return (f"{LABEL} {len(vulns)} known vulnerabilit{'y' if len(vulns) == 1 else 'ies'} "
            f"{'affecting' if version else 'reported for'} {what}{more}\n" + "\n".join(_line(v, name) for v in vulns[:limit]))
