"""The data tools — BigQuery, GCS (REST + the shared Google refresh flow), Elasticsearch,
Azure Blob Storage (REST + XML), Snowflake and MongoDB (optional drivers, offline) — against
fakes shaped like each documented API. No network or cloud accounts needed.
"""
import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

import tools

calls = []


def ok(body):
    return httpx.Response(200, json=body)


def bigquery(request, path, q, body):
    if request.headers.get("authorization") != "Bearer gq":
        return httpx.Response(401, json={"error": {"message": "Request had invalid authentication credentials."}})
    if path == "/bigquery/v2/projects/proj/queries":
        assert body["useLegacySql"] is False and body["timeoutMs"] == 10000
        assert "SELECT" in body["query"].upper()
        if body["query"].startswith("SELECT 1"):
            return ok({"jobComplete": False, "jobReference": {"jobId": "j1", "location": "US"}})
        return ok({"jobComplete": True, "jobReference": {"jobId": "j1", "location": "US"}, "totalRows": "2",
                   "schema": {"fields": [{"name": "user", "type": "STRING"}, {"name": "total", "type": "INTEGER"}]},
                   "rows": [{"f": [{"v": "ada"}, {"v": "10"}]}, {"f": [{"v": "grace"}, {"v": "9"}]}]})
    if path == "/bigquery/v2/projects/missing/queries":
        return httpx.Response(404, json={"error": {"message": "not found"}})
    assert path == "/bigquery/v2/projects/proj/queries/j1", "polling the still-running job"
    assert q["location"] == "US"
    return ok({"jobComplete": True, "totalRows": "2",
               "schema": {"fields": [{"name": "user", "type": "STRING"}, {"name": "total", "type": "INTEGER"}]},
               "rows": [{"f": [{"v": "ada"}, {"v": "10"}]}, {"f": [{"v": "grace"}, {"v": "9"}]}]})


def gcs(request, path, q, body):
    if request.headers.get("authorization") != "Bearer gq":
        if request.headers.get("authorization") == "Bearer revived":  # after the refresh flow
            return ok({"items": []})
        return httpx.Response(401, json={"error": {"code": 401, "message": "Invalid Credentials"}})
    if path == "/storage/v1/b/dataplatform/o":
        assert q["maxResults"] == "50" and q.get("delimiter") == "/"
        if not q.get("prefix"):
            return ok({"items": [
                {"name": "raw/2026/orders.csv", "size": "1048576", "contentType": "text/csv"},
                {"name": "README.md", "size": "310", "contentType": "text/markdown"}],
                "prefixes": ["raw/"]})
        assert q["prefix"] == "raw/"
        return ok({"items": [{"name": "raw/2026/orders.csv", "size": "1048576", "contentType": "text/csv"}]})
    if path == "/storage/v1/b/dataplatform/o/README.md":
        assert q["alt"] == "media"
        return httpx.Response(200, content=b"# Data dictionary\n\norders.csv: one row per order.\n")
    if path == "/storage/v1/b/dataplatform/o/raw/2026%2Fmissing.csv":
        return httpx.Response(404, json={"error": {"code": 404, "message": "No such object: orders-2027.csv"}})


def google_token(request, path, q, body):
    assert body["refresh_token"][0] == "rt-good" and body["grant_type"][0] == "refresh_token"
    return ok({"token_type": "Bearer", "access_token": "gq"})


def elasticsearch(request, path, q, body):
    if path == "/logs-2026/_search" and request.method == "POST":
        assert body["size"] == 10
        query = body["query"]
        if isinstance(query, dict) and "query_string" in query:
            text = query["query_string"]["query"]
            assert query["query_string"]["lenient"] is True
        else:
            text = ""
        if text == "service:api AND level:500":
            return ok({"hits": {"total": {"value": 1},
                                "hits": [{"_index": "logs-2026", "_id": "1", "_score": 2.5,
                                          "_source": {"service": "api", "message": "timeout on /orders"}}]}})
        return ok({"hits": {"total": {"value": 47},
                            "hits": [{"_index": "logs-2026", "_id": "1", "_score": 2.5,
                                      "_source": {"service": "api", "message": "timeout on /orders", "level": 500}},
                                     {"_index": "logs-2026", "_id": "2", "_score": 1.25,
                                      "_source": {"service": {"nested": {"deep": 1}}}}]}})
    if path == "/secret/_search":
        return httpx.Response(401, json={"error": {"reason": "unable to authenticate user"}})
    if path == "/lost/_search":
        return httpx.Response(404, json={"error": {"reason": "index_not_found_exception"}})


