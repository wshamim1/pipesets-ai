"""Langfuse export (services/langfuse_export.py): what one trace row becomes."""

import json

from services.langfuse_export import build_batch


def test_every_non_model_span_becomes_a_langfuse_span():
    trace = {"id": "gen-1", "run_id": "run-1", "status": "success", "latency_ms": 900, "model": "llama3",
             "spans_json": json.dumps([
                 {"span_type": "middleware", "name": "prompt checks", "latency_ms": 2},
                 {"span_type": "retrieval", "name": "handbook", "latency_ms": 120},
                 {"span_type": "embedding", "name": "all-MiniLM", "latency_ms": 80},
                 {"span_type": "llm", "step": 1, "model": "llama3", "latency_ms": 600},
                 {"span_type": "tool", "name": "web_search", "tool_id": "web_search", "latency_ms": 90}])}
    spans = [e["body"] for e in build_batch(trace, redact=True) if e["type"] == "span-create"]
    assert [(s["name"], s["metadata"]["type"]) for s in spans] == [
        ("prompt checks", "middleware"), ("handbook", "retrieval"), ("all-MiniLM", "embedding"),
        ("web_search", "tool")], "the model call is the generation, not a span"
