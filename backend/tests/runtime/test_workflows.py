"""The conversational workflow engine + API, with a stubbed tool executor (no network)."""
import json

import pytest

from db import get_db_connection
from routers import tools as tools_router

calls = []


@pytest.fixture(scope="module", autouse=True)
def _fake_tools(env):
    """Stub the real tool executor; record how it was called."""
    async def fake_execute_tool_real(tool_type, input_text, config=None):
        calls.append((tool_type, input_text, config or {}))
        if tool_type == "weather":
            return f"[Weather: {input_text}] Sunny, 31{(config or {}).get('units_label', 'C')}"
        if tool_type == "catalog_search":   # returns a JSON list, as a search-style tool would
            return json.dumps([{"id": "a1", "name": f"Alpha {input_text}"}, {"id": "b2", "name": f"Beta {input_text}"},
                               {"id": "c3", "name": f"Gamma {input_text}"}])
        if tool_type == "place_order":
            return json.dumps({"order_id": f"ORD-{input_text}", "status": "confirmed"})
        raise RuntimeError(f"unexpected tool {tool_type}")

    env.setattr(tools_router, "execute_tool_real", fake_execute_tool_real)


# ── Flow builders ─────────────────────────────────────────────────────────────
def step(id_, x, **data):
    base = dict(label=id_, prompt="", variable="", input_kind="text", options_source="",
                option_label_field="", option_value_field="", tool_id="", tool_input="")
    return {"id": id_, "type": "wf_step", "position": {"x": x, "y": 0}, "data": {**base, **data}}


def tool_node(id_, tool_id, **config):
    return {"id": id_, "type": "tool", "position": {"x": 0, "y": 100},
            "data": {"label": tool_id.title(), "toolId": tool_id, "toolType": "tool", "icon": "T",
                     "description": "", "config": config}}


def start_node():
    return {"id": "start", "type": "start", "position": {"x": 0, "y": 0}, "data": {"label": "Start"}}


def edge(s, t, label=None):
    e = {"id": f"{s}-{t}", "source": s, "target": t}
    if label:
        e["label"] = label
    return e


def publish(app_id, flow_data, status="published"):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO apps (id, tenant_id, project_id, owner_user_id, name, description, flow_data, status, version, created_at, updated_at)"
        " VALUES (?, 'tenant_demo', 'proj_research', 'user_admin', 'Test', '', ?, ?, 1, 'n', 'n')",
        (app_id, json.dumps(flow_data), status))
    conn.commit()
    conn.close()


@pytest.fixture(scope="module")
def wf(client):
    class Wf:
        def start(self, app_id, **body):
            return client.post(f"/api/workflows/{app_id}/start", json=body).json()

        def reply(self, run_id, **body):
            return client.post(f"/api/workflows/runs/{run_id}/reply", json=body).json()
    return Wf()


WEATHER_FLOW = {
    "nodes": [start_node(),
              step("city", 1, step_type="ask", prompt="Which city?", variable="city"),
              step("lookup", 2, step_type="tool_call", tool_input="{{city}}", variable="forecast"),
              step("show", 3, step_type="message", prompt="Weather: {{forecast}}"),
              tool_node("wx", "weather", units="imperial", units_label="F")],
    # wx is wired to the step as an attachment, and must NOT become part of the step order
    "edges": [edge("start", "city"), edge("city", "lookup"), edge("lookup", "show"), edge("wx", "lookup")],
}


def copy(flow):
    return json.loads(json.dumps(flow))


def test_weather_tool_node(wf):
    """Ask city → linked Weather tool node → show result."""
    publish("app-weather", WEATHER_FLOW)
    r = wf.start("app-weather", message="tell me weather")
    assert r["status"] == "waiting_input" and r["messages"] == ["Which city?"], r
    r = wf.reply(r["run_id"], message="Goa")
    assert r["status"] == "completed" and r["messages"] == ["Weather: [Weather: Goa] Sunny, 31F"], r
    assert calls[-1] == ("weather", "Goa", {"units": "imperial", "units_label": "F"}), "toolId + config from the node"

    rev = copy(WEATHER_FLOW)
    rev["edges"][-1] = edge("lookup", "wx")
    publish("app-weather-rev", rev)
    r = wf.reply(wf.start("app-weather-rev")["run_id"], message="Pune")
    assert r["status"] == "completed" and "Pune" in r["messages"][0], "step → tool link works too"

    nolink = copy(WEATHER_FLOW)
    nolink["nodes"] = [n for n in nolink["nodes"] if n["id"] != "wx"]
    nolink["edges"] = nolink["edges"][:-1]
    publish("app-nolink", nolink)
    r = wf.reply(wf.start("app-nolink")["run_id"], message="Goa")
    assert r["status"] == "failed" and "link a tool node" in r["error"], r

    fb = copy(nolink)
    fb["nodes"][2]["data"]["tool_id"] = "weather"
    publish("app-fallback", fb)
    r = wf.reply(wf.start("app-fallback")["run_id"], message="Delhi")
    assert r["status"] == "completed" and "Delhi" in r["messages"][0], "fallback tool_id without a linked node"


