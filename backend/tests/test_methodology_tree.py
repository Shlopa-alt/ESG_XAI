import pytest
from sqlalchemy.orm import Session

from app.models import Experiment, MethodologySection


@pytest.fixture
def tree(db_session: Session) -> None:
    """Корень: общий раздел О1 и направление Н1 с вариантом Н1.В1 и заданием Н1.В1.З1."""
    o1 = MethodologySection(number="О1", title="Проверка моделей", content="общий", kind="section", position=1)
    n1 = MethodologySection(number="Н1", title="Направление 1", content="н1", kind="direction", position=1)
    db_session.add_all([o1, n1])
    db_session.flush()
    v1 = MethodologySection(number="Н1.В1", title="Вариант 1", content="в1", kind="variant", parent_id=n1.id,
                            position=1)
    db_session.add(v1)
    db_session.flush()
    db_session.add(MethodologySection(number="Н1.В1.З1", title="Задание 1", content="з1", kind="task",
                                      parent_id=v1.id, position=1))
    db_session.add(Experiment(code="EXP-900", title="завершён", status="done", config={}, setup=[],
                              results=[], limitations=[], reproducibility=[]))
    db_session.commit()


def _accept(owner, code: str) -> dict:  # type: ignore[no-untyped-def,type-arg]
    owner.post(f"/api/change-requests/{code}/bases", json={"basis_type": "experiment", "experiment_code": "EXP-900"})
    owner.post(f"/api/change-requests/{code}/reviews", json={"verdict": "approve"})
    r = owner.patch(f"/api/change-requests/{code}", json={"status": "accepted"})
    assert r.status_code == 200, r.text
    return r.json()


def test_tree_order_and_parents(make_client, tree) -> None:  # type: ignore[no-untyped-def]
    sections = make_client("r", "reader").get("/api/methodology").json()["sections"]
    assert [(s["number"], s["parent"]) for s in sections] == [
        ("О1", ""), ("Н1", ""), ("Н1.В1", "Н1"), ("Н1.В1.З1", "Н1.В1")]


@pytest.mark.parametrize("parent,kind", [("Н1.В1.З1", "variant"), ("", "task"), ("Н1.В1", "direction")])
def test_add_refuses_wrong_nesting(make_client, tree, parent: str, kind: str) -> None:  # type: ignore[no-untyped-def]
    r = make_client("res", "researcher").post("/api/change-requests", json={
        "section": parent, "action": "add", "new_kind": kind, "new_title": "Новый узел", "title": "добавить",
        "proposed_content": "текст"})
    assert r.status_code == 422


def test_add_task_creates_numbered_node_on_accept(make_client, tree) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    r = owner.post("/api/change-requests", json={
        "section": "Н1.В1", "action": "add", "new_kind": "task", "new_title": "Задание 2. Бюджет региона",
        "title": "второе задание", "proposed_content": "оценить зависимость…"})
    assert r.status_code == 201, r.text
    assert r.json()["action"] == "add" and r.json()["section"] == "Н1.В1"
    _accept(owner, r.json()["code"])
    nodes = {s["number"]: s for s in owner.get("/api/methodology").json()["sections"]}
    assert nodes["Н1.В1.З2"]["kind"] == "task" and nodes["Н1.В1.З2"]["parent"] == "Н1.В1"
    assert nodes["Н1.В1.З2"]["title"] == "Задание 2. Бюджет региона"


def test_add_common_section_to_root(make_client, tree) -> None:  # type: ignore[no-untyped-def]
    owner = make_client("boss", "owner")
    r = owner.post("/api/change-requests", json={
        "section": "", "action": "add", "new_kind": "section", "new_title": "Источники данных",
        "title": "общий раздел", "proposed_content": "какие источники допустимы"})
    assert r.status_code == 201, r.text
    _accept(owner, r.json()["code"])
    nodes = {s["number"]: s for s in owner.get("/api/methodology").json()["sections"]}
    assert nodes["О2"]["parent"] == "" and nodes["О2"]["kind"] == "section"


def test_experiment_links_to_task(make_client, tree) -> None:  # type: ignore[no-untyped-def]
    c = make_client("res", "researcher")
    assert c.patch("/api/experiments/EXP-900", json={"methodology_node": "Н1.В1.З1"}).json()["methodology_node"] == "Н1.В1.З1"
    assert c.patch("/api/experiments/EXP-900", json={"methodology_node": "Н9"}).status_code == 422
    assert c.get("/api/experiments").json()[0]["methodology_node"] == "Н1.В1.З1"
