"""«Забыли пароль?»: ссылка на почту, новый пароль по ней, почта для восстановления.
Письма не отправляются — подменена отправка SMTP. Адреса — заглушки."""

from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import app
from app.models import User
from app.services import password_reset as reset
from app.services.passwords import hash_password

MAIL = "user@example.org"


@pytest.fixture
def mail_settings(settings: Settings) -> Settings:
    settings.auth_backend = "password"
    settings.smtp_host = "smtp.example.org"
    settings.public_url = "https://esg.example.org/"
    return settings


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[EmailMessage]:
    sent: list[EmailMessage] = []
    monkeypatch.setattr(reset, "send", lambda _s, msg: sent.append(msg))
    reset._sent.clear()
    return sent


@pytest.fixture
def ivanov(db_session: Session) -> User:
    u = User(login="ivanov", role="researcher", email=MAIL,
             password_hash=hash_password("old-pass-123"))
    db_session.add(u)
    db_session.commit()
    return u


def _login(login: str, password: str) -> TestClient:
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"login": login, "password": password}).status_code == 200
    return c


def _token(msg: EmailMessage) -> str:
    body = msg.get_content()
    link = next(w for w in body.split() if "/reset-password#" in w)
    assert link.startswith("https://esg.example.org/reset-password#")
    return link.split("#", 1)[1]


def test_link_sets_new_password_and_logs_in(
    client: TestClient, mail_settings: Settings, outbox: list[EmailMessage], ivanov: User,
) -> None:
    r = client.post("/api/auth/forgot", json={"login": "Ivanov"})
    assert r.status_code == 200 and "60 мин" in r.json()["detail"]
    assert len(outbox) == 1 and outbox[0]["To"] == MAIL
    token = _token(outbox[0])

    c = TestClient(app)
    r = c.post("/api/auth/reset", json={"token": token, "new_password": "new-pass-456"})
    assert r.status_code == 200, r.text
    assert c.get("/api/auth/me").json()["login"] == "ivanov"  # вход выполнен
    assert TestClient(app).post(
        "/api/auth/login", json={"login": "ivanov", "password": "new-pass-456"}).status_code == 200
    # ссылка одноразовая: пароль уже другой
    again = TestClient(app).post("/api/auth/reset",
                                 json={"token": token, "new_password": "other-pass-789"})
    assert again.status_code == 400


def test_answer_does_not_reveal_who_is_registered(
    client: TestClient, mail_settings: Settings, outbox: list[EmailMessage], ivanov: User,
) -> None:
    known = client.post("/api/auth/forgot", json={"login": "ivanov"})
    unknown = client.post("/api/auth/forgot", json={"login": "stranger"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert len(outbox) == 1


def test_search_by_email_and_no_flood(
    client: TestClient, mail_settings: Settings, outbox: list[EmailMessage], ivanov: User,
) -> None:
    assert client.post("/api/auth/forgot", json={"login": MAIL.upper()}).status_code == 200
    assert client.post("/api/auth/forgot", json={"login": "ivanov"}).status_code == 200
    assert len(outbox) == 1  # второе письмо тому же человеку — не раньше чем через 5 минут


def test_no_letter_without_email_or_for_blocked(
    client: TestClient, mail_settings: Settings, outbox: list[EmailMessage], db_session: Session,
) -> None:
    db_session.add_all([
        User(login="noemail", role="reader", password_hash=hash_password("pass-12345")),
        User(login="blocked", role="reader", email="blocked@example.org", is_active=False,
             password_hash=hash_password("pass-12345")),
    ])
    db_session.commit()
    for login in ("noemail", "blocked"):
        assert client.post("/api/auth/forgot", json={"login": login}).status_code == 200
    assert outbox == []


def test_bad_or_weak_reset_is_refused(
    client: TestClient, mail_settings: Settings, outbox: list[EmailMessage], ivanov: User,
) -> None:
    forged = client.post("/api/auth/reset", json={"token": "x", "new_password": "new-pass-456"})
    assert forged.status_code == 400
    client.post("/api/auth/forgot", json={"login": "ivanov"})
    weak = client.post("/api/auth/reset",
                       json={"token": _token(outbox[0]), "new_password": "short"})
    assert weak.status_code == 422


def test_without_mail_settings_says_so(
    client: TestClient, settings: Settings, ivanov: User,
) -> None:
    settings.auth_backend = "password"
    r = client.post("/api/auth/forgot", json={"login": "ivanov"})
    assert r.status_code == 409 and "не настроено" in r.json()["detail"]


def test_own_email_needs_current_password(
    client: TestClient, mail_settings: Settings, ivanov: User,
) -> None:
    c = _login("ivanov", "old-pass-123")
    wrong = c.post("/api/auth/email", json={"password": "wrong-123", "email": "new@example.org"})
    assert wrong.status_code == 403
    bad = c.post("/api/auth/email", json={"password": "old-pass-123", "email": "не почта"})
    assert bad.status_code == 422
    r = c.post("/api/auth/email", json={"password": "old-pass-123", "email": " New@Example.org "})
    assert r.status_code == 200 and r.json()["email"] == "new@example.org"


def test_owner_sets_user_email(
    client: TestClient, mail_settings: Settings, db_session: Session, ivanov: User,
) -> None:
    db_session.add(User(login="boss", role="owner", password_hash=hash_password("boss-pass-123")))
    db_session.commit()
    c = _login("boss", "boss-pass-123")
    assert c.patch("/api/users/ivanov", json={"email": "@@"}).status_code == 422
    r = c.patch("/api/users/ivanov", json={"email": ""})
    assert r.status_code == 200 and r.json()["email"] == ""
    created = c.post("/api/users", json={"login": "petrov", "email": "petrov@example.org"})
    assert created.status_code == 201 and created.json()["email"] == "petrov@example.org"
