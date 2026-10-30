import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.main import app
from app.models import User
from app.services.passwords import check_strength, hash_password, verify_password


def test_hash_roundtrip() -> None:
    h = hash_password("correct-horse-42")
    assert h.startswith("scrypt$")
    assert verify_password("correct-horse-42", h)
    assert not verify_password("wrong-horse-42", h)
    assert hash_password("correct-horse-42") != h  # соль своя у каждого хеша


@pytest.mark.parametrize("pw", ["short1", "onlyletterslong", "1234567890123"])
def test_weak_passwords(pw: str) -> None:
    assert check_strength(pw) is not None


@pytest.fixture
def pw_settings(settings: Settings) -> Settings:
    settings.auth_backend = "password"
    return settings


@pytest.fixture
def owner(client: TestClient, db_session: Session, pw_settings: Settings) -> TestClient:
    # client ставит подмену БД и настроек; pw_settings — тот же объект, в режиме password
    db_session.add(User(login="boss", role="owner", password_hash=hash_password("boss-pass-123")))
    db_session.commit()
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"login": "boss", "password": "boss-pass-123"}).status_code == 200
    return c


def _login(login: str, password: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return c


def test_unknown_user_is_not_created(client: TestClient, pw_settings: Settings, db_session: Session) -> None:
    assert app.dependency_overrides[get_settings]() is pw_settings
    r = client.post("/api/auth/login", json={"login": "stranger", "password": "anything-123"})
    assert r.status_code == 401
    assert db_session.query(User).filter_by(login="stranger").first() is None


def test_owner_creates_user_with_temporary_password(owner: TestClient) -> None:
    r = owner.post("/api/users", json={"login": "Ivanov", "role": "researcher"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["login"] == "ivanov" and body["must_change_password"] is True
    c = _login("ivanov", body["temporary_password"])
    assert c.get("/api/experiments").status_code == 403  # сначала сменить пароль
    assert c.get("/api/auth/me").status_code == 200
    r = c.post("/api/auth/change-password", json={"old_password": body["temporary_password"],
                                                  "new_password": "my-own-pass-77"})
    assert r.status_code == 200, r.text
    assert c.get("/api/experiments").status_code == 200
    _login("ivanov", "my-own-pass-77")


def test_weak_new_password_rejected(owner: TestClient) -> None:
    tmp = owner.post("/api/users", json={"login": "petrov"}).json()["temporary_password"]
    c = _login("petrov", tmp)
    r = c.post("/api/auth/change-password", json={"old_password": tmp, "new_password": "123"})
    assert r.status_code == 422


def test_reset_password_ends_old_sessions(owner: TestClient) -> None:
    tmp = owner.post("/api/users", json={"login": "sidorov"}).json()["temporary_password"]
    c = _login("sidorov", tmp)
    c.post("/api/auth/change-password", json={"old_password": tmp, "new_password": "sidorov-pass-1"})
    assert c.get("/api/auth/me").status_code == 200
    assert owner.post("/api/users/sidorov/reset-password").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_blocked_user_cannot_login(owner: TestClient) -> None:
    tmp = owner.post("/api/users", json={"login": "blocked"}).json()["temporary_password"]
    c = _login("blocked", tmp)
    assert owner.patch("/api/users/blocked", json={"is_active": False}).status_code == 200
    assert c.get("/api/auth/me").status_code == 401
    r = TestClient(app).post("/api/auth/login", json={"login": "blocked", "password": tmp})
    assert r.status_code == 401


def test_non_owner_cannot_create_users(owner: TestClient) -> None:
    tmp = owner.post("/api/users", json={"login": "reader1"}).json()["temporary_password"]
    c = _login("reader1", tmp)
    c.post("/api/auth/change-password", json={"old_password": tmp, "new_password": "reader-pass-1"})
    assert c.post("/api/users", json={"login": "x2"}).status_code == 403


def test_last_owner_cannot_be_blocked(owner: TestClient) -> None:
    assert owner.patch("/api/users/boss", json={"is_active": False}).status_code == 409
