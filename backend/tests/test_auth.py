import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.services import auth as auth_service


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_me_requires_login(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_local_login_creates_user_with_dev_role(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"login": "ivanov", "password": "dev"})
    assert r.status_code == 200
    assert r.json()["login"] == "ivanov"
    assert r.json()["role"] == "researcher"
    assert client.get("/api/auth/me").json()["login"] == "ivanov"


def test_session_cookie_is_httponly(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"login": "ivanov", "password": "dev"})
    assert "httponly" in r.headers["set-cookie"].lower()


def test_wrong_password_rejected(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"login": "ivanov", "password": "nope"})
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_empty_credentials_rejected(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"login": " ", "password": "dev"})
    assert r.status_code == 401


def test_logout_ends_session(client: TestClient) -> None:
    client.post("/api/auth/login", json={"login": "ivanov", "password": "dev"})
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_cookie_rejected(client: TestClient) -> None:
    client.cookies.set("esg_session", "garbage")
    assert client.get("/api/auth/me").status_code == 401


def test_existing_role_is_kept_on_relogin(client: TestClient) -> None:
    client.post("/api/auth/login", json={"login": "ivanov", "password": "dev"})
    settings = Settings(auth_backend="local", secret_key="test", local_dev_role="reader")
    app.dependency_overrides[get_settings] = lambda: settings
    r = client.post("/api/auth/login", json={"login": "ivanov", "password": "dev"})
    assert r.json()["role"] == "researcher"


@pytest.fixture
def ldap_client(client: TestClient) -> TestClient:
    settings = Settings(auth_backend="ldap", secret_key="test", initial_owner_logins=["boss"])
    app.dependency_overrides[get_settings] = lambda: settings
    return client


def test_ldap_new_user_is_reader(ldap_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_service,
        "_ldap_authenticate",
        lambda s, login, pw: auth_service.Identity(login, "Иван Иванов", "i@x.ru"),
    )
    r = ldap_client.post("/api/auth/login", json={"login": "ivanov", "password": "x"})
    assert r.status_code == 200
    assert r.json()["role"] == "reader"
    assert r.json()["full_name"] == "Иван Иванов"


def test_ldap_initial_owner(ldap_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_service, "_ldap_authenticate", lambda s, login, pw: auth_service.Identity(login)
    )
    r = ldap_client.post("/api/auth/login", json={"login": "boss", "password": "x"})
    assert r.json()["role"] == "owner"


def test_ldap_rejects_bad_credentials(
    ldap_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_service, "_ldap_authenticate", lambda s, login, pw: None)
    r = ldap_client.post("/api/auth/login", json={"login": "ivanov", "password": "bad"})
    assert r.status_code == 401
