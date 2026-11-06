"""
Tool body generator — produces real, runnable function bodies for every known
tool type. Used by the LangChain and AutoGen exporters.
"""

import json
import textwrap
from typing import Any, Dict, List, Optional

from exporters.helpers import MCP_DB_TOOLS, MCP_STDIO_TOOLS


def tool_body_langchain(
    fn_name: str,
    tool_id: str,
    desc: str,
    cfg: Dict[str, Any],
    conn_node: Optional[Dict],
) -> str:
    """Return a @tool-decorated Python function string for LangChain."""

    # ── MCP database tools backed by a Connection node ────────────────────────
    if tool_id in MCP_DB_TOOLS:
        conn_data = conn_node.get("data", {}) if conn_node else {}
        conn_type = conn_data.get("connection_type", conn_data.get("type", "postgres")).lower()
        conn_cfg  = conn_data.get("config", {})

        if conn_type in ("postgres", "postgresql"):
            host = conn_cfg.get("host", "localhost")
            port = conn_cfg.get("port", 5432)
            database = conn_cfg.get("database", "postgres")
            user = conn_cfg.get("user", "postgres")
            pw_default = conn_cfg.get("password", "")
            pw_var = f"DB_{fn_name.upper()}_PASSWORD"
            return textwrap.dedent(f'''\
                @tool
                def {fn_name}(query: str) -> str:
                    """{desc}"""
                    import psycopg2, os
                    pw = os.environ.get("{pw_var}", {repr(pw_default)})
                    conn = psycopg2.connect(
                        host={json.dumps(host)}, port={port},
                        dbname={json.dumps(database)}, user={json.dumps(user)}, password=pw
                    )
                    cur = conn.cursor()
                    cur.execute(query)
                    rows = cur.fetchall()
                    cols = [d[0] for d in (cur.description or [])]
                    conn.close()
                    if not rows:
                        return "Query returned 0 rows."
                    header = " | ".join(cols)
                    body = "\\n".join(" | ".join(str(v) for v in r) for r in rows[:100])
                    return f"{{header}}\\n{{'-'*len(header)}}\\n{{body}}"

            ''')

        elif conn_type in ("mysql", "mariadb"):
            host = conn_cfg.get("host", "localhost")
            port = conn_cfg.get("port", 3306)
            database = conn_cfg.get("database", "")
            user = conn_cfg.get("user", "root")
            pw_default_mysql = conn_cfg.get("password", "")
            pw_var = f"DB_{fn_name.upper()}_PASSWORD"
            return textwrap.dedent(f'''\
                @tool
                def {fn_name}(query: str) -> str:
                    """{desc}"""
                    import pymysql, os
                    pw = os.environ.get("{pw_var}", {repr(pw_default_mysql)})
                    conn = pymysql.connect(
                        host={json.dumps(host)}, port={port},
                        user={json.dumps(user)}, password=pw,
                        database={json.dumps(database)}, autocommit=True
                    )
                    cur = conn.cursor()
                    cur.execute(query)
                    rows = cur.fetchall()
                    cols = [d[0] for d in (cur.description or [])]
                    conn.close()
                    if not rows:
                        return "Query returned 0 rows."
                    header = " | ".join(str(c) for c in cols)
                    body = "\\n".join(" | ".join(str(v) for v in r) for r in rows[:100])
                    return f"{{header}}\\n{{'-'*len(header)}}\\n{{body}}"

            ''')

        elif conn_type == "sqlite":
            db_path = conn_cfg.get("path", ":memory:")
            return textwrap.dedent(f'''\
                @tool
                def {fn_name}(query: str) -> str:
                    """{desc}"""
                    import sqlite3
                    conn = sqlite3.connect({json.dumps(db_path)})
                    cur = conn.cursor()
                    cur.execute(query)
                    rows = cur.fetchall()
                    cols = [d[0] for d in (cur.description or [])]
                    conn.close()
                    if not rows:
                        return "Query returned 0 rows."
                    header = " | ".join(cols)
                    body = "\\n".join(" | ".join(str(v) for v in r) for r in rows[:100])
                    return f"{{header}}\\n{{'-'*len(header)}}\\n{{body}}"

            ''')

        elif conn_type == "snowflake":
            account   = conn_cfg.get("account", "")
            warehouse = conn_cfg.get("warehouse", "")
            database  = conn_cfg.get("database", "")
            user      = conn_cfg.get("user", "")
            pw_var    = f"SNOWFLAKE_{fn_name.upper()}_PASSWORD"
            return textwrap.dedent(f'''\
                @tool
                def {fn_name}(query: str) -> str:
                    """{desc}"""
                    import snowflake.connector, os
                    pw = os.environ.get("{pw_var}", "")
                    conn = snowflake.connector.connect(
                        account={json.dumps(account)},
                        user={json.dumps(user)},
                        password=pw,
                        warehouse={json.dumps(warehouse)},
                        database={json.dumps(database)},
                    )
                    cur = conn.cursor()
                    cur.execute(query)
                    rows = cur.fetchall()
                    cols = [d[0] for d in (cur.description or [])]
                    conn.close()
                    if not rows:
                        return "Query returned 0 rows."
                    header = " | ".join(cols)
                    body = "\\n".join(" | ".join(str(v) for v in r) for r in rows[:100])
                    return f"{{header}}\\n{{'-'*len(header)}}\\n{{body}}"

            ''')

        # Fallback — no connection node linked
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(query: str) -> str:
                """{desc}
                NOTE: Connect a Connection node in Pipesets AI to auto-populate credentials."""
                raise RuntimeError(
                    "No database credentials — set DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD "
                    "env vars or link a Connection node and re-export."
                )

        ''')

    # ── stdio MCP tools (npx-based) ───────────────────────────────────────────
    if tool_id in MCP_STDIO_TOOLS:
        command  = cfg.get("command", "npx")
        args     = cfg.get("args", [])
        env_vars: Dict[str, str] = cfg.get("env_vars", {})
        env_lines = "\n        ".join(
            f'os.environ.setdefault({json.dumps(k)}, os.environ.get({json.dumps(k)}, ""))'
            for k in env_vars
        ) or "pass  # no env vars required"
        args_repr = json.dumps(args)
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(input: str) -> str:
                """{desc}"""
                import subprocess, json as _json, os
                {env_lines}
                proc = subprocess.run(
                    [{json.dumps(command)}] + {args_repr},
                    input=_json.dumps({{"method": "tools/call", "params": {{"name": {json.dumps(tool_id)}, "arguments": {{"input": input}}}}}}),
                    capture_output=True, text=True, timeout=30,
                )
                return proc.stdout.strip() or proc.stderr.strip() or "(no output)"

        ''')

    # ── Built-in tool types ───────────────────────────────────────────────────
    if tool_id in ("web_search", "duckduckgo_search", "tavily_search"):
        api_key     = cfg.get("api_key", "")
        max_results = cfg.get("max_results", 5)
        # DuckDuckGo-only tool never uses Tavily, even when TAVILY_API_KEY is set
        key_expr = '""' if tool_id == "duckduckgo_search" else f'os.environ.get("TAVILY_API_KEY", {json.dumps(api_key)})'
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(query: str) -> str:
                """{desc}"""
                import os
                tavily_key = {key_expr}
                if tavily_key:
                    import httpx
                    resp = httpx.post(
                        "https://api.tavily.com/search",
                        json={{"api_key": tavily_key, "query": query, "max_results": {max_results}}},
                        timeout=15,
                    )
                    resp.raise_for_status()
                    results = resp.json().get("results", [])
                    return "\\n".join(f"{{i+1}}. {{r['title']}}\\n   {{r['url']}}\\n   {{r['content'][:200]}}"
                                      for i, r in enumerate(results[:{max_results}]))
                from ddgs import DDGS
                results = list(DDGS().text(query, max_results={max_results}))
                return "\\n".join(f"{{i+1}}. {{r['title']}}\\n   {{r['href']}}\\n   {{r['body'][:200]}}"
                                  for i, r in enumerate(results))

        ''')

    if tool_id == "python_interpreter":
        timeout = cfg.get("timeout", 10)
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(code: str) -> str:
                """{desc}"""
                import subprocess
                res = subprocess.run(["python3", "-c", code],
                                     capture_output=True, text=True, timeout={timeout})
                return res.stdout if res.returncode == 0 else f"Error:\\n{{res.stderr}}"

        ''')

    if tool_id == "calculator":
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(expression: str) -> str:
                """{desc}"""
                import ast, math, operator as op
                OPS = {{ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
                        ast.Div: op.truediv, ast.Pow: op.pow, ast.USub: op.neg,
                        ast.Mod: op.mod, ast.FloorDiv: op.floordiv}}
                FUNCS = {{k: getattr(math, k) for k in ("sqrt","sin","cos","tan","log","log10","log2","ceil","floor")}}
                FUNCS.update({{"abs": abs, "round": round, "pi": math.pi, "e": math.e}})
                def _eval(n):
                    if isinstance(n, ast.Constant): return n.value
                    if isinstance(n, ast.BinOp): return OPS[type(n.op)](_eval(n.left), _eval(n.right))
                    if isinstance(n, ast.UnaryOp): return OPS[type(n.op)](_eval(n.operand))
                    if isinstance(n, ast.Call):
                        fn = FUNCS.get(n.func.id if isinstance(n.func, ast.Name) else "")
                        return fn(*[_eval(a) for a in n.args])
                    if isinstance(n, ast.Name) and n.id in FUNCS: return FUNCS[n.id]
                    raise ValueError(f"Unsupported: {{type(n)}}")
                try:
                    return str(_eval(ast.parse(expression.strip(), mode="eval").body))
                except Exception as e:
                    return f"Error: {{e}}"

        ''')

    if tool_id == "rest_api_caller":
        method  = cfg.get("method", "GET").upper()
        url     = cfg.get("url", "https://api.example.com")
        headers = cfg.get("headers", "{}")
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(input: str) -> str:
                """{desc}"""
                import httpx, json as _json
                headers = {json.dumps(headers if isinstance(headers, dict) else json.loads(headers or "{}"))!r}
                try:
                    body = _json.loads(input)
                except Exception:
                    body = None
                resp = httpx.request(
                    {json.dumps(method)}, {json.dumps(url)},
                    headers=headers,
                    json=body if {json.dumps(method)} != "GET" and body else None,
                    params={{"q": input}} if {json.dumps(method)} == "GET" and not body else None,
                    timeout=15,
                )
                try:
                    return _json.dumps(resp.json(), indent=2)[:2000]
                except Exception:
                    return resp.text[:2000]

        ''')

    if tool_id == "sql_database":
        conn_str = cfg.get("connection_string", "")
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(query: str) -> str:
                """{desc}"""
                import os
                conn_str = os.environ.get("SQL_CONNECTION_STRING", {json.dumps(conn_str)})
                if conn_str.startswith(("postgresql://", "postgres://")):
                    import psycopg2
                    conn = psycopg2.connect(conn_str)
                else:
                    import sqlite3
                    conn = sqlite3.connect(conn_str or ":memory:")
                cur = conn.cursor()
                cur.execute(query)
                rows = cur.fetchall()
                cols = [d[0] for d in (cur.description or [])]
                conn.close()
                if not rows:
                    return "Query returned 0 rows."
                header = " | ".join(cols)
                body = "\\n".join(" | ".join(str(v) for v in r) for r in rows[:100])
                return f"{{header}}\\n{{'-'*len(header)}}\\n{{body}}"

        ''')

    if tool_id == "file_reader":
        allowed_dir = cfg.get("allowed_dir", "")
        max_bytes   = cfg.get("max_bytes", 32768)
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(path: str) -> str:
                """{desc}"""
                import os
                allowed_dir = {json.dumps(allowed_dir)}
                if allowed_dir and not os.path.abspath(path).startswith(os.path.abspath(allowed_dir)):
                    return f"Access denied: {{path}} is outside {{allowed_dir}}"
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    return fh.read({max_bytes})

        ''')

    if tool_id == "shell_executor":
        allowed_cmds = cfg.get("allowed_commands", "ls,cat,echo,pwd,date")
        timeout      = cfg.get("timeout", 15)
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(command: str) -> str:
                """{desc}"""
                import subprocess
                allowed = [c.strip() for c in {json.dumps(allowed_cmds)}.split(",") if c.strip()]
                first = command.split()[0] if command.strip() else ""
                if allowed and first not in allowed:
                    return f"Command '{{first}}' not in allowed list: {{allowed}}"
                res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout={timeout})
                return res.stdout if res.returncode == 0 else f"Exit {{res.returncode}}\\n{{res.stderr}}"

        ''')

    if tool_id == "datetime_tool":
        tz  = cfg.get("timezone", "UTC")
        fmt = cfg.get("format", "%Y-%m-%d %H:%M:%S %Z")
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(input: str = "now") -> str:
                """{desc}"""
                from datetime import datetime, timezone, timedelta
                import zoneinfo, re
                try:
                    tz = zoneinfo.ZoneInfo({json.dumps(tz)})
                except Exception:
                    tz = timezone.utc
                now = datetime.now(tz)
                m = re.match(r"([+-]\\d+)([smhdw])", input.strip())
                if m:
                    amt, unit = int(m.group(1)), m.group(2)
                    delta = {{"s": timedelta(seconds=amt), "m": timedelta(minutes=amt),
                              "h": timedelta(hours=amt), "d": timedelta(days=amt),
                              "w": timedelta(weeks=amt)}}.get(unit, timedelta(0))
                    now = now + delta
                return now.strftime({json.dumps(fmt)})

        ''')

    if tool_id == "json_transformer":
        filt = cfg.get("filter", ".")
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(input: str) -> str:
                """{desc}"""
                import json as _j
                data = _j.loads(input)
                filt = {json.dumps(filt)}
                if filt == ".":
                    return _j.dumps(data, indent=2)
                if filt == "keys":
                    return _j.dumps(list(data.keys()) if isinstance(data, dict) else list(range(len(data))))
                if filt == "length":
                    return str(len(data))
                parts = [p for p in filt.lstrip(".").split(".") if p]
                node = data
                for p in parts:
                    node = node.get(p) if isinstance(node, dict) else None
                return _j.dumps(node, indent=2) if node is not None else "null"

        ''')

    if tool_id == "email_sender":
        smtp_host = cfg.get("smtp_host", "smtp.gmail.com")
        smtp_port = cfg.get("smtp_port", 587)
        username  = cfg.get("username", "")
        to_addr   = cfg.get("to_address", "")
        subject   = cfg.get("subject", "Message from Agent")
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(message: str) -> str:
                """{desc}"""
                import smtplib, os
                from email.mime.text import MIMEText
                _to = {json.dumps(to_addr)}
                _from = {json.dumps(username)}
                pw = os.environ.get("SMTP_PASSWORD", "")
                msg = MIMEText(message, "plain")
                msg["Subject"] = {json.dumps(subject)}
                msg["From"] = _from
                msg["To"] = _to
                with smtplib.SMTP({json.dumps(smtp_host)}, {smtp_port}, timeout=10) as srv:
                    srv.starttls()
                    if _from and pw:
                        srv.login(_from, pw)
                    srv.sendmail(_from, [_to], msg.as_string())
                return "Email sent to " + _to

        ''')

    if tool_id == "slack_webhook":
        webhook = cfg.get("webhook_url", "")
        channel = cfg.get("channel", "")
        uname   = cfg.get("username", "Agentic Bot")
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(message: str) -> str:
                """{desc}"""
                import httpx, os
                webhook_url = os.environ.get("SLACK_WEBHOOK_URL", {json.dumps(webhook)})
                payload = {{"text": message, "username": {json.dumps(uname)}}}
                if {json.dumps(channel)}:
                    payload["channel"] = {json.dumps(channel)}
                resp = httpx.post(webhook_url, json=payload, timeout=10)
                return f"Slack HTTP {{resp.status_code}}"

        ''')

    if tool_id == "s3_reader":
        bucket = cfg.get("bucket", "")
        prefix = cfg.get("prefix", "")
        region = cfg.get("region", "us-east-1")
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(key: str) -> str:
                """{desc}"""
                import boto3, os
                s3 = boto3.client(
                    "s3", region_name={json.dumps(region)},
                    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", ""),
                    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
                )
                bucket = {json.dumps(bucket)}
                if not key or key.lower() in ("list", "ls"):
                    objs = s3.list_objects_v2(Bucket=bucket, Prefix={json.dumps(prefix)}, MaxKeys=50)
                    return "\\n".join(o["Key"] for o in objs.get("Contents", []))
                body = s3.get_object(Bucket=bucket, Key=key)["Body"].read(32768)
                return body.decode("utf-8", errors="replace")

        ''')

    if tool_id == "key_value_store":
        # Same actions as the platform's store (services/kv_store.py), in a local SQLite file
        namespace = str(cfg.get("namespace") or "default")
        per_user = cfg.get("scope", "user") != "project"
        read_only = cfg.get("access") == "read_only"
        try:
            default_ttl = max(0, int(float(cfg.get("default_ttl_seconds") or 0)))
        except (TypeError, ValueError):
            default_ttl = 0
        subject = 'os.environ.get("KV_STORE_USER", "local")' if per_user else '""'
        return textwrap.dedent(f'''\
            @tool
            def {fn_name}(input: str) -> str:
                """{desc} Input: a JSON object with "action" (get, set, delete or list), "key", "value" (any JSON, for set), optional "ttl_seconds" (set) and "prefix" (list)."""
                import json as _j, os, sqlite3, time
                try:
                    req = _j.loads(input or "{{}}")
                except ValueError:
                    req = None
                if not isinstance(req, dict) or req.get("action") not in ("get", "set", "delete", "list"):
                    return 'Expected a JSON object like {{"action": "get", "key": "k"}}; action is get, set, delete or list.'
                action, key = req["action"], str(req.get("key") or "").strip()
                if action in ("set", "delete") and {read_only!r}:
                    return "This store is read only."
                if action != "list" and not key:
                    return "key is required"
                scope = ({json.dumps(namespace)}, {subject})
                now = time.time()
                db = sqlite3.connect(os.environ.get("KV_STORE_PATH", "pipesets_store.db"))
                try:
                    db.execute("CREATE TABLE IF NOT EXISTS kv_entries (namespace TEXT, subject TEXT, key TEXT, value TEXT, "
                               "expires_at REAL, updated_at REAL, PRIMARY KEY (namespace, subject, key))")
                    db.execute("DELETE FROM kv_entries WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
                    if action == "get":
                        row = db.execute("SELECT value FROM kv_entries WHERE namespace = ? AND subject = ? AND key = ?",
                                         (*scope, key)).fetchone()
                        return _j.dumps({{"key": key, "found": bool(row), "value": _j.loads(row[0]) if row else None}})
                    if action == "set":
                        if "value" not in req:
                            return "set needs a value."
                        ttl = req.get("ttl_seconds") or {default_ttl}
                        expires = now + float(ttl) if ttl else None
                        db.execute("INSERT INTO kv_entries VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (namespace, subject, key) "
                                   "DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at, "
                                   "updated_at = excluded.updated_at", (*scope, key, _j.dumps(req["value"]), expires, now))
                        db.commit()
                        return _j.dumps({{"key": key, "stored": True, "expires_at": expires}})
                    if action == "delete":
                        n = db.execute("DELETE FROM kv_entries WHERE namespace = ? AND subject = ? AND key = ?",
                                       (*scope, key)).rowcount
                        db.commit()
                        return _j.dumps({{"key": key, "deleted": n == 1}})
                    rows = db.execute("SELECT key FROM kv_entries WHERE namespace = ? AND subject = ? AND substr(key, 1, ?) = ? "
                                      "ORDER BY key LIMIT 100", (*scope, len(req.get("prefix") or ""), req.get("prefix") or "")).fetchall()
                    return _j.dumps({{"keys": [r[0] for r in rows]}})
                finally:
                    db.close()

        ''')

    # ── Custom MCP or unknown tool ────────────────────────────────────────────
    return textwrap.dedent(f'''\
        @tool
        def {fn_name}(input: str) -> str:
            """{desc}"""
            # Custom tool — implement the body or call your MCP server here.
            cfg = {json.dumps(cfg, indent=8)}
            raise NotImplementedError(f"Implement tool '{tool_id}' here. Config: {{cfg}}")

    ''')


