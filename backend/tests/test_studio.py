"""Студия на платформе: сценарии SC-NN, версии, права, постановка расчёта, отчёт исполнителя.
Расчёт не выполняется (его делает runner/studio) — проверяется, что уходит в очередь. Заглушки."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import app
from app.models import Dataset, DatasetSnapshot
from app.services import run_queue

REPO = Path(__file__).resolve().parents[2]
TOKEN = {"X-Runner-Token": "tok"}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev",
                    runner_token="tok", repo_dir=str(REPO), esg_data_dir=str(tmp_path / "srv"),
                    esg_data_host="C:/data")


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    monkeypatch.setattr(run_queue, "enqueue_studio", lambda _b, _id, job: jobs.append(job) or "t")
    monkeypatch.setattr(run_queue, "is_alive", lambda *_a, **_k: False)
    monkeypatch.setattr(run_queue, "request_stop", lambda *_a, **_k: None)
    monkeypatch.setattr(run_queue, "revoke", lambda *_a, **_k: None)
    return jobs


def _snap(db: Session, code: str = "DS-01", access: str = "public") -> int:
    ds = Dataset(code=code, title="[набор]", access_level=access)
    db.add(ds)
    db.flush()
    s = DatasetSnapshot(dataset_id=ds.id, version="v1", sha256="0" * 64,
                        storage_path=f"C:/data/{code}/v1/t.csv", row_count=5)
    db.add(s)
    db.commit()
    return s.id


def _graph(snapshot_id: int) -> dict[str, Any]:
    return {"format": 1,
            "nodes": [{"id": "src", "type": "import.dataset", "params": {"snapshot_id": snapshot_id}},
                      {"id": "f", "type": "transform.filter", "params": {"expr": "[a] > 1"}},
                      {"id": "out", "type": "export.file", "params": {"name": "итог"}}],
            "edges": [{"from": "src", "to": "f", "port": "in"}, {"from": "f", "to": "out", "port": "in"}]}


def test_components_come_from_engine_catalog(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("rd", "reader")
    comps = c.get("/api/studio/components").json()["components"]
    assert len([x for x in comps if x["group"] == "Трансформация"]) == 15


def test_create_save_versions_and_rights(make_client, db_session: Session, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    author = make_client("ivanov", "researcher")
    other = make_client("petrov", "researcher")
    reader = make_client("rd", "reader")
    assert reader.post("/api/studio/scenarios", json={"title": "x"}).status_code == 403
    s = author.post("/api/studio/scenarios", json={"title": "Отрасли и ROE"}).json()
    assert s["code"] == "SC-01" and s["version"] == 1
    graph = _graph(_snap(db_session))
    saved = author.put("/api/studio/scenarios/SC-01", json={"version": 1, "graph": graph})
    assert saved.status_code == 200 and saved.json()["version"] == 2
    stale = author.put("/api/studio/scenarios/SC-01", json={"version": 1, "graph": graph})
    assert stale.status_code == 409  # изменили без вас
    assert other.put("/api/studio/scenarios/SC-01", json={"version": 2, "graph": graph}).status_code == 403
    copy = other.post("/api/studio/scenarios/SC-01/copy").json()
    assert copy["code"] == "SC-02" and copy["author"] == "petrov" and copy["nodes"] == 3
    assert [v["version"] for v in reader.get("/api/studio/scenarios/SC-01/versions").json()] == [2, 1]
    assert reader.get("/api/studio/scenarios/SC-01").json()["editable"] is False


@pytest.mark.parametrize(("graph", "message"), [
    ({"format": 2, "nodes": [], "edges": []}, "формат"),
    ({"format": 1, "nodes": [{"id": "a", "type": "нет.такого"}], "edges": []}, "Неизвестный компонент"),
    ({"format": 1, "nodes": [{"id": "a", "type": "transform.sort"}, {"id": "b", "type": "transform.sort"}],
      "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}, "цикл"),
    ({"format": 1, "nodes": [{"id": "a", "type": "transform.sort"}, {"id": "b", "type": "transform.merge"}],
      "edges": [{"from": "a", "to": "b", "port": "ref"}]}, "нет входа"),
])
def test_broken_graph_is_not_saved(make_client, graph: dict, message: str) -> None:  # type: ignore[no-untyped-def,type-arg]
    c = make_client("ivanov", "researcher")
    c.post("/api/studio/scenarios", json={"title": "x"})
    r = c.put("/api/studio/scenarios/SC-01", json={"version": 1, "graph": graph})
    assert r.status_code == 422 and message in r.json()["detail"]["message"]


def test_run_and_preview_go_to_studio_queue(make_client, db_session: Session, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    c = make_client("ivanov", "researcher")
    c.post("/api/studio/scenarios", json={"title": "x"})
    sid = _snap(db_session)
    c.put("/api/studio/scenarios/SC-01", json={"version": 1, "graph": _graph(sid)})
    preview = c.post("/api/studio/scenarios/SC-01/run", json={"until": "f"})
    assert preview.status_code == 201, preview.text
    job = queue[-1]
    assert job["until"] == "f" and job["rows"] == 100 and job["version"] == 2
    assert job["inputs"] == {"src": {"path": "C:/data/DS-01/v1/t.csv", "sha256": "0" * 64, "sheet": ""}}
    full = c.post("/api/studio/scenarios/SC-01/run", json={})
    assert full.status_code == 201 and queue[-1]["until"] == ""
    again = c.post("/api/studio/scenarios/SC-01/run", json={})
    assert again.status_code == 409  # свой полный расчёт уже идёт
    assert c.post("/api/studio/scenarios/SC-01/run", json={"until": "нет"}).status_code == 422


def test_worker_reports_and_nda_hides_results(make_client, db_session: Session, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    boss = make_client("boss", "owner")
    boss.post("/api/studio/scenarios", json={"title": "x"})
    boss.put("/api/studio/scenarios/SC-01", json={"version": 1, "graph": _graph(_snap(db_session, access="nda"))})
    researcher = make_client("ivanov", "researcher")
    assert researcher.post("/api/studio/scenarios/SC-01/copy").status_code == 201
    no = researcher.post("/api/studio/scenarios/SC-02/run", json={})
    assert no.status_code == 403 and "NDA" in no.json()["detail"]["message"]
    run_id = boss.post("/api/studio/scenarios/SC-01/run", json={}).json()["id"]
    w = TestClient(app)
    assert w.post(f"/api/studio/worker/{run_id}", headers=TOKEN, json={"status": "running"}).status_code == 200
    view = {"table": {"columns": [{"name": "[a]", "kind": "integer"}], "rows": [[2]], "total": 1}}
    done = {"status": "done", "summary": {"nodes": {"f": {"ok": True, "rows": 1}}}, "views": {"f": view},
            "files": ["итог.csv"], "results_path": "C:/data/studio/SC-01/run-00001",
            "runner_commit": "[коммит]", "env_lock_sha256": "1" * 64, "python": "3.12"}
    assert w.post(f"/api/studio/worker/{run_id}", headers=TOKEN, json=done).status_code == 200
    assert w.post(f"/api/studio/worker/{run_id}", headers=TOKEN, json=done).status_code == 409
    got = boss.get(f"/api/studio/runs/{run_id}").json()
    assert got["status"] == "done" and got["views"]["f"]["table"]["total"] == 1 and got["runner_commit"]
    hidden = researcher.get(f"/api/studio/runs/{run_id}").json()
    assert hidden["hidden"] and hidden["views"] == {} and hidden["files"] == []
    assert researcher.get(f"/api/studio/runs/{run_id}/files/итог.csv").status_code == 403
    assert w.post(f"/api/studio/worker/{run_id}", json=done).status_code == 403  # без токена


def test_stop_and_orphans(make_client, db_session: Session, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    c = make_client("ivanov", "researcher")
    c.post("/api/studio/scenarios", json={"title": "x"})
    c.put("/api/studio/scenarios/SC-01", json={"version": 1, "graph": _graph(_snap(db_session))})
    queued = c.post("/api/studio/scenarios/SC-01/run", json={}).json()["id"]
    assert c.post(f"/api/studio/runs/{queued}/stop").json()["status"] == "stopped"
    running = c.post("/api/studio/scenarios/SC-01/run", json={"until": "f"}).json()["id"]
    w = TestClient(app)
    w.post(f"/api/studio/worker/{running}", headers=TOKEN, json={"status": "running"})
    assert w.post("/api/studio/worker/orphans", headers=TOKEN).json() == {"failed": 1}
    assert c.get(f"/api/studio/runs/{running}").json()["status"] == "failed"
