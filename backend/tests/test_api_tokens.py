"""Открытый API: личные токены — выпуск, права, отзыв, срок, адреса /api/v1. Данные — заглушки."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.audit import AuditLog
from app.config import Settings
from app.main import app
from app.models import ApiToken, User
from app.services.passwords import hash_password


@pytest.fixture
def pw(settings: Settings) -> Settings:
    settings.auth_backend = "password"
    return settings


def _site(db: Session, login: str, role: str = "researcher") -> TestClient:
    db.add(User(login=login, role=role, password_hash=hash_password(f"{login}-pass-123")))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"login": login, "password": f"{login}-pass-123"})
    assert r.status_code == 200, r.text
    return c


def _api(token: str) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _new(site: TestClient, scope: str = "read", days: int = 30) -> dict:  # type: ignore[type-arg]
    r = site.post("/api/tokens", json={"name": "ноутбук", "scope": scope, "days": days})
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def test_token_works_like_its_owner_and_is_shown_once(
    client: TestClient, pw: Settings, db_session: Session,
) -> None:
    site = _site(db_session, "ivanov")
    got = _new(site)
    assert got["token"].startswith("esg_") and got["token"].startswith(got["prefix"])
    assert db_session.query(ApiToken).one().token_hash != got["token"]  # в базе — только хеш
    api = _api(got["token"])
    assert api.get("/api/auth/me").json()["login"] == "ivanov"
    assert api.get("/api/v1/auth/me").json()["login"] == "ivanov"  # адрес с версией — тот же
    listed = site.get("/api/tokens").json()
    assert "token" not in listed[0] and listed[0]["last_used_at"] is not None


def test_read_token_cannot_change_write_token_can(
    client: TestClient, pw: Settings, db_session: Session,
) -> None:
    site = _site(db_session, "ivanov")
    read = _api(_new(site, "read")["token"])
    write = _api(_new(site, "write")["token"])
    body = {"title": "[проверка]"}
    r = read.post("/api/experiments", json=body)
    assert r.status_code == 403 and "только для чтения" in r.json()["detail"]
    assert write.post("/api/experiments", json=body).status_code not in (401, 403)


def test_account_is_managed_only_on_site(
    client: TestClient, pw: Settings, db_session: Session,
) -> None:
    site = _site(db_session, "boss", role="owner")
    api = _api(_new(site, "write")["token"])
    assert api.post("/api/tokens", json={"name": "ещё"}).status_code == 403
    assert api.get("/api/users").status_code == 403
    pw_change = {"old_password": "boss-pass-123", "new_password": "new-pass-456"}
    assert api.post("/api/auth/change-password", json=pw_change).status_code == 403


def test_revoked_expired_and_blocked_tokens_do_not_work(
    client: TestClient, pw: Settings, db_session: Session,
) -> None:
    site = _site(db_session, "ivanov")
    a, b, c = _new(site), _new(site), _new(site)
    assert site.delete(f"/api/tokens/{a['id']}").status_code == 204
    assert _api(a["token"]).get("/api/auth/me").status_code == 401
    tok = db_session.get(ApiToken, b["id"])
    assert tok is not None
    tok.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()
    assert _api(b["token"]).get("/api/auth/me").status_code == 401
    db_session.query(User).filter_by(login="ivanov").one().is_active = False
    db_session.commit()
    assert _api(c["token"]).get("/api/auth/me").status_code == 401
    assert _api("esg_forged").get("/api/auth/me").status_code == 401


def test_owner_sees_and_revokes_all_others_only_own(
    client: TestClient, pw: Settings, db_session: Session,
) -> None:
    ivanov = _site(db_session, "ivanov")
    petrov = _site(db_session, "petrov")
    boss = _site(db_session, "boss", role="owner")
    t = _new(ivanov)
    assert petrov.delete(f"/api/tokens/{t['id']}").status_code == 404
    assert [x["login"] for x in boss.get("/api/tokens?all=true").json()] == ["ivanov"]
    assert petrov.get("/api/tokens?all=true").json() == []
    assert boss.delete(f"/api/tokens/{t['id']}").status_code == 204
    assert _api(t["token"]).get("/api/auth/me").status_code == 401


def test_password_reset_by_owner_revokes_tokens(
    client: TestClient, pw: Settings, db_session: Session,
) -> None:
    t = _new(_site(db_session, "ivanov"))
    boss = _site(db_session, "boss", role="owner")
    assert boss.post("/api/users/ivanov/reset-password").status_code == 200
    assert _api(t["token"]).get("/api/auth/me").status_code == 401


def test_limits_and_audit(client: TestClient, pw: Settings, db_session: Session) -> None:
    site = _site(db_session, "ivanov")
    assert site.post("/api/tokens", json={"name": "x", "days": 400}).status_code == 422
    write = _api(_new(site, "write")["token"])
    write.post("/api/experiments", json={"title": "[проверка]"})
    logins = [row.login for row in db_session.query(AuditLog).all()]
    assert "ivanov (API)" in logins
    for _ in range(9):
        _new(site)
    assert site.post("/api/tokens", json={"name": "лишний"}).status_code == 409


def test_openapi_describes_token_auth(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()
    assert schema["components"]["securitySchemes"]["token"]["scheme"] == "bearer"
    assert any(p.startswith("/api/tokens") for p in schema["paths"])
