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


def _save(c: TestClient, code: str, graph: dict[str, Any]) -> None:
    version = c.get(f"/api/studio/scenarios/{code}").json()["version"]
    r = c.put(f"/api/studio/scenarios/{code}", json={"version": version, "graph": graph})
    assert r.status_code == 200, r.text


def test_submodel_is_embedded_with_its_inputs(make_client, db_session: Session, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    c = make_client("ivanov", "researcher")
    sid = _snap(db_session)
    c.post("/api/studio/scenarios", json={"title": "подмодель"})
    c.post("/api/studio/scenarios", json={"title": "главный"})
    _save(c, "SC-01", {"format": 1, "nodes": [
        {"id": "d", "type": "import.dataset", "params": {"snapshot_id": sid}},
        {"id": "o", "type": "control.output", "params": {}}], "edges": [{"from": "d", "to": "o", "port": "in"}]})
    _save(c, "SC-02", {"format": 1, "nodes": [
        {"id": "sub", "type": "control.submodel", "params": {"scenario": "sc-01"}}], "edges": []})
    r = c.post("/api/studio/scenarios/SC-02/run", json={})
    assert r.status_code == 201, r.text
    job = queue[-1]
    inner = job["graph"]["nodes"][0]["params"]["__graph__"]
    assert [n["id"] for n in inner["nodes"]] == ["d", "o"]
    assert set(job["inputs"]) == {"sub/d"}
    assert r.json()["inputs"]["sub#подмодель"] == {"scenario": "SC-01", "version": 2}
    _save(c, "SC-01", {"format": 1, "nodes": [
        {"id": "me", "type": "control.submodel", "params": {"scenario": "SC-01"}}], "edges": []})
    loop = c.post("/api/studio/scenarios/SC-01/run", json={})
    assert loop.status_code == 422 and "сама себя" in loop.json()["detail"]["message"]


def test_python_code_needs_owner_approval(make_client, db_session: Session, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    author = make_client("ivanov", "researcher")
    boss = make_client("boss", "owner")
    author.post("/api/studio/scenarios", json={"title": "код"})
    good = {"format": 1, "nodes": [{"id": "py", "type": "code.python", "params": {"code": "out = df"}}], "edges": []}
    _save(author, "SC-01", good)
    state = author.get("/api/studio/scenarios/SC-01").json()["python"]
    assert state == {"py": {"problems": [], "approved": False}}
    denied = author.post("/api/studio/scenarios/SC-01/run", json={})
    assert denied.status_code == 403 and "не одобрен" in denied.json()["detail"]["message"]
    assert author.post("/api/studio/scenarios/SC-01/approve-python", json={"node": "py"}).status_code == 403
    assert boss.post("/api/studio/scenarios/SC-01/approve-python", json={"node": "py"}).status_code == 200
    assert author.post("/api/studio/scenarios/SC-01/run", json={}).status_code == 201
    changed = {**good, "nodes": [{"id": "py", "type": "code.python", "params": {"code": "out = df.head()"}}]}
    _save(author, "SC-01", changed)
    assert author.post("/api/studio/scenarios/SC-01/run", json={"until": "py"}).status_code == 403  # код другой
    bad = {**good, "nodes": [{"id": "py", "type": "code.python", "params": {"code": "import os\nout = df"}}]}
    _save(author, "SC-01", bad)
    r = author.post("/api/studio/scenarios/SC-01/run", json={"until": "py"})
    assert r.status_code == 422 and "«os» не разрешена" in r.json()["detail"]["message"]
    assert boss.post("/api/studio/scenarios/SC-01/approve-python", json={"node": "py"}).status_code == 422


def test_reference_cycle_is_not_saved(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("ivanov", "researcher")
    c.post("/api/studio/scenarios", json={"title": "x"})
    g = {"format": 1, "nodes": [{"id": "a", "type": "control.ref", "params": {"node": "b"}},
                                {"id": "b", "type": "control.ref", "params": {"node": "a"}}], "edges": []}
    r = c.put("/api/studio/scenarios/SC-01", json={"version": 1, "graph": g})
    assert r.status_code == 422 and "цикл" in r.json()["detail"]["message"]


CONN = {"title": "[учётная база]", "kind": "postgresql", "host": "[хост]", "port": 5432, "database": "[база]",
        "username": "[читатель]", "password": "[пароль-заглушка]"}


def test_connections_keep_password_secret(make_client, db_session: Session, settings: Settings) -> None:  # type: ignore[no-untyped-def]
    from app.models import DbConnection
    from app.services import secrets as sec

    boss = make_client("boss", "owner")
    researcher = make_client("ivanov", "researcher")
    assert researcher.post("/api/studio/connections", json=CONN).status_code == 403
    created = boss.post("/api/studio/connections", json=CONN)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == "DB-01" and body["has_password"] and "password" not in body
    row = db_session.query(DbConnection).one()
    assert "[пароль-заглушка]" not in row.password_enc and sec.decrypt(settings, row.password_enc) == "[пароль-заглушка]"
    listed = researcher.get("/api/studio/connections").json()
    assert listed[0]["code"] == "DB-01" and "[пароль-заглушка]" not in str(listed)
    upd = boss.put("/api/studio/connections/DB-01", json={**CONN, "password": None, "allow_write": True}).json()
    assert upd["allow_write"] and sec.decrypt(settings, db_session.query(DbConnection).one().password_enc) == "[пароль-заглушка]"
    assert boss.delete("/api/studio/connections/DB-01").status_code == 204


def test_database_nodes_and_runner_credentials(make_client, db_session: Session, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    boss = make_client("boss", "owner")
    boss.post("/api/studio/connections", json=CONN)
    c = make_client("ivanov", "researcher")
    c.post("/api/studio/scenarios", json={"title": "база"})
    graph = {"format": 1, "nodes": [
        {"id": "q", "type": "import.database", "params": {"connection": "DB-01", "query": "SELECT 1"}},
        {"id": "w", "type": "export.database", "params": {"connection": "DB-01", "table": "t"}}],
        "edges": [{"from": "q", "to": "w", "port": "in"}]}
    _save(c, "SC-01", graph)
    denied = c.post("/api/studio/scenarios/SC-01/run", json={})
    assert denied.status_code == 403 and "запись не разрешена" in denied.json()["detail"]["message"]
    r = c.post("/api/studio/scenarios/SC-01/run", json={"until": "q"})  # только чтение — можно
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["inputs"]["q"]["connection"] == "DB-01" and queue[-1]["connections"] == ["DB-01"]
    assert "[пароль-заглушка]" not in str(queue[-1]) and "[пароль-заглушка]" not in str(run)
    w = TestClient(app)
    assert w.get(f"/api/studio/worker/{run['id']}/connections").status_code == 403  # без токена
    creds = w.get(f"/api/studio/worker/{run['id']}/connections", headers=TOKEN).json()
    assert creds["DB-01"]["password"] == "[пароль-заглушка]" and creds["DB-01"]["kind"] == "postgresql"
    w.post(f"/api/studio/worker/{run['id']}", headers=TOKEN, json={"status": "done"})
    assert w.get(f"/api/studio/worker/{run['id']}/connections", headers=TOKEN).status_code == 409  # расчёт закончен


def test_publish_and_call_web_service(make_client, db_session: Session, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    c = make_client("ivanov", "researcher")
    c.post("/api/studio/scenarios", json={"title": "сервис"})
    _save(c, "SC-01", {"format": 1, "nodes": [{"id": "i", "type": "control.input", "params": {"port": "in"}}],
                       "edges": []})
    no_out = c.post("/api/studio/scenarios/SC-01/publish", json={})
    assert no_out.status_code == 422 and "Выход подмодели" in no_out.json()["detail"]
    _save(c, "SC-01", {"format": 1, "nodes": [{"id": "i", "type": "control.input", "params": {"port": "in"}},
                                              {"id": "o", "type": "control.output", "params": {}}],
                       "edges": [{"from": "i", "to": "o", "port": "in"}]})
    assert c.post("/api/services/x", json={}).status_code == 404
    assert c.post("/api/studio/services/SC-01/run", json={}).status_code == 404  # не опубликован
    pub = c.post("/api/studio/scenarios/SC-01/publish", json={}).json()
    assert pub["published_version"] == 3
    rows = [{"a": 1}, {"a": 2}]
    call = c.post("/api/studio/services/SC-01/run", json={"inputs": {"in": rows}, "wait": 0})
    assert call.status_code == 200, call.text
    got = call.json()
    assert got["status"] == "queued" and got["output"] is None
    assert queue[-1]["inject"] == {"in": rows} and queue[-1]["output"] is True and queue[-1]["version"] == 3
    out = {"columns": ["a"], "rows": [[1], [2]], "total": 2}
    TestClient(app).post(f"/api/studio/worker/{got['run_id']}", headers=TOKEN,
                         json={"status": "done", "views": {"__output__": out}})
    assert c.get(f"/api/studio/services/runs/{got['run_id']}").json()["output"] == out
    assert c.post("/api/studio/services/SC-01/run", json={"inputs": {"x": []}, "wait": 0}).status_code == 422
    c.delete("/api/studio/scenarios/SC-01/publish")
    assert c.post("/api/studio/services/SC-01/run", json={"wait": 0}).status_code == 404

