import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app import audit
from app.audit import AuditLog
from app.config import Settings


@pytest.fixture(autouse=True)
def audit_to_test_db(db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    # Журнал пишет прослойкой — мимо подмен зависимостей FastAPI: направляем его сессию в тестовую
    # базу, а настройки (секрет сессии) — тестовые, иначе cookie тестового входа не читается
    monkeypatch.setattr(audit, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(audit, "get_settings", lambda: settings)


def test_write_requests_are_logged(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    owner.post("/api/hypotheses", json={"title": "проверка журнала", "statement": "утверждение для журнала"})
    rows = db_session.query(AuditLog).filter_by(path="/api/hypotheses").all()
    assert rows and rows[-1].login == "boss" and rows[-1].status == 201


def test_reads_are_not_logged(make_client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    before = db_session.query(AuditLog).count()
    owner.get("/api/experiments")
    assert db_session.query(AuditLog).count() == before


def test_audit_is_owner_only(make_client) -> None:  # type: ignore[no-untyped-def]
    assert make_client("res", "researcher").get("/api/audit").status_code == 403
    assert make_client("boss", "owner").get("/api/audit").status_code == 200
