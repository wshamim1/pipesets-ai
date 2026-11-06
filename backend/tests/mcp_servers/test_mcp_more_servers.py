"""Mailgun, Contentful, AWS Cost Explorer and GitMCP MCP servers (2026-11-05): node config → launch args, env
vars and the default tool call, pinned versions, catalog registration. Tool and env names checked against
each package's source (@mailgun/mcp-server 2.1.3, @contentful/mcp-server 1.24.4 with @contentful/mcp-tools
0.12.60, awslabs.cost-explorer-mcp-server 0.0.21), not launched; GitMCP's tools from a live tools/list."""
import importlib
from datetime import date

import pytest

import tools


def launch(module, config, input=""):
    mod = importlib.import_module(module)
    env = {}
    args, name, call = mod.prepare(config, input, list(mod.ARGS), env, {"default_tool": mod.DEFAULT_TOOL})
    return args, name, call, env


def remote(module, config, input=""):
    mod = importlib.import_module(module)
    return mod.prepare(config, input, {"default_tool": mod.DEFAULT_TOOL})


def test_mailgun_key_region_and_tags():
    args, name, call, env = launch("tools.mcp.productivity.mcp_mailgun", {"mailgun_api_key": "key-1"})
    assert args == ["-y", "@mailgun/mcp-server@2.1.3"] and env == {"MAILGUN_API_KEY": "key-1", "MAILGUN_API_REGION": "us"}
    assert name == "get-v4-domains" and call == {}
    args, name, call, env = launch("tools.mcp.productivity.mcp_mailgun",
                                   {"mailgun_api_key": "k", "region": "eu", "tags": "validate"}, "mg.example.com")
    assert args[-2:] == ["--tags", "validate"] and env["MAILGUN_API_REGION"] == "eu"
    assert name == "get_metrics_summary" and call == {"domain": "mg.example.com"}


def test_contentful_passes_space_and_searches():
    cfg = {"contentful_management_access_token": "CFPAT-x", "space_id": "sp1"}
    args, name, call, env = launch("tools.mcp.productivity.mcp_contentful", cfg)
    assert args == ["-y", "@contentful/mcp-server@1.24.4"]
    assert env == {"CONTENTFUL_MANAGEMENT_ACCESS_TOKEN": "CFPAT-x", "SPACE_ID": "sp1", "ENVIRONMENT_ID": "master",
                   "CONTENTFUL_HOST": "api.contentful.com"}
    assert name == "list_content_types" and call == {"spaceId": "sp1", "environmentId": "master"}
    _, name, call, _ = launch("tools.mcp.productivity.mcp_contentful", {**cfg, "environment_id": "staging"}, "pricing page")
    assert name == "search_entries" and call == {"spaceId": "sp1", "environmentId": "staging",
                                                 "query": {"query": "pricing page", "limit": 10}}


def test_cost_explorer_reads_month_to_date_by_service():
    from tools.mcp.developer.mcp_cost_explorer import month_to_date
    args, name, call, env = launch("tools.mcp.developer.mcp_cost_explorer", {
        "aws_region": "us-east-1", "aws_access_key_id": "AKIA", "aws_secret_access_key": "s"})
    assert args == ["--from", "awslabs.cost-explorer-mcp-server@0.0.21", "awslabs.cost-explorer-mcp-server"]
    assert env == {"AWS_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "AKIA", "AWS_SECRET_ACCESS_KEY": "s", "FASTMCP_LOG_LEVEL": "ERROR"}
    assert name == "get_cost_and_usage" and call["granularity"] == "MONTHLY" and call["group_by"] == "SERVICE"
    assert month_to_date(date(2026, 11, 5)) == {"start_date": "2026-11-01", "end_date": "2026-11-05"}
    assert month_to_date(date(2026, 3, 1)) == {"start_date": "2026-02-01", "end_date": "2026-03-01"}, "the 1st reads last month"
    _, name, call, _ = launch("tools.mcp.developer.mcp_cost_explorer", {"aws_region": "x", "tool_name": "get_today_date"})
    assert name == "get_today_date" and call == {}


def test_gitmcp_routes_the_input():
    m = "tools.mcp.developer.mcp_gitmcp"
    url, headers, name, call = remote(m, {}, "pydantic/pydantic: how do validators work?")
    assert url == "https://gitmcp.io/docs" and headers == {}
    assert name == "search_generic_documentation" and call == {"owner": "pydantic", "repo": "pydantic", "query": "how do validators work?"}
    assert remote(m, {}, "https://github.com/vercel/next.js")[2:] == ("fetch_generic_documentation", {"owner": "vercel", "repo": "next.js"})
    assert remote(m, {}, "https://example.com/llms.txt")[2:] == ("fetch_generic_url_content", {"url": "https://example.com/llms.txt"})
    assert remote(m, {}, "fastapi")[2:] == ("match_common_libs_owner_repo_mapping", {"library": "fastapi"})
    assert remote(m, {"repo_name": "tiangolo/fastapi"}, "dependencies")[3] == {"owner": "tiangolo", "repo": "fastapi", "query": "dependencies"}


@pytest.mark.parametrize("tool_id,category,required", [
    ("mcp_mailgun", "Productivity", ["mailgun_api_key"]),
    ("mcp_contentful", "Productivity", ["contentful_management_access_token", "space_id"]),
    ("mcp_cost_explorer", "DevOps & Observability", ["aws_region"]),
    ("mcp_gitmcp", "Developer Tools", None),
])
def test_catalog_registers_them(tool_id, category, required):
    tools._load()
    entry = next(t for s in tools.catalog() if s["id"] == "mcp_servers" for t in s["tools"] if t["id"] == tool_id)
    assert entry["category"] == category and entry["type"] == "mcp" and entry.get("required_config") == required
    if "args" in entry["default_config"]:
        assert any("@" in a for a in entry["default_config"]["args"]), "the package version is pinned"


def test_missing_key_is_named_before_anything_starts():
    import asyncio
    out = asyncio.run(tools.execute("mcp_mailgun", "", {}, None))
    assert "mailgun_api_key" in out
