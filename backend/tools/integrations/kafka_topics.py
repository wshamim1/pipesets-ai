"""Kafka topics — built-in tool `kafka_topics` (Kafka REST API v3)."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params
from tools.integrations import _kafka as k

SHOWN_CONFIGS = ("cleanup.policy", "retention.ms", "retention.bytes", "min.insync.replicas", "max.message.bytes",
                 "compression.type")

TOOL = ToolSpec(
    id="kafka_topics",
    name="Kafka Topics",
    icon="🧵",
    category="APIs & Integrations",
    description="List the topics of a Kafka cluster, or describe one (partitions, replication, key settings). Uses the Kafka REST API of Confluent Cloud, Confluent Platform or a REST Proxy. Input: a topic name, or empty to list.",
    default_config={**k.CONNECTION_CONFIG, "max_results": 50},
    order=40,
    required=("base_url",),
    selects={"rest_path": k.REST_PATH_SELECT},
    parameters=params(
        {},
        {
            "topic_name": {"type": "string", "description": "A topic to describe; leave out to list topics"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 200, "description": "How many topics to list"},
        },
    ),
    input_param="topic_name",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not k.base_url(cfg):
        return k.NO_BASE_URL
    topic = inp.strip()
    try:
        limit = max(1, min(int(cfg.get("max_results", 50)), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        async with k.client(cfg) as client:
            cluster, err = await k.cluster_url(client, cfg)
            if err:
                return err
            if not topic:
                resp = await client.get(f"{cluster}/topics")
                if err := k.failed(resp):
                    return err
                topics = resp.json().get("data", [])
                visible = sorted((t for t in topics if not t.get("is_internal") and not t["topic_name"].startswith("_")),
                                 key=lambda t: t["topic_name"])
                if not visible:
                    return "[Kafka] No topics."
                lines = [f"[Kafka] {len(visible)} topic(s)" + (f" (showing {limit})" if len(visible) > limit else "")
                         + (f", {len(topics) - len(visible)} internal hidden" if len(topics) > len(visible) else "")]
                for t in visible[:limit]:
                    lines.append(f"  {t['topic_name']} — {t.get('partitions_count', '?')} partition(s), "
                                 f"replication {t.get('replication_factor', '?')}")
                return "\n".join(lines)

            resp = await client.get(f"{cluster}/topics/{topic}")
            if err := k.failed(resp):
                return err
            t = resp.json()
            lines = [f"[Kafka Topic] {t.get('topic_name', topic)}",
                     f"  Partitions  : {t.get('partitions_count', '?')}",
                     f"  Replication : {t.get('replication_factor', '?')}"]
            resp = await client.get(f"{cluster}/topics/{topic}/configs")
            if resp.status_code == 200:
                configs = {c["name"]: c.get("value") for c in resp.json().get("data", []) if c.get("name") in SHOWN_CONFIGS}
                lines += [f"  {name:<19}: {configs[name]}" for name in SHOWN_CONFIGS if configs.get(name) is not None]
            return "\n".join(lines)
    except httpx.HTTPError as e:
        return f"[Kafka] Error: {e}"
