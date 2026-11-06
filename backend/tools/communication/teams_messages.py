"""Microsoft Teams messages — built-in tool `teams_messages` (Microsoft Graph teams).

Actions: ``channels`` (the user's teams and their channels) and ``messages`` (top-level posts in
a channel, and the replies of one). Config holds team_id and channel_id (from ``channels``);
message_id is optional for replies. Auth is a delegated Microsoft OAuth access token (+ refresh
token / client id / secret when present) in the node config, resolved from a ``secret://`` ref.
Delegate scopes: ``offline_access Team.ReadBasic.All Channel.ReadBasic.All ChannelMessage.Read.All``.
For posting, use the existing `teams_webhook` tool.
"""

from typing import Any, Dict, List, Optional

from tools.base import MAX_RESULTS, ToolSpec, enum, params
from tools.productivity._ms_auth import GRAPH, call as ms_call
from tools.productivity._ms_auth import ms_error

LABEL = "[Teams Messages]"


def _clean(html_text: str) -> str:
    """A message body (text or HTML) as readable text."""
    import html as _html
    import re as _re
    text = html_text or ""
    if "<" in text and ">" in text:
        text = _html.unescape(_re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", text))).strip()
    return text


TOOL = ToolSpec(
    id="teams_messages",
    name="Microsoft Teams Messages",
    icon="💬",
    category="Communication",
    description=("Reads Microsoft Teams through Microsoft Graph: lists the user's teams and "
                 "channels, lists the posts in a channel and the replies of a post (posting uses "
                 "the Microsoft Teams Webhook tool). Delegated Graph scope: ChannelMessage.Read.All."),
    default_config={"access_token": "", "action": "channels", "team_id": "", "channel_id": "",
                    "message_id": "", "max_results": 10},
    order=100,
    required=("access_token",),
    parameters=params(
        {"action": enum(["channels", "messages"], "channels = your teams and their channels, messages = the posts of a channel")},
        {
            "team_id": {"type": "string", "description": "The team id (from channels)"},
            "channel_id": {"type": "string", "description": "The channel id (from channels)"},
            "message_id": {"type": "string", "description": "Optional: a post id to read its replies"},
            "max_results": MAX_RESULTS,
        },
    ),
    input_param="action",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = (cfg.get("access_token") or "").strip()
    if not token:
        return (f"{LABEL} access_token is required in config — provide a Microsoft OAuth access token "
                "(or a secret:// ref) with the ChannelMessage.Read.All delegated scope.")
    action = str(inp or cfg.get("action") or "").strip().lower() or "channels"
    if action not in ("channels", "messages"):
        return f'{LABEL} Action is "channels" or "messages" — got "{inp}".'

    if action == "channels":
        teams = await ms_call(cfg, "GET", f"{GRAPH}/me/joinedTeams", query={"$select": "id,displayName", "$top": 10})
        if teams.status_code != 200:
            return ms_error(LABEL, teams)
        team_list: List[Dict[str, Any]] = teams.json().get("value") or []
        if not team_list:
            return f"{LABEL} The user is not a member of any team."
        lines = [f"{LABEL} {len(team_list)} team(s) and their channels", ""]
        for t in team_list[:5]:
            lines.append(f"Team: {t.get('displayName') or '?'} ({t.get('id')})")
            chans = await ms_call(cfg, "GET", f"{GRAPH}/teams/{t['id']}/channels",
                                  query={"$select": "id,displayName", "$top": 20})
            if chans.status_code != 200:
                lines.append(f"  {ms_error(LABEL, chans)}")
                continue
            for c in chans.json().get("value") or []:
                lines.append(f"  #{c.get('id')} · {c.get('displayName') or '?'}")
            lines.append("")
        return "\n".join(lines).rstrip()

    team_id = str(cfg.get("team_id") or "").strip()
    channel_id = str(cfg.get("channel_id") or "").strip()
    if not (team_id and channel_id):
        return f'{LABEL} messages needs a team_id and channel_id — run action "channels" for the ids.'
    message_id = str(cfg.get("message_id") or "").strip()
    if message_id:
        resp = await ms_call(cfg, "GET", f"{GRAPH}/teams/{team_id}/channels/{channel_id}"
                                         f"/messages/{message_id}/replies", query={"$top": 15})
    else:
        top = min(max(int(cfg.get("max_results", 10) or 10), 1), 20)
        resp = await ms_call(cfg, "GET", f"{GRAPH}/teams/{team_id}/channels/{channel_id}/messages",
                             query={"$top": top})
    if resp.status_code != 200:
        return ms_error(LABEL, resp)
    found: List[Dict[str, Any]] = resp.json().get("value") or []
    if not found:
        return f"{LABEL} No messages {'in this thread' if message_id else 'in this channel'}."
    # Graph returns newest first; show oldest first like a conversation
    found.reverse()
    head = f"{LABEL} {len(found)} reply/replies to post {message_id}" if message_id \
        else f"{LABEL} {len(found)} message(s) in the channel (oldest first)"
    lines = [head, ""]
    for m in found:
        who = str(((m.get("from") or {}).get("user") or {}).get("displayName") or "(no sender)")
        when = str(m.get("createdDateTime") or "").replace("T", " ")[:19]
        body = _clean(str((m.get("body") or {}).get("content") or ""))[:400]
        lines.append(f"  {who} · {when}:")
        lines.append(f"    {body or '[attachment / no text]'}")
        if not message_id:
            lines.append(f"    id {m.get('id')}")
    return "\n".join(lines)
