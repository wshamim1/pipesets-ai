"""WhatsApp — built-in tool `whatsapp_cloud` (Meta WhatsApp Cloud API).

Sends the input as a text message to the number in ``to``, set in config (the model never picks the
recipient). WhatsApp only delivers free-form text within 24 hours of the recipient's last message;
outside that window set ``template_name`` to an approved template, and the input fills its first
body variable ({{1}}) when there is one.
"""

import re
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params

LABEL = "[WhatsApp]"
GRAPH = "https://graph.facebook.com"
_PHONE = re.compile(r"^\d{7,15}$")

TOOL = ToolSpec(
    id="whatsapp_cloud",
    name="WhatsApp",
    icon="💬",
    category="Communication",
    description="Sends a WhatsApp message through the WhatsApp Cloud API to a number set in config — free text within the 24-hour window, or an approved template.",
    default_config={"access_token": "", "phone_number_id": "", "to": "", "template_name": "", "template_language": "en_US",
                    "api_version": "v23.0"},
    order=130,
    required=("access_token", "phone_number_id", "to"),
    parameters=params({"message": {"type": "string", "description": "The message text (or the template's {{1}} value)"}}),
    input_param="message",
    is_new=True,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    token = str(cfg.get("access_token") or "").strip()
    phone_id = str(cfg.get("phone_number_id") or "").strip()
    to = re.sub(r"[\s()+-]", "", str(cfg.get("to") or ""))
    if not token or not phone_id or not to:
        return f"{LABEL} access_token, phone_number_id and to are required in config."
    if not _PHONE.match(to) or not phone_id.isdigit():
        return f"{LABEL} to is a phone number with country code (e.g. 919812345678), phone_number_id is numeric."
    version = str(cfg.get("api_version") or "v23.0").strip()
    if not re.match(r"^v\d+\.\d+$", version):
        return f"{LABEL} api_version looks like v23.0 — got '{version}'."
    text = inp.strip()
    template = str(cfg.get("template_name") or "").strip()
    if template:
        body: Dict[str, Any] = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": {
            "name": template, "language": {"code": str(cfg.get("template_language") or "en_US").strip()}}}
        if text:
            body["template"]["components"] = [{"type": "body", "parameters": [{"type": "text", "text": text[:1024]}]}]
    else:
        if not text:
            return f"{LABEL} The message is empty."
        if len(text) > 4096:
            return f"{LABEL} WhatsApp text messages are at most 4096 characters — this one is {len(text)}."
        body = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text, "preview_url": False}}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{GRAPH}/{version}/{phone_id}/messages", json=body,
                                     headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach the WhatsApp Cloud API: {e}"
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code < 400:
        msg_id = ((data.get("messages") or [{}])[0]).get("id", "")
        return f"{LABEL} Sent {'template ' + template if template else 'message'} to +{to} ({msg_id})."
    err = data.get("error") or {}
    code = err.get("code")
    if code == 131047:
        return f"{LABEL} +{to} hasn't messaged in the last 24 hours, so only a template can be sent — set template_name."
    if code == 190 or resp.status_code == 401:
        return f"{LABEL} The access_token is invalid or expired ({err.get('message', 'HTTP 401')})."
    detail = (err.get("error_data") or {}).get("details") or err.get("message") or resp.text[:200]
    return f"{LABEL} HTTP {resp.status_code}{f' (code {code})' if code else ''}: {detail}"
