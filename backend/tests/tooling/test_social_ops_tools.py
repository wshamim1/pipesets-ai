"""Bluesky, Mastodon, Jenkins, Freshdesk, World Bank and Wikidata against a fake HTTP server shaped like
each vendor's documented API, plus the offline JWT decoder and CSV SQL tool (including its read-only
guard). No network or vendor accounts needed.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest

import tools

calls = []


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    host, path, q, h = request.url.host, request.url.path, request.url.params, request.headers
    body = json.loads(request.content) if request.content and h.get("content-type", "").startswith("application/json") else None

    if host == "bsky.social":
        if path == "/xrpc/com.atproto.server.createSession":
            if body != {"identifier": "ana.bsky.social", "password": "app-pw"}:
                return httpx.Response(401, json={"error": "AuthenticationRequired"})
            return httpx.Response(200, json={"accessJwt": "jwt1", "did": "did:plc:ana", "handle": "ana.bsky.social"})
        if path == "/xrpc/com.atproto.repo.createRecord":
            assert h["authorization"] == "Bearer jwt1" and body["repo"] == "did:plc:ana"
            calls.append(body["record"])
            return httpx.Response(200, json={"uri": "at://did:plc:ana/app.bsky.feed.post/3kabc", "cid": "c"})

    if host == "mastodon.example":
        if h.get("authorization") != "Bearer mtok":
            return httpx.Response(401, json={"error": "The access token is invalid"})
        form = parse_qs(request.content.decode())
        if form["status"] == [""]:
            return httpx.Response(422, json={"error": "Validation failed: Text can't be blank"})
        assert form["visibility"] == ["unlisted"]
        return httpx.Response(200, json={"id": "1", "url": "https://mastodon.example/@ana/1"})

    if host == "ci.example":
        if h.get("authorization") != "Basic " + base64.b64encode(b"bot:jtok").decode():
            return httpx.Response(401, text="Unauthorized")
        if path == "/job/team/job/deploy/lastBuild/api/json":
            return httpx.Response(200, json={"number": 41, "result": "FAILURE", "building": False, "duration": 92000,
                                             "timestamp": 1730000000000, "url": "https://ci.example/job/team/job/deploy/41/",
                                             "actions": [{"causes": [{"shortDescription": "Started by user Ana"}]}, {}]})
        if path == "/job/team/job/deploy/lastBuild/consoleText":
            return httpx.Response(200, text="x" * 5000 + "\nERROR: tests failed")
        if path == "/job/team/job/deploy/build" and request.method == "POST":
            return httpx.Response(201, headers={"Location": "https://ci.example/queue/item/9/"})
        if path == "/api/json":
            return httpx.Response(200, json={"jobs": [{"name": "deploy", "color": "red_anime"}, {"name": "team"}]})
        return httpx.Response(404, text="Not Found")

    if host == "acme.freshdesk.com":
        if h.get("authorization") != "Basic " + base64.b64encode(b"fdkey:X").decode():
            return httpx.Response(401, json={"code": "invalid_credentials"})
        if path == "/api/v2/tickets/123":
            assert q["include"] == "conversations,requester"
            return httpx.Response(200, json={"id": 123, "subject": "Refund request", "status": 3, "priority": 2,
                                             "requester": {"email": "c@x.com"}, "created_at": "2026-11-01T00:00:00Z",
                                             "description_text": "Charged twice.",
                                             "conversations": [{"private": True, "body_text": "Checked Stripe", "created_at": "2026-11-02"}]})
        if path == "/api/v2/tickets" and request.method == "POST":
            assert body == {"subject": "Printer down", "description": "Floor 3", "email": "it@acme.com", "status": 2, "priority": 1}
            return httpx.Response(201, json={"id": 124, "subject": "Printer down"})
        if path == "/api/v2/tickets":
            return httpx.Response(200, json=[{"id": 1, "subject": "Login broken", "status": 2, "priority": 4, "updated_at": "2026-11-03"},
                                             {"id": 2, "subject": "Invoice copy", "status": 4, "priority": 1, "updated_at": "2026-11-02"}])
        if path == "/api/v2/search/tickets":
            assert q["query"] == '"status:2 AND priority:4"'
            return httpx.Response(200, json={"total": 1, "results": [{"id": 1, "subject": "Login broken", "status": 2, "priority": 4}]})

    if host == "api.worldbank.org":
        if path == "/v2/country/US;IN/indicator/NY.GDP.MKTP.CD":
            assert q["date"] == "2022:2023" and q["format"] == "json"
            return httpx.Response(200, json=[{"page": 1}, [
                {"indicator": {"value": "GDP (current US$)"}, "country": {"value": "India"}, "date": "2023", "value": 3.5e12},
                {"indicator": {"value": "GDP (current US$)"}, "country": {"value": "United States"}, "date": "2023", "value": 2.77e13},
                {"indicator": {"value": "GDP (current US$)"}, "country": {"value": "United States"}, "date": "2022", "value": None}]])
        return httpx.Response(200, json=[{"message": [{"id": "120", "value": "The provided parameter value is not valid"}]}])

    if host == "query.wikidata.org":
        assert "pipesets-ai" in h["user-agent"]
        return httpx.Response(200, json={"head": {"vars": ["item", "itemLabel"]}, "results": {"bindings": [
            {"item": {"value": "http://www.wikidata.org/entity/Q677525"}, "itemLabel": {"value": "Orangey"}}]}})
    if host == "www.wikidata.org":
        if q["action"] == "wbgetentities":
            return httpx.Response(200, json={"entities": {"Q42": {"labels": {"mul": {"value": "Douglas Adams"}},
                                                                   "descriptions": {"en": {"value": "writer"}}}}})
        if q["action"] == "wbsearchentities":
            return httpx.Response(200, json={"search": [{"id": "Q42", "label": "Douglas Adams", "description": "writer"}]})

    return httpx.Response(599, json={"error": f"unexpected request {request.method} {request.url}"})


@pytest.fixture(autouse=True)
def vendors(monkeypatch):
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def run(tool, inp, cfg, args=None):
    calls.clear()
    return asyncio.run(tools.execute(tool, inp, cfg, args))


def test_bluesky_posts_with_link_facets():
    cfg = {"handle": "@ana.bsky.social", "app_password": "app-pw"}
    out = run("bluesky_post", "Café notes: https://example.com/a?b=1.", cfg)
    assert out == "[Bluesky] Posted.\nhttps://bsky.app/profile/ana.bsky.social/post/3kabc"
    record = calls[-1]
    facet = record["facets"][0]
    assert facet["features"][0]["uri"] == "https://example.com/a?b=1", "trailing punctuation isn't part of the link"
    raw = record["text"].encode()
    assert raw[facet["index"]["byteStart"]:facet["index"]["byteEnd"]] == b"https://example.com/a?b=1", "byte offsets, not characters"
    assert "Sign-in failed" in run("bluesky_post", "hi", {**cfg, "app_password": "wrong"})
    assert "limited to 300" in run("bluesky_post", "x" * 301, cfg) and not calls


def test_mastodon():
    cfg = {"instance_url": "mastodon.example", "access_token": "mtok", "visibility": "unlisted"}
    assert run("mastodon_post", "Hello fediverse", cfg) == "[Mastodon] Posted (unlisted).\nhttps://mastodon.example/@ana/1"
    assert "access_token is invalid" in run("mastodon_post", "x", {**cfg, "access_token": "bad"})
    assert "Visibility is one of" in run("mastodon_post", "x", {**cfg, "visibility": "loud"})


def test_jenkins():
    cfg = {"base_url": "https://ci.example/", "username": "bot", "api_token": "jtok"}
    out = run("jenkins", "team/deploy", cfg)
    assert "team/deploy #41: FAILURE" in out and "Started by user Ana" in out and "92s" in out
    out = run("jenkins", "team/deploy", {**cfg, "action": "log"})
    assert out.endswith("ERROR: tests failed") and "last 4000 characters" in out
    assert "queued" in run("jenkins", "team/deploy", {**cfg, "action": "build"}) and calls[0].method == "POST"
    out = run("jenkins", "", {**cfg, "action": "list"})
    assert "deploy · failing (building)" in out and "team · folder" in out
    assert "not found" in run("jenkins", "nope", cfg)
    assert "HTTP 401" in run("jenkins", "team/deploy", {**cfg, "api_token": "x"})


def test_freshdesk():
    cfg = {"domain": "https://acme.freshdesk.com/", "api_key": "fdkey", "requester_email": "it@acme.com"}
    out = run("freshdesk", "#123", cfg)
    assert "#123: Refund request" in out and "Status: Pending · Priority: Medium" in out and "note 2026-11-02: Checked Stripe" in out
    assert "Created #124" in run("freshdesk", "create: Printer down\nFloor 3", cfg)
    out = run("freshdesk", "login", {**cfg, "domain": "acme"})
    assert "#1 Login broken · Open · Urgent" in out and "Invoice copy" not in out
    assert "1 ticket(s) for status:2 AND priority:4" in run("freshdesk", "status:2 AND priority:4", cfg)
    assert "api_key is invalid" in run("freshdesk", "#123", {**cfg, "api_key": "bad"})


def test_world_bank():
    out = run("world_bank_indicators", "", {}, {"indicator": "gdp", "countries": "us,in", "years": "2022:2023"})
    assert "GDP (current US$) (NY.GDP.MKTP.CD)" in out and "India\n  2023: 3.50T" in out
    assert "United States\n  2023: 27.70T" in out and "2022" not in out.split("United States")[1], "empty years are dropped"
    assert "not valid" in run("world_bank_indicators", "nonsense ZZ", {})
    assert "Input is" in run("world_bank_indicators", "gdp", {})


def test_wikidata():
    out = run("wikidata_query", "SELECT ?item ?itemLabel WHERE { ?item wdt:P31 wd:Q146 } LIMIT 1", {})
    assert "| Q677525 | Orangey |" in out
    assert run("wikidata_query", "q42", {}).startswith("[Wikidata] Q42: Douglas Adams\n  writer"), "falls back to the mul label"
    assert "- Q42: Douglas Adams — writer" in run("wikidata_query", "Douglas Adams", {})


def _jwt(claims, secret="s3cret", alg="HS256"):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    head = f"{enc({'alg': alg, 'typ': 'JWT'})}.{enc(claims)}"
    sig = hmac.new(secret.encode(), head.encode(), {"HS256": hashlib.sha256, "HS512": hashlib.sha512}[alg]).digest()
    return f"{head}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"


def test_jwt_decoder():
    token = _jwt({"sub": "ana", "exp": int(time.time()) - 7200, "iat": 1700000000})
    out = run("jwt_decoder", f"Bearer {token}", {"hmac_secret": "s3cret"})
    assert "HS256 token · signature VALID · EXPIRED 2 hours ago" in out and '"sub": "ana"' in out
    assert "iat: 1700000000 → 2023-11-14 22:13:20 UTC" in out
    assert "INVALID" in run("jwt_decoder", token, {"hmac_secret": "other"})
    assert "not verified" in run("jwt_decoder", _jwt({"exp": int(time.time()) + 90000}, alg="HS512"), {})
    assert "expires in 1 day" in run("jwt_decoder", _jwt({"exp": int(time.time()) + 90000}), {})
    assert "three dot-separated parts" in run("jwt_decoder", "abc.def", {})
    assert "Not a valid JWT" in run("jwt_decoder", "a.b.c", {})


CSV = "Region,Amount,Region\nEU,10,x\nUS,5,y\nEU,2.5,z\n"


def test_csv_sql_queries_text_and_files(tmp_path):
    out = run("csv_sql", "", {}, {"csv": CSV, "sql": "SELECT region, SUM(amount) AS total FROM data GROUP BY region ORDER BY total DESC"})
    assert "| EU | 12.5 |" in out and out.index("| EU") < out.index("| US")
    assert "| x |" in run("csv_sql", "", {}, {"csv": CSV, "sql": "SELECT region_2 FROM data LIMIT 1"}), "duplicate headers get a suffix"
    (tmp_path / "sales.csv").write_text(CSV)
    cfg = {"allowed_dir": str(tmp_path), "max_rows": 2}
    out = run("csv_sql", "", cfg, {"path": "sales.csv", "sql": "SELECT * FROM data"})
    assert "2+ row(s) from 3 CSV row(s)" in out and "More rows not shown" in out
    assert "Access denied" in run("csv_sql", "", cfg, {"path": "../etc/passwd", "sql": "SELECT 1"})


@pytest.mark.parametrize("sql", [
    "ATTACH DATABASE 'x.db' AS x", "DROP TABLE data", "INSERT INTO data VALUES (1, 2, 3)",
    "PRAGMA table_info(data)", "SELECT load_extension('x')",
])
def test_csv_sql_is_read_only(sql, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = run("csv_sql", "", {}, {"csv": CSV, "sql": sql})
    assert "Query failed" in out
    assert not list(tmp_path.iterdir()), "nothing is written"


def test_csv_sql_stops_runaway_queries():
    out = run("csv_sql", "", {}, {"csv": CSV, "sql": "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c"})
    assert "ran too long" in out
