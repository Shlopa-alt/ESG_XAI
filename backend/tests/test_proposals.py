from typing import Any

import pytest
from sqlalchemy.orm import Session

import app.api.runs as runs_api
from app.config import Settings
from app.models import Dataset, DatasetSnapshot, ExperimentProposal, Hypothesis, QwenJob
from app.services.run_templates import TEMPLATES, ParamError, check_params

TOKEN = {"X-Qwen-Token": "tok"}


@pytest.fixture
def settings() -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", qwen_token="tok")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_api.run_queue, "enqueue", lambda b, rid, job, q: jobs.append(job) or f"run-{rid}")
    return jobs


@pytest.fixture
def snapshot(db_session: Session) -> int:
    ds = Dataset(code="DS-04", title="TWSE", access_level="public")
    db_session.add(ds)
    db_session.flush()
    snap = DatasetSnapshot(dataset_id=ds.id, version="2026-10-30", sha256="a" * 64, storage_path="/data/esg/x.csv")
    db_session.add(snap)
    db_session.add(Hypothesis(code="H-001", title="ESG и ROA", statement="ESG-признаки предсказывают ROA",
                              status="proposed", source="qwen"))
    db_session.commit()
    return snap.id


def test_generic_params_checked_against_columns() -> None:
    t = TEMPLATES["predictive-check"]
    cols, num = ["roa", "x1", "x2", "name"], {"roa", "x1", "x2"}
    ok = check_params(t, {"target": "roa", "features": ["x1", "x2"]}, cols, num)
    assert ok["splits"] == 30 and ok["features"] == ["x1", "x2"]
    for bad in ({"target": "roa", "features": ["x9"]}, {"target": "roa", "features": ["name"]},
                {"target": "roa", "features": ["roa", "x1"]}, {"target": "", "features": ["x1"]}):
        with pytest.raises(ParamError):
            check_params(t, bad, cols, num)
    with pytest.raises(ParamError):
        check_params(TEMPLATES["rank-agreement"], {"columns": ["x1"]}, cols, num)


def test_accept_queues_qwen_proposal(make_client, snapshot: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    rev = make_client("rev", "reviewer")
    assert rev.patch("/api/hypotheses/H-001", json={"status": "accepted"}).status_code == 200
    job = db_session.query(QwenJob).filter_by(kind="experiment").one()
    assert job.payload == {"hypothesis": "H-001"} and job.trigger == "hypothesis"


def _proposal(db: Session, snapshot: int, method: str = "exp007-hsu") -> int:
    h = db.query(Hypothesis).filter_by(code="H-001").one()
    h.status = "accepted"
    p = ExperimentProposal(hypothesis_id=h.id, title="Повтор Hsu", method=method, snapshot_id=snapshot,
                           params={"seed": 7, "trials": 20}, setup=["шаг"], expected="R² < 0,1 — опровергнет")
    db.add(p)
    db.commit()
    return p.id


def test_approve_creates_experiment_and_run(make_client, snapshot: int, sent: list,  # type: ignore[no-untyped-def,type-arg]
                                            db_session: Session) -> None:
    c = make_client("res", "researcher")
    pid = _proposal(db_session, snapshot)
    r = c.post(f"/api/experiment-proposals/{pid}/approve", json={"title": "Повтор Hsu на DS-04"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved" and body["experiment"] == "EXP-001" and body["run_id"]
    assert sent[0]["experiment"] == "EXP-001" and sent[0]["args"] == ["--seed", "7", "--trials", "20"]
    exp = c.get("/api/experiments/EXP-001").json()
    assert exp["title"] == "Повтор Hsu на DS-04" and exp["status"] == "running"
    assert c.get("/api/hypotheses/H-001").json()["status"] == "testing"
    assert c.post(f"/api/experiment-proposals/{pid}/reject", json={"note": "поздно"}).status_code == 409


def test_approve_refuses_problems_and_reject_needs_note(make_client, snapshot: int, sent: list,  # type: ignore[no-untyped-def,type-arg]
                                                        db_session: Session) -> None:
    c = make_client("res", "researcher")
    pid = _proposal(db_session, snapshot, method="")
    assert c.post(f"/api/experiment-proposals/{pid}/approve", json={}).status_code == 422
    assert sent == []
    assert c.post(f"/api/experiment-proposals/{pid}/reject", json={"note": ""}).status_code == 422
    assert c.post(f"/api/experiment-proposals/{pid}/reject", json={"note": "нет данных"}).json()["status"] == "rejected"


def test_reader_cannot_approve(make_client, snapshot: int, sent: list, db_session: Session) -> None:  # type: ignore[no-untyped-def,type-arg]
    pid = _proposal(db_session, snapshot)
    assert make_client("r", "reader").post(f"/api/experiment-proposals/{pid}/approve", json={}).status_code == 403