AZ_LIST_ROOT = b"""<EnumerationResults><Blobs><BlobPrefix><Name>raw/</Name></BlobPrefix>
<Blob><Name>README.md</Name><Properties><Content-Length>310</Content-Length>
<Content-Type>text/markdown</Content-Type></Properties></Blob></Blobs></EnumerationResults>"""

AZ_LIST_PREFIX = b"""<EnumerationResults><Blobs><Blob><Name>raw/2026/orders.csv</Name>
<Properties><Content-Length>1048576</Content-Length><Content-Type>text/csv</Content-Type>
</Properties></Blob></Blobs></EnumerationResults>"""


def azure(request, path, q, body):
    if "sig=SAS" not in request.url.query.decode():
        return httpx.Response(403, json={"message": "Authentication information is not given"})
    assert q["restype"] == "container" and q["comp"] == "list"
    if not q.get("prefix"):
        return httpx.Response(200, content=AZ_LIST_ROOT)
    assert q["prefix"] == "raw/"
    return httpx.Response(200, content=AZ_LIST_PREFIX)


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    q = {k: v[0] for k, v in parse_qs(request.url.query.decode(), keep_blank_values=True).items()}
    ctype = request.headers.get("content-type", "")
    body = json.loads(request.content) if request.content and ctype.startswith("application/json") else (
        parse_qs(request.content.decode()) if request.content and ctype.startswith("application/x-www-form-urlencoded") else {})
    if request.url.host in VENDORS:
        res = VENDORS[request.url.host](request, request.url.raw_path.decode().split("?")[0], q, body)
        return res if res is not None else httpx.Response(404, text=f"unexpected {request.method} {request.url}")
    return httpx.Response(502, text=f"no fake for {request.method} {request.url}")


VENDORS = {"bigquery.googleapis.com": bigquery, "storage.googleapis.com": gcs,
           "oauth2.googleapis.com": google_token, "es.local": elasticsearch,
           "acctdemo.blob.core.windows.net": azure}


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


def test_bigquery():
    cfg = {"access_token": "gq", "project_id": "proj"}
    out = run("bigquery_reader", "SELECT user, COUNT(*) AS total FROM orders", cfg)
    assert "| user | total |" in out and out.index("| user | total |") < out.index("ada")
    assert "10" in out and "grace" in out
    out_slow = run("bigquery_reader", "SELECT 1", cfg)
    assert "2 row(s)" in out_slow, "still-running job is polled until complete"
    assert "not found" in run("bigquery_reader", "SELECT 1", {"access_token": "gq", "project_id": "missing"})
    assert "access_token is required" in run("bigquery_reader", "SELECT 1", {"project_id": "proj"})
    assert "project_id is required" in run("bigquery_reader", "SELECT 1", {"access_token": "gq"})
    assert "Only select," in run("bigquery_reader", "DELETE FROM orders", cfg)
    assert run("bigquery_reader", "SELECT 1", {"access_token": "bad", "project_id": "proj"}).startswith("[BigQuery]")


def test_gcs():
    cfg = {"access_token": "gq", "bucket": "dataplatform"}
    out = run("gcs_reader", "list", cfg)
    assert "raw/ (folder)" in out and "README.md  (310 B, text/markdown)" in out
    raw = run("gcs_reader", "", {**cfg, "prefix": "raw/"})
    assert "raw/2026/orders.csv" in raw
    read = run("gcs_reader", "README.md", cfg)
    assert "Data dictionary" in read and "one row per order" in read
    assert run("gcs_reader", "list", {"access_token": "gq"}).startswith("[GCS] bucket is required")
    assert "access_token is required" in run("gcs_reader", "list", {"bucket": "dataplatform"})
    missing = run("gcs_reader", "raw/2026/missing.csv", cfg)
    assert missing.startswith("[GCS]") and "Not found" in missing


