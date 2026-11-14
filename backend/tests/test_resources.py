"""Учёт ресурсов: цена расчёта до запуска, совет уложиться в лимит, лимиты на сервере, поправка
оценки по прошлым расчётам. Наборы данных и параметры — заглушки."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

import app.api.runs as runs_api
from app.config import Settings
from app.models import Dataset, DatasetSnapshot, Experiment, Run
from app.services import resources
from app.services.run_templates import TEMPLATES

SHA = "c" * 64


@pytest.fixture
def settings() -> Settings:
    return Settings(
        auth_backend="local",
        secret_key="test",
        local_dev_password="dev",
        run_active_per_user=2,
        run_cpu_minutes_per_day=200,
    )


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        runs_api.run_queue,
        "enqueue",
        lambda broker, run_id, job, q: sent.append({"job": job, "queue": q}) or f"run-{run_id}",
    )
    return sent


@pytest.fixture
def snapshot(db_session: Session) -> int:
    ds = Dataset(code="DS-04", title="[набор]", access_level="public")
    db_session.add(ds)
    db_session.add(
        Experiment(
            code="EXP-007",
            title="[повтор]",
            status="review",
            config={},
            setup=[],
            results=[],
            limitations=[],
            reproducibility=[],
        )
    )
    db_session.flush()
    snap = DatasetSnapshot(
        dataset_id=ds.id,
        version="v1",
        sha256=SHA,
        storage_path=r"C:\data\DS-04\v1\t.csv",
        row_count=194,
    )
    db_session.add(snap)
    db_session.commit()
    return snap.id


def _launch(c, snapshot: int, trials: int):  # type: ignore[no-untyped-def]
    return c.post(
        "/api/runs",
        json={"template": "exp007-hsu", "snapshot_id": snapshot, "params": {"trials": trials}},
    )


def test_estimate_before_launch(make_client, snapshot: int) -> None:  # type: ignore[no-untyped-def]
    r = make_client("rd", "reader").post(
        "/api/runs/estimate",
        json={"template": "exp007-hsu", "snapshot_id": snapshot, "params": {"trials": 100}},
    )
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["resource"] == "cpu" and e["within_limit"] and e["limit_min"] == 240
    assert e["low"] < e["minutes"] < e["high"] and e["minutes"] == 75
    assert e["queue"]["ahead"] == 0 and e["usage"]["minutes_limit"] == 200 and e["blocked"] == ""


def test_over_limit_is_refused_on_server_with_advice(
    make_client,
    snapshot: int,  # type: ignore[no-untyped-def]
    queue: list,
) -> None:  # type: ignore[type-arg]
    c = make_client("own", "owner")
    est = c.post(
        "/api/runs/estimate",
        json={"template": "exp007-hsu", "snapshot_id": snapshot, "params": {"trials": 500}},
    ).json()
    assert not est["within_limit"] and est["suggestion"]["params"]["trials"] < 500
    assert est["suggestion"]["minutes"] <= 240 and "испытаний" in est["suggestion"]["text"]
    r = _launch(c, snapshot, 500)
    assert r.status_code == 422 and "лимита метода" in r.json()["detail"]
    assert queue == []


def test_active_runs_and_daily_quota(make_client, snapshot: int, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    c = make_client("res", "researcher")
    assert _launch(c, snapshot, 100).status_code == 201  # 75 мин из квоты 200
    r = _launch(c, snapshot, 200)  # ещё 150 мин — больше квоты
    assert r.status_code == 409 and "квота" in r.json()["detail"]
    assert _launch(c, snapshot, 100).status_code == 201  # 150 из 200
    r = _launch(c, snapshot, 5)  # уже два расчёта в очереди
    assert r.status_code == 409 and "в очереди" in r.json()["detail"]
    assert len(queue) == 2 and queue[0]["queue"] == "cpu"


def test_owner_has_no_daily_quota(make_client, snapshot: int, queue: list) -> None:  # type: ignore[no-untyped-def,type-arg]
    c = make_client("own", "owner")
    assert _launch(c, snapshot, 200).status_code == 201
    assert _launch(c, snapshot, 200).status_code == 201


def test_estimate_is_recorded_and_calibrated_by_past_runs(
    db_session: Session, settings: Settings, snapshot: int
) -> None:
    t = TEMPLATES["exp007-hsu"]
    plain = resources.estimate(db_session, settings, t, {"trials": 100}, 194)
    assert "по формуле метода" in plain.basis and plain.minutes == 75
    start = datetime(2026, 11, 1, tzinfo=UTC)
    for _ in range(3):  # три расчёта шли вдвое дольше оценки
        db_session.add(
            Run(
                experiment_id=1,
                status="done",
                template="exp007-hsu",
                config={"estimate": {"minutes": 75}},
                started_at=start,
                finished_at=start + timedelta(minutes=150),
            )
        )
    db_session.commit()
    calibrated = resources.estimate(db_session, settings, t, {"trials": 100}, 194)
    assert calibrated.minutes == 150 and "3 прошлым расчётам" in calibrated.basis


def test_transformer_prefers_gpu_only_when_executor_exists(db_session: Session) -> None:
    t = TEMPLATES["lab-mlp"]
    params = {
        "target": "[R]",
        "features": [f"[x{i}]" for i in range(20)],
        "architecture": "transformer",
        "splits": 30,
        "trials": 3,
    }
    off = resources.estimate(db_session, Settings(gpu_executor=False), t, params, 300)
    on = resources.estimate(db_session, Settings(gpu_executor=True), t, params, 300)
    assert off.resource == "cpu" and "не подключён" in off.resource_why
    assert on.resource == "gpu" and on.minutes < off.minutes
    mlp = resources.estimate(db_session, Settings(), t, {**params, "architecture": "mlp"}, 300)
    assert mlp.minutes < off.minutes
