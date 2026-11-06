"""Snowflake Cortex Analyst — built-in tool `snowflake_cortex_analyst`: a plain-language question
over a semantic view (or semantic model YAML on a stage) → Cortex Analyst's interpretation and SQL,
and, unless turned off, the first rows of running that SQL."""

from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, params
from tools.data import _snowflake as sf
from tools.data.snowflake_reader import READONLY, _first_keyword

LABEL = "Snowflake Cortex Analyst"

TOOL = ToolSpec(
    id="snowflake_cortex_analyst",
    name=LABEL,
    icon="📊",
    category="Data & Files",
    description="Answers a question about your data with Snowflake Cortex Analyst: returns the generated SQL and its result rows.",
    default_config={**sf.DEFAULT_CONFIG, "semantic_model": "", "run_sql": "true", "max_rows": 50},
    required=(*sf.REQUIRED, "semantic_model"),
    selects={"token_type": sf.TOKEN_SELECT,
             "run_sql": Select("Run the SQL", [("true", "Run and return rows"), ("false", "Only return the SQL")])},
    order=425,
    parameters=params(
        {"question": {"type": "string", "description": "Question about the data the semantic model covers"}},
        {"max_rows": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum result rows to return"}},
    ),
    input_param="question",
    config_args=("max_rows",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    model = (cfg.get("semantic_model") or "").strip()
    problem = sf.credentials_missing(LABEL, cfg) or sf.missing(LABEL, semantic_model=model, question=inp)
    if problem:
        return problem
    body: Dict[str, Any] = {"messages": [{"role": "user", "content": [{"type": "text", "text": inp}]}]}
    if model.startswith("@"):
        body["semantic_model_file"] = model
    else:
        body["semantic_view"] = model
    data, error = await sf.request(LABEL, cfg, "POST", "/api/v2/cortex/analyst/message", body=body, timeout=120.0)
    if error:
        return error

    answer: Dict[str, Any] = {}
    for item in (data.get("message") or {}).get("content") or []:
        if item.get("type") == "text":
            answer["interpretation"] = item.get("text")
        elif item.get("type") == "sql":
            answer["sql"] = item.get("statement")
        elif item.get("type") == "suggestions":
            answer["suggestions"] = item.get("suggestions")
    for warning in data.get("warnings") or []:
        answer.setdefault("warnings", []).append(warning.get("message"))

    if answer.get("sql") and str(cfg.get("run_sql", "true")).lower() != "false":
        if _first_keyword(answer["sql"]) not in READONLY:
            answer["result_error"] = "Not run: the generated SQL isn't a read statement"
            return sf.report(LABEL, answer)
        rows, error = await sf.statement(LABEL, cfg, answer["sql"], max_rows=int(cfg.get("max_rows") or 50))
        if error:
            answer["result_error"] = error
        else:
            answer["row_count"] = len(rows)
            answer["rows"] = rows
    return sf.report(LABEL, answer)
