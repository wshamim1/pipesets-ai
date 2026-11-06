"""Built-in MCP servers: config → launch args / env / default tool call in ``prepare``, pinned package
versions, required keys named before anything starts, the remote GitHub and Linear servers, and
catalog registration. The generic stdio runner underneath
(handshake, tools/call, stored tools) is covered in test_mcp_typed.py against a real local server.
"""
import tools


def launch(tool_type, config, input=""):
    """prepare() for a server module: (args, tool_name, call_args, env_vars)."""
    mod = {"mcp_playwright": __import__("tools.mcp.web.mcp_playwright", fromlist=["x"]),
           "mcp_stripe": __import__("tools.mcp.developer.mcp_stripe", fromlist=["x"]),
           "mcp_kubernetes": __import__("tools.mcp.developer.mcp_kubernetes", fromlist=["x"])}[tool_type]
    env = {}
    got_args, name, call_args = mod.prepare(config, input, list(mod.ARGS), env, {"default_tool": mod.DEFAULT_TOOL})
    return got_args, name, call_args, env


def test_playwright_launch_args():
    args, name, call, _ = launch("mcp_playwright", {}, "https://example.com")
    assert args == ["-y", "@playwright/mcp@0.0.84"], "defaults launch the stdio server, no browser flags"
    assert name == "browser_navigate" and call == {"url": "https://example.com"}
    args, _, _, _ = launch("mcp_playwright", {"browser": "firefox", "headless": "on"})
    assert args == ["-y", "@playwright/mcp@0.0.84", "--browser", "firefox", "--headless"]
    args, _, _, _ = launch("mcp_playwright", {"browser": "FIREFOX", "headless": "no"})
    assert args == ["-y", "@playwright/mcp@0.0.84", "--browser", "firefox"]
    name, call = launch("mcp_playwright", {"tool_name": "browser_snapshot", "arguments": {"background": True}})[1:3]
    assert name == "browser_snapshot" and call == {"background": True}


def test_stripe_needs_the_secret_key():
    args, name, call, envs = launch("mcp_stripe", {"stripe_secret_key": "sk_test_abc"}, "why is pricing flat")
    assert envs == {"STRIPE_SECRET_KEY": "sk_test_abc"}
    assert name == "search_docs" and call == {"query": "why is pricing flat"}, "the input is a doc search"
    _, _, _, envs = launch("mcp_stripe", {"STRIPE_SECRET_KEY": "sk_live_1"})
    assert envs == {"STRIPE_SECRET_KEY": "sk_live_1"}, "the raw env-name key also works"
    args, name, call, envs = launch("mcp_stripe", {"tool_name": "create_payment_link",
                                                   "arguments": {"price": "price_1", "quantity": 3}})
    assert name == "create_payment_link" and call == {"price": "price_1", "quantity": 3}


def test_kubernetes_config():
    args, name, call, envs = launch("mcp_kubernetes", {})
    assert args == ["-y", "mcp-server-kubernetes@4.2.1"] and not envs
    assert name == "list_namespaces" and call == {}
    args, name, call, envs = launch("mcp_kubernetes", {"kubeconfig": "/etc/kube/prod", "tool_name": "list_pods",
                                                       "arguments": {"namespace": "prod"}})
    assert args == ["-y", "mcp-server-kubernetes@4.2.1"] and envs == {"KUBECONFIG": "/etc/kube/prod"}
    assert name == "list_pods" and call == {"namespace": "prod"}


def test_the_catalog_registers_the_three_servers():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers"
               for e in section["tools"]}
    for tool_type, category in (("mcp_playwright", "Web & Browser"), ("mcp_stripe", "Developer Tools"),
                                ("mcp_kubernetes", "Developer Tools")):
        assert entries[tool_type]["category"] == category
        assert entries[tool_type]["type"] == "mcp"
    assert entries["mcp_playwright"]["config_options"]["browser"]["options"][0]["value"] == "chrome"


def test_the_catalog_registers_remote_mcp_servers():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers"
               for e in section["tools"]}
    assert entries["mcp_remote_http"]["category"] == "Web & Browser"
    assert entries["mcp_remote_sse"]["category"] == "Web & Browser"
    assert entries["mcp_remote_http"]["type"] == "mcp"
    assert entries["mcp_remote_sse"]["type"] == "mcp"


def test_the_catalog_registers_new_productivity_servers():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers"
               for e in section["tools"]}
    for tool_type in ("mcp_slack", "mcp_trello", "mcp_asana"):
        assert entries[tool_type]["category"] == "Productivity"
        assert entries[tool_type]["type"] == "mcp"


def test_the_catalog_registers_more_web_and_ai_servers():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers"
               for e in section["tools"]}
    assert entries["mcp_pdf"]["category"] == "Web & Browser"
    assert entries["mcp_google_maps"]["category"] == "Web & Browser"
    assert entries["mcp_aws_kb"]["category"] == "AI & Memory"
    assert entries["mcp_everything"]["category"] == "AI & Memory"


# ── Every server pinned; new and replaced servers (verified against each package's source) ──────────
import asyncio
import importlib
import pkgutil

import pytest

import tools.mcp


def _modules():
    for info in pkgutil.walk_packages(tools.mcp.__path__, prefix="tools.mcp."):
        if not info.ispkg and not info.name.rsplit(".", 1)[-1].startswith("_"):
            yield importlib.import_module(info.name)


def _mod(tool_id):
    return next(m for m in _modules() if getattr(m, "TOOL", None) is not None and m.TOOL.id == tool_id)


def _launch(tool_id, config, input=""):
    mod = _mod(tool_id)
    env = {}
    args, name, call = mod.prepare(config, input, list(mod.ARGS), env, {"default_tool": mod.DEFAULT_TOOL})
    return args, name, call, env


def test_every_stdio_server_is_pinned():
    for mod in _modules():
        if not hasattr(mod, "ARGS"):
            continue
        package = next(a for a in mod.ARGS if not a.startswith("-"))
        assert "@" in package.lstrip("@"), f"{mod.TOOL.id}: {package} isn't pinned to a version"
        assert package in mod.TOOL.default_config.get("args", []), f"{mod.TOOL.id}: the catalog shows another package"


