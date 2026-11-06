"""PyPI / npm package info — built-in tool `package_info`."""

import asyncio
from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

TOOL = ToolSpec(
    id="package_info",
    name="PyPI / npm Package Info",
    icon="📦",
    category="Code & Compute",
    description="Latest version, release date, licence, Python/Node requirements and dependencies of a PyPI or npm package. Input like 'httpx' or 'npm:react'.",
    default_config={"registry": "auto"},
    order=100,
    selects={
        "registry": Select("Registry", (("auto", "Auto (PyPI, then npm)"), ("pypi", "PyPI"), ("npm", "npm"))),
    },
    parameters=params(
        {"package": {"type": "string", "description": "Package name, e.g. httpx or npm:react"}},
        {"registry": enum(["auto", "pypi", "npm"], "Where to look")},
    ),
    input_param="package",
)


async def _pypi(client: httpx.AsyncClient, name: str) -> Optional[str]:
    resp = await client.get(f"https://pypi.org/pypi/{name}/json")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    d = resp.json()
    info = d.get("info", {})
    released = (d.get("urls") or [{}])[0].get("upload_time", "")[:10]
    deps = [r.split(";")[0].strip() for r in (info.get("requires_dist") or []) if "extra ==" not in r]
    urls = info.get("project_urls") or {}
    home = info.get("home_page") or urls.get("Homepage") or urls.get("Source") or next(iter(urls.values()), "")
    licence = info.get("license_expression") or (info.get("license") or "").split("\n")[0][:60] or "unknown"
    return (f"[PyPI: {info.get('name', name)} {info.get('version', '?')}]" + (f" released {released}" if released else "")
            + f"\n  {info.get('summary', '')}\n  licence: {licence}"
            + (f" · requires Python {info['requires_python']}" if info.get("requires_python") else "")
            + (f"\n  dependencies: {', '.join(deps[:15])}{' …' if len(deps) > 15 else ''}" if deps else "\n  dependencies: none")
            + (f"\n  {home}" if home else "") + f"\n  https://pypi.org/project/{info.get('name', name)}/")


async def _npm(client: httpx.AsyncClient, name: str) -> Optional[str]:
    resp, dl = await asyncio.gather(
        client.get(f"https://registry.npmjs.org/{name}/latest"),
        client.get(f"https://api.npmjs.org/downloads/point/last-week/{name}"),
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    d = resp.json()
    deps = list((d.get("dependencies") or {}).keys())
    downloads = dl.json().get("downloads") if dl.status_code == 200 else None
    repo = d.get("repository")
    repo_url = repo.get("url", "") if isinstance(repo, dict) else (repo or "")
    return (f"[npm: {d.get('name', name)} {d.get('version', '?')}]"
            + (f" — {downloads:,} downloads last week" if downloads is not None else "")
            + f"\n  {d.get('description', '')}\n  licence: {d.get('license', 'unknown')}"
            + (f" · node {d['engines']['node']}" if isinstance(d.get("engines"), dict) and d["engines"].get("node") else "")
            + (f"\n  dependencies: {', '.join(deps[:15])}{' …' if len(deps) > 15 else ''}" if deps else "\n  dependencies: none")
            + (f"\n  {repo_url.replace('git+', '')}" if repo_url else "") + f"\n  https://www.npmjs.com/package/{d.get('name', name)}")


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    raw = inp.strip().split()[0] if inp.strip() else ""
    if not raw:
        return "[Packages] Provide a package name, e.g. 'httpx' or 'npm:react'."
    registry = cfg.get("registry", "auto")
    if ":" in raw and raw.split(":", 1)[0].lower() in ("pypi", "npm", "pip"):
        prefix, raw = raw.split(":", 1)
        registry = "npm" if prefix.lower() == "npm" else "pypi"
    if registry == "auto" and (raw.startswith("@") or "/" in raw):
        registry = "npm"  # scoped packages only exist on npm
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            order = {"pypi": [_pypi], "npm": [_npm]}.get(registry, [_pypi, _npm])
            for lookup in order:
                found = await lookup(client, raw)
                if found:
                    return found
        return f"[Packages] '{raw}' was not found on {'PyPI or npm' if registry == 'auto' else registry}."
    except Exception as e:
        return f"[Packages] Error: {e}"