def test_longer_flow(client, wf):
    """ask → number → search tool → choice → confirm (yes / no) → action tool."""
    flow = {
        "nodes": [start_node(),
                  step("topic", 1, step_type="ask", prompt="What topic?", variable="topic"),
                  step("qty", 2, step_type="ask", prompt="How many?", variable="qty", input_kind="number"),
                  step("search", 3, step_type="tool_call", tool_input="{{topic}}", variable="results"),
                  step("pick", 4, step_type="choice", prompt="Results for {{topic}}:", variable="item",
                       options_source="results", option_label_field="name", option_value_field="id"),
                  step("ok", 5, step_type="confirm", prompt="Order {{qty}} x {{item_item.name}}?", variable="go"),
                  step("order", 6, step_type="tool_call", tool_input="{{item}}", variable="order"),
                  step("done", 7, step_type="message", prompt="Done! {{order.order_id}} for {{item_item.name}}."),
                  {"id": "stop", "type": "stop", "position": {"x": 8, "y": 0}, "data": {"label": "Stop"}},
                  tool_node("t_search", "catalog_search"), tool_node("t_order", "place_order")],
        "edges": [edge("start", "topic"), edge("topic", "qty"), edge("qty", "search"), edge("search", "pick"),
                  edge("pick", "ok"), edge("ok", "order", "yes"), edge("ok", "pick", "no"),
                  edge("order", "done"), edge("done", "stop"),
                  edge("t_search", "search"), edge("t_order", "order")],
    }
    publish("app-flow", flow)

    r = wf.start("app-flow", message="hi")
    rid = r["run_id"]
    assert r["variables"]["initial_message"] == "hi"
    r = wf.reply(rid, message="shoes")
    assert r["input"]["type"] == "number", r
    r = wf.reply(rid, message="two")
    assert r["status"] == "waiting_input" and "not a number" in r["messages"][0], "bad number re-asks"
    r = wf.reply(rid, message="2")
    opts = r["input"]["options"]
    assert r["input"]["type"] == "choice" and len(opts) == 3 and opts[0]["label"] == "Alpha shoes", \
        "tool output list becomes choice options"
    assert r["variables"]["qty"] == 2
    r = wf.reply(rid, choice="nope")
    assert "not one of the options" in r["messages"][0] and r["status"] == "waiting_input"
    r = wf.reply(rid, choice="b2")
    assert r["input"]["type"] == "confirm" and r["messages"][0] == "Order 2 x Beta shoes?"
    r = wf.reply(rid, message="no")
    assert r["input"]["type"] == "choice", "'no' loops back to the choice"
    r = wf.reply(rid, choice="3")
    assert r["input"]["type"] == "confirm" and "Gamma shoes" in r["messages"][0], "pick by list number"
    r = wf.reply(rid, message="Yes")
    assert r["status"] == "completed" and r["messages"] == ["Done! ORD-c3 for Gamma shoes."], r
    assert calls[-1][0] == "place_order" and calls[-1][1] == "c3", "the second tool used its own node"
    assert client.post(f"/api/workflows/runs/{rid}/reply", json={"message": "hi"}).status_code == 409

    g = client.get(f"/api/workflows/runs/{rid}").json()
    assert g["status"] == "completed" and any(h["role"] == "user" for h in g["history"])
    assert g["variables"]["order"]["status"] == "confirmed"

    r = wf.start("app-flow", variables={"topic": "hats", "qty": 1})
    assert r["input"]["type"] == "choice" and r["input"]["options"][0]["label"] == "Alpha hats", "pre-filled answers"


def test_guards(client, wf):
    publish("app-draft", WEATHER_FLOW, "draft")
    assert client.post("/api/workflows/app-draft/start", json={}).status_code == 409
    assert client.post("/api/workflows/nope/start", json={}).status_code == 404
    r = wf.start("app-weather")
    assert client.get(f"/api/workflows/runs/{r['run_id']}", headers={"x-user-id": "someone_else"}).status_code in (403, 404)
    assert client.post(f"/api/workflows/runs/{r['run_id']}/reply", json={}).status_code == 422

    loop = {"nodes": [start_node(), step("a", 1, step_type="message", prompt="x"),
                      step("b", 2, step_type="message", prompt="y")],
            "edges": [edge("start", "a"), edge("a", "b"), edge("b", "a")]}
    publish("app-loop", loop)
    r = wf.start("app-loop")
    assert r["status"] == "failed" and "possible loop" in r["error"]

    mini = {"nodes": [step("c", 1, step_type="confirm", prompt="Sure?", variable="s"),
                      step("m", 2, step_type="message", prompt="done")], "edges": [edge("c", "m")]}
    publish("app-mini", mini)
    r = wf.reply(wf.start("app-mini")["run_id"], message="no")
    assert r["status"] == "completed" and "stopped" in r["messages"][0].lower(), "'no' without a no-edge ends cleanly"
