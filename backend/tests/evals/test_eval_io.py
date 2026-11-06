"""Eval Excel / CSV import + export, and pipeline-backed eval runs (mock LLM)."""
import io

import pytest
from openpyxl import Workbook, load_workbook

from helpers import mock_flow

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx(rows):
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(scope="module")
def ds(client):
    return client.post("/api/eval/datasets", json={"name": "Imported"}).json()["id"]


def test_import(client, ds):
    # Header aliases, a title row above the header, blank rows, ';'-separated tags, an in-file duplicate
    book = xlsx([["My test sheet"], ["Question", "Answer", "Category"],
                 ["Weather in Allentown?", "Allentown", "happy path; tool_use"],
                 [None, None, None],
                 ["weather in allentown", "dup", ""],
                 ["Tell me a joke", None, "edge_case"]])
    r = client.post(f"/api/eval/datasets/{ds}/import", files={"file": ("cases.xlsx", book, XLSX)}).json()
    assert r["cases_created"] == 2 and r["skipped_duplicates"] == 1
    assert r["columns"] == {"prompt": "Question", "expected": "Answer", "tags": "Category"}
    cases = client.get(f"/api/eval/datasets/{ds}/cases").json()
    assert cases[0]["tags"] == ["happy_path", "tool_use"] and cases[0]["source"] == "import"

    r = client.post(f"/api/eval/datasets/{ds}/import",
                    files={"file": ("x.csv", b"Brand new prompt;expected bit\nAnother one;\n", "text/csv")}).json()
    assert r["cases_created"] == 2 and r["columns"]["prompt"] == "column A", "headerless csv, ; delimiter"
    r = client.post(f"/api/eval/datasets/{ds}/import", data={"replace": "all"},
                    files={"file": ("x.csv", b"prompt\nOnly me\n", "text/csv")}).json()
    assert r["cases_created"] == 1 and r["replaced"] == 4
    assert client.post(f"/api/eval/datasets/{ds}/import",
                       files={"file": ("x.pdf", b"%PDF", "application/pdf")}).status_code == 400
    assert client.post(f"/api/eval/datasets/{ds}/import",
                       files={"file": ("x.csv", b"prompt\n\n", "text/csv")}).status_code == 400


def test_template_and_dataset_export(client, ds):
    wb = load_workbook(io.BytesIO(client.get("/api/eval/import-template").content))
    assert [x.value for x in wb.active[1]] == ["prompt", "expected_output", "tags"]

    exp = client.get(f"/api/eval/datasets/{ds}/export?format=xlsx")
    wb = load_workbook(io.BytesIO(exp.content))
    assert exp.headers["content-disposition"].endswith('Imported.xlsx"') and wb.active.cell(2, 1).value == "Only me"
    csv = client.get(f"/api/eval/datasets/{ds}/export?format=csv").content.decode("utf-8-sig")
    assert csv.splitlines()[1].startswith("Only me")


def test_pipeline_backed_run_and_export(client):
    app = client.post("/api/apps", json={"name": "Mocky", "description": "", "flow_data": mock_flow("l")}).json()
    client.post(f"/api/apps/{app['id']}/publish")
    run_ds = client.post("/api/eval/datasets", json={"name": "Run me", "app_id": app["id"], "app_version": 1}).json()["id"]
    client.post(f"/api/eval/datasets/{run_ds}/cases/bulk", json={"cases": [
        {"prompt": "hello", "expected_output": "", "tags": ["happy_path"]},
        {"prompt": "zzz", "expected_output": "definitely-not-in-output-xyz", "tags": ["edge_case"]}]})
    run = client.post("/api/eval/run", json={"app_id": app["id"], "app_version": 1, "dataset_id": run_ds,
                                             "scorer": "contains"}).json()
    assert run["total"] == 2 and all(r["actual_output"] for r in run["results"])
    assert run["app_version"] == 1 and run["results"][1]["tags"] == ["edge_case"]
    assert run["results"][1]["pass"] == 0, "contains scorer fails a missing phrase"
    assert client.get(f"/api/eval/runs/{run['id']}/results").json()[0]["tags"] == ["happy_path"]

    wb = load_workbook(io.BytesIO(client.get(f"/api/eval/runs/{run['id']}/export?format=xlsx").content))
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(min_row=2, values_only=True)}
    assert wb.sheetnames == ["Summary", "Results", "By tag"]
    assert summary["Pipeline"] == "Mocky v1" and summary["Cases"] == 2
    assert wb["Results"].max_row == 3 and wb["Results"].cell(3, 2).value == "FAIL"
    csv = client.get(f"/api/eval/runs/{run['id']}/export?format=csv").content.decode("utf-8-sig")
    assert csv.splitlines()[0].startswith("#,result,score")
