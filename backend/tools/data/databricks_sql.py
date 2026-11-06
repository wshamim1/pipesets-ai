"""Databricks SQL — built-in tool `databricks_sql`."""

from typing import Any, Dict, Optional

from tools.base import ToolSpec, params

TOOL = ToolSpec(
    id="databricks_sql",
    name="Databricks SQL",
    icon="🧊",
    category="Data & Files",
    description="Runs a read-only SQL query against a Databricks SQL warehouse using a PAT or service principal token.",
    default_config={"host": "", "http_path": "", "token": "", "max_rows": 50},
    required=("host", "http_path", "token"),
    order=210,
    parameters=params(
        {"query": {"type": "string", "description": "Read-only SQL query to run against Databricks"}},
        {
            "max_rows": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "description": "Maximum number of rows to return",
            }
        },
    ),
    input_param="query",
    config_args=("max_rows",),
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    query = (inp or "").strip()
    if not query:
        return "[Databricks SQL] Please provide a SQL query to run."

    host = (cfg.get("host") or "").strip().rstrip("/").removeprefix("https://").removeprefix("http://")
    http_path = (cfg.get("http_path") or "").strip()
    token = (cfg.get("token") or "").strip()
    max_rows = int(cfg.get("max_rows") or 50)

    missing = [name for name, value in {"host": host, "http_path": http_path, "token": token}.items() if not value]
    if missing:
        return f"[Databricks SQL] Missing required config: {', '.join(missing)}"

    try:
        import databricks.sql as databricks_sql
    except Exception:
        return "[Databricks SQL] databricks-sql-connector is not installed in this environment."

    try:
        with databricks_sql.connect(server_hostname=host, http_path=http_path, access_token=token) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query)
                columns = [c[0] for c in (cursor.description or [])]
                rows = cursor.fetchmany(max_rows)
                if not rows:
                    return f"[Databricks SQL] Query returned 0 rows.\nSQL: {query}"
                header = " | ".join(str(c) for c in columns)
                lines = [header, "-" * len(header)]
                for row in rows:
                    lines.append(" | ".join("" if v is None else str(v) for v in row))
                return "\n".join(lines)
    except Exception as exc:
        return f"[Databricks SQL] Error: {exc}"
