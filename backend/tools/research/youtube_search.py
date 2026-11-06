"""YouTube Search — built-in tool `youtube_search` (YouTube Data API v3).

Searches videos, channels or playlists: title, channel, publish date, description and link.
Auth is a YouTube Data API v3 key in the node config (an API key, not OAuth), resolved from a
``secret://`` ref like any other credential.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import MAX_RESULTS, ToolSpec, enum, params
from tools.productivity._google_auth import http_error

LABEL = "[YouTube]"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

_LINK = {
    "video": lambda vid: f"https://www.youtube.com/watch?v={vid}",
    "playlist": lambda vid: f"https://www.youtube.com/playlist?list={vid}",
    "channel": lambda vid: f"https://www.youtube.com/channel/{vid}",
}
_ID_FIELD = {"video": "videoId", "playlist": "playlistId", "channel": "channelId"}


TOOL = ToolSpec(
    id="youtube_search",
    name="YouTube Search",
    icon="▶️",
    category="Research & Knowledge",
    description="Searches YouTube for videos, channels or playlists (titles, channels, dates, links) via the YouTube Data API.",
    default_config={"api_key": "", "type": "video", "query": "", "max_results": 10},
    order=135,
    required=("api_key",),
    parameters=params(
        {"query": {"type": "string", "description": "What to search for"}},
        {
            "max_results": MAX_RESULTS,
            "type": enum(["video", "channel", "playlist"], "What kind of result"),
        },
    ),
    input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    query = inp if inp.strip() else str(cfg.get("query") or "").strip()
    if not query:
        return f"{LABEL} Provide a search query as input."
    kind = str(cfg.get("type") or "video").strip() or "video"
    if kind not in _LINK:
        return f'{LABEL} type is "video", "channel" or "playlist" — got "{kind}".'
    max_results = min(max(int(cfg.get("max_results", 10) or 10), 1), 20)

    key = (cfg.get("api_key") or "").strip()
    if not key:
        return f"{LABEL} api_key is required in config — provide a YouTube Data API v3 key (or a secret:// ref)."
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{YOUTUBE_API}/search", params={
                "part": "snippet", "q": query, "type": kind, "maxResults": max_results, "key": key})
    except Exception as e:
        return f"{LABEL} Error: {e}"
    if resp.status_code != 200:
        if resp.status_code == 403:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            return (f"{LABEL} 403 Forbidden — the api_key is invalid or the YouTube Data API isn't "
                    f"enabled for it.{f' ({detail[:200]})' if detail else ''}")
        return http_error(LABEL, resp)
    items = resp.json().get("items") or []
    if not items:
        return f'{LABEL} No {kind} results for "{query}".'

    lines = [f'{LABEL} {len(items)} {kind}(s) for "{query}"', ""]
    for item in items:
        snippet = item.get("snippet") or {}
        title = str(snippet.get("title") or "(untitled)").replace("\n", " ")
        vid = (item.get("id") or {}).get(_ID_FIELD[kind]) or ""
        lines.append(f"  {title}\n    {snippet.get('channelTitle') or '?'}  {str(snippet.get('publishedAt') or '')[:10]}\n"
                     f"    {_LINK[kind](vid)}")
        desc = str(snippet.get("description") or "").strip()
        if desc:
            lines.append(f"    {desc[:150]}")
    return "\n".join(lines)
