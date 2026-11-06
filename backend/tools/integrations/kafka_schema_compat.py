"""Schema compatibility check — built-in tool `kafka_schema_compat` (Confluent Schema Registry REST API).

Asks the registry whether a candidate schema is compatible with a subject's existing version(s), under the
subject's compatibility level. Nothing is registered: the check only reads.
"""

from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from tools.base import Select, ToolSpec, enum, params
from tools.integrations import _kafka as k

LABEL = "Schema Registry"
SCHEMA_TYPES = ("AVRO", "JSON", "PROTOBUF")

TOOL = ToolSpec(
    id="kafka_schema_compat",
    name="Schema Compatibility",
    icon="🧬",
    category="APIs & Integrations",
    description="Check whether a new Avro, JSON Schema or Protobuf schema is compatible with a Schema Registry subject before it is registered, and say why not. Nothing is registered. Input: the candidate schema.",
    default_config={"base_url": "http://localhost:8081", "api_key": "", "api_secret": "", "subject": "",
                    "version": "latest", "schema_type": "AVRO"},
    order=47,
    required=("base_url",),
    selects={"schema_type": Select("Schema type", (("AVRO", "Avro"), ("JSON", "JSON Schema"), ("PROTOBUF", "Protobuf")))},
    parameters=params(
        {
            "schema": {"type": "string", "description": "The candidate schema, as text (an Avro schema is JSON)"},
            "subject": {"type": "string", "description": "The subject to check against, such as orders-value"},
        },
        {
            "version": {"type": "string", "description": "A version number to check against, or 'latest' (default)"},
            "schema_type": enum(SCHEMA_TYPES, "AVRO (default), JSON or PROTOBUF"),
        },
    ),
    input_param="schema",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    base = k.base_url(cfg)
    if not base:
        return f"[{LABEL}] base_url (e.g. http://localhost:8081) is required in config."
    subject = str(cfg.get("subject") or "").strip()
    if not subject:
        return f"[{LABEL}] subject is required."
    schema = inp.strip()
    if not schema:
        return f"[{LABEL}] Provide the candidate schema."
    version = str(cfg.get("version") or "latest").strip()
    if version != "latest" and not version.isdigit():
        return f"[{LABEL}] version must be a number or 'latest'."
    schema_type = str(cfg.get("schema_type") or "AVRO").strip().upper()
    if schema_type not in SCHEMA_TYPES:
        return f"[{LABEL}] schema_type must be one of {', '.join(SCHEMA_TYPES)}."

    body: Dict[str, Any] = {"schema": schema}
    if schema_type != "AVRO":
        body["schemaType"] = schema_type
    name = quote(subject, safe="")
    try:
        async with k.client(cfg) as client:
            resp = await client.post(f"{base}/compatibility/subjects/{name}/versions/{version}",
                                     params={"verbose": "true"}, json=body)
            if err := k.failed(resp, LABEL):
                return err
            result = resp.json()
            level = None
            cfg_resp = await client.get(f"{base}/config/{name}", params={"defaultToGlobal": "true"})
            if cfg_resp.status_code == 200:
                level = cfg_resp.json().get("compatibilityLevel")
    except httpx.HTTPError as e:
        return f"[{LABEL}] Error: {e}"

    compatible = result.get("is_compatible")
    if compatible is None:
        return f"[{LABEL}] Unexpected response: {str(result)[:300]}"
    head = (f"[{LABEL}] {'Compatible' if compatible else 'NOT compatible'} with {subject} ({version})"
            + (f" under {level}" if level else ""))
    messages = [str(m) for m in result.get("messages") or []]
    if compatible or not messages:
        return head
    return "\n".join([head] + [f"  {m}" for m in messages[:10]] + ([f"  … {len(messages) - 10} more"] if len(messages) > 10 else []))
