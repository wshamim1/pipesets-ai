"""native_json and openapi exporters."""

import json
from typing import Any, Dict

import yaml

from exporters.helpers import nodes_by_type, edge_map


def to_native_json(app: Dict) -> str:
    return json.dumps(app, indent=2)


def to_openapi(app: Dict) -> str:
    flow  = app["flow_data"]
    nodes = nodes_by_type(flow)
    paths: Dict[str, Any] = {}

    def _add_tool_path(tool_id: str, label: str, description: str, cfg: Dict) -> None:
        path_key = f"/{tool_id.replace('_', '-')}"
        paths[path_key] = {
            "post": {
                "operationId": tool_id,
                "summary": label,
                "description": description,
                "tags": ["tools"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "input": {"type": "string", "description": "Tool input text"},
                                    "config": {"type": "object", "description": "Config overrides", "default": cfg},
                                },
                                "required": ["input"],
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Tool execution result",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "output": {"type": "string"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        }

    for node in nodes["tool"]:
        d = node.get("data", {})
        _add_tool_path(
            d.get("toolId", node.get("id", "tool")),
            d.get("label", d.get("toolId", "Tool")),
            d.get("description", ""),
            d.get("config", {}),
        )

    for node in nodes["toolkit"]:
        for sub in node.get("data", {}).get("subTools", []):
            _add_tool_path(
                sub.get("toolId", "sub_tool"),
                sub.get("label", sub.get("toolId", "Sub Tool")),
                sub.get("description", ""),
                sub.get("config", {}),
            )

    if nodes["retriever"]:
        paths["/retriever/search"] = {
            "post": {
                "operationId": "retrieverSearch",
                "summary": "RAG Retriever Search",
                "description": "Semantic search over the connected Knowledge Base.",
                "tags": ["rag"],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
                },
                "responses": {"200": {"description": "Matching document chunks"}},
            }
        }

    for node in nodes["llm"]:
        d = node.get("data", {})
        paths["/run"] = {
            "post": {
                "operationId": "runPrompt",
                "summary": "Run a prompt through the agent",
                "tags": ["agent"],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object", "properties": {"prompt": {"type": "string"}, "session_id": {"type": "string"}}, "required": ["prompt"]}}},
                },
                "responses": {"200": {"description": "LLM response", "content": {"application/json": {"schema": {"type": "object", "properties": {"output": {"type": "string"}}}}}}},
                "x-llm-config": {"provider": d.get("provider", "openai"), "model": d.get("model", "gpt-4o"), "temperature": d.get("temperature", 0.7), "max_tokens": d.get("max_tokens", 1024)},
            }
        }
        break

    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": app["name"],
            "description": app.get("description", ""),
            "version": "1.0.0",
            "x-generated-by": "Pipesets AI",
        },
        "servers": [{"url": "http://localhost:8000", "description": "Local Pipesets AI backend"}],
        "paths": paths,
    }
    return yaml.dump(spec, sort_keys=False, allow_unicode=True)
