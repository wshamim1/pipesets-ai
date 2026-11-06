"""Argo CD, PagerDuty, CloudWatch and dbt MCP servers (2026-11-04): node config → launch args, env vars
and the default tool call, read-only by default, pinned versions, catalog registration. Tool and env
names checked against each package's source (argocd-mcp 0.9.0, pagerduty-mcp 1.1.0,
awslabs.cloudwatch-mcp-server 0.3.1, dbt-mcp 2.10.1), not launched."""
import importlib

import pytest

import tools


def launch(module, config, input=""):
    mod = importlib.import_module(module)
    env = {}
    args, name, call = mod.prepare(config, input, list(mod.ARGS), env, {"default_tool": mod.DEFAULT_TOOL})
    return args, name, call, env


def test_argocd_is_read_only_unless_switched_off():
    cfg = {"argocd_base_url": "https://argocd.example", "argocd_api_token": "tok"}
    args, name, call, env = launch("tools.mcp.developer.mcp_argocd", cfg, "payments")
    assert args == ["-y", "argocd-mcp@0.9.0", "stdio"]
    assert env == {"ARGOCD_BASE_URL": "https://argocd.example", "ARGOCD_API_TOKEN": "tok", "MCP_READ_ONLY": "true"}
    assert name == "list_applications" and call == {"search": "payments"}
    _, _, call, env = launch("tools.mcp.developer.mcp_argocd", {**cfg, "read_only": "off"})
    assert "MCP_READ_ONLY" not in env and call == {}
    _, name, call, _ = launch("tools.mcp.developer.mcp_argocd", {**cfg, "tool_name": "get_application",
                                                                  "arguments": {"applicationName": "web"}}, "x")
    assert name == "get_application" and call == {"applicationName": "web"}


def test_pagerduty_write_tools_are_opt_in():
    args, name, call, env = launch("tools.mcp.developer.mcp_pagerduty", {"pagerduty_user_api_key": "pd"})
    assert args == ["--from", "pagerduty-mcp@1.1.0", "--python", "3.12", "pagerduty-mcp"] and env == {"PAGERDUTY_USER_API_KEY": "pd"}
    assert name == "list_incidents" and call == {"request_scope": "all", "statuses": ["triggered", "acknowledged"]}
    args, _, _, env = launch("tools.mcp.developer.mcp_pagerduty", {"pagerduty_user_api_key": "pd", "write_tools": "on",
                                                                    "api_host": "https://api.eu.pagerduty.com"})
    assert args[-1] == "--enable-write-tools" and env["PAGERDUTY_API_HOST"] == "https://api.eu.pagerduty.com"


def test_cloudwatch_passes_aws_credentials():
    args, name, call, env = launch("tools.mcp.developer.mcp_cloudwatch", {
        "aws_region": "eu-west-1", "aws_access_key_id": "AKIA", "aws_secret_access_key": "s"})
    assert args == ["--from", "awslabs.cloudwatch-mcp-server@0.3.1", "awslabs.cloudwatch-mcp-server"]
    assert env == {"AWS_REGION": "eu-west-1", "AWS_ACCESS_KEY_ID": "AKIA", "AWS_SECRET_ACCESS_KEY": "s",
                   "FASTMCP_LOG_LEVEL": "ERROR"}
    assert name == "get_active_alarms" and call == {}


def test_dbt_switches_off_local_toolsets_and_writes():
    args, name, call, env = launch("tools.mcp.databases.mcp_dbt", {
        "dbt_host": "ab123.us1.dbt.com", "dbt_token": "dbtu_x", "dbt_account_id": "42", "dbt_prod_env_id": "7"})
    assert args == ["dbt-mcp@2.10.1"] and name == "list_jobs" and call == {}
    assert env["DBT_HOST"] == "ab123.us1.dbt.com" and env["DBT_TOKEN"] == "dbtu_x"
    assert env["DBT_ACCOUNT_ID"] == "42" and env["DBT_PROD_ENV_ID"] == "7"
    assert env["DISABLE_DBT_CLI"] == env["DISABLE_LSP"] == env["DISABLE_DBT_CODEGEN"] == "true"
    assert env["DISABLE_TOOLS"] == "trigger_job_run,cancel_job_run,retry_job_run"
    _, _, _, env = launch("tools.mcp.databases.mcp_dbt", {"dbt_token": "t", "dbt_account_id": "1", "read_only": "off"})
    assert "DISABLE_TOOLS" not in env


@pytest.mark.parametrize("tool_id,category,required", [
    ("mcp_argocd", "DevOps & Observability", ["argocd_base_url", "argocd_api_token"]),
    ("mcp_pagerduty", "DevOps & Observability", ["pagerduty_user_api_key"]),
    ("mcp_cloudwatch", "DevOps & Observability", ["aws_region"]),
    ("mcp_dbt", "Databases & Data", ["dbt_token", "dbt_account_id"]),
])
def test_catalog_registers_them(tool_id, category, required):
    tools._load()
    entry = next(t for s in tools.catalog() if s["id"] == "mcp_servers" for t in s["tools"] if t["id"] == tool_id)
    assert entry["category"] == category and entry["type"] == "mcp" and entry["required_config"] == required
    assert any("@" in a for a in entry["default_config"]["args"]), "the package version is pinned"


def test_missing_key_is_named_before_anything_starts():
    import asyncio
    out = asyncio.run(tools.execute("mcp_pagerduty", "", {}, None))
    assert "pagerduty_user_api_key" in out
