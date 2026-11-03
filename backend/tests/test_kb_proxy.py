import pytest
from fastapi.testclient import TestClient

from app.api import kb as kb_api


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []

    def fake_fetch(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
        seen.append((url, token))
        return 200, b'{"documents": 6}', "application/json"

    monkeypatch.setattr(kb_api, "fetch", fake_fetch)
    return seen


def test_kb_requires_login(client: TestClient, calls: list[tuple[str, str]]) -> None:
    assert client.get("/api/kb/stats").status_code == 401
    assert calls == []


@pytest.mark.parametrize("role", ["reader", "researcher", "reviewer", "owner"])
def test_kb_readable_by_any_role(make_client, calls, role: str) -> None:  # type: ignore[no-untyped-def]
    c = make_client("u-" + role, role)
    r = c.get("/api/kb/stats", params={"kb": "esg"})
    assert r.status_code == 200
    assert r.json() == {"documents": 6}
    assert calls[-1][0].endswith("/api/stats?kb=esg")


def test_kb_forwards_platform_token(make_client, calls, settings) -> None:  # type: ignore[no-untyped-def]
    settings.kbrag_token = "service-token"
    c = make_client("ivanov", "reader")
    c.get("/api/kb/search", params={"q": "ROA", "kb": "esg.finance"})
    url, token = calls[-1]
    assert token == "service-token"
    assert "q=ROA" in url and "kb=esg.finance" in url


def test_kb_rejects_unknown_endpoint(make_client, calls) -> None:  # type: ignore[no-untyped-def]
    c = make_client("ivanov", "owner")
    assert c.get("/api/kb/chat").status_code == 404
    assert c.get("/api/kb/pdf").status_code == 404
    assert calls == []


def test_kb_unavailable_is_502(make_client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    def down(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
        raise OSError("connection refused")

    monkeypatch.setattr(kb_api, "fetch", down)
    c = make_client("ivanov", "reader")
    assert c.get("/api/kb/stats").status_code == 502


@pytest.fixture(autouse=True)
def empty_network_cache() -> None:
    kb_api.NETWORK_CACHE.clear()


GRAPH = (
    b'{"nodes":[{"id":"\xd1\x81:A","spellings":["a"]}],'
    b'"edges":[{"source":"A","target":"B","quotes":[{"quote":"q"}]}]}'
)


def test_kb_unpacks_gzip() -> None:
    import gzip

    assert kb_api.unpack(gzip.compress(b'{"x": 1}'), "gzip") == b'{"x": 1}'
    assert kb_api.unpack(b'{"x": 1}', None) == b'{"x": 1}'


def test_kb_network_is_slimmed_and_cached(make_client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    seen: list[str] = []

    def fake_fetch(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
        seen.append(url)
        return 200, GRAPH, "application/json"

    monkeypatch.setattr(kb_api, "fetch", fake_fetch)
    c = make_client("ivanov", "reader")
    first = c.get("/api/kb/network", params={"kb": "esg"}).json()
    second = c.get("/api/kb/network", params={"kb": "esg"}).json()
    assert first == second
    assert "quotes" not in first["edges"][0] and "spellings" not in first["nodes"][0]
    assert len(seen) == 1  # второй раз — из памяти, без похода в KBRAG
    c.get("/api/kb/network", params={"kb": "esg.finance"})
    assert len(seen) == 2  # у другой ветки свой граф


def test_kb_network_error_is_not_cached(make_client, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    answers = [(500, b'{"error": "x"}', "application/json"), (200, GRAPH, "application/json")]

    def fake_fetch(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
        return answers.pop(0)

    monkeypatch.setattr(kb_api, "fetch", fake_fetch)
    c = make_client("ivanov", "reader")
    assert c.get("/api/kb/network", params={"kb": "esg"}).status_code == 500
    assert c.get("/api/kb/network", params={"kb": "esg"}).status_code == 200


def test_kb_stale_network_served_while_refreshing(make_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen: list[str] = []

    def fake_fetch(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
        seen.append(url)
        return 200, GRAPH, "application/json"

    monkeypatch.setattr(kb_api, "fetch", fake_fetch)
    monkeypatch.setattr(kb_api, "NETWORK_FRESH_S", -1.0)  # любой граф сразу устаревший
    c = make_client("ivanov", "reader")
    c.get("/api/kb/network", params={"kb": "esg"})
    assert c.get("/api/kb/network", params={"kb": "esg"}).status_code == 200  # не ждёт KBRAG
    url = next(iter(kb_api.NETWORK_CACHE))
    with kb_api._network_busy[url]:  # дождаться фонового обновления
        pass
    assert len(seen) == 2
