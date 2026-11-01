import pytest
from sqlalchemy.orm import Session

from app.models import Dataset, Experiment

SHA = "a" * 64


@pytest.fixture
def seeded(db_session: Session) -> None:
    db_session.add(Dataset(code="DS-04", title="TWSE", access_level="public"))
    db_session.add(Experiment(code="EXP-007", title="повтор", status="review", config={}, setup=[],
                              results=[], limitations=[], reproducibility=[]))
    db_session.commit()


def _run(commit: str = "abc1234", code: int = 0) -> dict:  # type: ignore[type-arg]
    return {"runner_commit": commit, "dataset": {"code": "DS-04", "sha256": SHA},
            "env_lock_sha256": "b" * 64, "python": "3.12.10", "seeds": {"split": 42},
            "parts": {"hsu_paper": {"exit_code": code, "seconds": 10}}}


def test_clean_successful_run_fills_reproducibility(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    r = c.post("/api/experiments/EXP-007/runs", json=_run())
    assert r.status_code == 201, r.text
    assert r.json()["reproducible"] is True and r.json()["dataset_sha256"] == SHA
    r = c.patch("/api/experiments/EXP-007", json={"status": "done"})
    assert r.status_code == 200, r.text  # правило 3 выполнено запуском


def test_dirty_commit_does_not_count(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    r = c.post("/api/experiments/EXP-007/runs", json=_run(commit="abc1234-dirty"))
    assert r.json()["reproducible"] is False
    assert c.patch("/api/experiments/EXP-007", json={"status": "done"}).status_code == 422


def test_failed_part_marks_run_failed(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    r = c.post("/api/experiments/EXP-007/runs", json=_run(code=1))
    assert r.json()["status"] == "failed" and r.json()["reproducible"] is False


def test_same_dataset_hash_reuses_snapshot(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    c.post("/api/experiments/EXP-007/runs", json=_run())
    c.post("/api/experiments/EXP-007/runs", json=_run())
    runs = c.get("/api/experiments/EXP-007/runs").json()
    assert len(runs) == 2 and runs[0]["dataset_sha256"] == runs[1]["dataset_sha256"]


def test_reader_cannot_import(make_client, seeded) -> None:  # type: ignore[no-untyped-def]
    assert make_client("r", "reader").post("/api/experiments/EXP-007/runs", json=_run()).status_code == 403


def test_seed_from_other_key_names() -> None:
    from app.api.runs import _seed

    assert _seed({"split": 7, "bootstrap": 42}) == 7
    assert _seed({"n_boot": 10000, "bootstrap": 42}) == 42
    assert _seed({"repeats": "0..29"}) is None
