"""«Что говорят статьи» по пункту методики: сводка фактов KBRAG.

Тексты — заглушки [...], не данные статей."""

import json

import pytest
from sqlalchemy.orm import Session

from app.api import kb as kb_api
from app.models import Experiment, Hypothesis, MethodologySection
from app.services import articles_summary as svc

Q = [{"quote": "[цитата]", "doc_id": "d1", "title": "[статья]", "year": 2024, "url": "",
      "chunk_id": 1}]
FACTOR = {"name": "[фактор]", "includes": ["[часть фактора]"], "facts": [
    {"about": "[фактор]", "direction": "→", "relation": "повышает", "other": "[результат]",
     "documents": 5, "quotes": Q},
    {"about": "[часть фактора]", "direction": "→", "relation": "предположительно повышает",
     "other": "[результат]", "documents": 1, "quotes": Q},
    {"about": "[фактор]", "direction": "→", "relation": "снижает", "other": "[результат]",
     "documents": 2, "quotes": Q},
    {"about": "[фактор]", "direction": "→", "relation": "не влияет",
     "other": "[синоним результата]", "documents": 2, "quotes": Q},
    # не о результате и не от фактора — в сводку не идут
    {"about": "[фактор]", "direction": "→", "relation": "повышает", "other": "[другое]",
     "documents": 9, "quotes": Q},
    {"about": "[фактор]", "direction": "←", "relation": "повышает", "other": "[результат]",
     "documents": 9, "quotes": Q},
]}
OUTCOME = {"name": "[результат]", "includes": ["[синоним результата]"], "facts": []}


def test_summarize_counts_directions_and_agreement() -> None:
    s = svc.summarize(FACTOR, OUTCOME)
    docs = {g["key"]: g["documents"] for g in s["groups"]}
    assert docs == {"up": 6, "down": 2, "none": 2, "other": 0}
    assert (s["total"], s["leader"], s["agreement"]) == (10, "up", 0.6)
    up = next(g for g in s["groups"] if g["key"] == "up")
    assert [link["hedged"] for link in up["links"]] == [False, True]
    assert up["links"][0]["quotes"] == Q


def test_summarize_without_facts_has_no_agreement() -> None:
    s = svc.summarize({"name": "[фактор]", "facts": []}, OUTCOME)
    assert (s["total"], s["leader"], s["agreement"]) == (0, "", None)


@pytest.mark.parametrize(("relation", "key"), [
    ("повышает", "up"), ("предположительно снижает", "down"), ("не влияет", "none"),
    ("не повышает", "other"), ("входит в", "other"),
])
def test_direction(relation: str, key: str) -> None:
    assert svc.direction(relation) == key


@pytest.fixture
def node(db_session: Session) -> MethodologySection:
    n = MethodologySection(number="Н1.В1.З1", title="[фактор] и [результат]", content="",
                           kind="task", position=1)
    db_session.add(n)
    db_session.flush()
    db_session.add(Experiment(code="EXP-001", title="[проверка]", status="done", outcome="rejected",
                              methodology_node_id=n.id))
    db_session.add(Hypothesis(code="H-001", title="[идея]", statement="[утверждение]",
                              effect="increases", target_kind="financial", weight=2,
                              methodology_node_id=n.id))
    db_session.commit()
    return n


def _kbrag(monkeypatch: pytest.MonkeyPatch, answers: dict[str, tuple[int, object]]) -> list[str]:
    seen: list[str] = []

    def fake(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
        seen.append(url)
        name = next(k for k in answers if f"name={k}" in url)
        code, body = answers[name]
        return code, json.dumps(body).encode(), "application/json"

    monkeypatch.setattr(kb_api, "fetch", fake)
    return seen


def test_articles_endpoint_adds_our_results(make_client, node, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    seen = _kbrag(monkeypatch, {"%5B%D1%84": (200, FACTOR), "%5B%D1%80": (200, OUTCOME)})
    c = make_client("r", "reader")
    r = c.get(f"/api/methodology/sections/{node.number}/articles",
              params={"factor": "[фактор]", "outcome": "[результат]"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total"], body["leader"]) == (10, "up")
    assert body["experiments"] == [{"code": "EXP-001", "title": "[проверка]", "status": "done",
                                    "outcome": "rejected"}]
    assert body["hypotheses"][0]["effect"] == "increases"
    assert all("kb=esg" in u and "/api/dataset?" in u for u in seen)


def test_articles_unknown_concept_is_404(make_client, node, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _kbrag(monkeypatch, {"%5B%D1%84": (400, {"error": "[...]"}), "%5B%D1%80": (200, OUTCOME)})
    r = make_client("r", "reader").get(f"/api/methodology/sections/{node.number}/articles",
                                       params={"factor": "[фактор]", "outcome": "[результат]"})
    assert r.status_code == 404 and "в статьях банка нет" in r.json()["detail"]


def test_articles_needs_login_and_node(client, make_client) -> None:  # type: ignore[no-untyped-def]
    params = {"factor": "[ф]", "outcome": "[р]"}
    assert client.get("/api/methodology/sections/Н9/articles", params=params).status_code == 401
    r = make_client("r", "reader").get("/api/methodology/sections/Н9/articles", params=params)
    assert r.status_code == 404
