"""GitHub API — built-in tool `github_api`."""

import os
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, enum, params

TOOL = ToolSpec(
    id="github_api",
    name="GitHub API",
    icon="🐙",
    category="APIs & Integrations",
    description="Fetch repo info, issues, PRs, commits, or file contents from GitHub. Input is owner/repo or a natural language query.",
    default_config={"github_token": "", "action": "repo_info"},
    order=20,
    parameters=params({"repo": {"type": "string", "description": "owner/repo or a GitHub URL"}},
                      {"action": enum(["repo_info", "issues", "pulls", "commits"], "What to fetch")}),
    input_param="repo",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = cfg.get("github_token", "") or os.environ.get("GITHUB_TOKEN", "")
    action = cfg.get("action", "repo_info")
    gh_headers: Dict[str, Any] = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        gh_headers["Authorization"] = f"Bearer {token}"
    # Parse owner/repo from input — accept "owner/repo" or full GitHub URLs
    import re as _re
    slug_match = _re.search(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", inp.strip())
    slug = slug_match.group(1) if slug_match else inp.strip()
    base = "https://api.github.com"
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=gh_headers) as client:
            if action == "issues":
                resp = await client.get(f"{base}/repos/{slug}/issues", params={"state": "open", "per_page": 10})
                resp.raise_for_status()
                issues = resp.json()
                if not issues:
                    return f"[GitHub] No open issues for {slug}"
                lines = [f"[GitHub Issues: {slug}]"]
                for iss in issues[:10]:
                    lines.append(f"  #{iss['number']} {iss['title']} — {iss.get('user', {}).get('login', '?')}")
                return "\n".join(lines)
            elif action == "commits":
                resp = await client.get(f"{base}/repos/{slug}/commits", params={"per_page": 10})
                resp.raise_for_status()
                commits = resp.json()
                lines = [f"[GitHub Commits: {slug}]"]
                for c in commits[:10]:
                    msg = c.get("commit", {}).get("message", "").split("\n")[0]
                    author = c.get("commit", {}).get("author", {}).get("name", "?")
                    sha = c.get("sha", "")[:7]
                    lines.append(f"  {sha} {author}: {msg}")
                return "\n".join(lines)
            elif action == "pulls":
                resp = await client.get(f"{base}/repos/{slug}/pulls", params={"state": "open", "per_page": 10})
                resp.raise_for_status()
                prs = resp.json()
                if not prs:
                    return f"[GitHub] No open PRs for {slug}"
                lines = [f"[GitHub Pull Requests: {slug}]"]
                for pr in prs[:10]:
                    lines.append(f"  #{pr['number']} {pr['title']} — {pr.get('user', {}).get('login', '?')}")
                return "\n".join(lines)
            else:  # repo_info (default)
                resp = await client.get(f"{base}/repos/{slug}")
                resp.raise_for_status()
                r = resp.json()
                return (
                    f"[GitHub Repo: {slug}]\n"
                    f"  Description : {r.get('description', 'N/A')}\n"
                    f"  Stars       : {r.get('stargazers_count', 0)}\n"
                    f"  Forks       : {r.get('forks_count', 0)}\n"
                    f"  Open Issues : {r.get('open_issues_count', 0)}\n"
                    f"  Language    : {r.get('language', 'N/A')}\n"
                    f"  Default Br. : {r.get('default_branch', 'main')}\n"
                    f"  URL         : {r.get('html_url', '')}"
                )
    except Exception as e:
        return f"[GitHub] Error: {e}"
