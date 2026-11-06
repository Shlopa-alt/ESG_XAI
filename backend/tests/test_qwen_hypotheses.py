import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Dataset, MethodologySection
from app.services.qwen_hypotheses import repeats

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
    # разные идеи: проверяется лимит, не повторы
    words = ["[альфа]", "[бета]", "[гамма]", "[дельта]", "[эпсилон]"]
    job = _run(c, [_h(title=f"ESG-инвестиции и {w}", dataset="DS-77" if i == 0 else "DS-04")
                   for i, w in enumerate(words)])
    assert len(job["result"]["created"]) == 3  # не больше трёх за проход на задание
    first = c.get(f"/api/hypotheses/{job['result']['created'][0]}").json()
    assert first["suggested"] == {"dataset": "", "method": "", "data_needed": ""}  # нет такого датасета → и метода
    # три уже ждут рецензии
    assert _run(c, [_h(title="ESG-инвестиции и [омега]")])["result"]["created"] == []


def test_paraphrase_of_existing_is_a_repeat(make_client, tree) -> None:  # type: ignore[no-untyped-def]
    """Qwen перефразирует уже предложенные («влияют на» → «улучшают»); отклонённые — тоже повтор."""
    c = make_client("boss", "owner")
    first = _run(c, [_h(title="ESG-инвестиции влияют на [показатель альфа] через 3 года")])
    first = first["result"]["created"]
    c.patch(f"/api/hypotheses/{first[0]}", json={"status": "rejected", "note": "[причина]"})
    job = _run(c, [
        _h(title="ESG-инвестиции улучшают [показатель альфа] компаний"),  # перефраз отклонённой
        _h(title="ESG-инвестиции влияют на результаты компаний"),  # пересказ задания без своих слов
        _h(title="ESG-инвестиции снижают [показатель бета]"),  # другая идея
    ])
    assert len(job["result"]["created"]) == 1
    assert len(job["result"]["repeats"]) == 2  # отброшенное видно в итоге задачи
    assert "отброшено как повтор: 2" in job["message"]
    kept = c.get(f"/api/hypotheses/{job['result']['created'][0]}").json()
    assert kept["title"].endswith("[показатель бета]")


@pytest.mark.parametrize(("title", "existing", "same"), [
    ("Веса критериев влияют на согласованность ESG-рейтингов",
     ["Разные веса ESG-блоков влияют на согласованность рейтингов"], True),
    ("ESG-инвестиции влияют на региональный бюджет через 3 года",
     ["ESG-инвестиции влияют на бюджет региона через экономические показатели"], True),
    ("Согласованность ESG-рейтингов влияет на их предсказательную силу",
     ["Разные веса ESG-блоков влияют на согласованность рейтингов"], False),
    ("ESG-инвестиции повышают эффективность энергопотребления в регионах",
     ["ESG-инвестиции улучшают экологические показатели региона"], False),
    ("ESG-инвестиции влияют на бюджет региона", [], False),  # первая по заданию — не повтор
    # другая буква ESG при тех же остальных словах — другая идея
    ("Экологические затраты связаны со стоимостью капитала",
     ["Социальные затраты связаны со стоимостью капитала"], False),
    ("Экологические затраты снижают стоимость капитала",
     ["Экологические затраты связаны со стоимостью капитала"], True),
])
def test_repeats(title: str, existing: list[str], same: bool) -> None:
    """Названия — из стресс-теста генерации гипотез на пилотном корпусе ESG (ноябрь 2026)."""
    assert (repeats(title, existing) is not None) is same