@pytest.mark.parametrize("tool_id,config,input,env,tool,call", [
    ("mcp_tavily", {"tavily_api_key": "tvly-1"}, "rent law", {"TAVILY_API_KEY": "tvly-1"}, "tavily_search", {"query": "rent law"}),
    ("mcp_exa", {"exa_api_key": "e1"}, "x", {"EXA_API_KEY": "e1"}, "web_search_exa", {"query": "x"}),
    ("mcp_perplexity", {"perplexity_api_key": "p1"}, "x", {"PERPLEXITY_API_KEY": "p1"}, "perplexity_search", {"query": "x"}),
    ("mcp_context7", {}, "next.js", {}, "resolve-library-id", {"libraryName": "next.js", "query": "next.js"}),
    ("mcp_pinecone", {"pinecone_api_key": "pc"}, "", {"PINECONE_API_KEY": "pc"}, "list-indexes", {}),
    ("mcp_hubspot", {"hubspot_access_token": "pat"}, "", {"PRIVATE_APP_ACCESS_TOKEN": "pat"}, "hubspot-get-user-details", {}),
    ("mcp_airtable", {"airtable_api_key": "pat"}, "", {"AIRTABLE_API_KEY": "pat"}, "list_bases", {}),
    ("mcp_qdrant", {"qdrant_url": "http://q:6333", "collection_name": "leases"}, "rent",
     {"QDRANT_URL": "http://q:6333", "COLLECTION_NAME": "leases"}, "qdrant-find", {"query": "rent"}),
    ("mcp_neo4j", {"neo4j_uri": "bolt://n", "neo4j_password": "pw"}, "MATCH (n) RETURN n",
     {"NEO4J_URI": "bolt://n", "NEO4J_PASSWORD": "pw", "NEO4J_READ_ONLY": "true"}, "read_neo4j_cypher",
     {"query": "MATCH (n) RETURN n"}),
    ("mcp_confluence", {"confluence_url": "https://a.atlassian.net/wiki", "confluence_api_token": "t"}, "lease",
     {"CONFLUENCE_URL": "https://a.atlassian.net/wiki", "CONFLUENCE_API_TOKEN": "t", "READ_ONLY_MODE": "true"},
     "confluence_search", {"query": "lease"}),
    ("mcp_aws_docs", {}, "s3 naming", {"FASTMCP_LOG_LEVEL": "ERROR"}, "search_documentation", {"search_phrase": "s3 naming"}),
    ("mcp_aws_kb", {"bedrock_kb_id": "KB1", "aws_region": "us-west-2"}, "rent", {"AWS_REGION": "us-west-2", "FASTMCP_LOG_LEVEL": "ERROR"},
     "QueryKnowledgeBases", {"query": "rent", "knowledge_base_id": "KB1"}),
    ("mcp_trello", {"trello_api_key": "k", "trello_token": "t"}, "", {"TRELLO_API_KEY": "k", "TRELLO_TOKEN": "t"}, "list_boards", {}),
    ("mcp_docker", {}, "", {}, "list_containers", {}),
])
def test_server_config(tool_id, config, input, env, tool, call, monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE", "CONTEXT7_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    _, got_tool, got_call, got_env = _launch(tool_id, config, input)
    assert (got_tool, got_call) == (tool, call)
    assert {k: v for k, v in got_env.items() if v} == env


def test_read_only_and_flags():
    args, tool, _, env = _launch("mcp_supabase", {"supabase_access_token": "sbp", "read_only": "true"})
    assert args[-1] == "--read-only" and env == {"SUPABASE_ACCESS_TOKEN": "sbp"} and tool == "list_projects"
    args, tool, _, _ = _launch("mcp_supabase", {"supabase_access_token": "sbp", "read_only": "false", "project_ref": "abc"})
    assert "--read-only" not in args and args[-1] == "--project-ref=abc" and tool == "list_tables", \
        "scoped to a project, list_projects isn't offered"
    assert _launch("mcp_neo4j", {"read_only": "false"})[3]["NEO4J_READ_ONLY"] == "false"
    assert _launch("mcp_gitlab", {"read_only": "true"})[3]["GITLAB_READ_ONLY_MODE"] == "true"
    assert "GITLAB_READ_ONLY_MODE" not in _launch("mcp_gitlab", {})[3], "older nodes keep write access"
    args = _launch("mcp_time", {"local_timezone": "America/New_York"})[0]
    assert args[-2:] == ["--local-timezone", "America/New_York"]
    assert _launch("mcp_time", {})[2] == {"timezone": "UTC"}
    env = _launch("mcp_chroma", {"client_type": "cloud", "chroma_tenant": "t", "chroma_database": "d",
                                 "chroma_api_key": "k", "chroma_host": "ignored"})[3]
    assert env == {"CHROMA_CLIENT_TYPE": "cloud", "CHROMA_TENANT": "t", "CHROMA_DATABASE": "d", "CHROMA_API_KEY": "k"}
    env = _launch("mcp_openapi", {"openapi_spec_url": "https://x/openapi.json", "api_base_url": "https://x", "api_token": "tk"})[3]
    assert env == {"OPENAPI_SPEC_PATH": "https://x/openapi.json", "API_BASE_URL": "https://x", "TOOLS_MODE": "dynamic",
                   "API_HEADERS": "Authorization:Bearer tk"}


def test_redis_url_goes_in_env_not_on_the_command_line():
    args, tool, call, env = _launch("mcp_redis", {"redis_url": "rediss://app:s%40cret@cache.local:6380/2"}, "session:1")
    assert "s@cret" not in " ".join(args) and "--url" not in args
    assert env == {"REDIS_HOST": "cache.local", "REDIS_PORT": "6380", "REDIS_SSL": "true", "REDIS_USERNAME": "app",
                   "REDIS_PWD": "s@cret", "REDIS_DB": "2"}
    assert (tool, call) == ("get", {"key": "session:1"})
    assert _launch("mcp_redis", {"redis_url": "localhost"})[3] == {"REDIS_HOST": "localhost", "REDIS_PORT": "6379",
                                                                    "REDIS_SSL": "false"}


def test_podman_default_has_no_home_path():
    cfg = _mod("mcp_podman").TOOL.default_config
    assert "wilsonshamim" not in str(cfg) and cfg["podman_socket"] == ""


def test_database_servers_config(monkeypatch):
    for name in ("MDB_MCP_CONNECTION_STRING", "CLICKHOUSE_HOST", "MYSQL_HOST", "SNOWFLAKE_ACCOUNT",
                 "BIGQUERY_PROJECT_ID", "ES_URL"):
        monkeypatch.delenv(name, raising=False)

    args, tool, call, env = _launch("mcp_mongodb", {"mdb_connection_string": "mongodb://db:27017"}, "")
    assert args == ["-y", "mongodb-mcp-server@3.2.2", "--readOnly"]
    assert env == {"MDB_MCP_CONNECTION_STRING": "mongodb://db:27017"}
    assert (tool, call) == ("list-databases", {})
    args, tool, call, _ = _launch("mcp_mongodb",
                                  {"mdb_connection_string": "mongodb://db", "database": "app", "collection": "users"},
                                  '{"status": "active"}')
    assert tool == "find" and call == {"database": "app", "collection": "users", "filter": {"status": "active"}}
    assert "--readOnly" not in _launch("mcp_mongodb", {"mdb_connection_string": "mongodb://db", "read_only": "false"})[0]

    args, tool, call, env = _launch("mcp_clickhouse", {
        "clickhouse_host": "ch.local", "clickhouse_port": "8443", "clickhouse_user": "app",
        "clickhouse_password": "pw", "clickhouse_database": "analytics", "clickhouse_secure": "true"}, "SELECT 1")
    assert args == ["mcp-clickhouse@0.7.0"]
    assert env == {"CLICKHOUSE_HOST": "ch.local", "CLICKHOUSE_PORT": "8443", "CLICKHOUSE_USER": "app",
                   "CLICKHOUSE_PASSWORD": "pw", "CLICKHOUSE_DATABASE": "analytics", "CLICKHOUSE_SECURE": "true",
                   "CLICKHOUSE_VERIFY": "true", "CLICKHOUSE_ALLOW_WRITE_ACCESS": "false"}
    assert (tool, call) == ("run_query", {"query": "SELECT 1"})

    args, tool, call, env = _launch("mcp_mysql", {
        "mysql_host": "mysql.local", "mysql_port": "3307", "mysql_user": "app", "mysql_pass": "pw",
        "mysql_db": "shop"}, "SELECT 1")
    assert args == ["-y", "@benborla29/mcp-server-mysql@2.0.9"]
    assert env == {"MYSQL_HOST": "mysql.local", "MYSQL_PORT": "3307", "MYSQL_USER": "app", "MYSQL_PASS": "pw",
                   "MYSQL_DB": "shop"}
    assert (tool, call) == ("mysql_query", {"sql": "SELECT 1"})
    env = _launch("mcp_mysql", {"read_only": "false"})[3]
    assert env["ALLOW_INSERT_OPERATION"] == "true" and env["ALLOW_DDL_OPERATION"] == "true"

    args, tool, call, env = _launch("mcp_snowflake", {
        "snowflake_account": "acct", "snowflake_user": "app", "snowflake_password": "pw",
        "snowflake_database": "analytics", "snowflake_warehouse": "wh"}, "SELECT 1")
    assert args == ["--from", "mcp-server-snowflake@0.3.8", "mcp_server_snowflake"]
    assert env == {"SNOWFLAKE_ACCOUNT": "acct", "SNOWFLAKE_USER": "app", "SNOWFLAKE_PASSWORD": "pw",
                   "SNOWFLAKE_DATABASE": "analytics", "SNOWFLAKE_SCHEMA": "PUBLIC", "SNOWFLAKE_WAREHOUSE": "wh"}
    assert (tool, call) == ("read_query", {"query": "SELECT 1"})
    assert _launch("mcp_snowflake", {"read_only": "false"})[0][-1] == "--allow_write"

    args, tool, call, env = _launch("mcp_bigquery", {
        "bigquery_project_id": "proj", "bigquery_location": "EU", "bigquery_key_file": "/keys/sa.json"}, "SELECT 1")
    assert args == ["-y", "@ergut/mcp-bigquery-server@1.0.4", "--project-id", "proj", "--location", "EU"]
    assert env == {"GOOGLE_APPLICATION_CREDENTIALS": "/keys/sa.json"}
    assert (tool, call) == ("query", {"sql": "SELECT 1"})

    args, tool, call, env = _launch("mcp_elasticsearch", {"elasticsearch_url": "https://es:9200"}, "")
    assert args == ["-y", "@elastic/mcp-server-elasticsearch@0.3.1"]
    assert env == {"ES_URL": "https://es:9200"} and (tool, call) == ("list_indices", {})
    args, tool, call, env = _launch("mcp_elasticsearch", {
        "elasticsearch_url": "https://es:9200", "elasticsearch_api_key": "key", "index": "logs"}, "connection timeout")
    assert env["ES_API_KEY"] == "key" and tool == "search"
    assert call == {"index": "logs", "queryBody": {"query": {"query_string": {"query": "connection timeout"}}}}


def test_devops_servers_config():
    args, tool, call, env = _launch("mcp_grafana", {
        "grafana_url": "https://grafana.example.com", "grafana_token": "glsa_1"}, "latency")
    assert args == ["mcp-grafana@2.2.0", "--disable-write"]
    assert env == {"GRAFANA_URL": "https://grafana.example.com", "GRAFANA_SERVICE_ACCOUNT_TOKEN": "glsa_1"}
    assert (tool, call) == ("search_dashboards", {"query": "latency"})
    assert _launch("mcp_grafana", {"grafana_token": "t", "read_only": "false"})[0][-1] != "--disable-write"

    args, tool, call, env = _launch("mcp_prometheus", {
        "prometheus_url": "https://prom.example.com", "prometheus_token": "tok"}, "up")
    assert args == ["prometheus-mcp-server@1.6.2"]
    assert env == {"PROMETHEUS_URL": "https://prom.example.com", "PROMETHEUS_TOKEN": "tok"}
    assert (tool, call) == ("execute_query", {"query": "up"})


def test_airflow_config():
    args, tool, call, env = _launch("mcp_airflow", {
        "airflow_host": "https://airflow.example.com", "airflow_username": "admin", "airflow_password": "pw"}, "etl")
    assert args == ["mcp-server-apache-airflow@0.2.10", "--read-only"], "read-only unless turned off"
    assert env == {"AIRFLOW_HOST": "https://airflow.example.com", "AIRFLOW_API_VERSION": "v1",
                   "AIRFLOW_USERNAME": "admin", "AIRFLOW_PASSWORD": "pw"}
    assert (tool, call) == ("fetch_dags", {"dag_id_pattern": "etl"})

    args, tool, call, env = _launch("mcp_airflow", {
        "airflow_jwt_token": "jwt", "airflow_username": "admin", "airflow_password": "pw",
        "airflow_api_version": "v2", "read_only": "false", "tool_name": "post_dag_run",
        "arguments": {"dag_id": "etl"}})
    assert args == ["mcp-server-apache-airflow@0.2.10"]
    assert env == {"AIRFLOW_HOST": "http://localhost:8080", "AIRFLOW_API_VERSION": "v2", "AIRFLOW_JWT_TOKEN": "jwt"}, \
        "a token replaces basic auth"
    assert (tool, call) == ("post_dag_run", {"dag_id": "etl"})
    assert _launch("mcp_airflow", {})[2] == {}, "no input lists every DAG"


def test_productivity_servers_config():
    args, tool, call, env = _launch("mcp_salesforce", {}, "SELECT Id FROM Account")
    assert args == ["-y", "@salesforce/mcp@0.30.15", "--orgs", "DEFAULT_TARGET_ORG", "--toolsets", "orgs,data"]
    assert env == {} and (tool, call) == ("run_soql_query", {"query": "SELECT Id FROM Account"})
    call = _launch("mcp_salesforce", {"salesforce_orgs": "prod", "salesforce_username": "me@example.com"},
                   "SELECT Id FROM Account")[2]
    assert call == {"query": "SELECT Id FROM Account", "usernameOrAlias": "me@example.com"}

    args, tool, call, env = _launch("mcp_figma", {"figma_api_key": "fig_1"},
                                    "https://www.figma.com/design/AbC123/My-File?node-id=12-34")
    assert args == ["-y", "figma-developer-mcp@0.13.2", "--stdio"]
    assert env == {"FIGMA_API_KEY": "fig_1"}
    assert (tool, call) == ("get_figma_data", {"fileKey": "AbC123", "nodeId": "12:34"})
    assert _launch("mcp_figma", {"figma_api_key": "fig_1"}, "BareKey")[2] == {"fileKey": "BareKey"}

    args, tool, call, env = _launch("mcp_discord", {"discord_bot_token": "bot"}, "123")
    assert args == ["-y", "discord-mcp@2.4.0"] and env == {"DISCORD_BOT_TOKEN": "bot"}
    assert (tool, call) == ("discord_get_channel", {"channelId": "123"})


def test_datadog_uses_its_remote_server(monkeypatch):
    from tools.mcp import _http

    calls = []

    async def fake_call(label, url, headers, transport, tool_name, arguments, timeout=30):
        calls.append((url, headers, tool_name, arguments))
        return "ok"

    monkeypatch.setattr(_http, "call_remote", fake_call)
    datadog = _mod("mcp_datadog")
    assert asyncio.run(datadog.run("service:web", {"dd_api_key": "api", "dd_application_key": "app"},
                                   "mcp_datadog")) == "ok"
    assert calls[-1] == ("https://mcp.datadoghq.com/v1/mcp",
                         {"DD-API-KEY": "api", "DD-APPLICATION-KEY": "app"},
                         "search_datadog_logs", {"query": "service:web"})
    asyncio.run(datadog.run("", {"dd_api_key": "api", "dd_application_key": "app", "datadog_site": "eu1"},
                            "mcp_datadog"))
    assert calls[-1][0] == "https://mcp.datadoghq.eu/v1/mcp" and calls[-1][3] == {"query": "*"}
    out = asyncio.run(datadog.run("x", {"dd_api_key": "api"}, "mcp_datadog"))
    assert "dd_application_key" in out and len(calls) == 2, "no request without both keys"


def test_catalog_registers_new_database_and_devops_servers():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers"
               for e in section["tools"]}
    for tool_type in ("mcp_mongodb", "mcp_clickhouse", "mcp_mysql", "mcp_snowflake", "mcp_bigquery",
                      "mcp_elastic_agent_builder", "mcp_opensearch"):
        assert entries[tool_type]["category"] == "Databases & Data"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    for tool_type in ("mcp_grafana", "mcp_prometheus", "mcp_datadog", "mcp_airflow"):
        assert entries[tool_type]["category"] == "DevOps & Observability"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    for tool_type in ("mcp_salesforce", "mcp_figma", "mcp_discord"):
        assert entries[tool_type]["category"] == "Productivity"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    assert entries["mcp_datadog"]["default_config"]["transport"] == "http"
    assert "mcp_elasticsearch" not in entries and tools.get_spec("mcp_elasticsearch"), "deprecated upstream: hidden, still runnable"
    assert entries["mcp_snowflake"]["required_config"] == ["snowflake_account", "snowflake_user",
                                                          "snowflake_password", "snowflake_database"]


