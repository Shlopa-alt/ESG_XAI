"""Проверка не висит «в работе» после расчётов, ход работы и вывод видны сразу (п. 12–13 фидбека).
Данные — заглушки."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Experiment, ExperimentReport, Run
from app.services.experiments import progress, refresh_after_runs

TOKEN = {"X-Runner-Token": "tok"}


@pytest.fixture
def settings() -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", runner_token="tok")


def _exp(db: Session, code: str = "EXP-010", status: str = "running") -> Experiment:
    e = Experiment(code=code, title="[проверка]", status=status, config={}, setup=[], results=[],
                   limitations=[], reproducibility=[])
    db.add(e)
    db.flush()
    return e


def _run(db: Session, e: Experiment, status: str, **kw: Any) -> Run:
    r = Run(experiment_id=e.id, status=status, template="lab-mlp", config=kw.pop("config", {}), **kw)
    db.add(r)
    db.flush()
    return r


@pytest.mark.parametrize(("statuses", "expected"), [
    (["done", "done", "done"], "review"),
    (["done", "failed"], "review"),  # хоть один удачный — есть что рецензировать
    (["failed", "stopped"], "failed"),
    (["done", "running"], "running"),  # набор ещё считается
    (["done", "queued"], "running"),
])
def test_status_follows_runs(db_session: Session, statuses: list[str], expected: str) -> None:
    e = _exp(db_session)
    for s in statuses:
        _run(db_session, e, s)
    refresh_after_runs(db_session, e)
    assert e.status == expected


def test_reviewed_or_finished_checks_are_not_rolled_back(db_session: Session) -> None:
    for st in ("review", "done"):
        e = _exp(db_session, f"EXP-0{1 if st == 'review' else 2}", st)
        _run(db_session, e, "failed")
        refresh_after_runs(db_session, e)
        assert e.status == st


def test_progress_shows_what_is_left(db_session: Session) -> None:
    e = _exp(db_session)
    _run(db_session, e, "done")
    _run(db_session, e, "running", started_at=datetime.now(UTC) - timedelta(minutes=40),
         config={"estimate": {"minutes": 147}})
    _run(db_session, e, "queued", config={"estimate": {"minutes": 11}})
    p = progress(db_session, e)
    assert p is not None and p["total"] == 3 and p["done"] == 1
    assert [a["status"] for a in p["active"]] == ["running", "queued"]  # type: ignore[index]
    assert 110 <= float(p["left_min"]) <= 120  # type: ignore[arg-type]  # 147 − 40 + 11


def test_last_run_report_moves_check_to_review_and_shows_draft(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    """Исполнитель сообщил, что последний расчёт упал, — проверка уже не «в работе», а её вывод из
    отчёта ИИ-помощника виден с пометкой «черновик»."""
    e = _exp(db_session)
    _run(db_session, e, "done")
    last = _run(db_session, e, "running")
    db_session.add(ExperimentReport(experiment_id=e.id, version=1, status="draft", facts={},
                                    sections={"verdict": "confirmed", "summary": "[связь подтверждена]"}))
    db_session.commit()
    c = make_client("rd", "reader")
    before = c.get("/api/experiments/EXP-010").json()
    assert before["status"] == "running" and before["progress"]["active"][0]["run_id"] == last.id
    r = c.post(f"/api/runs/worker/{last.id}", headers=TOKEN, json={"status": "failed", "message": "[сбой]"})
    assert r.status_code == 200, r.text
    after = c.get("/api/experiments/EXP-010").json()
    assert after["status"] == "review" and after["progress"]["active"] == []
    assert after["draft"] == {"version": 1, "status": "draft", "verdict": "confirmed",
                              "summary": "[связь подтверждена]", "verdict_reason": ""}
    listed = {x["code"]: x for x in c.get("/api/experiments").json()}
    assert listed["EXP-010"]["progress"]["done"] == 1
