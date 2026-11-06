"""Сбор опор и проверка гипотез в runner/qwen/worker.py — без модели и KBRAG (ответы подменены).

Тексты — явные заглушки: проверяется логика решений, не содержание."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location(
    "qwen_worker", Path(__file__).resolve().parents[2] / "runner" / "qwen" / "worker.py"
)
W = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(W)  # type: ignore[union-attr]

PROSE = (
    "[заглушка] фактор альфа заметно повышает показатель бета "
    "у компаний выборки за три года наблюдения"
)
TARGET = {
    "number": "Н1.В1.З1",
    "title": "[задание]",
    "content": "[заглушка] зависимость на период 3 года",
}
CITED = [{"kind": "fragment", "title": "[статья]", "text": PROSE}]
H = {
    "title": "[гипотеза]",
    "statement": "Фактор альфа повышает показатель бета через 3 года",
    "rationale": "[обоснование генератора]",
}


def answer(**kw: Any) -> dict[str, Any]:
    base = {
        "task_level": "компания",
        "factor": "альфа",
        "outcome": "бета",
        "level": "компания",
        "refs_level": "компания",
        "factor_kind": "другое",
        "refs_factor_kind": "другое",
        "direction": "рост",
        "link_quote": "фактор альфа заметно повышает показатель бета",
        "refs_direction": "рост",
        "direction_quote": "заметно повышает показатель бета у компаний",
        "link_scope": "не сказано",
        "comment": "",
    }
    return {**base, **kw}


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Подменяет ask_json; в calls — что проверке показали и с какой температурой."""
    state: dict[str, Any] = {"answer": answer(), "calls": []}

    def fake(
        prompt: str, max_tokens: int, system: str, schema: dict[str, Any], temperature: float = 0.3
    ) -> Any:
        state["calls"].append({"prompt": prompt, "temperature": temperature})
        if state.get("queue"):  # несколько вызовов подряд: проверка → переписывание → проверка
            return state["queue"].pop(0)
        return state["answer"]

    monkeypatch.setattr(W, "ask_json", fake)
    return state


@pytest.mark.parametrize(
    "text",
    [
        "Table 6. Correlation matrix (1) ROA, (1) = 1.000. (1) ROA, (2) = . (1) ROA, (3) = .",
        "Energy Efficiency, Improvement (%) = +20%. Energy Efficiency, Source = UN. Waste = 5%.",
        "|Строительство|1,50|0,55|1,60|2,20|3,22|2,14|0|0|0|0,40|0,15|0,11|",
        "$$ S _ { \\ } C o n t r y = \\beta \\cdot \\text {Co} $$",
    ],
)
def test_tables_and_formulas_are_not_evidence(text: str) -> None:
    assert not W._is_prose(text)


def test_prose_is_evidence() -> None:
    assert W._is_prose(PROSE)


def test_quote_must_be_in_sources() -> None:
    assert W._quoted(
        "Фактор альфа заметно повышает показатель", [PROSE]
    )  # регистр и знаки — не важны
    # одно слово из десяти с другим окончанием — всё ещё цитата
    assert W._quoted("фактор альфа заметно повышает показатели бета у компаний выборки за", [PROSE])
    assert not W._quoted("фактор гамма снижает показатель дельта", [PROSE])  # пересказ — не цитата
    assert not W._quoted("альфа повышает", [PROSE])  # слишком коротко


def test_years() -> None:
    assert W._years("на 3-летнем горизонте") == {"3"}
    assert W._years("через 3–5 лет") == {"3", "5"}
    assert W._years("over 10 years") == {"10"}


def test_grounded_hypothesis_passes_at_zero_temperature(model: dict[str, Any]) -> None:
    ok, comment, *_ = W._verify(H, CITED, TARGET)
    assert ok, comment
    assert "связь в опорах" in comment
    call = model["calls"][0]
    assert call["temperature"] == 0
    assert (
        "[обоснование генератора]" not in call["prompt"]
    )  # уговоры генератора проверке не показываются


@pytest.mark.parametrize(
    ("kw", "why"),
    [
        ({"level": "бюджет региона"}, "не о результате задания"),
        ({"refs_level": "бюджет региона"}, "опоры о другом уровне"),
        ({"link_quote": "фактор гамма связан с налогами региона"}, "цитата не дословная"),
        ({"link_quote": ""}, "в опорах нет связи"),
        ({"refs_direction": "снижение"}, "в опорах: снижение"),
        ({"direction_quote": "[нет такой цитаты в опорах вообще]"}, "нет цитаты"),
    ],
)
def test_verifier_decides_in_code(model: dict[str, Any], kw: dict[str, Any], why: str) -> None:
    model["answer"] = answer(**kw)
    ok, comment, *_ = W._verify(H, CITED, TARGET)
    assert not ok
    assert why in comment


