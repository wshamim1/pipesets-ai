"""LangChain exporter — generates a ready-to-run LangChain agent script."""

import json
import textwrap
from typing import Any, Dict, List

from exporters.helpers import (
    nodes_by_type, edge_map, find_connection_for_tool,
    safe_fn, provider_env_var, collect_env_vars, pip_packages,
)
from exporters.tool_bodies import tool_body_langchain


def to_langchain(app: Dict) -> str:
    flow       = app["flow_data"]
    nodes      = nodes_by_type(flow)
    adj        = edge_map(flow)
    app_name   = app["name"]
    app_desc   = app.get("description", "")

    # ── LLM config ────────────────────────────────────────────────────────────
    llm_cfg       = nodes["llm"][0].get("data", {}) if nodes["llm"] else {}
    provider      = llm_cfg.get("provider", "openai")
    model         = llm_cfg.get("model", "gpt-4o")
    temperature   = llm_cfg.get("temperature", 0.7)
    max_tokens    = llm_cfg.get("max_tokens", 1024)
    system_prompt = llm_cfg.get("system_prompt", "You are a helpful assistant.")
    api_key_val   = llm_cfg.get("api_key", "")
    env_key       = provider_env_var(provider)

    if provider == "anthropic":
        llm_import = "from langchain_anthropic import ChatAnthropic"
        llm_init   = f'ChatAnthropic(model="{model}", temperature={temperature}, max_tokens={max_tokens})'
    elif provider == "ollama":
        llm_import = "from langchain_ollama import ChatOllama"
        llm_init   = f'ChatOllama(model="{model}", temperature={temperature})'
    elif provider == "llamacpp":
        llm_import = "from langchain_openai import ChatOpenAI"
        llm_init   = f'ChatOpenAI(model="{model}", base_url="http://localhost:8080/v1", api_key="sk-no-key", temperature={temperature}, max_tokens={max_tokens})'
    elif provider == "jan":
        llm_import = "from langchain_openai import ChatOpenAI"
        llm_init   = f'ChatOpenAI(model="{model}", base_url="http://127.0.0.1:1337/v1", api_key=os.environ.get("JAN_API_KEY", "jan-local"), temperature={temperature}, max_tokens={max_tokens})'
    elif provider == "groq":
        llm_import = "from langchain_groq import ChatGroq"
        llm_init   = f'ChatGroq(model="{model}", temperature={temperature}, max_tokens={max_tokens})'
    else:
        llm_import = "from langchain_openai import ChatOpenAI"
        llm_init   = f'ChatOpenAI(model="{model}", temperature={temperature}, max_tokens={max_tokens})'

    # ── Tools ─────────────────────────────────────────────────────────────────
    tool_blocks: List[str] = []
    tool_fn_names: List[str] = []

    for node in nodes["tool"]:
        d    = node.get("data", {})
        tid  = d.get("toolId", "custom_tool")
        fn   = safe_fn(tid)
        desc = d.get("description", f"Tool: {d.get('label', tid)}")
        cfg  = d.get("config", {})
        conn = find_connection_for_tool(node, nodes, adj)
        tool_blocks.append(tool_body_langchain(fn, tid, desc, cfg, conn))
        tool_fn_names.append(fn)

    for node in nodes["toolkit"]:
        for sub in node.get("data", {}).get("subTools", []):
            tid  = sub.get("toolId", "sub_tool")
            fn   = safe_fn(tid)
            desc = sub.get("description", f"Tool: {sub.get('label', tid)}")
            cfg  = sub.get("config", {})
            tool_blocks.append(tool_body_langchain(fn, tid, desc, cfg, None))
            tool_fn_names.append(fn)

    if nodes["retriever"]:
        r       = nodes["retriever"][0].get("data", {})
        coll    = r.get("collection_name", "default_collection")
        top_k   = r.get("top_k", 4)
        emb_key = r.get("embedding_api_key", "")
        tool_blocks.append(textwrap.dedent(f'''\
            @tool
            def rag_retriever(query: str) -> str:
                """Retrieves relevant document chunks from the knowledge base for the given query."""
                import os
                from langchain_openai import OpenAIEmbeddings
                from langchain_community.vectorstores import Chroma
                embeddings = OpenAIEmbeddings(
                    api_key=os.environ.get("OPENAI_API_KEY", {json.dumps(emb_key)})
                )
                db = Chroma(collection_name={json.dumps(coll)}, embedding_function=embeddings)
                docs = db.similarity_search(query, k={top_k})
                return "\\n\\n".join(d.page_content for d in docs)

        '''))
        tool_fn_names.append("rag_retriever")

    tools_list = f"[{', '.join(tool_fn_names)}]" if tool_fn_names else "[]"

    # ── Memory ────────────────────────────────────────────────────────────────
    mem_cfg      = nodes["memory"][0].get("data", {}) if nodes["memory"] else {}
    use_memory   = bool(mem_cfg)
    mem_strategy = mem_cfg.get("strategy", "sliding_window")
    token_budget = mem_cfg.get("token_budget", 4096)

    memory_import = ""
    memory_init   = ""
    if use_memory:
        if mem_strategy == "summarize":
            memory_import = "from langchain.memory import ConversationSummaryBufferMemory"
            memory_init   = textwrap.dedent(f"""\
                memory = ConversationSummaryBufferMemory(
                    llm=llm,
                    max_token_limit={token_budget},
                    return_messages=True,
                    memory_key="chat_history",
                )""")
        else:
            k = max(1, token_budget // 512)
            memory_import = "from langchain.memory import ConversationBufferWindowMemory"
            memory_init   = textwrap.dedent(f"""\
                memory = ConversationBufferWindowMemory(
                    k={k},
                    return_messages=True,
                    memory_key="chat_history",
                )""")

    # ── Env vars & pip ────────────────────────────────────────────────────────
    env_vars = collect_env_vars(provider, nodes, adj)
    pip_pkgs = pip_packages(provider, nodes, "langchain")
    if use_memory:
        pip_pkgs.append("langchain")
    pip_line = f"# pip install {' '.join(sorted(set(pip_pkgs)))}"

    lines = [
        '"""',
        f"  {app_name}",
        f"  {app_desc}",
        "  Generated by Pipesets AI",
        "",
        f"  {pip_line}",
        "",
        "  Environment variables (set in your shell or a .env file):",
        *[f"    {k}=...  # {v}" for k, v in env_vars.items()],
        '"""',
        "",
        "import os",
        llm_import,
        *(["from langchain_community.vectorstores import Chroma"] if nodes["retriever"] else []),
        *([memory_import] if memory_import else []),
        "from langchain.tools import tool",
        "from langchain.agents import AgentExecutor, create_openai_tools_agent",
        "from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder",
        "",
        "# ── LLM ──────────────────────────────────────────────────────────────────────",
        f"os.environ.setdefault({json.dumps(env_key)}, {json.dumps(api_key_val)})",
        f"llm = {llm_init}",
        "",
        "# ── Tools ────────────────────────────────────────────────────────────────────",
        *[line for block in tool_blocks for line in block.splitlines()],
        f"tools = {tools_list}",
        "",
    ]

    if use_memory:
        lines += [
            "# ── Memory ───────────────────────────────────────────────────────────────────",
            *memory_init.splitlines(),
            "",
        ]

    lines += [
        "# ── Agent ────────────────────────────────────────────────────────────────────",
        "prompt = ChatPromptTemplate.from_messages([",
        f'    ("system", """{system_prompt}"""),',
        '    MessagesPlaceholder("chat_history", optional=True),',
        '    ("human", "{input}"),',
        '    MessagesPlaceholder("agent_scratchpad"),',
        "])",
        "",
        "agent = create_openai_tools_agent(llm, tools, prompt)",
        "agent_executor = AgentExecutor(",
        "    agent=agent,",
        "    tools=tools,",
        "    verbose=True,",
        *(["    memory=memory,"] if use_memory else []),
        ")",
        "",
        'if __name__ == "__main__":',
        '    result = agent_executor.invoke({"input": "Hello, what can you do?"})',
        '    print(result["output"])',
    ]
    return "\n".join(lines)
