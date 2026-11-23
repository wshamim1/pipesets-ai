"""The OKF bundle loader (loaders/files/okf.py): frontmatter, reserved files, trust tiers, freshness,
status filtering, links, zip bundles and the spec's "never reject" consumer rules."""
import asyncio
import os
import zipfile
from datetime import datetime, timezone

import pytest

import loaders
from loaders.base import LoaderError
from loaders.files.okf import parse_bundle, trust_tier

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def md(front: str, body: str = "") -> bytes:
    return f"---\n{front}\n---\n{body}".encode()


BUNDLE = {
    "index.md": md('okf_version: "0.3"\ntitle: Support KB', "* [Refunds](/policies/refunds.md) - refund rules\n"),
    "log.md": b"# 2026-11-01\nAdded refunds.\n",
    "policies/refunds.md": md(
        "type: policy\ntitle: Refunds\ndescription: How refunds work\ntags: [billing, refunds]\n"
        "generated: {by: writer/1.0, at: 2026-10-01T00:00:00Z}\n"
        "verified:\n  - {by: 'human:ana', at: 2026-10-02T00:00:00Z}\n"
        "sources:\n  - {id: s1, resource: 'https://example.com/terms'}\n",
        "Refunds within 30 days. See [plans](plans.md) and [terms](https://example.com/terms).\n"),
    "policies/plans.md": md("type: product\ntitle: Plans\nverified: {by: 'process:ci', at: 2026-10-05}\n"
                            "stale_after: 2026-11-01T00:00:00Z", "Pro is $20.\n"),
    "policies/old-refunds.md": md("type: policy\nstatus: deprecated\nsuperseded_by: /policies/refunds.md", "14 days.\n"),
    "notes/no-frontmatter.md": b"Just a note.\n",
    "notes/no-type.md": md("title: Missing type"),
    "notes/weird.md": md("type: gizmo\nunknown_key: 1\nstatus: draft", "Links to [nowhere](/missing.md).\n"),
}


def files(d=BUNDLE):
    return list(d.items())


def by_path(docs):
    return {d["metadata"]["okf_path"]: d for d in docs}


def test_concepts_reserved_and_nonconformant_files():
    docs = by_path(parse_bundle(files(), "kb", {}, NOW))
    assert set(docs) == {"policies/refunds.md", "policies/plans.md", "notes/weird.md"}
    r = docs["policies/refunds.md"]["metadata"]
    assert r["okf_type"] == "policy" and r["okf_version"] == "0.3" and r["tags"] == ["billing", "refunds"]
    assert r["sources"] == ["https://example.com/terms"] and r["source"] == "kb/policies/refunds.md"
    assert r["links"] == ["policies/plans.md"]                      # relative to the file (v0.3); external dropped
    assert docs["notes/weird.md"]["metadata"]["links"] == ["missing.md"]   # broken links tolerated
    skipped = parse_bundle(files(), "kb", {}, NOW)[0]["metadata"]["okf_skipped"]
    assert skipped == {"nonconformant": 2, "deprecated": 1}


def test_header_tells_the_model_status_and_trust():
    docs = by_path(parse_bundle(files(), "kb", {}, NOW))
    text = docs["policies/plans.md"]["text"]
    assert text.startswith("# Plans\n[OKF product · status: stable · trust: machine · STALE]")
    assert "Pro is $20." in text


def test_trust_tiers():
    assert trust_tier({}) == "unverified"
    assert trust_tier({"verified": {"by": "process:ci", "at": "2026-01-01"}}) == "machine"
    assert trust_tier({"verified": [{"by": "team:x", "at": "2026-01-01"}, {"by": "human:a", "at": "2026-01-02"}]}) == "human"
    # Only verifications at or after generation count
    assert trust_tier({"generated": {"by": "x", "at": "2026-05-01T00:00:00Z"},
                       "verified": [{"by": "human:a", "at": "2026-04-01T00:00:00Z"}]}) == "unverified"


def test_filters():
    paths = lambda cfg: set(by_path(parse_bundle(files(), "kb", cfg, NOW)))  # noqa: E731
    assert "policies/old-refunds.md" in paths({"okf_include_deprecated": True})
    assert "policies/plans.md" not in paths({"okf_include_stale": False})
    assert paths({"okf_min_trust": "human"}) == {"policies/refunds.md"}
    assert paths({"okf_min_trust": "machine"}) == {"policies/refunds.md", "policies/plans.md"}
    with pytest.raises(LoaderError):
        parse_bundle(files(), "kb", {"okf_min_trust": "nope"}, NOW)


def test_deprecated_metadata_names_replacement():
    d = by_path(parse_bundle(files(), "kb", {"okf_include_deprecated": True}, NOW))["policies/old-refunds.md"]
    assert d["metadata"]["status"] == "deprecated" and d["metadata"]["superseded_by"] == "/policies/refunds.md"
    assert "superseded by /policies/refunds.md" in d["text"]


def test_v02_links_fall_back_to_bundle_root():
    b = {"a/x.md": md("type: t", "[y](b/y.md)"), "b/y.md": md("type: t")}
    assert by_path(parse_bundle(list(b.items()), "kb", {}, NOW))["a/x.md"]["metadata"]["links"] == ["b/y.md"]


def test_nothing_loadable_explains_why():
    with pytest.raises(LoaderError, match="1 deprecated"):
        parse_bundle([("x.md", md("type: t\nstatus: deprecated"))], "kb", {}, NOW)
    with pytest.raises(LoaderError, match="No concept files"):
        parse_bundle([("index.md", b"")], "kb", {}, NOW)


def _write(root, bundle):
    for rel, data in bundle.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)


def test_load_folder_and_zip(tmp_path):
    root = tmp_path / "kb"
    _write(str(root), BUNDLE)
    docs = asyncio.run(loaders.load_documents("okf", str(root)))
    assert {d["metadata"]["okf_path"] for d in docs} == {"policies/refunds.md", "policies/plans.md", "notes/weird.md"}

    z = tmp_path / "kb.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for rel, data in BUNDLE.items():
            zf.writestr(f"kb/{rel}", data)            # zipped folder: one top-level dir
        zf.writestr("__MACOSX/kb/._x.md", b"junk")
        zf.writestr("../evil.md", md("type: t"))       # path traversal ignored
    docs = asyncio.run(loaders.load_documents("open_knowledge_format", str(z)))
    assert {d["metadata"]["okf_path"] for d in docs} == {"policies/refunds.md", "policies/plans.md", "notes/weird.md"}


def test_load_errors(tmp_path):
    with pytest.raises(LoaderError, match="not found"):
        asyncio.run(loaders.load_documents("okf", str(tmp_path / "nope")))
    f = tmp_path / "x.md"
    f.write_bytes(b"x")
    with pytest.raises(LoaderError, match="folder or a .zip"):
        asyncio.run(loaders.load_documents("okf", str(f)))