def test_sign_taken_from_statement_words(model: dict[str, Any]) -> None:
    """Модель пишет «связь без знака», чтобы не искать цитату о направлении, —
    знак берётся из утверждения."""
    model["answer"] = answer(
        direction="связь без знака", refs_direction="не сказано", direction_quote=""
    )
    ok, comment, *_ = W._verify(H, CITED, TARGET)
    assert not ok
    assert "направление «рост»" in comment


def test_horizon_not_in_task_or_refs(model: dict[str, Any]) -> None:
    ok, comment, *_ = W._verify(
        {**H, "statement": "Фактор альфа повышает показатель бета через 3–5 лет"}, CITED, TARGET
    )
    assert not ok
    assert "горизонт 5 лет" in comment


def test_quote_from_table_does_not_count(model: dict[str, Any]) -> None:
    table = (
        "ESG, 1 = 0.011. ESG, 2 = 0.013. ROA, 1 = 0.2. ROA, 2 = 0.3. "
        "фактор альфа повышает показатель бета"
    )
    model["answer"] = answer(link_quote="фактор альфа повышает показатель бета")
    ok, comment, *_ = W._verify(
        H, [{"kind": "fragment", "title": "[таблица]", "text": table}], TARGET
    )
    assert not ok
    assert "в опорах нет связи" in comment


def test_evidence_takes_every_query_and_title_last(monkeypatch: pytest.MonkeyPatch) -> None:
    """По кругу: лучший фрагмент каждого запроса раньше вторых; название задания — последним;
    таблицы выброшены; один факт от двух сущностей — один раз."""
    queries = ["q1", "q2", "q3"]
    monkeypatch.setattr(W, "_plan", lambda t: (queries, ["e1", "e2"]))
    monkeypatch.setattr(W, "log", lambda *a: None)
    fact = {
        "about": "[a]",
        "other": "[b]",
        "relation": "повышает",
        "direction": "→",
        "documents": 1,
        "quotes": [{"doc_id": "d-f", "title": "[ф]", "quote": "[цитата факта]"}],
    }

    def kbrag_get(path: str, params: dict[str, Any], token: str) -> dict[str, Any]:
        if path == "dataset":
            return {"facts": [fact]}
        q = params["q"]
        hits = [
            {"chunk_id": hash((q, i)), "doc_id": f"{q}-{i}", "title": q, "text": f"{PROSE} {q} {i}"}
            for i in range(6)
        ]
        hits.insert(
            0,
            {
                "chunk_id": hash((q, "t")),
                "doc_id": f"{q}-t",
                "title": q,
                "text": "Table 1. A, 1 = 2. B, 1 = 3. C = 4",
            },
        )
        return {"hits": hits}

    monkeypatch.setattr(W, "kbrag_get", kbrag_get)
    items = W._evidence(TARGET, "")
    frags = [it["doc_id"] for it in items if it["kind"] == "fragment"]
    assert frags[:4] == ["q1-0", "q2-0", "q3-0", "[задание]-0"]
    assert len(frags) == W.FRAGMENTS
    assert not any(d.endswith("-t") for d in frags)
    assert [it["fact"] for it in items if it["kind"] == "fact"] == ["[a] — повышает — [b]"]


def test_rating_instead_of_investment_is_marked(model: dict[str, Any]) -> None:
    """Правило 8: утверждение об объёме ESG-инвестиций, опоры — об ESG-рейтинге, модель молчит —
    гипотеза проходит, но с пометкой в названии и утверждении."""
    model["answer"] = answer(factor_kind=W.INVESTMENT, refs_factor_kind="ESG-рейтинг или балл")
    ok, _, marks, _ = W._verify(H, CITED, TARGET)
    assert ok
    assert marks == {"proxy": "ESG-рейтинг или балл"}
    marked = W._mark(H, marks)
    assert marked["title"] == "[гипотеза] (по ESG-рейтингу)"
    assert "ESG-рейтинг или балл как замена объёма ESG-инвестиций" in marked["statement"]
    assert marked["rationale"] == H["rationale"]


def test_replacement_already_said_is_not_marked_twice(model: dict[str, Any]) -> None:
    model["answer"] = answer(factor_kind=W.INVESTMENT, refs_factor_kind="ESG-рейтинг или балл")
    said = {**H, "statement": f"{H['statement']} (ESG-рейтинг как замена объёма инвестиций)"}
    assert W._verify(said, CITED, TARGET)[2] == {}
    assert W._mark(said, {}) is said


def test_investment_in_refs_is_not_marked(model: dict[str, Any]) -> None:
    model["answer"] = answer(factor_kind=W.INVESTMENT, refs_factor_kind=W.INVESTMENT)
    assert W._verify(H, CITED, TARGET)[2] == {}


