"""
Shared helper utilities used by all framework exporters.
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from db import get_db_connection

# ── MCP tool IDs that delegate credentials to a connected Connection node ─────
MCP_DB_TOOLS = {"mcp_postgres", "mcp_database"}

# ── Tools that use stdio MCP servers (npx / uvx) ─────────────────────────────
MCP_STDIO_TOOLS = {
    "mcp_filesystem", "mcp_github", "mcp_brave_search",
    "mcp_puppeteer", "mcp_slack", "mcp_google_maps",
    "mcp_aws_kb", "mcp_everything",
}


def load_app(app_id: str, tenant_id: str, project_id: str) -> Dict[str, Any]:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM apps WHERE id = ? AND tenant_id = ? AND project_id = ?",
                           (app_id, tenant_id, project_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"App '{app_id}' not found")
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "flow_data": json.loads(row["flow_data"] or "{}"),
        "docs": row["docs"] if "docs" in row.keys() else "",
    }


def nodes_by_type(flow_data: Dict[str, Any]) -> Dict[str, List[Dict]]:
    buckets: Dict[str, List[Dict]] = {
        "llm": [], "tool": [], "toolkit": [], "memory": [], "cache": [],
        "connection": [], "knowledge_base": [], "retriever": [], "skill": [],
        "embedding": [], "vector_store": [], "doc_loader": [],
        "text_splitter": [], "master_agent": [], "child_agent": [],
    }
    for node in flow_data.get("nodes", []):
        t = node.get("type", "")
        if t in buckets:
            buckets[t].append(node)
    return buckets


def edge_map(flow_data: Dict[str, Any]) -> Dict[str, List[str]]:
    """Returns node_id → [list of neighbour node_ids]."""
    adj: Dict[str, List[str]] = {}
    for edge in flow_data.get("edges", []):
        src, tgt = edge.get("source", ""), edge.get("target", "")
        adj.setdefault(src, []).append(tgt)
        adj.setdefault(tgt, []).append(src)
    return adj


def find_connection_for_tool(
    tool_node: Dict,
    nodes: Dict[str, List[Dict]],
    adj: Dict[str, List[str]],
) -> Optional[Dict]:
    """Return the Connection node linked to *tool_node* via an edge, if any."""
    conn_ids = {n["id"]: n for n in nodes["connection"]}
    for neighbour_id in adj.get(tool_node["id"], []):
        if neighbour_id in conn_ids:
            return conn_ids[neighbour_id]
    return None


def safe_fn(name: str) -> str:
    """Sanitise a tool id/label into a valid Python identifier."""
    import re
    s = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    return s if s[0].isalpha() or s[0] == "_" else f"tool_{s}"


def safe_class(name: str) -> str:
    return "".join(w.capitalize() for w in safe_fn(name).split("_")) + "Tool"


def provider_env_var(provider: str) -> str:
    mapping = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "typesafe": "TYPESAFE_API_KEY",
        "jev": "TYPESAFE_API_KEY",
        "groq": "GROQ_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "cohere": "COHERE_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "bedrock": "AWS_ACCESS_KEY_ID",
        "azure": "AZURE_OPENAI_API_KEY",
        "huggingface": "HUGGINGFACE_API_KEY",
        "nvidia": "NVIDIA_NIM_API_KEY",
        "watsonx": "WATSONX_APIKEY",
    }
    return mapping.get(provider, "OPENAI_API_KEY")


def collect_env_vars(
    provider: str,
    nodes: Dict[str, List[Dict]],
    adj: Dict[str, List[str]],
) -> Dict[str, str]:
    """Return {ENV_VAR: "description"} for the .env / os.environ section."""
    env: Dict[str, str] = {}
    env_key = provider_env_var(provider)
    env[env_key] = f"{provider.title()} API key"
    if provider == "azure":
        env["AZURE_API_BASE"] = "Azure OpenAI endpoint URL"

    for node in nodes["tool"]:
        d   = node.get("data", {})
        tid = d.get("toolId", "")
        fn  = safe_fn(d.get("toolId", "tool"))

        conn_node = find_connection_for_tool(node, nodes, adj)
        conn_data = conn_node.get("data", {}) if conn_node else {}
        conn_cfg  = conn_data.get("config", {})
        conn_type = conn_data.get("connection_type", conn_data.get("type", "")).lower()

        if tid in MCP_DB_TOOLS:
            if conn_type in ("postgres", "postgresql"):
                env[f"DB_{fn.upper()}_PASSWORD"] = f"PostgreSQL password for {d.get('label', tid)}"
            elif conn_type in ("mysql", "mariadb"):
                env[f"DB_{fn.upper()}_PASSWORD"] = f"MySQL password for {d.get('label', tid)}"
            elif conn_type == "snowflake":
                env[f"SNOWFLAKE_{fn.upper()}_PASSWORD"] = f"Snowflake password for {d.get('label', tid)}"

        cfg = d.get("config", {})
        if tid == "web_search" and not cfg.get("api_key"):
            env["TAVILY_API_KEY"] = "Tavily API key (optional — falls back to DuckDuckGo)"
        if tid == "tavily_search" and not cfg.get("api_key"):
            env["TAVILY_API_KEY"] = "Tavily API key"
        if tid == "email_sender":
            env["SMTP_PASSWORD"] = "SMTP password"
        if tid == "key_value_store":
            env["KV_STORE_PATH"] = "SQLite file for the key-value store (optional, default pipesets_store.db)"
            if cfg.get("scope", "user") != "project":
                env["KV_STORE_USER"] = "Whose entries the key-value store reads and writes (optional, default local)"
        if tid == "slack_webhook" and not cfg.get("webhook_url"):
            env["SLACK_WEBHOOK_URL"] = "Slack incoming webhook URL"
        if tid == "s3_reader":
            env["AWS_ACCESS_KEY_ID"] = "AWS access key ID"
            env["AWS_SECRET_ACCESS_KEY"] = "AWS secret access key"
        if tid in MCP_STDIO_TOOLS:
            for k in cfg.get("env_vars", {}):
                env[k] = f"Required by {d.get('label', tid)}"

    return env


def pip_packages(
    provider: str,
    nodes: Dict[str, List[Dict]],
    framework: str,
) -> List[str]:
    """Return the pip install line packages for the generated script."""
    pkgs = {
        "langchain": ["langchain"],
        "crewai": ["crewai"],
        "autogen": ["pyautogen"],
    }.get(framework, [])

    if provider == "openai":
        pkgs.append("langchain-openai" if framework == "langchain" else "openai")
    elif provider == "anthropic":
        pkgs.append("langchain-anthropic" if framework == "langchain" else "anthropic")
    elif provider == "ollama":
        pkgs.append("langchain-ollama" if framework == "langchain" else "ollama")
    elif provider == "groq":
        pkgs.append("langchain-groq" if framework == "langchain" else "groq")
    else:
        pkgs.append("langchain-openai" if framework == "langchain" else "openai")

    for node in nodes["tool"]:
        d   = node.get("data", {})
        tid = d.get("toolId", "")
        if tid in MCP_DB_TOOLS:
            conn = nodes["connection"][0] if nodes["connection"] else None
            ct   = (conn.get("data", {}).get("connection_type", "postgres") if conn else "postgres").lower()
            if ct in ("postgres", "postgresql"):
                pkgs.append("psycopg2-binary")
            elif ct in ("mysql", "mariadb"):
                pkgs.append("pymysql")
            elif ct == "snowflake":
                pkgs.append("snowflake-connector-python")
        if tid == "sql_database":
            pkgs.append("psycopg2-binary")
        if tid in ("web_search", "duckduckgo_search", "tavily_search"):
            pkgs += ["httpx", "ddgs"]
        if tid in ("rest_api_caller", "slack_webhook"):
            pkgs.append("httpx")
        if tid == "s3_reader":
            pkgs.append("boto3")

    if nodes["retriever"] or nodes["knowledge_base"]:
        pkgs += ["langchain-community", "chromadb"]

    for node in nodes["embedding"]:
        ep = node.get("data", {}).get("provider", "openai")
        if ep == "openai":
            pkgs.append("langchain-openai")
        elif ep == "local":
            pkgs += ["sentence-transformers", "langchain-huggingface"]
        elif ep == "cohere":
            pkgs += ["cohere", "langchain-cohere"]
        elif ep == "google":
            pkgs += ["google-generativeai", "langchain-google-genai"]
        elif ep == "azure_openai":
            pkgs.append("langchain-openai")
        elif ep == "mistral":
            pkgs += ["mistralai", "langchain-mistralai"]
        elif ep == "ollama":
            pkgs.append("langchain-ollama")
        elif ep == "llamacpp":
            pkgs.append("langchain-openai")
        elif ep == "bedrock":
            pkgs += ["boto3", "langchain-aws"]
        elif ep in ("voyage", "anthropic"):
            pkgs += ["voyageai", "langchain-voyageai"]
        elif ep == "nomic":
            pkgs += ["nomic", "langchain-nomic"]

    for node in nodes["vector_store"]:
        st = node.get("data", {}).get("store_type", "chroma")
        if st == "pgvector":
            pkgs.append("psycopg2-binary")
        elif st == "pinecone":
            pkgs += ["pinecone-client", "langchain-pinecone"]
        elif st == "weaviate":
            pkgs += ["weaviate-client", "langchain-weaviate"]
        elif st == "qdrant":
            pkgs += ["qdrant-client", "langchain-qdrant"]
        elif st == "milvus":
            pkgs += ["pymilvus", "langchain-milvus"]
        elif st == "elasticsearch":
            pkgs += ["elasticsearch", "langchain-elasticsearch"]
        elif st == "mongodb_atlas":
            pkgs += ["pymongo", "langchain-mongodb"]
        elif st == "opensearch":
            pkgs += ["opensearch-py", "langchain-community"]
        elif st == "redis":
            pkgs += ["redis", "langchain-redis"]
        elif st == "faiss":
            pkgs += ["faiss-cpu"]
        elif st == "azure_ai_search":
            pkgs += ["azure-search-documents", "langchain-community"]
        elif st == "vertex_ai":
            pkgs += ["google-cloud-aiplatform", "langchain-google-vertexai"]
        elif st == "lancedb":
            pkgs += ["lancedb", "langchain-community"]

    return sorted(set(pkgs))
