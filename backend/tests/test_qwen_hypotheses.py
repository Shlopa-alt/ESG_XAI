import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Dataset, MethodologySection

TOKEN = {"X-Qwen-Token": "tok"}
REF = {"doc_id": "10.1_a", "title": "Статья", "doi": "10.1/a", "quote": "ESG investments reduce profitability"}


@pytest.fixture
def settings() -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev", qwen_token="tok")


@pytest.fixture
def tree(db_session: Session) -> None:
    n1 = MethodologySection(number="Н1", title="Направление 1", content="", kind="direction")
    n2 = MethodologySection(number="Н2", title="Направление 2", content="рейтинги", kind="direction")
    db_session.add_all([n1, n2])
    db_session.flush()
    v1 = MethodologySection(number="Н1.В1", title="Вариант 1", content="", kind="variant", parent_id=n1.id)
    v3 = MethodologySection(number="Н1.В3", title="Вариант 3", content="не расписан", kind="variant", parent_id=n1.id)
    db_session.add_all([v1, v3])
    db_session.flush()
    db_session.add(MethodologySection(number="Н1.В1.З1", title="Задание 1", content="компании", kind="task",
                                      parent_id=v1.id))
    db_session.add(MethodologySection(number="О1", title="Проверка моделей", content="отложенная выборка",
                                      kind="section"))
    db_session.add(Dataset(code="DS-04", title="TWSE", access_level="public"))
    db_session.commit()


def _run(c, hypotheses: list) -> dict:  # type: ignore[no-untyped-def,type-arg]
    job = c.post("/api/qwen/jobs", json={"kind": "hypotheses"}).json()
    c.post("/api/qwen/worker/next", headers=TOKEN)
    r = c.post(f"/api/qwen/worker/{job['id']}/result", headers=TOKEN,
               json={"status": "done", "result": {"hypotheses": hypotheses}})
    assert r.status_code == 200, r.text
    return r.json()


def _h(**kw: object) -> dict:  # type: ignore[type-arg]
    return {"node": "Н1.В1.З1", "title": "ESG-инвестиции снижают прибыльность", "statement": "Рост ESG-затрат снижает ROA",
            "rationale": "[1]", "dataset": "DS-04", "method": "exp007-hsu", "refs": [REF], **kw}


def test_context_targets_tasks_and_directions_without_tasks(make_client, tree) -> None:  # type: ignore[no-untyped-def]
    c = make_client("boss", "owner")
    ctx = c.post("/api/qwen/worker/context", headers=TOKEN).json()
    targets = {t["number"]: t for t in ctx["targets"]}
    assert set(targets) == {"Н1.В1.З1", "Н2"}  # вариант 3 без заданий — не цель
    assert [s["number"] for s in targets["Н1.В1.З1"]["sections"]] == ["О1"]
    assert [m["key"] for m in ctx["methods"]] and ctx["datasets"][0]["code"] == "DS-04"


def test_result_creates_proposed_qwen_hypothesis_with_refs(make_client, tree) -> None:  # type: ignore[no-untyped-def]
    c = make_client("boss", "owner")
    job = _run(c, [_h()])
    assert job["result"]["created"] == ["H-001"]
    h = c.get("/api/hypotheses/H-001").json()
    assert h["status"] == "proposed" and h["source"] == "qwen" and h["methodology_node"] == "Н1.В1.З1"
    assert h["suggested"]["dataset"] == "DS-04" and h["suggested"]["method"] == "exp007-hsu"
    assert h["refs"][0]["quote"] == REF["quote"]


def test_result_drops_ungrounded_wrong_node_and_duplicates(make_client, tree) -> None:  # type: ignore[no-untyped-def]
    c = make_client("boss", "owner")
    job = _run(c, [_h(refs=[]), _h(node="Н1.В3"), _h(node="Н9"), _h(), _h()])
    assert job["result"]["created"] == ["H-001"]  # без опоры, вариант без заданий, чужой узел, повтор — нет


def test_method_must_match_dataset_and_pending_limit(make_client, tree) -> None:  # type: ignore[no-untyped-def]
    c = make_client("boss", "owner")
    job = _run(c, [_h(title=f"Гипотеза номер {i}", dataset="DS-77" if i == 0 else "DS-04") for i in range(5)])
    assert len(job["result"]["created"]) == 3  # не больше трёх за проход на задание
    first = c.get(f"/api/hypotheses/{job['result']['created'][0]}").json()
    assert first["suggested"] == {"dataset": "", "method": "", "data_needed": ""}  # нет такого датасета → и метода
    assert _run(c, [_h(title="Ещё одна гипотеза")])["result"]["created"] == []  # три уже ждут рецензии
