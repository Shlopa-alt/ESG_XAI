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
        "direction": "рост",
        "link_quote": "фактор альфа заметно повышает показатель бета",
        "refs_direction": "рост",
        "direction_quote": "заметно повышает показатель бета у компаний",
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
    ok, comment = W._verify(H, CITED, TARGET)
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
    ok, comment = W._verify(H, CITED, TARGET)
    assert not ok
    assert why in comment


def test_sign_taken_from_statement_words(model: dict[str, Any]) -> None:
    """Модель пишет «связь без знака», чтобы не искать цитату о направлении, —
    знак берётся из утверждения."""
    model["answer"] = answer(
        direction="связь без знака", refs_direction="не сказано", direction_quote=""
    )
    ok, comment = W._verify(H, CITED, TARGET)
    assert not ok
    assert "направление «рост»" in comment


def test_horizon_not_in_task_or_refs(model: dict[str, Any]) -> None:
    ok, comment = W._verify(
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
    ok, comment = W._verify(H, [{"kind": "fragment", "title": "[таблица]", "text": table}], TARGET)
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
