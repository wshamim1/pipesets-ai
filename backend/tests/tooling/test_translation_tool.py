"""Translation tool — DeepL (API key) and LibreTranslate (free), against a fake HTTP server."""
import asyncio
import json

import httpx
import pytest

import tools

calls = []


def handler(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    if request.url.host == "api.libretranslate.com":
        body = json.loads(request.content) if request.content else {}
        return httpx.Response(200, json={"translatedText": f"[{body.get('source', '?')} → {body.get('target', '?')}] {body.get('q', '')}"})
    if request.url.host == "api-free.deepl.com":
        body = json.loads(request.content) if request.content else {}
        translated = (body.get("text") or [""])[0]
        return httpx.Response(200, json={"translations": [{"detected_source_language": "FR", "text": f"[{body.get('target_lang', '?')}] {translated}"}]})
    return httpx.Response(599, json={"error": f"unexpected request {request.method} {request.url}"})


@pytest.fixture
def vendors(monkeypatch):
    real = httpx.AsyncClient

    class FakeClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


def run(tool, inp, cfg):
    calls.clear()
    return asyncio.run(tools.execute(tool, inp, cfg))


def test_libretranslate(vendors):
    out = run("translation", "hello world", {"source": "auto", "target": "es"})
    assert calls[0].url.host == "api.libretranslate.com"
    assert json.loads(calls[0].content) == {"q": "hello world", "source": "auto", "target": "es"}
    assert out == "[Translation] auto → es\n[auto → es] hello world"


def test_deepl(vendors):
    out = run("translation", "bonjour", {"api_key": "test-deepl-key", "source": "auto", "target": "en"})
    assert calls[0].url.host == "api-free.deepl.com"
    body = json.loads(calls[0].content)
    assert body["auth_key"] == "test-deepl-key" and body["target_lang"] == "EN"
    assert out == "[Translation] auto → en\n[EN] bonjour"


def test_deepl_passes_the_source(vendors):
    run("translation", "hallo welt", {"api_key": "k", "source": "de", "target": "en"})
    assert json.loads(calls[0].content)["source_lang"] == "DE"


def test_empty_input():
    out = run("translation", "   ", {"source": "auto", "target": "es"})
    assert "Please provide the text" in out


def test_execute_rejects_undeclared_arguments():
    out = asyncio.run(tools.execute("translation", "hi", {"source": "auto", "target": "es"}, {"text": "hi", "nope": 1}))
    assert "unknown argument" in out