def test_missing_required_key_is_named_before_launch(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    started = []

    async def no_start(*a, **k):
        started.append(a)
        raise AssertionError("launched")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_start)
    out = asyncio.run(_mod("mcp_tavily").run("x", {}, "mcp_tavily"))
    assert "tavily_api_key" in out and not started
    with pytest.raises(RuntimeError, match="tavily_api_key"):
        asyncio.run(_mod("mcp_tavily").run.discover({}, "mcp_tavily"))
    monkeypatch.setenv("TAVILY_API_KEY", "from-env")
    assert _launch("mcp_tavily", {})[3] == {"TAVILY_API_KEY": "from-env"}, "the env var also satisfies it"


def test_github_and_linear_use_their_remote_servers(monkeypatch):
    from tools.mcp import _http

    calls = []

    async def fake_call(label, url, headers, transport, tool_name, arguments, timeout=30):
        calls.append((url, headers, tool_name, arguments))
        return "ok"

    monkeypatch.setattr(_http, "call_remote", fake_call)
    github, linear = _mod("mcp_github"), _mod("mcp_linear")
    assert asyncio.run(github.run("pipesets", {"github_token": "ghp_1", "read_only": "true"}, "mcp_github")) == "ok"
    assert calls[-1] == ("https://api.githubcopilot.com/mcp/", {"Authorization": "Bearer ghp_1", "X-MCP-Readonly": "true"},
                         "search_repositories", {"query": "pipesets"})
    asyncio.run(github.run("x", {"github_token": "ghp_1"}, "mcp_github"))
    assert "X-MCP-Readonly" not in calls[-1][1], "nodes saved before read_only keep write access"
    asyncio.run(linear.run("", {"linear_api_key": "lin_1", "read_only": "true"}, "mcp_linear"))
    assert calls[-1] == ("https://mcp.linear.app/mcp/readonly", {"Authorization": "Bearer lin_1"}, "list_issues", {})
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    out = asyncio.run(linear.run("x", {}, "mcp_linear"))
    assert "linear_api_key" in out and len(calls) == 3, "no request without a key"