def tool_body_crewai(
    class_name: str,
    fn_name: str,
    tool_id: str,
    label: str,
    desc: str,
    cfg: Dict[str, Any],
    conn_node: Optional[Dict],
) -> str:
    """Wrap a langchain @tool function body inside a CrewAI BaseTool class."""
    inner = tool_body_langchain(fn_name, tool_id, desc, cfg, conn_node)
    lines = inner.strip().splitlines()

    body_lines: List[str] = []
    state = "before_def"

    for line in lines:
        stripped = line.strip()

        if state == "before_def":
            if stripped.startswith(f"def {fn_name}"):
                state = "in_def"
            continue

        if state == "in_def":
            if stripped.startswith('"""') or stripped.startswith("'''"):
                state = "in_docstring"
                rest = stripped[3:]
                if '"""' in rest or "'''" in rest:
                    state = "in_body"
            else:
                state = "in_body"
                body_lines.append("    " + line)
            continue

        if state == "in_docstring":
            if '"""' in stripped or "'''" in stripped:
                state = "in_body"
            continue

        if state == "in_body":
            body_lines.append("    " + line)

    body_str = "\n".join(body_lines) if body_lines else "        raise NotImplementedError"

    return (
        f"class {class_name}(BaseTool):\n"
        f"    name: str = {json.dumps(label)}\n"
        f"    description: str = {json.dumps(desc)}\n"
        f"\n"
        f"    def _run(self, input: str) -> str:\n"
        f"{body_str}\n"
        f"\n"
    )