def test_gcs_refresh():
    cfg = {"access_token": "expired", "refresh_token": "rt-good", "client_id": "cid", "client_secret": "cs",
           "bucket": "dataplatform"}
    out = run("gcs_reader", "list", cfg)
    assert "[GCS]" in out
    assert any("oauth2.googleapis.com" in str(c.url) for c in calls), "refreshed once on 401"


def test_elasticsearch():
    cfg = {"base_url": "http://es.local", "index": "logs-2026"}
    out = run("elasticsearch_search", "timeout spike", cfg)
    assert "2 of 47 hit(s)" in out
    assert "service: api · message: timeout on /orders · level: 500" in out
    assert "nested" in out, "Dict values appear as JSON"
    lucene = run("elasticsearch_search", "service:api AND level:500", cfg)
    assert "1 hit(s)" in lucene and "timeout on /orders" in lucene
    assert calls[0].method == "POST"
    assert json.loads(calls[0].content)["query"]["query_string"]["query"].endswith("level:500")
    json_out = run("elasticsearch_search", '{"query": {"term": {"service": "api"}}}', cfg)
    assert "2 of 47 hit(s)" in json_out and '| 2' not in json_out
    assert "Authentication failed" in run("elasticsearch_search", "x", {**cfg, "index": "secret"})
    assert "not found" in run("elasticsearch_search", "x", {**cfg, "index": "lost"})
    assert "index is required" in run("elasticsearch_search", "x", {"base_url": "http://es.local"})
    assert "Pass the query text" in run("elasticsearch_search", "", cfg)


def test_azure_blob():
    cfg = {"account_url": "https://acctdemo.blob.core.windows.net", "container": "import",
           "sas_token": "sig=SAS&se=2027"}
    out = run("azure_blob_reader", "list", cfg)
    assert "raw/" in out and "README.md  (310 B, text/markdown)" in out
    raw = run("azure_blob_reader", "raw/", cfg)
    assert "raw/2026/orders.csv  (1.0 MB, text/csv)" in raw
    assert "11 KB" not in raw
    assert calls[0].url.params["prefix"] == "raw/"
    assert "403" not in out
    assert "sas_token is required" in run("azure_blob_reader", "list", {**cfg, "sas_token": ""})
    assert "account_url is required" in run("azure_blob_reader", "list", {"container": "x", "sas_token": "?sig=1"})
    bad = run("azure_blob_reader", "list", {**cfg, "sas_token": "?wrong"})
    assert "SAS token doesn't allow" in bad


def test_snowflake_offline():
    assert "Only select, show, describe, desc, explain, with statements are allowed" in run(
        "snowflake_reader", "DROP TABLE x", {"account": "a", "user": "u", "password": "p"})
    assert "account, user and password" in run("snowflake_reader", "SELECT 1", {})
    out = run("snowflake_reader", "SELECT 1", {"account": "a", "user": "u", "password": "p"})
    assert "pip install snowflake-connector-python" in out, "friendly message when the driver is missing"


def test_mongodb_offline():
    assert "database and collection" in run("mongodb_reader", '{"a": 1}',
                                            {"uri": "mongodb://user:pass@localhost:27017"})
    assert "valid JSON" in run("mongodb_reader", "not json",
                               {"uri": "mongodb://localhost", "database": "db", "collection": "c"})
    assert "A mongodb://" in run("mongodb_reader", '{}', {"database": "db", "collection": "c"})
    assert "Pass a JSON filter" in run("mongodb_reader", "",
                                       {"uri": "mongodb://localhost", "database": "db", "collection": "c"})
    out = run("mongodb_reader", '{"status": "A"}',
              {"uri": "mongodb://localhost", "database": "db", "collection": "c"})
    assert "pip install pymongo" in out, "friendly message when the driver is missing"
