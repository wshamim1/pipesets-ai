"""Databricks Genie — built-in tool `databricks_genie`: asks an AI/BI Genie space a question in
plain language and returns its answer, the SQL it generated and the first rows of the result.
The conversation API is asynchronous, so the message is polled until it completes or times out."""

import asyncio
import time
from typing import Any, Dict, Optional

from tools.base import ToolSpec, params
from tools.data._databricks import missing, report, request

LABEL = "Databricks Genie"
DONE = {"COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"}

TOOL = ToolSpec(
    id="databricks_genie",
    name=LABEL,
    icon="🧞",
    category="Data & Files",
    description="Asks a Databricks AI/BI Genie space a question about your data and returns the answer, SQL and result rows.",
    default_config={"host": "", "token": "", "space_id": "", "timeout_seconds": 120, "max_rows": 50},
    required=("host", "token", "space_id"),
    order=360,
    parameters=params(
        {"question": {"type": "string", "description": "Question about the data in the Genie space"}},
        {"max_rows": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum result rows to return"}},
    ),
    input_param="question",
    config_args=("max_rows",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    space_id = (cfg.get("space_id") or "").strip()
    problem = missing(LABEL, space_id=space_id, question=inp)
    if problem:
        return problem
    base = f"/api/2.0/genie/spaces/{space_id}"

    started, error = await request(LABEL, cfg, "POST", f"{base}/start-conversation", body={"content": inp})
    if error:
        return error
    conversation_id, message_id = started.get("conversation_id"), started.get("message_id")
    message_path = f"{base}/conversations/{conversation_id}/messages/{message_id}"

    deadline = time.monotonic() + int(cfg.get("timeout_seconds") or 120)
    message: Dict[str, Any] = started.get("message") or {}
    while message.get("status") not in DONE:
        if time.monotonic() > deadline:
            return f"[{LABEL}] Genie didn't finish in time (status {message.get('status')}, conversation {conversation_id})"
        await asyncio.sleep(2)
        message, error = await request(LABEL, cfg, "GET", message_path)
        if error:
            return error
    if message.get("status") != "COMPLETED":
        return f"[{LABEL}] Genie {message.get('status', '').lower()}: {(message.get('error') or {}).get('error', '')}"

    answer: Dict[str, Any] = {"conversation_id": conversation_id}
    max_rows = int(cfg.get("max_rows") or 50)
    for attachment in message.get("attachments") or []:
        if (attachment.get("text") or {}).get("content"):
            answer["answer"] = attachment["text"]["content"]
        query = attachment.get("query")
        if not query:
            continue
        answer["sql"] = query.get("query")
        answer["description"] = query.get("description")
        result, error = await request(LABEL, cfg, "GET",
                                      f"{message_path}/attachments/{attachment.get('attachment_id')}/query-result")
        if error:
            answer["result_error"] = error
            continue
        statement = result.get("statement_response") or {}
        names = [c.get("name") for c in ((statement.get("manifest") or {}).get("schema") or {}).get("columns") or []]
        rows = (statement.get("result") or {}).get("data_array") or []
        answer["row_count"] = len(rows)
        answer["rows"] = [dict(zip(names, row)) for row in rows[:max_rows]]
    return report(LABEL, answer)
