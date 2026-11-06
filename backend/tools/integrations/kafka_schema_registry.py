"""Schema Registry — built-in tool `kafka_schema_registry` (Confluent Schema Registry REST API)."""

from typing import Any, Dict, Optional

import httpx

from tools.base import ToolSpec, params
from tools.integrations import _kafka as k

MAX_SCHEMA_CHARS = 4000

TOOL = ToolSpec(
    id="kafka_schema_registry",
    name="Schema Registry",
    icon="📐",
    category="APIs & Integrations",
    description="List the subjects in a Confluent Schema Registry, or read a subject's schema (Avro, Protobuf or JSON Schema). Input: a subject such as orders-value, or empty to list.",
    default_config={"base_url": "http://localhost:8081", "api_key": "", "api_secret": "", "version": "latest"},
    order=43,
    required=("base_url",),
    parameters=params(
        {},
        {
            "subject": {"type": "string", "description": "A subject to read; leave out to list subjects"},
            "version": {"type": "string", "description": "A version number, or 'latest' (default)"},
        },
    ),
    input_param="subject",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    base = k.base_url(cfg)
    if not base:
        return "[Schema Registry] base_url (e.g. http://localhost:8081) is required in config."
    subject = inp.strip()
    version = str(cfg.get("version") or "latest").strip()
    if version != "latest" and not version.isdigit():
        return "[Schema Registry] version must be a number or 'latest'."
    try:
        async with k.client(cfg) as client:
            if not subject:
                resp = await client.get(f"{base}/subjects")
                if err := k.failed(resp, "Schema Registry"):
                    return err
                subjects = sorted(resp.json())
                if not subjects:
                    return "[Schema Registry] No subjects."
                return "\n".join([f"[Schema Registry] {len(subjects)} subject(s)"] + [f"  {s}" for s in subjects[:200]])
            resp = await client.get(f"{base}/subjects/{subject}/versions/{version}")
            if err := k.failed(resp, "Schema Registry"):
                return err
    except httpx.HTTPError as e:
        return f"[Schema Registry] Error: {e}"
    s = resp.json()
    schema = str(s.get("schema", ""))
    return (f"[Schema Registry] {s.get('subject', subject)} v{s.get('version')} (id {s.get('id')}, {s.get('schemaType', 'AVRO')})\n"
            + schema[:MAX_SCHEMA_CHARS] + ("\n… truncated" if len(schema) > MAX_SCHEMA_CHARS else ""))
