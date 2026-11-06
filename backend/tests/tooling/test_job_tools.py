"""Google Jobs (SerpApi), Adzuna, Jooble, Company Jobs (Greenhouse / Lever / Ashby) and LinkedIn Post against a
fake HTTP server shaped like each documented API. No network or accounts needed (Company Jobs was also
checked live against public boards)."""
import asyncio
import json

import httpx
import pytest

import tools

calls = []


def handler(request: httpx.Request) -> httpx.Response:  # noqa: C901
    calls.append(request)
    host, path, q, h = request.url.host, request.url.path, request.url.params, request.headers
    if host == "serpapi.com":
        assert q["engine"] == "google_jobs" and q["api_key"] == "serp"
        if q["q"] == "nothing":
            return httpx.Response(200, json={"error": "Google hasn't returned any results for this query."})
        assert q.get("location") == "Bengaluru, India" and q.get("gl") == "in"
        return httpx.Response(200, json={"jobs_results": [
            {"title": "Data Engineer", "company_name": "Acme", "location": "Bengaluru", "via": "LinkedIn",
             "detected_extensions": {"posted_at": "2 days ago", "schedule_type": "Full-time", "salary": "₹25–35 LPA"},
             "apply_options": [{"title": "LinkedIn", "link": "https://linkedin.com/jobs/view/1"},
                               {"title": "Naukri.com", "link": "https://naukri.com/job/2"}]}],
            "serpapi_pagination": {"next_page_token": "tok2"}})
    if host == "api.adzuna.com":
        assert path == "/v1/api/jobs/in/search/1" and q["app_id"] == "aid" and q["app_key"] == "akey"
        assert q["what"] == "python developer" and q["where"] == "Pune" and q["sort_by"] == "date"
        return httpx.Response(200, json={"count": 120, "results": [
            {"title": "Python Developer", "company": {"display_name": "Infosys"}, "location": {"display_name": "Pune, Maharashtra"},
             "salary_min": 800000, "salary_max": 1200000, "salary_is_predicted": "0", "contract_time": "full_time",
             "created": "2026-11-01T10:00:00Z", "redirect_url": "https://www.adzuna.in/details/1"}]})
    if host == "jooble.org":
        if path != "/api/jkey":
            return httpx.Response(403, text="forbidden")
        body = json.loads(request.content)
        assert body["keywords"] == "react developer" and body["location"] == "Hyderabad"
        return httpx.Response(200, json={"totalCount": 42, "jobs": [
            {"title": "React Developer", "company": "TCS", "location": "Hyderabad", "salary": "₹12 LPA", "type": "Full-time",
             "source": "naukri.com", "updated": "2026-11-02T00:00:00", "link": "https://jooble.org/desc/1"}]})
    if host == "boards-api.greenhouse.io":
        if path == "/v1/boards/acme/jobs":
            return httpx.Response(200, json={"jobs": [
                {"title": "Backend Engineer ", "departments": [{"name": "Platform"}], "location": {"name": "Remote, India"},
                 "absolute_url": "https://acme.com/jobs/1"},
                {"title": "Recruiter", "departments": [{"name": "People"}], "location": {"name": "London"}, "absolute_url": "https://acme.com/jobs/2"}]})
        return httpx.Response(404, json={})
    if host == "api.lever.co":
        if path == "/v0/postings/leverco":
            assert q["mode"] == "json"
            return httpx.Response(200, json=[{"text": "SRE", "categories": {"team": "Infra", "location": "Berlin", "commitment": "Full-time"},
                                              "workplaceType": "hybrid", "hostedUrl": "https://jobs.lever.co/leverco/1"}])
        return httpx.Response(404, json={})
    if host == "api.ashbyhq.com":
        if path == "/posting-api/job-board/ashco":
            return httpx.Response(200, json={"jobs": [
                {"title": "Designer", "team": "Design", "location": "NYC", "employmentType": "FullTime", "workplaceType": "OnSite",
                 "jobUrl": "https://jobs.ashbyhq.com/ashco/1", "isListed": True,
                 "compensation": {"compensationTierSummary": "$150K – $180K"}},
                {"title": "Hidden", "isListed": False, "jobUrl": "x"}]})
        return httpx.Response(404, json={})
    if host == "api.linkedin.com":
        if h.get("authorization") != "Bearer li":
            return httpx.Response(401, json={})
        if path == "/v2/userinfo":
            return httpx.Response(200, json={"sub": "abc123", "name": "Ana"})
        if path == "/rest/posts":
            assert h["linkedin-version"] == "202610" and h["x-restli-protocol-version"] == "2.0.0"
            body = json.loads(request.content)
            assert body["author"] == "urn:li:person:abc123" and body["commentary"] == "Hello LinkedIn"
            assert body["visibility"] == "CONNECTIONS" and body["lifecycleState"] == "PUBLISHED"
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:999"})
    return httpx.Response(599, text=f"unexpected {request.method} {request.url}")


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