def test_second_batch_stdio_servers_config(monkeypatch):
    for name in ("MOTHERDUCK_TOKEN", "AWS_REGION", "NETLIFY_PERSONAL_ACCESS_TOKEN", "TODOIST_API_KEY",
                 "APIFY_TOKEN", "BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    args, tool, call, env = _launch("mcp_motherduck", {"motherduck_token": "md_tok"}, "SELECT 1")
    assert args == ["--from", "mcp-server-motherduck@1.1.0", "mcp-server-motherduck", "--db-path", "md:"]
    assert env == {"MOTHERDUCK_TOKEN": "md_tok"}
    assert (tool, call) == ("execute_query", {"sql": "SELECT 1"})
    assert _launch("mcp_motherduck", {"motherduck_token": "md_tok", "read_only": "false"})[0][-1] == "--read-write"
    assert _launch("mcp_motherduck", {"motherduck_token": "md_tok", "motherduck_db_path": "local.db"})[0][-2:] == \
        ["--db-path", "local.db"]

    args, tool, call, env = _launch("mcp_dynamodb", {"aws_region": "us-east-1", "aws_profile": "prod"}, "")
    assert args == ["--from", "awslabs.dynamodb-mcp-server@2.1.9", "awslabs.dynamodb-mcp-server"]
    assert env == {"AWS_REGION": "us-east-1", "AWS_PROFILE": "prod"}
    assert (tool, call) == ("dynamodb_data_modeling", {})

    args, tool, call, env = _launch("mcp_netlify", {"netlify_personal_access_token": "pat"}, "pipesets")
    assert args == ["-y", "@netlify/mcp@1.21.0"]
    assert env == {"NETLIFY_PERSONAL_ACCESS_TOKEN": "pat"}
    assert tool == "netlify-project-services-reader"
    assert call == {"selectSchema": {"operation": "get-projects", "params": {"projectNameSearchValue": "pipesets"}}}
    assert _launch("mcp_netlify", {"netlify_personal_access_token": "pat"})[2] == \
        {"selectSchema": {"operation": "get-projects"}}

    args, tool, call, env = _launch("mcp_todoist", {"todoist_api_key": "t"}, "buy milk")
    assert args == ["-y", "@doist/todoist-mcp@13.8.4"]
    assert env == {"TODOIST_API_KEY": "t"}
    assert (tool, call) == ("find-tasks", {"searchText": "buy milk"})

    args, tool, call, env = _launch("mcp_apify", {"apify_token": "ap"}, "google maps")
    assert args == ["-y", "@apify/actors-mcp-server@0.20.0"]
    assert env == {"APIFY_TOKEN": "ap"}
    assert (tool, call) == ("search-actors", {"keywords": "google maps"})

    args, tool, call, env = _launch("mcp_browserbase", {
        "browserbase_api_key": "bb", "browserbase_project_id": "proj", "gemini_api_key": "g"}, "https://example.com")
    assert args == ["-y", "@browserbasehq/mcp@3.0.0"]
    assert env == {"BROWSERBASE_API_KEY": "bb", "BROWSERBASE_PROJECT_ID": "proj", "GEMINI_API_KEY": "g"}
    assert (tool, call) == ("navigate", {"url": "https://example.com"})
    assert _launch("mcp_browserbase", {"browserbase_api_key": "bb", "browserbase_project_id": "proj"})[1:3] == \
        ("start", {}), "a call without a URL starts a browser session"


def test_second_batch_remote_servers(monkeypatch):
    from tools.mcp import _http

    for name in ("NEON_API_KEY", "POSTMAN_API_KEY", "POSTHOG_API_KEY", "HF_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    calls = []

    async def fake_call(label, url, headers, transport, tool_name, arguments, timeout=30):
        calls.append((url, headers, tool_name, arguments))
        return "ok"

    monkeypatch.setattr(_http, "call_remote", fake_call)
    neon, postman, posthog, huggingface = (_mod(i) for i in
                                          ("mcp_neon", "mcp_postman", "mcp_posthog", "mcp_huggingface"))

    assert asyncio.run(neon.run("rent", {"neon_api_key": "n"}, "mcp_neon")) == "ok"
    assert calls[-1] == ("https://mcp.neon.tech/mcp", {"Authorization": "Bearer n"},
                         "list_projects", {"search": "rent"})

    assert asyncio.run(postman.run("stripe", {"postman_api_key": "pm"}, "mcp_postman")) == "ok"
    assert calls[-1] == ("https://mcp.postman.com/minimal", {"Authorization": "Bearer pm"},
                         "searchPostmanElements", {"q": "stripe"})
    asyncio.run(postman.run("", {"postman_api_key": "pm", "postman_region": "eu"}, "mcp_postman"))
    assert calls[-1][0] == "https://mcp.eu.postman.com/minimal" and calls[-1][3] == {}

    assert asyncio.run(posthog.run("SELECT event FROM events", {"posthog_api_key": "ph"}, "mcp_posthog")) == "ok"
    assert calls[-1] == ("https://mcp.posthog.com/mcp?mode=tools&features=sql,dashboards,insights,flags,error_tracking",
                         {"Authorization": "Bearer ph"}, "execute-sql", {"query": "SELECT event FROM events"})
    asyncio.run(posthog.run("", {"posthog_api_key": "ph", "posthog_region": "eu"}, "mcp_posthog"))
    assert calls[-1][0].startswith("https://mcp-eu.posthog.com/mcp?")

    assert asyncio.run(huggingface.run("qwen", {"hf_token": "hf"}, "mcp_huggingface")) == "ok"
    assert calls[-1] == ("https://huggingface.co/mcp", {"Authorization": "Bearer hf"},
                         "hub_repo_search", {"query": "qwen"})
    out = asyncio.run(huggingface.run("x", {}, "mcp_huggingface"))
    assert "hf_token" in out and len(calls) == 6, "no request without a token"


def test_catalog_registers_second_batch_servers():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers"
               for e in section["tools"]}
    for tool_type in ("mcp_neon", "mcp_motherduck", "mcp_dynamodb"):
        assert entries[tool_type]["category"] == "Databases & Data"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    for tool_type in ("mcp_netlify", "mcp_postman"):
        assert entries[tool_type]["category"] == "Developer Tools"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    assert entries["mcp_posthog"]["category"] == "DevOps & Observability"
    for tool_type in ("mcp_apify", "mcp_browserbase"):
        assert entries[tool_type]["category"] == "Web & Browser"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    assert entries["mcp_todoist"]["category"] == "Productivity"
    assert entries["mcp_huggingface"]["category"] == "AI & Memory"
    for tool_type in ("mcp_neon", "mcp_postman", "mcp_posthog", "mcp_huggingface"):
        assert entries[tool_type]["default_config"]["transport"] == "http"
    assert entries["mcp_motherduck"]["required_config"] == ["motherduck_token"]
    assert entries["mcp_postman"]["config_options"]["postman_region"]["options"][0]["value"] == "us"


def test_catalog_lists_new_servers_and_hides_puppeteer():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers" for e in section["tools"]}
    new = ["mcp_tavily", "mcp_exa", "mcp_perplexity", "mcp_context7", "mcp_time", "mcp_aws_docs", "mcp_supabase",
           "mcp_qdrant", "mcp_chroma", "mcp_neo4j", "mcp_pinecone", "mcp_hubspot", "mcp_airtable", "mcp_confluence"]
    assert all(entries[i]["is_new"] for i in new)
    assert entries["mcp_supabase"]["required_config"] == ["supabase_access_token"]
    assert entries["mcp_github"]["default_config"]["transport"] == "http"
    assert "mcp_puppeteer" not in entries and "mcp_puppeteer" in tools._runners, "hidden, but old pipelines still run"


def test_databricks_stdio_server(monkeypatch):
    for name in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID"):
        monkeypatch.delenv(name, raising=False)
    args, tool, call, env = _launch("mcp_databricks", {"databricks_host": "adb-1.azuredatabricks.net/",
                                                       "databricks_token": "dapi"})
    assert args == ["--from", "databricks-mcp-server@0.4.4", "databricks-mcp-server"]
    assert env == {"DATABRICKS_HOST": "https://adb-1.azuredatabricks.net", "DATABRICKS_TOKEN": "dapi"}
    assert (tool, call) == ("list_clusters", {}), "no input lists clusters"
    _, tool, call, env = _launch("mcp_databricks", {"databricks_host": "https://h", "databricks_token": "dapi",
                                                    "databricks_warehouse_id": "w1"}, "SELECT 1")
    assert (tool, call) == ("execute_sql", {"statement": "SELECT 1"}) and env["DATABRICKS_WAREHOUSE_ID"] == "w1"
    _, tool, call, _ = _launch("mcp_databricks", {"tool_name": "list_catalogs"}, "ignored")
    assert (tool, call) == ("list_catalogs", {})


def test_databricks_managed_server_urls(monkeypatch):
    from tools.mcp import _http

    calls = []

    async def fake_call(label, url, headers, transport, tool_name, arguments, timeout=30):
        calls.append((url, headers, tool_name, arguments))
        return "ok"

    monkeypatch.setattr(_http, "call_remote", fake_call)
    managed = _mod("mcp_databricks_managed")
    base = {"databricks_host": "adb-1.azuredatabricks.net", "databricks_token": "dapi"}

    assert "Pick a tool" in asyncio.run(managed.run("q", base, "mcp_databricks_managed")) and not calls
    assert asyncio.run(managed.run("SELECT 1", {**base, "tool_name": "execute_sql"}, "mcp_databricks_managed")) == "ok"
    assert calls[-1] == ("https://adb-1.azuredatabricks.net/api/2.0/mcp/sql", {"Authorization": "Bearer dapi"},
                         "execute_sql", {"query": "SELECT 1"})

    out = asyncio.run(managed.run("q", {**base, "server": "genie", "tool_name": "t"}, "mcp_databricks_managed"))
    assert "genie_space_id" in out and len(calls) == 1
    asyncio.run(managed.run("q", {**base, "server": "genie", "genie_space_id": "01ef", "tool_name": "t"},
                            "mcp_databricks_managed"))
    assert calls[-1][0].endswith("/api/2.0/mcp/genie/01ef")
    asyncio.run(managed.run("", {**base, "server": "vector-search", "catalog": "main", "schema": "docs",
                                 "tool_name": "t", "arguments": {"query": "x"}}, "mcp_databricks_managed"))
    assert calls[-1][0].endswith("/api/2.0/mcp/vector-search/main/docs") and calls[-1][3] == {"query": "x"}
    with pytest.raises(RuntimeError, match="catalog and schema"):
        asyncio.run(managed.run.discover({**base, "server": "functions"}, "mcp_databricks_managed"))


def test_catalog_registers_databricks_servers():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers" for e in section["tools"]}
    for tool_type in ("mcp_databricks", "mcp_databricks_managed"):
        assert entries[tool_type]["category"] == "Databases & Data" and entries[tool_type]["is_new"]
        assert entries[tool_type]["required_config"] == ["databricks_host", "databricks_token"]
    assert entries["mcp_databricks_managed"]["default_config"]["transport"] == "http"
    assert entries["mcp_databricks_managed"]["config_options"]["server"]["options"][0]["value"] == "sql"


def test_snowflake_official_server_config(monkeypatch):
    for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD", "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE"):
        monkeypatch.delenv(name, raising=False)
    import json as _json
    creds = {"snowflake_account": "org-acct", "snowflake_user": "bot", "snowflake_password": "pat"}
    args, tool, call, env = _launch("mcp_snowflake_labs", creds, "SELECT 1")
    assert args == ["--from", "snowflake-labs-mcp@1.4.2", "snowflake-labs-mcp"]
    assert (tool, call) == ("run_snowflake_query", {"statement": "SELECT 1"})
    assert {k: env[k] for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")} == \
        {"SNOWFLAKE_ACCOUNT": "org-acct", "SNOWFLAKE_USER": "bot", "SNOWFLAKE_PASSWORD": "pat"}
    with open(env["SERVICE_CONFIG_FILE"]) as f:
        doc = _json.load(f)
    assert doc["sql_statement_permissions"] == [{"Select": True}, {"Describe": True}], "read-only by default"
    assert doc["other_services"]["object_manager"] is False
    assert "pat" not in _json.dumps(doc), "no secrets in the config file"
    assert _launch("mcp_snowflake_labs", creds)[2]["statement"].startswith("SELECT CURRENT_ACCOUNT()")

    _, _, _, env = _launch("mcp_snowflake_labs", {**creds, "read_only": "false", "search_service": "DB.DOCS.FAQ",
                                                  "semantic_model": "DB.SALES.REV"})
    with open(env["SERVICE_CONFIG_FILE"]) as f:
        doc = _json.load(f)
    assert doc["sql_statement_permissions"] == [{"All": True}] and doc["other_services"]["object_manager"]
    assert doc["search_services"][0] == {"service_name": "FAQ", "database_name": "DB", "schema_name": "DOCS",
                                         "description": "Cortex Search service configured on this node"}
    assert doc["analyst_services"][0]["semantic_model"] == "DB.SALES.REV"


def test_snowflake_managed_server(monkeypatch):
    from tools.mcp import _http

    calls = []

    async def fake_call(label, url, headers, transport, tool_name, arguments, timeout=30):
        calls.append((url, headers, tool_name, arguments))
        return "ok"

    monkeypatch.setattr(_http, "call_remote", fake_call)
    managed = _mod("mcp_snowflake_managed")
    base = {"snowflake_account": "MyOrg-Acct", "snowflake_token": "pat", "mcp_server": "DB.AGENTS.SALES_MCP"}
    assert "Pick a tool" in asyncio.run(managed.run("q", base, "mcp_snowflake_managed")) and not calls
    assert asyncio.run(managed.run("revenue", {**base, "tool_name": "sales-search"}, "mcp_snowflake_managed")) == "ok"
    assert calls[-1] == ("https://myorg-acct.snowflakecomputing.com/api/v2/databases/DB/schemas/AGENTS/mcp-servers/SALES_MCP",
                         {"Authorization": "Bearer pat"}, "sales-search", {"query": "revenue"})
    out = asyncio.run(managed.run("q", {**base, "mcp_server": "SALES_MCP", "tool_name": "t"}, "mcp_snowflake_managed"))
    assert "db.schema.server_name" in out and len(calls) == 1


def test_catalog_registers_snowflake_servers():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers" for e in section["tools"]}
    for tool_type in ("mcp_snowflake_labs", "mcp_snowflake_managed"):
        assert entries[tool_type]["category"] == "Databases & Data" and entries[tool_type]["is_new"]
    assert entries["mcp_snowflake_managed"]["default_config"]["transport"] == "http"
    assert entries["mcp_snowflake_labs"]["config_options"]["read_only"]["options"][0]["value"] == "true"


def test_third_batch_stdio_servers_config(monkeypatch):
    for name in ("AWS_REGION", "AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                 "ACCESS_MODE", "E2B_API_KEY", "HYPERBROWSER_API_KEY", "HB_API_KEY", "DSN"):
        monkeypatch.delenv(name, raising=False)

    args, tool, call, env = _launch("mcp_hyperbrowser", {"hyperbrowser_api_key": "hb"}, "https://example.com")
    assert args == ["-y", "hyperbrowser-mcp@1.0.25"]
    assert env == {"HYPERBROWSER_API_KEY": "hb"}
    assert (tool, call) == ("scrape_webpage", {"url": "https://example.com", "outputFormat": ["markdown"]})
    assert _launch("mcp_hyperbrowser", {"HB_API_KEY": "from-env-name"}, "")[3] == {"HYPERBROWSER_API_KEY": "from-env-name"}

    args, tool, call, env = _launch("mcp_e2b", {"e2b_api_key": "e2b"}, "print('hi')")
    assert args == ["-y", "@e2b/mcp-server@0.2.3"]
    assert env == {"E2B_API_KEY": "e2b"}
    assert (tool, call) == ("run_code", {"code": "print('hi')"})
    assert _launch("mcp_e2b", {"e2b_api_key": "e2b"}, "")[2] == {}

    args, tool, call, env = _launch("mcp_redshift", {"aws_region": "us-east-1", "aws_profile": "prod"}, "")
    assert args == ["--from", "awslabs.redshift-mcp-server@0.1.2", "awslabs.redshift-mcp-server"]
    assert env == {"AWS_REGION": "us-east-1", "AWS_PROFILE": "prod", "ACCESS_MODE": "read-only"}
    assert (tool, call) == ("list_clusters", {})
    args, tool, call, env = _launch("mcp_redshift", {
        "aws_region": "eu-west-1", "aws_access_key_id": "AKIA", "aws_secret_access_key": "secret",
        "aws_session_token": "tok", "access_mode": "read-write", "tool_name": "execute_query",
        "arguments": {"cluster_identifier": "c", "cluster_type": "provisioned", "database_name": "dev",
                      "sql": "SELECT 1"}}, "")
    assert env == {"AWS_REGION": "eu-west-1", "AWS_ACCESS_KEY_ID": "AKIA", "AWS_SECRET_ACCESS_KEY": "secret",
                   "AWS_SESSION_TOKEN": "tok", "ACCESS_MODE": "read-write"}
    assert tool == "execute_query" and call["sql"] == "SELECT 1"

    args, tool, call, env = _launch("mcp_dbhub", {"dsn": "postgres://u:p@db:5432/app"}, "SELECT 1")
    assert args == ["-y", "@bytebase/dbhub@1.5.0", "--transport", "stdio"]
    assert env == {"DSN": "postgres://u:p@db:5432/app"}
    assert (tool, call) == ("execute_sql", {"sql": "SELECT 1"})
    args, tool, call, env = _launch("mcp_dbhub", {"dsn": "sqlite:///tmp/a.db", "tool_name": "search_objects",
                                                  "arguments": {"object_type": "table"}}, "")
    assert (tool, call) == ("search_objects", {"object_type": "table"})


def test_third_batch_remote_servers(monkeypatch):
    from tools.mcp import _http

    for name in ("CLOUDFLARE_API_TOKEN", "RENDER_API_KEY", "NEWRELIC_API_KEY", "HONEYCOMB_API_KEY",
                 "MONDAY_API_TOKEN", "JINA_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    calls = []

    async def fake_call(label, url, headers, transport, tool_name, arguments, timeout=30):
        calls.append((url, headers, tool_name, arguments))
        return "ok"

    monkeypatch.setattr(_http, "call_remote", fake_call)
    cloudflare, render, newrelic, honeycomb, monday, jina = (_mod(i) for i in (
        "mcp_cloudflare", "mcp_render", "mcp_newrelic", "mcp_honeycomb", "mcp_monday", "mcp_jina"))

    assert asyncio.run(cloudflare.run("workers", {"cloudflare_api_token": "cf"}, "mcp_cloudflare")) == "ok"
    assert calls[-1] == ("https://mcp.cloudflare.com/mcp", {"Authorization": "Bearer cf"},
                         "docs", {"query": "workers"})
    asyncio.run(cloudflare.run("", {"cloudflare_api_token": "cf"}, "mcp_cloudflare"))
    assert calls[-1][2:] == ("whoami", {})

    assert asyncio.run(render.run("", {"render_api_key": "r"}, "mcp_render")) == "ok"
    assert calls[-1] == ("https://mcp.render.com/mcp", {"Authorization": "Bearer r"}, "list_services", {})
    asyncio.run(render.run("", {"render_api_key": "r", "tool_name": "get_service",
                                "arguments": {"serviceId": "srv-1"}}, "mcp_render"))
    assert calls[-1][2:] == ("get_service", {"serviceId": "srv-1"})

    assert asyncio.run(newrelic.run("SELECT count(*) FROM Transaction",
                                    {"newrelic_api_key": "NRAK-1", "newrelic_account_id": "123"},
                                    "mcp_newrelic")) == "ok"
    assert calls[-1] == ("https://mcp.newrelic.com/mcp/", {"api-key": "NRAK-1"},
                         "execute_nrql_query", {"account_id": "123", "nrql": "SELECT count(*) FROM Transaction"})
    asyncio.run(newrelic.run("", {"newrelic_api_key": "NRAK-1", "newrelic_region": "eu"}, "mcp_newrelic"))
    assert calls[-1][0] == "https://mcp.eu.newrelic.com/mcp/"
    assert calls[-1][2:] == ("list_available_new_relic_accounts", {})

    assert asyncio.run(honeycomb.run("", {"honeycomb_api_key": "kid:secret"}, "mcp_honeycomb")) == "ok"
    assert calls[-1] == ("https://mcp.honeycomb.io/mcp", {"Authorization": "Bearer kid:secret"},
                         "get_workspace_context", {})
    asyncio.run(honeycomb.run("", {"honeycomb_api_key": "k:s", "honeycomb_region": "eu"}, "mcp_honeycomb"))
    assert calls[-1][0] == "https://mcp.eu1.honeycomb.io/mcp"

    assert asyncio.run(monday.run("deals", {"monday_api_token": "m"}, "mcp_monday")) == "ok"
    assert calls[-1] == ("https://mcp.monday.com/mcp", {"Authorization": "Bearer m"},
                         "search", {"searchType": "BOARD", "searchTerm": "deals"})
    asyncio.run(monday.run("", {"monday_api_token": "m"}, "mcp_monday"))
    assert calls[-1][2:] == ("get_user_context", {})

    assert asyncio.run(jina.run("qwen", {"jina_api_key": "j"}, "mcp_jina")) == "ok"
    assert calls[-1] == ("https://mcp.jina.ai/v1", {"Authorization": "Bearer j"},
                         "search_web", {"query": "qwen"})
    asyncio.run(jina.run("https://example.com/a.pdf", {"jina_api_key": "j"}, "mcp_jina"))
    assert calls[-1][2:] == ("read_url", {"url": "https://example.com/a.pdf"})
    asyncio.run(jina.run("", {"jina_api_key": "j"}, "mcp_jina"))
    assert calls[-1][2:] == ("primer", {})

    out = asyncio.run(cloudflare.run("x", {}, "mcp_cloudflare"))
    assert "cloudflare_api_token" in out and len(calls) == 13, "no request without a token"


def test_catalog_registers_third_batch_servers():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() if section["id"] == "mcp_servers"
               for e in section["tools"]}
    for tool_type in ("mcp_redshift", "mcp_dbhub"):
        assert entries[tool_type]["category"] == "Databases & Data"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    for tool_type in ("mcp_cloudflare", "mcp_render"):
        assert entries[tool_type]["category"] == "Developer Tools"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    for tool_type in ("mcp_newrelic", "mcp_honeycomb"):
        assert entries[tool_type]["category"] == "DevOps & Observability"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    assert entries["mcp_monday"]["category"] == "Productivity"
    for tool_type in ("mcp_jina", "mcp_hyperbrowser"):
        assert entries[tool_type]["category"] == "Web & Browser"
        assert entries[tool_type]["type"] == "mcp" and entries[tool_type]["is_new"]
    assert entries["mcp_e2b"]["category"] == "AI & Memory"
    for tool_type in ("mcp_cloudflare", "mcp_render", "mcp_newrelic", "mcp_honeycomb", "mcp_monday", "mcp_jina"):
        assert entries[tool_type]["default_config"]["transport"] == "http"
    assert entries["mcp_newrelic"]["config_options"]["newrelic_region"]["options"][1]["value"] == "eu"
    assert entries["mcp_honeycomb"]["config_options"]["honeycomb_region"]["options"][1]["value"] == "eu"
    assert entries["mcp_redshift"]["required_config"] == ["aws_region"]
    assert entries["mcp_dbhub"]["required_config"] == ["dsn"]


# ── Batch of 2026-11-04 (tool names and env vars checked against each package's source / tools/list) ──
@pytest.mark.parametrize("tool_id,config,input,env,tool,call", [
    ("mcp_circleci", {"circleci_token": "cc"}, "", {"CIRCLECI_TOKEN": "cc", "DISABLE_TELEMETRY": "true"},
     "list_followed_projects", {}),
    ("mcp_mapbox", {"mapbox_access_token": "pk.1"}, "Eiffel Tower", {"MAPBOX_ACCESS_TOKEN": "pk.1"},
     "search_and_geocode_tool", {"q": "Eiffel Tower"}),
    ("mcp_shopify_dev", {}, "metafields on orders", {}, "search_docs_chunks", {"prompt": "metafields on orders"}),
    ("mcp_duckduckgo", {}, "rent law", {"DDG_SAFE_SEARCH": "MODERATE"}, "search", {"query": "rent law"}),
    ("mcp_duckduckgo", {"safe_search": "off", "region": "de-de"}, "https://example.com",
     {"DDG_SAFE_SEARCH": "OFF", "DDG_REGION": "de-de"}, "fetch_content", {"url": "https://example.com"}),
    ("mcp_arxiv", {}, "diffusion transformers", {}, "search_papers", {"query": "diffusion transformers"}),
    ("mcp_arxiv", {}, "arXiv:2401.12345v2", {}, "get_abstract", {"paper_id": "2401.12345v2"}),
    ("mcp_arxiv", {}, "hep-th/9901001", {}, "get_abstract", {"paper_id": "hep-th/9901001"}),
])
def test_new_server_config(tool_id, config, input, env, tool, call, monkeypatch):
    for name in ("CIRCLECI_BASE_URL", "MAPBOX_ACCESS_TOKEN", "CIRCLECI_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    _, got_tool, got_call, got_env = _launch(tool_id, config, input)
    assert (got_tool, got_call) == (tool, call)
    assert {k: v for k, v in got_env.items() if v} == env


def test_elevenlabs_writes_audio_outside_the_home_desktop(monkeypatch):
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    _, tool, call, env = _launch("mcp_elevenlabs", {"elevenlabs_api_key": "xi"}, "Hello there")
    assert (tool, call) == ("text_to_speech", {"text": "Hello there"})
    assert env["ELEVENLABS_API_KEY"] == "xi" and "Desktop" not in env["ELEVENLABS_MCP_BASE_PATH"]
    _, tool, call, env = _launch("mcp_elevenlabs", {"elevenlabs_api_key": "xi", "output_dir": "/data/audio",
                                                   "default_voice_id": "v1"})
    assert (tool, call) == ("search_voices", {}), "no input lists the voices"
    assert env["ELEVENLABS_MCP_BASE_PATH"] == "/data/audio" and env["ELEVENLABS_DEFAULT_VOICE_ID"] == "v1"
    args = _launch("mcp_arxiv", {"storage_path": "/data/papers"}, "x")[0]
    assert args[-2:] == ["--storage-path", "/data/papers"]


def test_keyless_remote_servers():
    learn = _mod("mcp_microsoft_learn")
    d = {"default_tool": learn.DEFAULT_TOOL}
    assert learn.prepare({}, "azure functions python", d) == (learn.URL, {}, "microsoft_docs_search",
                                                              {"query": "azure functions python"})
    assert learn.prepare({}, "https://learn.microsoft.com/x", d)[2:] == ("microsoft_docs_fetch",
                                                                         {"url": "https://learn.microsoft.com/x"})
    wiki = _mod("mcp_deepwiki")
    d = {"default_tool": wiki.DEFAULT_TOOL}
    assert wiki.prepare({}, "facebook/react: how does reconciliation work?", d)[2:] == (
        "ask_wiki_question", {"repoName": "facebook/react", "question": "how does reconciliation work?"})
    assert wiki.prepare({}, "facebook/react", d)[2:] == ("read_wiki_structure", {"repoName": "facebook/react"})
    assert wiki.prepare({"repo_name": "vercel/next.js"}, "what is ISR?", d)[2:] == (
        "ask_wiki_question", {"repoName": "vercel/next.js", "question": "what is ISR?"})
    for mod in (learn, wiki):
        assert not mod.TOOL.required and mod.TOOL.default_config["url"] == mod.URL


def test_the_catalog_registers_the_new_batch():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() for e in section["tools"]}
    for tool_id, category in (("mcp_microsoft_learn", "Developer Tools"), ("mcp_deepwiki", "Developer Tools"),
                              ("mcp_shopify_dev", "Developer Tools"), ("mcp_circleci", "DevOps & Observability"),
                              ("mcp_mapbox", "Web & Browser"), ("mcp_duckduckgo", "Web & Browser"),
                              ("mcp_arxiv", "Web & Browser"), ("mcp_elevenlabs", "AI & Memory")):
        assert entries[tool_id]["category"] == category and entries[tool_id]["type"] == "mcp"
    assert entries["mcp_circleci"]["required_config"] == ["circleci_token"]
    for tool_id in ("semantic_scholar_search", "crossref_search", "sec_edgar_filings", "gitlab_api", "sentry_issues",
                    "prometheus_query", "clickup", "cron_helper", "xml_converter", "pushover_notify"):
        assert entries[tool_id]["type"] == "tool" and entries[tool_id]["parameters"]


# ── Batch 2 of 2026-11-04 ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tool_id,config,input,env,tool,call", [
    ("mcp_kagi", {"kagi_api_key": "k1"}, "rust async", {"KAGI_API_KEY": "k1"}, "kagi_search_fetch", {"query": "rust async"}),
    ("mcp_kagi", {"kagi_api_key": "k1"}, "https://example.com/post", {"KAGI_API_KEY": "k1"}, "kagi_extract",
     {"url": "https://example.com/post"}),
    ("mcp_wikipedia", {}, "Ada Lovelace", {}, "search_wikipedia", {"query": "Ada Lovelace"}),
    ("mcp_upstash", {"upstash_email": "a@x.com", "upstash_api_key": "u1"}, "",
     {"UPSTASH_EMAIL": "a@x.com", "UPSTASH_API_KEY": "u1"}, "redis_database_list_databases", {}),
    ("mcp_chart", {}, '[{"time": "2025", "value": 3}]', {}, "generate_line_chart", {"data": [{"time": "2025", "value": 3}]}),
    ("mcp_chart", {"chart_type": "pie"}, '{"data": [{"category": "a", "value": 1}], "title": "Mix"}', {},
     "generate_pie_chart", {"data": [{"category": "a", "value": 1}], "title": "Mix"}),
    ("mcp_chart", {}, "not json", {}, "generate_line_chart", {"data": []}),
])
def test_batch2_server_config(tool_id, config, input, env, tool, call, monkeypatch):
    for name in ("KAGI_API_KEY", "UPSTASH_EMAIL", "UPSTASH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    _, got_tool, got_call, got_env = _launch(tool_id, config, input)
    assert (got_tool, got_call) == (tool, call)
    assert {k: v for k, v in got_env.items() if v} == env


def test_launch_args_keep_secrets_off_the_command_line(monkeypatch):
    import base64
    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    args, tool, call, env = _launch("mcp_azure_devops", {"organization": "contoso", "azure_devops_pat": "p@t"})
    assert args == ["-y", "@azure-devops/mcp@2.10.0", "contoso", "--authentication", "pat", "--domains", "all"]
    assert base64.b64decode(env["PERSONAL_ACCESS_TOKEN"]).decode().split(":", 1)[1] == "p@t", \
        "the server takes base64(user:pat) and keeps what follows the first colon"
    assert (tool, call) == ("core_list_projects", {})
    args = _launch("mcp_azure_devops", {"organization": "contoso", "azure_devops_pat": "p", "domains": "core repositories"})[0]
    assert args[-3:] == ["--domains", "core", "repositories"]
    args, _, _, env = _launch("mcp_upstash", {"upstash_email": "a@x.com", "upstash_api_key": "secret-key"})
    assert "secret-key" not in " ".join(args) and args[-1] == "--disable-telemetry"
    assert _launch("mcp_wikipedia", {"language": "de"}, "x")[0][-2:] == ["--language", "de"]


def test_aws_knowledge_remote_server():
    mod = _mod("mcp_aws_knowledge")
    d = {"default_tool": mod.DEFAULT_TOOL}
    assert mod.prepare({}, "lambda timeout", d)[2:] == ("aws___search_documentation", {"search_phrase": "lambda timeout"})
    assert mod.prepare({}, "https://docs.aws.amazon.com/x", d)[2:] == ("aws___read_documentation",
                                                                       {"requests": [{"url": "https://docs.aws.amazon.com/x"}]})
    assert mod.prepare({}, "", d)[2:] == ("aws___list_regions", {})
    assert not mod.TOOL.required


def test_the_catalog_registers_batch2():
    tools._load()
    entries = {e["id"]: e for section in tools.catalog() for e in section["tools"]}
    for tool_id, category in (("mcp_aws_knowledge", "Developer Tools"), ("mcp_azure_devops", "Developer Tools"),
                              ("mcp_kagi", "Web & Browser"), ("mcp_wikipedia", "Web & Browser"),
                              ("mcp_upstash", "Databases & Data"), ("mcp_chart", "AI & Memory")):
        assert entries[tool_id]["category"] == category and entries[tool_id]["type"] == "mcp"
    for tool_id in ("bluesky_post", "mastodon_post", "jenkins", "ssl_certificate_check", "world_bank_indicators",
                    "wikidata_query", "freshdesk", "jwt_decoder", "csv_sql"):
        assert entries[tool_id]["type"] == "tool" and entries[tool_id]["parameters"]
