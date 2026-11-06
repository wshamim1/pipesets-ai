"""Legacy combined web search (Tavily when a key is set, else DuckDuckGo) — `web_search`.

Hidden from the catalog (replaced by one tool per provider); kept so saved pipelines run.
"""

import os
from typing import Any, Dict, Optional

from tools.base import ToolSpec, query_params
from tools.search import duckduckgo_search, tavily_search

TOOL = ToolSpec(
    id="web_search",
    name="Web Search (Tavily/DuckDuckGo)",
    icon="🌐",
    category="Web Search",
    description="Searches real-time web information and answers.",
    default_config={"api_key": "", "max_results": 5},
    hidden=True,
    parameters=query_params("What to search the web for"), input_param="query",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    if not inp:
        return "[Web Search] Please provide a search query."
    if cfg.get("api_key") or os.environ.get("TAVILY_API_KEY"):
        result = await tavily_search.search(inp, cfg)
        if not result.startswith("[Tavily] Error"):
            return result
    return await duckduckgo_search.search(inp, cfg)
