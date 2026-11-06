"""Kafka produce — built-in tool `kafka_produce` (Kafka REST API v3).

The topic is a node setting, not something the model chooses, and producing is off until ``allow_produce``
is true on the node.
"""

import json
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params
from tools.integrations import _kafka as k

TOOL = ToolSpec(
    id="kafka_produce",
    name="Kafka Produce",
    icon="📤",
    category="APIs & Integrations",
    description="Send one message to a Kafka topic through the Kafka REST API (producing must be enabled on the node). Input: the message — plain text, or a JSON object or array.",
    default_config={**k.CONNECTION_CONFIG, "topic": "", "allow_produce": False},
    order=42,
    required=("base_url", "topic"),
    selects={"rest_path": k.REST_PATH_SELECT},
    parameters=params(
        {"message": {"type": "string", "description": "The message value: plain text, or a JSON object / array"}},
        {"message_key": {"type": "string", "description": "An optional message key"}},
    ),
    input_param="message",
)


def _data(text: str) -> Any:
    """A JSON object or array is sent as JSON; anything else as a string."""
    if text[:1] in ("{", "["):
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not k.base_url(cfg):
        return k.NO_BASE_URL
    topic = (cfg.get("topic") or "").strip()
    if not topic:
        return "[Kafka] topic is required in config."
    if cfg.get("allow_produce") is not True:
        return "[Kafka] Producing is disabled; set allow_produce to true on the node."
    message = inp.strip()
    if not message:
        return "[Kafka] Provide the message to send."
    body: Dict[str, Any] = {"value": {"type": "JSON", "data": _data(message)}}
    if cfg.get("message_key"):
        body["key"] = {"type": "JSON", "data": _data(str(cfg["message_key"]))}
    try:
        async with k.client(cfg) as client:
            cluster, err = await k.cluster_url(client, cfg)
            if err:
                return err
            resp = await client.post(f"{cluster}/topics/{topic}/records", json=body)
    except httpx.HTTPError as e:
        return f"[Kafka] Error: {e}"
    if err := k.failed(resp):
        return err
    result = resp.json()
    if result.get("error_code", 200) != 200:
        return f"[Kafka] Produce failed: {result.get('message') or result.get('error_code')}"
    return f"[Kafka] Sent to {topic}: partition {result.get('partition_id')}, offset {result.get('offset')}"
