from typing import Any

import pytest
from sqlalchemy.orm import Session

import app.api.runs as runs_api
from app.config import Settings
from app.models import Dataset, DatasetSnapshot, Experiment

SHA = "c" * 64
TOKEN = {"X-Runner-Token": "tok"}


@pytest.fixture
def settings() -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", runner_token="tok")


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Очередь без Redis: задачи складываются в список."""
    sent: list[dict[str, Any]] = []

    def enqueue(broker: str, run_id: int, job: dict[str, Any], queue: str) -> str:
        sent.append({"job": job, "queue": queue})
        return f"run-{run_id}"

    monkeypatch.setattr(runs_api.run_queue, "enqueue", enqueue)
    monkeypatch.setattr(runs_api.run_queue, "request_stop", lambda url, run_id: None)
    monkeypatch.setattr(runs_api.run_queue, "revoke", lambda broker, task_id: None)
    ALIVE.clear()
    monkeypatch.setattr(runs_api.run_queue, "is_alive", lambda url, run_id: run_id in ALIVE)
    return sent


ALIVE: set[int] = set()  # запуски, у которых есть пульс исполнителя


@pytest.fixture
def snapshot(db_session: Session) -> int:
    ds = Dataset(code="DS-01", title="Dow30", access_level="public")
    db_session.add(ds)
    db_session.add(Experiment(code="EXP-001", title="рейтинги", status="review", config={}, setup=[],
                              results=[], limitations=[], reproducibility=[]))
    db_session.flush()
    snap = DatasetSnapshot(dataset_id=ds.id, version="2026-10-30", sha256=SHA,
                           storage_path=r"C:\data\DS-01\raw\dow30.csv")
    db_session.add(snap)
    db_session.commit()
    return snap.id


def _launch(c, snapshot: int, **params: Any):  # type: ignore[no-untyped-def]
    return c.post("/api/runs", json={"template": "exp001-dow30", "snapshot_id": snapshot, "params": params})


def _run_json() -> dict[str, Any]:
    return {"runner_commit": "abc1234", "dataset": {"code": "DS-01", "sha256": SHA},
            "env_lock_sha256": "b" * 64, "python": "3.12.10", "seeds": {"bootstrap": 42},
            "parts": {"spearman": {"exit_code": 0, "seconds": 3}}}


def test_reader_cannot_launch(make_client, snapshot: int, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    assert _launch(make_client("r", "reader"), snapshot).status_code == 403
    assert queue == []


def test_launch_checks_params_and_snapshot(make_client, snapshot: int, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    c = make_client("res", "researcher")
    assert _launch(c, snapshot, n_boot=5).status_code == 422  # меньше минимума
    assert _launch(c, snapshot, unknown=1).status_code == 422
    assert _launch(c, snapshot, seed="42").status_code == 422
    assert _launch(c, snapshot + 100).status_code == 422
    assert c.post("/api/runs", json={"template": "nope", "snapshot_id": snapshot}).status_code == 404
    assert queue == []


def test_launch_queues_job_with_snapshot(make_client, snapshot: int, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    c = make_client("res", "researcher")
    r = _launch(c, snapshot, seed=7)
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "queued" and run["config"]["params"] == {"seed": 7, "n_boot": 10000, "n_perm": 10000}
    job = queue[0]["job"]
    assert queue[0]["queue"] == "cpu" and job["snapshot_sha256"] == SHA
    assert job["args"] == ["--seed", "7", "--n-boot", "10000", "--n-perm", "10000"]


def test_worker_cycle_fills_reproducibility(make_client, snapshot: int, queue: list,  # type: ignore[no-untyped-def,type-arg]
                                            db_session: Session) -> None:
    c = make_client("res", "researcher")
    run_id = _launch(c, snapshot).json()["id"]
    assert c.post(f"/api/runs/worker/{run_id}", json={"status": "running"}).status_code == 403
    r = c.post(f"/api/runs/worker/{run_id}", headers=TOKEN, json={"status": "running"})
    assert r.json()["status"] == "running"
    r = c.post(f"/api/runs/worker/{run_id}", headers=TOKEN,
               json={"status": "done", "run": _run_json(), "mlflow_run_id": "ml1"})
    body = r.json()
    assert body["status"] == "done" and body["reproducible"] and body["mlflow_run_id"] == "ml1"
    exp = db_session.query(Experiment).filter_by(code="EXP-001").one()
    db_session.refresh(exp)
    assert exp.runner_commit == "abc1234" and exp.seed == 42
    # законченный запуск исполнитель не переписывает
    late = c.post(f"/api/runs/worker/{run_id}", headers=TOKEN, json={"status": "failed"})
    assert late.status_code == 409


def test_failed_run_does_not_touch_experiment(make_client, snapshot: int, queue: list,  # type: ignore[no-untyped-def,type-arg]
                                              db_session: Session) -> None:
    c = make_client("res", "researcher")
    run_id = _launch(c, snapshot).json()["id"]
    r = c.post(f"/api/runs/worker/{run_id}", headers=TOKEN,
               json={"status": "stopped", "run": _run_json(), "message": "остановлен"})
    assert r.json()["status"] == "stopped" and not r.json()["reproducible"]
    exp = db_session.query(Experiment).filter_by(code="EXP-001").one()
    assert exp.runner_commit == ""


def test_stop_queued_run_and_permissions(make_client, snapshot: int, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    author = make_client("res", "researcher")
    other = make_client("res2", "researcher")
    run_id = _launch(author, snapshot).json()["id"]
    assert other.post(f"/api/runs/{run_id}/stop").status_code == 403
    r = author.post(f"/api/runs/{run_id}/stop")
    assert r.status_code == 200 and r.json()["status"] == "stopped"
    assert author.post(f"/api/runs/{run_id}/stop").status_code == 409


def test_stop_running_run_waits_for_live_runner(make_client, snapshot: int, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    """Исполнитель ведёт расчёт (есть пульс) — остановка только запрашивается, итог пришлёт он."""
    c = make_client("res", "researcher")
    run_id = _launch(c, snapshot).json()["id"]
    c.post(f"/api/runs/worker/{run_id}", headers=TOKEN, json={"status": "running"})
    ALIVE.add(run_id)
    r = c.post(f"/api/runs/{run_id}/stop")
    assert r.status_code == 200 and r.json()["status"] == "running"
    assert "запрошена" in r.json()["message"]


def test_stop_orphan_run_releases_it(make_client, snapshot: int, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    """«Идёт», а пульса нет (итог не дошёл до платформы, исполнитель упал) — снимается сразу,
    иначе висел бы «идёт» и занимал место в лимите проверок."""
    c = make_client("res", "researcher")
    run_id = _launch(c, snapshot).json()["id"]
    c.post(f"/api/runs/worker/{run_id}", headers=TOKEN, json={"status": "running"})
    r = c.post(f"/api/runs/{run_id}/stop")
    assert r.status_code == 200 and r.json()["status"] == "stopped"
    assert "уже не вёл" in r.json()["message"]
    # итог, пришедший потом, запуск не переписывает
    assert c.post(f"/api/runs/worker/{run_id}", headers=TOKEN, json={"status": "failed"}).status_code == 409


def test_orphans_fail_running_runs(make_client, snapshot: int, queue: list,  # type: ignore[no-untyped-def,type-arg]
                                   db_session: Session) -> None:
    c = make_client("res", "researcher")
    run_id = _launch(c, snapshot).json()["id"]
    c.post(f"/api/runs/worker/{run_id}", headers=TOKEN, json={"status": "running"})
    exp = db_session.query(Experiment).filter_by(code="EXP-001").one()
    exp.status = "running"
    db_session.commit()
    assert c.post("/api/runs/worker/orphans?queue=cpu", headers=TOKEN).json() == {"failed": 1}
    assert c.get(f"/api/runs/{run_id}").json()["status"] == "failed"
    # проверка не висит «в работе»: её единственный расчёт закончился сбоем
    db_session.refresh(exp)
    assert exp.status == "failed"
