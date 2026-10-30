import pytest
from fastapi.testclient import TestClient

from app.config import Settings, check_settings
from app.services import auth as auth_service


@pytest.mark.parametrize("password", ["", "dev", "change-me"])
def test_local_auth_with_default_password_refuses_to_start(password: str) -> None:
    with pytest.raises(RuntimeError):
        check_settings(Settings(auth_backend="local", local_dev_password=password))


def test_local_auth_with_own_password_starts() -> None:
    check_settings(Settings(auth_backend="local", local_dev_password="s3cret-pass"))


def test_ldap_backend_ignores_local_password() -> None:
    check_settings(Settings(auth_backend="ldap", local_dev_password="dev"))


def test_ldap_login_is_escaped_in_dn(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class FakeConnection:
        def __init__(self, server: object, user: str, password: str) -> None:
            seen.append(user)

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def bind(self) -> bool:
            return False

    monkeypatch.setattr(auth_service, "Connection", FakeConnection)
    settings = Settings(ldap_user_dn_template="uid={login},ou=people,dc=x")
    auth_service._ldap_authenticate(settings, "evil,ou=admins", "pw")
    assert seen == ["uid=evil\\,ou\\=admins,ou=people,dc=x"]


def test_login_is_case_insensitive(client: TestClient) -> None:
    first = client.post("/api/auth/login", json={"login": "Ivanov", "password": "dev"}).json()
    second = client.post("/api/auth/login", json={"login": "ivanov", "password": "dev"}).json()
    assert first["login"] == "ivanov"
    assert first["id"] == second["id"]


def test_last_owner_cannot_be_demoted(make_client) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    r = owner.patch("/api/users/boss", json={"role": "reader"})
    assert r.status_code == 409


def test_owner_can_be_demoted_when_another_exists(make_client) -> None:  # type: ignore[no-untyped-def]
    make_client("second", "owner")
    owner = make_client("boss", "owner")
    assert owner.patch("/api/users/second", json={"role": "reader"}).status_code == 200
