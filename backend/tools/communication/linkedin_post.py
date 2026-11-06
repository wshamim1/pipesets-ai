"""LinkedIn Post — built-in tool `linkedin_post` (LinkedIn Posts API, as the signed-in member).

Publishes a text post to the member's own feed. Needs a member access token with the ``openid`` and
``w_member_social`` scopes (a LinkedIn app with "Share on LinkedIn" and "Sign In with OpenID Connect"); the
member's id comes from /v2/userinfo. ``api_version`` is LinkedIn's YYYYMM version header — each is
supported for about a year, so move it forward over time. This is the only LinkedIn write LinkedIn
allows without a partner program; job search and profiles aren't available through its public API.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, params

LABEL = "[LinkedIn]"
API_VERSION = "202610"
MAX_CHARS = 3000

TOOL = ToolSpec(
    id="linkedin_post",
    name="LinkedIn Post",
    icon="🔗",
    category="Communication",
    description="Publishes a text post to your own LinkedIn feed via the official Posts API (member token with w_member_social). Input: the post text.",
    default_config={"access_token": "", "visibility": "PUBLIC", "api_version": API_VERSION},
    order=126,
    required=("access_token",),
    selects={"visibility": Select("Visibility", (("PUBLIC", "Anyone"), ("CONNECTIONS", "Connections only")))},
    parameters=params({"text": {"type": "string", "description": f"The post text (up to {MAX_CHARS} characters)"}}),
    input_param="text",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = str(cfg.get("access_token") or "").strip()
    if not token:
        return f"{LABEL} access_token (a member token with w_member_social) is required in config."
    text = inp.strip()
    if not text:
        return f"{LABEL} Provide the post text."
    if len(text) > MAX_CHARS:
        return f"{LABEL} The post is {len(text)} characters; LinkedIn allows {MAX_CHARS}."
    visibility = str(cfg.get("visibility") or "PUBLIC").upper()
    if visibility not in ("PUBLIC", "CONNECTIONS"):
        return f"{LABEL} visibility is PUBLIC or CONNECTIONS — got '{visibility}'."
    auth = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            me = await client.get("https://api.linkedin.com/v2/userinfo", headers=auth)
            if me.status_code in (401, 403):
                return f"{LABEL} HTTP {me.status_code} reading your profile — the token needs the openid scope and mustn't be expired."
            if me.status_code >= 400:
                return f"{LABEL} HTTP {me.status_code} from /v2/userinfo: {me.text[:200]}"
            author = f"urn:li:person:{me.json().get('sub')}"
            resp = await client.post("https://api.linkedin.com/rest/posts", headers={
                **auth, "LinkedIn-Version": str(cfg.get("api_version") or API_VERSION), "X-Restli-Protocol-Version": "2.0.0",
            }, json={
                "author": author, "commentary": text, "visibility": visibility,
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
            })
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach LinkedIn: {e}"
    if resp.status_code == 403:
        return f"{LABEL} HTTP 403 — the token needs the w_member_social scope."
    if resp.status_code == 426 or "NONEXISTENT_VERSION" in resp.text or "VERSION_MISSING" in resp.text:
        return f"{LABEL} LinkedIn rejected API version {cfg.get('api_version') or API_VERSION} — set api_version to a current YYYYMM."
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"
    post_id = resp.headers.get("x-restli-id", "")
    return f"{LABEL} Posted ({visibility.lower()})." + (f" https://www.linkedin.com/feed/update/{post_id}/" if post_id else "")
