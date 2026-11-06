"""Elasticsearch Ops — built-in tool `elasticsearch_ops` (Elasticsearch REST, read-only).

Actions: ``health`` (cluster status, nodes, shards, and why the first unassigned shard is unassigned),
``indices`` (indices by size with health, docs and store size; the input filters by name pattern) and
``esql`` (run an ES|QL query, e.g. ``FROM logs-* | WHERE log.level == "error" | STATS c = COUNT(*) BY
service.name``, returned as a table). Auth: ``api_key`` (an encoded API key) or username / password.
``health`` and ``indices`` also work on OpenSearch; ES|QL needs Elasticsearch 8.11+.
"""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params

LABEL = "[Elasticsearch]"
ACTIONS = ("health", "indices", "esql")

TOOL = ToolSpec(
    id="elasticsearch_ops",
    name="Elasticsearch Ops",
    icon="🩺",
    category="Data & Files",
    description="Checks an Elasticsearch cluster (read-only): health and why shards are unassigned, indices by size, or an ES|QL query as a table. Input: an index pattern (indices) or the ES|QL query.",
    default_config={"base_url": "", "api_key": "", "username": "", "password": "", "action": "health",
                    "max_results": 50, "verify_tls": True},
    order=55,
    required=("base_url",),
    selects={"action": Select("Action", (("health", "Cluster health"), ("indices", "Indices by size"), ("esql", "ES|QL query")))},
    parameters=params({}, {"input": {"type": "string", "description": "Index pattern (indices) or ES|QL query (esql)"},
                           "action": enum(list(ACTIONS), "What to do")}),
    input_param="input",
    is_new=True,
)


def _size(b: Any) -> str:
    n = float(b or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return str(b)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    api = (cfg.get("base_url") or "").strip().rstrip("/")
    if not api:
        return f"{LABEL} base_url (e.g. https://my-deployment.es.us-east-1.aws.elastic.cloud) is required in config."
    action = cfg.get("action") or "health"
    if action not in ACTIONS:
        return f"{LABEL} Action is one of {', '.join(ACTIONS)} — got '{action}'."
    text = inp.strip()
    if action == "esql" and not text:
        return f"{LABEL} Provide an ES|QL query, e.g. FROM logs-* | LIMIT 10."
    key = (cfg.get("api_key") or "").strip()
    user = (cfg.get("username") or "").strip()
    limit = max(1, min(int(cfg.get("max_results") or 50), 500))
    verify = cfg.get("verify_tls") not in (False, "false", "off", "no", 0)
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=verify,
                                     headers={"Authorization": f"ApiKey {key}"} if key else {},
                                     auth=(user, cfg.get("password") or "") if user and not key else None) as client:
            if action == "health":
                resp = await client.get(f"{api}/_cluster/health")
                explain = None
                if resp.status_code < 400 and resp.json().get("unassigned_shards"):
                    explain = await client.get(f"{api}/_cluster/allocation/explain")
            elif action == "indices":
                resp = await client.get(f"{api}/_cat/indices/{text or '*'}", params={
                    "format": "json", "bytes": "b", "s": "store.size:desc", "h": "index,health,status,docs.count,store.size,pri,rep"})
            else:
                resp = await client.post(f"{api}/_query", params={"format": "json"}, json={"query": text})
    except httpx.HTTPError as e:
        return f"{LABEL} Couldn't reach {api}: {e}"
    if resp.status_code in (401, 403):
        return f"{LABEL} HTTP {resp.status_code} — check api_key (or username / password) and its privileges (monitor, read)."
    if resp.status_code == 404:
        return f"{LABEL} Not found — no index matches '{text}'." if action == "indices" else f"{LABEL} Not found: {resp.request.url.path}"
    if resp.status_code == 400 and action == "esql":
        err = (resp.json().get("error") or {}) if "json" in resp.headers.get("content-type", "") else {}
        return f"{LABEL} ES|QL error: {err.get('reason') or resp.text[:300]}"
    if resp.status_code >= 400:
        return f"{LABEL} HTTP {resp.status_code}: {resp.text[:300]}"
    data = resp.json()

    if action == "health":
        lines = [f"{LABEL} Cluster {data.get('cluster_name')}: {str(data.get('status', '')).upper()}",
                 f"  Nodes: {data.get('number_of_nodes')} ({data.get('number_of_data_nodes')} data) · "
                 f"Shards: {data.get('active_shards')} active, {data.get('relocating_shards')} relocating, "
                 f"{data.get('initializing_shards')} initializing, {data.get('unassigned_shards')} unassigned",
                 f"  Pending tasks: {data.get('number_of_pending_tasks')} · Active shards: {data.get('active_shards_percent_as_number')}%"]
        if explain is not None and explain.status_code < 400:
            e = explain.json()
            lines.append(f"  First unassigned: {e.get('index')} shard {e.get('shard')} ({'primary' if e.get('primary') else 'replica'})"
                         f" — {(e.get('unassigned_info') or {}).get('reason')}: {e.get('allocate_explanation') or ''}"[:500])
        return "\n".join(lines)
    if action == "indices":
        if not data:
            return f"{LABEL} No indices match '{text or '*'}'."
        bad = [i for i in data if i.get("health") in ("red", "yellow")]
        return (f"{LABEL} {len(data)} index(es), largest first" + (f" · {len(bad)} not green" if bad else "") + "\n" + "\n".join(
            f"- {i.get('index')} · {i.get('health')} · {i.get('status')} · {i.get('docs.count')} docs · {_size(i.get('store.size'))}"
            f" · {i.get('pri')}p/{i.get('rep')}r" for i in data[:limit]))
    cols = [c.get("name") for c in data.get("columns") or []]
    rows = (data.get("values") or [])[:limit]
    if not rows:
        return f"{LABEL} ES|QL returned no rows."
    return "\n".join([f"{LABEL} {len(rows)} row(s)", " | ".join(cols)]
                     + [" | ".join("" if v is None else str(v)[:120] for v in r) for r in rows])