UNSIGNED = {
    "title": "[гипотеза без знака]",
    "statement": "Фактор альфа связан с показателем бета через 3 года",
}
NO_SIGN_IN_REFS = {"refs_direction": "связь без знака", "direction_quote": ""}


def test_sign_not_in_refs_is_removed(model: dict[str, Any]) -> None:
    """Опоры говорят только, что связь есть, — знак убирается,
    гипотеза проходит после повторной проверки."""
    model["queue"] = [answer(**NO_SIGN_IN_REFS), UNSIGNED,
                      answer(direction="связь без знака", **NO_SIGN_IN_REFS)]
    h, comment = W._review(H, CITED, TARGET)
    assert h is not None, comment
    assert h["statement"] == UNSIGNED["statement"]
    assert comment.startswith("знак убран")
    assert len(model["calls"]) == 3 and all(c["temperature"] == 0 for c in model["calls"])


def test_contradicted_sign_is_not_rewritten(model: dict[str, Any]) -> None:
    """Опора с цитатой называет другой знак — это опровержение, а не пробел:
    гипотеза отклоняется."""
    model["answer"] = answer(refs_direction="снижение")
    assert W._verify(H, CITED, TARGET)[3] is False
    h, comment = W._review(H, CITED, TARGET)
    assert h is None and "в опорах: снижение" in comment
    assert len(model["calls"]) == 2  # без переписывания


def test_sign_left_after_rewrite_is_rejected(model: dict[str, Any]) -> None:
    model["queue"] = [answer(**NO_SIGN_IN_REFS),
                      {**UNSIGNED,
                       "statement": "Фактор альфа положительно связан с показателем бета"}]
    h, comment = W._review(H, CITED, TARGET)
    assert h is None and "направление «рост»" in comment


def test_other_failure_is_not_rescued_by_unsign(model: dict[str, Any]) -> None:
    model["answer"] = answer(level="бюджет региона", **NO_SIGN_IN_REFS)
    assert W._verify(H, CITED, TARGET)[3] is False
    assert W._review(H, CITED, TARGET)[0] is None


@pytest.mark.parametrize(
    ("text", "signed"),
    [
        ("Фактор альфа повышает показатель бета", True),
        ("Фактор альфа положительно влияет на бета", True),
        ("Затраты на снижение выбросов связаны с показателем бета", False),
        ("Фактор альфа связан с показателем бета", False),
    ],
)
def test_sign_words(text: str, signed: bool) -> None:
    assert bool(W.SIGNED.search(text)) is signed


ABROAD_PROSE = (
    "[заглушка] согласованность рейтингов провайдеров альфа и бета "
    "в среднем составляет 24% по выборке компаний"
)
ABROAD_CITED = [{"kind": "fragment", "title": "[статья]", "text": ABROAD_PROSE}]
ABROAD_ANSWER = {
    "link_quote": "согласованность рейтингов провайдеров альфа и бета",
    "link_scope": "другие страны или мир",
    "direction": "связь без знака",
    "refs_direction": "связь без знака",
    "direction_quote": "",
}


def test_foreign_figure_for_russia_is_marked(model: dict[str, Any]) -> None:
    """Правило 8: число зарубежных провайдеров, выданное за ожидаемое для России, —
    гипотеза проходит, но число названо ориентиром, а не ожиданием."""
    model["answer"] = answer(**ABROAD_ANSWER)
    h = {**H, "statement": "Рейтинги российских агентств согласованы на уровне 24% через 3 года"}
    ok, comment, marks, _ = W._verify(h, ABROAD_CITED, TARGET)
    assert ok, comment
    assert marks == {"abroad": ["24%"]}
    marked = W._mark(h, marks)
    assert marked["title"] == "[гипотеза] (по зарубежным данным)"
    assert "24% — ориентир для сравнения, а не ожидаемое значение" in marked["statement"]


@pytest.mark.parametrize(
    ("statement", "scope", "marked"),
    [
        # о России не сказано — переносить не на что
        ("Рейтинги провайдеров согласованы на уровне 24% через 3 года", W.ABROAD, False),
        # опоры о России
        ("Рейтинги российских агентств согласованы на уровне 24% через 3 года", "Россия", False),
        # перенос назван, чисел из опор нет
        ("По зарубежным данным рейтинги российских агентств согласованы слабо", W.ABROAD, False),
        # перенос не назван, чисел нет — пометка без чисел
        ("Рейтинги российских агентств согласованы слабо", W.ABROAD, True),
    ],
)
def test_foreign_data_mark_only_when_needed(
    model: dict[str, Any], statement: str, scope: str, marked: bool
) -> None:
    model["answer"] = answer(**{**ABROAD_ANSWER, "link_scope": scope})
    ok, comment, marks, _ = W._verify({**H, "statement": statement}, ABROAD_CITED, TARGET)
    assert ok, comment
    assert ("abroad" in marks) is marked
