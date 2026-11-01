import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import KbImport

TOKEN = {"X-Qwen-Token": "tok"}


@pytest.fixture
def settings() -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", qwen_token="tok",
                    kb_import_token="imp")


def test_only_owner_sees_and_adds(make_client) -> None:  # type: ignore[no-untyped-def]
    for role in ("reader", "researcher", "reviewer"):
        c = make_client(f"u-{role}", role)
        assert c.post("/api/qwen/jobs", json={"kind": "ping"}).status_code == 403
        assert c.get("/api/qwen/jobs").status_code == 403
        assert c.get("/api/qwen/status").status_code == 403


def test_add_dedupes_and_refuses_internal_kinds(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("boss", "owner")
    first = c.post("/api/qwen/jobs", json={"kind": "graph", "payload": {"kb": "esg"}}).json()
    again = c.post("/api/qwen/jobs", json={"kind": "graph", "payload": {"kb": "esg"}}).json()
    assert first["id"] == again["id"] and first["status"] == "queued"
    assert c.post("/api/qwen/jobs", json={"kind": "report"}).status_code == 422


def test_worker_cycle(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("boss", "owner")
    job = c.post("/api/qwen/jobs", json={"kind": "ping"}).json()
    assert c.post("/api/qwen/worker/peek").status_code == 403
    assert c.post("/api/qwen/worker/peek", headers=TOKEN).json() == {"queued": 1}
    claimed = c.post("/api/qwen/worker/next", headers=TOKEN).json()
    assert claimed["id"] == job["id"] and claimed["status"] == "running"
    assert c.post("/api/qwen/worker/next", headers=TOKEN).status_code == 204
    assert c.post("/api/qwen/worker/requeue", headers=TOKEN).json() == {"requeued": 1}
    c.post("/api/qwen/worker/next", headers=TOKEN)
    r = c.post(f"/api/qwen/worker/{job['id']}/result", headers=TOKEN,
               json={"status": "done", "result": {"answer": "Готова"}, "message": "ok"})
    assert r.json()["status"] == "done" and r.json()["result"] == {"answer": "Готова"}
    assert c.post(f"/api/qwen/worker/{job['id']}/result", headers=TOKEN, json={"status": "failed"}).status_code == 409


def test_cancel_only_queued(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client("boss", "owner")
    job = c.post("/api/qwen/jobs", json={"kind": "ping"}).json()
    assert c.post(f"/api/qwen/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    assert c.post(f"/api/qwen/jobs/{job['id']}/cancel").status_code == 409


def test_imported_article_queues_graph(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    c = make_client("boss", "owner")
    imp = KbImport(kb_path="esg", source="file", filename="a.pdf", sha256="0" * 64, status="processing")
    db_session.add(imp)
    db_session.commit()
    r = c.post(f"/api/kb-imports/worker/{imp.id}/result", headers={"X-Import-Token": "imp"},
               json={"status": "done", "doc_id": "10.1_x"})
    assert r.status_code == 200, r.text
    jobs = c.get("/api/qwen/jobs").json()
    assert sorted((j["kind"], j["trigger"]) for j in jobs) == [("graph", "import"), ("hypotheses", "import")]
