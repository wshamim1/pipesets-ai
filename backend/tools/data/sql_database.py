"""SQL database — built-in tool `sql_database`."""

from typing import Any, Dict, Optional

from tools.base import params, ToolSpec

TOOL = ToolSpec(
    parameters=params({"query": {"type": "string", "description": "One SQL statement"}}), input_param="query",
    id="sql_database",
    name="Postgres / SQL Database",
    icon="🗄️",
    category="Data & Files",
    description="Queries tables and extracts structured enterprise data.",
    default_config={"connection_string": "postgresql://user:pass@localhost:5432/db", "read_only": True},
    order=10,
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    conn_str = cfg.get("connection_string", "")
    if conn_str.startswith("postgresql://") or conn_str.startswith("postgres://"):
        try:
            import psycopg2
            conn = psycopg2.connect(conn_str)
            cur = conn.cursor()
            cur.execute(inp)
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description] if cur.description else []
            conn.close()
            if not rows:
                return "SQL: Query returned 0 rows."
            header = " | ".join(cols)
            sep = "-" * len(header)
            body_lines = [" | ".join(str(v) for v in row) for row in rows[:50]]
            return f"SQL Results ({len(rows)} rows):\n{header}\n{sep}\n" + "\n".join(body_lines)
        except ImportError:
            return "[SQL] psycopg2 not installed. pip install psycopg2-binary"
        except Exception as e:
            return f"SQL Error: {e}"
    else:
        # SQLite — use connection_string as file path (default :memory:)
        import sqlite3
        db_path = conn_str if conn_str and not conn_str.startswith("postgresql") else ":memory:"
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(inp)
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description] if cur.description else []
            conn.close()
            if not rows:
                return "SQL: Query returned 0 rows."
            header = " | ".join(cols)
            sep = "-" * len(header)
            body_lines = [" | ".join(str(v) for v in row) for row in rows[:50]]
            return f"SQL Results ({len(rows)} rows):\n{header}\n{sep}\n" + "\n".join(body_lines)
        except Exception as e:
            return f"SQLite Error: {e}"
