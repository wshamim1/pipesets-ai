"""Mastodon — built-in tool `mastodon_post` (Mastodon API v1 statuses, any instance)."""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, params

LABEL = "[Mastodon]"
VISIBILITY = (("public", "Public"), ("unlisted", "Unlisted"), ("private", "Followers only"), ("direct", "Mentioned people only"))

TOOL = ToolSpec(
    id="mastodon_post",
    name="Mastodon Post",
    icon="🐘",
    category="Communication",
    description="Posts a status to Mastodon (or any Mastodon-compatible server) with an access token.",
    default_config={"instance_url": "https://mastodon.social", "access_token": "", "visibility": "public"},
    order=125,
    required=("instance_url", "access_token"),
    selects={"visibility": Select("Visibility", VISIBILITY)},
    parameters=params({"text": {"type": "string", "description": "The status text"}}),
    input_param="text",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    instance = (cfg.get("instance_url") or "").strip().rstrip("/")
    token = (cfg.get("access_token") or "").strip()
    if not instance:
        return f"{LABEL} instance_url (e.g. https://mastodon.social) is required in config."
    if not token:
        return f"{LABEL} access_token (Preferences → Development → New application, write:statuses) is required in config."
    if not inp:
        return f"{LABEL} Provide the text to post."
    if not instance.startswith(("http://", "https://")):
        instance = f"https://{instance}"
    visibility = cfg.get("visibility") or "public"
    if visibility not in dict(VISIBILITY):
        return f"{LABEL} Visibility is one of {', '.join(dict(VISIBILITY))} — got '{visibility}'."
    try:
        async with httpx.AsyncClient(timeout=15.0, headers={"Authorization": f"Bearer {token}"}) as client:
            resp = await client.post(f"{instance}/api/v1/statuses", data={"status": inp, "visibility": visibility})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {instance}: {e}"
    if resp.status_code == 401:
        return f"{LABEL} The access_token is invalid or lacks write:statuses."
    try:
        body = resp.json()
    except ValueError:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:200]}"
    if resp.status_code != 200:
        return f"{LABEL} Not posted: {body.get('error') or f'HTTP {resp.status_code}'}"
    return f"{LABEL} Posted ({visibility}).\n{body.get('url', '')}"
