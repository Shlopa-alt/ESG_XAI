"""Анализ данных: рекомендация метода по показателю и данным, запуск в один шаг, NDA.
Столбцы — заглушки, числа — порядковые, не данные компаний (правило 7)."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.api.runs as runs_api
from app.config import Settings
from app.models import Dataset, DatasetSnapshot, Experiment, MethodologySection, Run

ROWS = 40
HEADER = ["[компания]", "[отрасль]", "[ROA_2021]", "[ROA_2022]", "[x1]", "[x2]"]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        auth_backend="local",
        secret_key="test",
        local_dev_password="dev",
        esg_data_dir=str(tmp_path),
        esg_data_host="C:/data",
    )


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    def enqueue(broker: str, run_id: int, job: dict[str, Any], queue: str) -> str:
        sent.append({"job": job, "queue": queue})
        return f"run-{run_id}"

    monkeypatch.setattr(runs_api.run_queue, "enqueue", enqueue)
    return sent


def _snapshot(db: Session, tmp_path: Path, code: str = "DS-09", access: str = "public") -> int:
    path = tmp_path / code / "v1" / "t.csv"
    path.parent.mkdir(parents=True)
    lines = [",".join(HEADER)] + [
        f"[c{i}],[отрасль {i % 3}],{i},{i + 1},{i * 2},{i % 7}" for i in range(ROWS)
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    ds = Dataset(code=code, title="[набор]", access_level=access)
    db.add(ds)
    db.flush()
    snap = DatasetSnapshot(
        dataset_id=ds.id,
        version="v1",
        sha256="a" * 64,
        storage_path=f"C:/data/{code}/v1/t.csv",
        row_count=ROWS,
    )
    db.add(snap)
    db.commit()
    return snap.id


def test_target_gives_lab_network_with_reasons(
    make_client,
    db_session: Session,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    sid = _snapshot(db_session, tmp_path)
    r = make_client("rd", "reader").post(
        "/api/analysis/recommend", json={"snapshot_id": sid, "target": "[ROA_2022]"}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["task"]["key"] == "predict" and out["categories"] == ["[отрасль]"]
    first = out["recommendations"][0]
    assert first["template"] == "lab-mlp" and first["primary"] and first["runnable"]
    # прошлый год показателя — не вход, а прогноз «как в прошлом году»; название компании — не категория
    assert first["params"]["lag"] == "[ROA_2021]"
    assert first["params"]["features"] == ["[x1]", "[x2]"] and first["params"]["context"] == [
        "[отрасль]"
    ]
    assert first["why"] and any("меньше 100" in w for w in first["warnings"])
    # альтернативы: та же сеть с заменой на трансформер и быстрая проверка без нейросети
    assert [r["net"] for r in out["recommendations"]] == ["mlp", "transformer", "gbm"]
    assert out["recommendations"][2]["template"] == "predictive-check"


def test_without_target_compares_columns(make_client, db_session: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    sid = _snapshot(db_session, tmp_path)
    out = (
        make_client("rd", "reader")
        .post("/api/analysis/recommend", json={"snapshot_id": sid})
        .json()
    )
    assert out["task"]["key"] == "agreement"
    assert out["recommendations"][0]["template"] == "rank-agreement"
    assert out["recommendations"][0]["params"]["columns"] == [
        "[ROA_2021]",
        "[ROA_2022]",
        "[x1]",
        "[x2]",
    ]


def test_methodology_item_ranks_target_candidates(
    make_client,
    db_session: Session,  # type: ignore[no-untyped-def]
    tmp_path: Path,
) -> None:
    sid = _snapshot(db_session, tmp_path)
    db_session.add(
        MethodologySection(
            number="1.1.1", title="[задание]: рентабельность активов (ROA)", content="", kind="task"
        )
    )
    db_session.commit()
    out = (
        make_client("rd", "reader")
        .post("/api/analysis/recommend", json={"snapshot_id": sid, "node": "1.1.1"})
        .json()
    )
    cands = [c["column"] for c in out["target_candidates"]]
    assert cands[:2] == ["[ROA_2022]", "[ROA_2021]"]  # поздний год — результат, ранний — прошлый период
    assert "рентабельность активов" in out["target_candidates"][0]["reason"]


def test_text_target_is_refused(make_client, db_session: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    sid = _snapshot(db_session, tmp_path)
    r = make_client("rd", "reader").post(
        "/api/analysis/recommend", json={"snapshot_id": sid, "target": "[отрасль]"}
    )
    assert r.status_code == 422


def test_nda_columns_only_with_access(make_client, db_session: Session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    sid = _snapshot(db_session, tmp_path, "DS-10", access="nda")
    body = {"snapshot_id": sid, "target": "[ROA_2022]"}
    assert (
        make_client("res", "researcher").post("/api/analysis/recommend", json=body).status_code
        == 403
    )
    assert make_client("own", "owner").post("/api/analysis/recommend", json=body).status_code == 200


def test_launch_creates_check_and_run_in_one_step(
    make_client,
    db_session: Session,
    tmp_path: Path,  # type: ignore[no-untyped-def]
    queue: list,
) -> None:  # type: ignore[type-arg]
    sid = _snapshot(db_session, tmp_path)
    db_session.add(MethodologySection(number="1.1.1", title="[задание]", content="", kind="task"))
    db_session.commit()
    body = {
        "snapshot_id": sid,
        "template": "lab-mlp",
        "node": "1.1.1",
        "params": {
            "target": "[ROA_2022]",
            "features": ["[x1]", "[x2]"],
            "context": ["[отрасль]"],
            "lag": "[ROA_2021]",
            "trials": 3,
        },
        "choice": {"key": "lab-mlp", "title": "[нейросеть]", "why": ["[причина]"], "primary": True},
    }
    assert make_client("rd", "reader").post("/api/analysis/launch", json=body).status_code == 403
    r = make_client("res", "researcher").post("/api/analysis/launch", json=body)
    assert r.status_code == 201, r.text
    exp = db_session.scalar(select(Experiment).where(Experiment.code == r.json()["experiment"]))
    assert exp is not None and exp.status == "running" and exp.dataset_snapshot_id == sid
    assert exp.config["analysis"]["why"] == ["[причина]"] and exp.config["analysis"]["primary"]
    assert "[ROA_2022]" in exp.hypothesis and exp.setup == ["[причина]"]
    run = db_session.get(Run, r.json()["run_id"])
    assert run is not None and run.experiment_id == exp.id and run.config["params"]["trials"] == 3
    assert queue[0]["job"]["experiment"] == exp.code


def test_launch_with_bad_params_leaves_no_check(
    make_client,
    db_session: Session,
    tmp_path: Path,  # type: ignore[no-untyped-def]
    queue: list,
) -> None:  # type: ignore[type-arg]
    sid = _snapshot(db_session, tmp_path)
    c = make_client("res", "researcher")
    bad = {
        "snapshot_id": sid,
        "template": "lab-mlp",
        "params": {"target": "[ROA_2022]", "features": ["[ROA_2022]"]},
    }
    assert c.post("/api/analysis/launch", json=bad).status_code == 422
    replication = {"snapshot_id": sid, "template": "exp001-dow30", "params": {}}
    assert c.post("/api/analysis/launch", json=replication).status_code == 422
    assert db_session.scalars(select(Experiment)).all() == [] and queue == []


def test_outcome_columns_beat_input_columns_sharing_words() -> None:
    """«ESG-инвестиции → ROA»: результат — ROA, а не столбцы входов с теми же словами."""
    from app.services.analysis import target_candidates
    from app.services.data_files import Table

    node = MethodologySection(number="1.1.1", title="[задание]: рентабельность активов (ROA) от ESG-инвестиций",
                              content="", kind="task")
    cols = ["[ESG-инвестиции: экология]", "[ROA 2022]", "[размер]"]
    t = Table(columns=cols, numeric=set(cols))
    assert [c["column"] for c in target_candidates(node, t)] == ["[ROA 2022]"]
