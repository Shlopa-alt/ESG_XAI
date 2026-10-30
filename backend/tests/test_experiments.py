import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, DatasetSnapshot, Experiment, Hypothesis


def _create(c, code: str = "EXP-100"):  # type: ignore[no-untyped-def]
    r = c.post("/api/experiments", json={"code": code, "title": "Проверка правила 3"})
    assert r.status_code == 201, r.text
    return r


@pytest.fixture
def snapshot(db_session: Session) -> int:
    ds = Dataset(code="DS-99", title="тестовый срез", access_level="public")
    db_session.add(ds)
    db_session.flush()
    snap = DatasetSnapshot(dataset_id=ds.id, version="1", sha256="0" * 64)
    db_session.add(snap)
    db_session.commit()
    return snap.id


def test_reader_cannot_create(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("reader1", "reader")
    assert c.post("/api/experiments", json={"code": "EXP-100", "title": "x x x"}).status_code == 403


def test_done_requires_reproducibility(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _create(c)
    r = c.patch("/api/experiments/EXP-100", json={"status": "done"})
    assert r.status_code == 422
    for field in ("runner_commit", "dataset_snapshot_id", "env_lock", "seed"):
        assert field in r.json()["detail"]
    assert c.get("/api/experiments/EXP-100").json()["status"] == "draft"


def test_done_with_full_reproducibility(make_client, snapshot: int) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _create(c)
    r = c.patch(
        "/api/experiments/EXP-100",
        json={"status": "done", "runner_commit": "abc123", "dataset_snapshot_id": snapshot,
              "env_lock": "numpy==2.1", "seed": 42, "outcome": "rejected"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"
    assert r.json()["finished_at"] is not None


def test_rejected_outcome_is_normal(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _create(c)
    r = c.patch("/api/experiments/EXP-100", json={"status": "review", "outcome": "rejected"})
    assert r.status_code == 200
    assert r.json()["outcome"] == "rejected"


def test_duplicate_code_conflict(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _create(c)
    assert c.post("/api/experiments", json={"code": "EXP-100", "title": "ещё раз"}).status_code == 409


def test_code_format_enforced(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    assert c.post("/api/experiments", json={"code": "E1", "title": "плохой код"}).status_code == 422


def test_review_requires_reviewer(make_client) -> None:  # type: ignore[no-untyped-def]
    res = make_client("res", "researcher")
    _create(res)
    body = {"target_code": "EXP-100", "verdict": "approve", "text": "ок"}
    assert res.post("/api/reviews", json=body).status_code == 403
    rev = make_client("rev", "reviewer")
    r = rev.post("/api/reviews", json=body)
    assert r.status_code == 201
    assert r.json()["reviews"][0]["reviewer"] == "rev"


def test_link_to_kbrag_article(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _create(c)
    r = c.post(
        "/api/experiments/EXP-100/links",
        json={"relation": "replicates", "kind": "article", "kbrag_id": "10.3390_x",
              "title": "Hsu et al. 2025", "doi": "10.3390/x"},
    )
    assert r.status_code == 200
    assert r.json()["links"][0]["relation"] == "replicates"


def test_list_requires_login(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/experiments").status_code == 401


def test_done_marks_hypothesis_tested(make_client, snapshot: int, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    _create(c)
    exp_id = db_session.scalar(select(Experiment.id).where(Experiment.code == "EXP-100"))
    db_session.add(Hypothesis(code="H-100", title="проверка", statement="s", status="testing",
                              experiment_id=exp_id))
    db_session.commit()
    r = c.patch(
        "/api/experiments/EXP-100",
        json={"status": "done", "runner_commit": "abc123", "dataset_snapshot_id": snapshot,
              "env_lock": "numpy==2.1", "seed": 42},
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.scalar(select(Hypothesis.status).where(Hypothesis.code == "H-100")) == "tested"