def test_google_jobs_shows_where_it_was_posted_and_apply_links():
    out = run("google_jobs", "data engineer", {"api_key": "serp", "location": "Bengaluru, India", "gl": "in"})
    assert "Data Engineer · Acme · Bengaluru · LinkedIn · 2 days ago · Full-time · ₹25–35 LPA" in out
    assert "apply on Naukri.com: https://naukri.com/job/2" in out and "next_page_token=tok2" in out
    assert "No jobs found" in run("google_jobs", "nothing", {"api_key": "serp"})
    assert "api_key" in run("google_jobs", "x", {})


def test_adzuna():
    out = run("adzuna_jobs", "python developer", {"app_id": "aid", "app_key": "akey", "country": "in", "where": "Pune"})
    assert "1 of 120 job(s) in India" in out and "Python Developer · Infosys · Pune, Maharashtra · 800,000–1,200,000" in out
    assert "country is one of" in run("adzuna_jobs", "x", {"app_id": "a", "app_key": "b", "country": "zz"})


def test_jooble():
    out = run("jooble_jobs", "react developer", {"api_key": "jkey", "location": "Hyderabad"})
    assert "1 of 42 job(s)" in out and "React Developer · TCS · Hyderabad · ₹12 LPA · Full-time · via naukri.com" in out
    assert "HTTP 403" in run("jooble_jobs", "react developer", {"api_key": "bad", "location": "Hyderabad"})


def test_company_jobs_tries_each_board():
    out = run("company_jobs", "acme", {"filter": "engineer"})
    assert "1 open role(s) at acme on Greenhouse matching 'engineer'" in out and "Backend Engineer · Platform · Remote, India" in out
    out = run("company_jobs", "leverco", {})
    assert "on Lever" in out and "SRE · Infra · Berlin · Full-time · hybrid" in out
    assert [c.url.host for c in calls] == ["boards-api.greenhouse.io", "api.lever.co"], "Greenhouse first, then Lever"
    out = run("company_jobs", "ashby:ashco", {})
    assert "Designer · Design · NYC · FullTime · OnSite · $150K – $180K" in out and "Hidden" not in out
    assert "No Greenhouse / Lever / Ashby job board" in run("company_jobs", "nobody", {})
    assert "Platform is one of" in run("company_jobs", "workday:acme", {})
    assert "board name" in run("company_jobs", "../etc", {})


def test_linkedin_post():
    out = run("linkedin_post", "Hello LinkedIn", {"access_token": "li", "visibility": "CONNECTIONS"})
    assert "Posted (connections)" in out and "urn:li:share:999" in out
    assert "openid" in run("linkedin_post", "Hello", {"access_token": "bad"})
    assert "3000" in run("linkedin_post", "x" * 3001, {"access_token": "li"})


def test_catalog():
    tools._load()
    jobs = [t for s in tools.catalog() for t in s["tools"] if t.get("category") == "Jobs & Careers"]
    assert {t["id"] for t in jobs} == {"google_jobs", "adzuna_jobs", "jooble_jobs", "company_jobs"}
