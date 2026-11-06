"""Monitor → Metrics (routers/metrics.py): run metrics from the app database, scoped to the project."""

import json
import uuid
from datetime import datetime, timedelta

import pytest

from db import get_db_connection
from helpers import hdr, mock_flow
from routers.traces import write_trace


def _app(client, project="proj_research"):
    r = client.post("/api/apps", headers=hdr(project=project), json={"name": f"m-{uuid.uuid4().hex[:6]}",
                                                                    "description": "", "flow_data": mock_flow()})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _trace(app_id, latency, status="success", cost=0.0, tokens=0, simulated=False, spans=None, model="gpt-x"):
    write_trace(run_id=str(uuid.uuid4()), app_id=app_id, node_id="m", node_type="llm", provider="openai", model=model,
                latency_ms=latency, cost_usd=cost, total_tokens=tokens, status=status,
                error="boom" if status == "error" else None,
                metadata_json=json.dumps({"simulated": True}) if simulated else None,
                spans_json=json.dumps(spans) if spans else None)


@pytest.fixture(scope="module")
def apps(client):
    a, b, other = _app(client), _app(client), _app(client, project="proj_support")
    _trace(a, 100, cost=0.01, tokens=100, spans=[
        {"span_type": "retrieval", "name": "kb", "latency_ms": 40},
        {"span_type": "tool", "name": "web_search", "latency_ms": 30},
        {"span_type": "llm", "latency_ms": 60}])
    _trace(a, 300, status="error", spans=[{"span_type": "tool", "name": "web_search", "latency_ms": 5, "status": "error"}])
    _trace(b, 200, cost=0.02, tokens=50, model="gpt-y")
    _trace(b, 50, simulated=True, model="mock-gpt-4")
    _trace(other, 9999, cost=5.0)   # another project: never counted
    return a, b


def _overview(client, **params):
    r = client.get("/api/metrics/overview", headers=hdr(), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_totals_cover_this_projects_runs_only(client, apps):
    a, b = apps
    data = _overview(client, hours=24)
    mine = [_overview(client, hours=24, app_id=x)["totals"] for x in (a, b)]
    assert sum(t["runs"] for t in mine) == 4
    assert data["totals"]["runs"] >= 4 and data["totals"]["cost_usd"] < 5, "the other project's run is left out"
    t = _overview(client, hours=24, app_id=a)["totals"]
    assert (t["runs"], t["failed"], t["error_rate"], t["p95_ms"], t["cost_usd"]) == (2, 1, 0.5, 300, 0.01)


def test_series_buckets_add_up(client, apps):
    a, _ = apps
    data = _overview(client, hours=24, app_id=a)
    assert data["bucket_seconds"] == 3600 and 24 <= len(data["series"]) <= 25
    assert sum(p["runs"] for p in data["series"]) == 2 and sum(p["failed"] for p in data["series"]) == 1


def test_breakdowns_by_model_tool_and_phase(client, apps):
    _, b = apps
    by_model = {m["model"]: m for m in _overview(client, hours=24, app_id=b)["models"]}
    assert set(by_model) == {"gpt-y"}, "a simulated run called no model"
    a, _ = apps
    data = _overview(client, hours=24, app_id=a)
    assert data["tools"] == [{"name": "web_search", "calls": 2, "failed": 1, "p95_ms": 30}]
    assert data["phases"] == [{"phase": "retrieval", "count": 1, "p95_ms": 40, "total_ms": 40}]
    assert _overview(client, hours=24, app_id=b)["totals"]["simulated"] == 1


def test_window_snaps_and_old_runs_drop_out(client, apps):
    a, _ = apps
    with get_db_connection() as conn:
        old = (datetime.utcnow() - timedelta(hours=3)).isoformat()
        rid = str(uuid.uuid4())
        conn.execute("INSERT INTO traces (id, run_id, app_id, node_id, node_type, provider, model, latency_ms, status, "
                     "created_at) VALUES (?, ?, ?, 'm', 'llm', 'openai', 'gpt-x', 10, 'success', ?)", (rid, rid, a, old))
        conn.commit()
    assert _overview(client, hours=1, app_id=a)["totals"]["runs"] == 2
    assert _overview(client, hours=6, app_id=a)["totals"]["runs"] == 3
    assert _overview(client, hours=5)["hours"] == 6, "an unsupported window snaps to the nearest"


def test_needs_read_access(client):
    r = client.get("/api/metrics/overview", headers=hdr(user="nobody-here"))
    assert r.status_code in (401, 403)
