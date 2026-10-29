import pytest

ROLES = ["reader", "researcher", "reviewer", "owner"]


@pytest.mark.parametrize("role", ROLES)
def test_users_list_is_owner_only(make_client, role: str) -> None:  # type: ignore[no-untyped-def]
    c = make_client("u-" + role, role)
    expected = 200 if role == "owner" else 403
    assert c.get("/api/users").status_code == expected


@pytest.mark.parametrize("role", ROLES)
def test_only_owner_changes_roles(make_client, role: str) -> None:  # type: ignore[no-untyped-def]
    make_client("target", "reader")
    c = make_client("actor-" + role, role)
    r = c.patch("/api/users/target", json={"role": "reviewer", "nda_access": True})
    assert r.status_code == (200 if role == "owner" else 403)


def test_owner_assigns_role_and_nda(make_client) -> None:  # type: ignore[no-untyped-def]
    make_client("target", "reader")
    owner = make_client("boss", "owner")
    r = owner.patch("/api/users/target", json={"role": "reviewer", "nda_access": True})
    assert r.json()["role"] == "reviewer"
    assert r.json()["nda_access"] is True


def test_unknown_role_rejected(make_client) -> None:  # type: ignore[no-untyped-def]
    make_client("target", "reader")
    owner = make_client("boss", "owner")
    assert owner.patch("/api/users/target", json={"role": "god"}).status_code == 422


def test_unknown_user_404(make_client) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    assert owner.patch("/api/users/ghost", json={"role": "reader"}).status_code == 404


def test_anonymous_gets_401(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/users").status_code == 401
