"""Общий граф банка статей: главная тема понятия — по графам тем KBRAG (подменён). Понятия — заглушки."""

import json
from collections.abc import Iterator

import pytest

from app.api import kb as kb_api
from app.services import kb_topics

TREE = {"nodes": [
    {"path": "esg", "title": "ESG", "depth": 0, "in_db": True, "subtree": 30},
    {"path": "esg.finance", "title": "[финансы]", "depth": 1, "in_db": True, "subtree": 20},
    {"path": "esg.ratings", "title": "[рейтинги]", "depth": 1, "in_db": True, "subtree": 10},
    {"path": "esg.experiments", "title": "[отчёты]", "depth": 1, "in_db": False, "subtree": None},
]}


def _net(*nodes: tuple[str, int]) -> dict:
    return {"nodes": [{"id": f"сущность:{n}", "kind": "сущность", "facts": k} for n, k in nodes]
            + [{"id": "документ:[d]", "kind": "документ", "facts": 99}], "edges": []}


NETS = {
    "esg.finance": _net(("[ROA]", 5), ("[рейтинг]", 2), ("[поровну]", 3)),
    "esg.ratings": _net(("[рейтинг]", 7), ("[поровну]", 3)),
}


@pytest.fixture
def kbrag(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    seen: list[str] = []

    def fake(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
        seen.append(url)
        if "/api/kbs?" in url:
            return 200, json.dumps(TREE).encode(), "application/json"
        kb = url.split("kb=")[1].replace("%2E", ".")
        return (200, json.dumps(NETS[kb]).encode(), "application/json") if kb in NETS else (404, b"{}", "")

    monkeypatch.setattr(kb_api, "fetch", fake)
    kb_topics.reset()
    yield seen
    kb_topics.reset()


def test_main_topic_is_where_most_is_written(make_client, kbrag: list[str], monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    started: list = []
    monkeypatch.setattr(kb_topics.threading, "Thread", lambda target, daemon: started.append(target) or type(
        "T", (), {"start": lambda self: None})())
    c = make_client("rd", "reader")
    ids = ["сущность:[ROA]", "сущность:[рейтинг]", "сущность:[поровну]", "сущность:[нет нигде]"]
    first = c.post("/api/kb/concept-topics", json={"ids": ids}).json()
    assert first["ready"] is False and first["building"] is True and first["main"] == {}  # собирается в фоне
    assert len(started) == 1
    assert c.post("/api/kb/concept-topics", json={"ids": ids}).json()["building"] is True and len(started) == 1
    started[0]()  # фоновая сборка
    out = c.post("/api/kb/concept-topics", json={"ids": ids}).json()
    assert out["ready"] and not out["building"]
    assert [t["path"] for t in out["topics"]] == ["esg.finance", "esg.ratings"]  # без пустой ветки отчётов
    assert out["topics"][0] == {"path": "esg.finance", "title": "[финансы]", "articles": 20, "concepts": 3}
    # больше утверждений — в той теме; поровну — в более крупной; нет нигде — без темы
    assert out["main"] == {"сущность:[ROA]": "esg.finance", "сущность:[рейтинг]": "esg.ratings",
                           "сущность:[поровну]": "esg.finance"}
    assert not any("esg.experiments" in u for u in kbrag)


def test_needs_login_and_limits_ids(client, make_client, kbrag: list[str]) -> None:  # type: ignore[no-untyped-def]
    assert client.post("/api/kb/concept-topics", json={"ids": []}).status_code == 401
    c = make_client("rd", "reader")
    assert c.post("/api/kb/concept-topics", json={"ids": ["x"] * 1001}).status_code == 422


def test_kbrag_down_is_reported_not_crashed(kbrag: list[str], monkeypatch: pytest.MonkeyPatch, settings) -> None:  # type: ignore[no-untyped-def]
    def down(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
        raise OSError("[нет связи]")

    kb_topics.ensure(settings, down, start=lambda job: job())
    out = kb_topics.lookup(["сущность:[ROA]"])
    assert out["ready"] is False and out["building"] is False and "[нет связи]" in out["error"]
