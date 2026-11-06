"""Kafka consumer lag — built-in tool `kafka_consumer_lag` (Kafka REST API v3)."""

from collections import defaultdict
from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params
from tools.integrations import _kafka as k

TOOL = ToolSpec(
    id="kafka_consumer_lag",
    name="Kafka Consumer Lag",
    icon="⏱️",
    category="APIs & Integrations",
    description="List consumer groups with their state, or show one group's lag per topic and its worst partitions. Input: a consumer group id, or empty to list the groups.",
    default_config={**k.CONNECTION_CONFIG},
    order=41,
    required=("base_url",),
    selects={"rest_path": k.REST_PATH_SELECT},
    parameters=params({}, {"group_id": {"type": "string", "description": "A consumer group to inspect; leave out to list groups"}}),
    input_param="group_id",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not k.base_url(cfg):
        return k.NO_BASE_URL
    group = inp.strip()
    try:
        async with k.client(cfg) as client:
            cluster, err = await k.cluster_url(client, cfg)
            if err:
                return err
            if not group:
                resp = await client.get(f"{cluster}/consumer-groups")
                if err := k.failed(resp):
                    return err
                groups = sorted(resp.json().get("data", []), key=lambda g: g["consumer_group_id"])
                if not groups:
                    return "[Kafka] No consumer groups."
                return "\n".join([f"[Kafka] {len(groups)} consumer group(s)"] + [
                    f"  {g['consumer_group_id']} [{g.get('state', 'unknown')}]" for g in groups[:100]])

            info = await client.get(f"{cluster}/consumer-groups/{group}")
            if err := k.failed(info):
                return err
            resp = await client.get(f"{cluster}/consumer-groups/{group}/lags")
            if err := k.failed(resp):
                return err
            rows = resp.json().get("data", [])
    except httpx.HTTPError as e:
        return f"[Kafka] Error: {e}"

    state = info.json().get("state", "unknown")
    if not rows:
        return f"[Kafka] Group {group} [{state}] has no committed offsets."
    per_topic: Dict[str, int] = defaultdict(int)
    for r in rows:
        per_topic[r.get("topic_name", "?")] += int(r.get("lag") or 0)
    lines = [f"[Kafka Lag] {group} [{state}] — total lag {sum(per_topic.values())} across {len(rows)} partition(s)"]
    lines += [f"  {topic}: {lag}" for topic, lag in sorted(per_topic.items(), key=lambda kv: -kv[1])]
    worst = [r for r in sorted(rows, key=lambda r: -int(r.get("lag") or 0)) if int(r.get("lag") or 0) > 0][:5]
    if worst:
        lines.append("  Worst partitions:")
        lines += [f"    {r.get('topic_name')}[{r.get('partition_id')}] lag {r.get('lag')} "
                  f"(offset {r.get('current_offset')} of {r.get('log_end_offset')})" for r in worst]
    return "\n".join(lines)
