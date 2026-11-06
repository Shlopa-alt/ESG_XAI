"""Задачи обработчика Qwen `tables` и `table_edit` (runner/qwen/worker.py) — без модели и KBRAG:
ответы модели, список статей и платформа подменены. Таблицы — заглушки."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

QWEN = Path(__file__).resolve().parents[2] / "runner" / "qwen"
sys.path.insert(0, str(QWEN))  # worker импортирует tables.py рядом с собой
_spec = importlib.util.spec_from_file_location("qwen_worker_tables", QWEN / "worker.py")
W = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(W)  # type: ignore[union-attr]


def _table(rows: list[list[str]], caption_idx: int | None = None) -> dict[str, Any]:
    t: dict[str, Any] = {
        "data": {
            "grid": [[{"text": c} for c in r] for r in rows],
            "table_cells": [{"start_row_offset_idx": 0, "column_header": True}],
        },
        "prov": [{"page_no": 2}],
    }
    if caption_idx is not None:
        t["captions"] = [{"$ref": f"#/texts/{caption_idx}"}]
    return t


DATA = _table(
    [["[объект]", "[а]", "[б]"]] + [[f"[объект {i}]", str(i), str(i * 2)] for i in range(12)]
)
RESULTS = _table(
    [["[переменная]", "[коэф.]", "[t]"]] + [[f"[x{i}]", "0,5***", "(2,1)"] for i in range(12)]
)


class Platform:
    def __init__(self, known: list[list[Any]], draft: dict[str, Any] | None = None) -> None:
        self.known, self.draft = known, draft
        self.calls: list[str] = []

    def post(self, path: str, body: Any = None) -> tuple[int, Any]:
        self.calls.append(path)
        if path == "tables-context":
            return 200, {"known": self.known}
        if path == "draft-context":
            return 200, self.draft
        raise AssertionError(path)


@pytest.fixture
def kbrag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    acq = tmp_path / ".local" / "acquired"
    acq.mkdir(parents=True)
    doc = {
        "texts": [{"text": "[подпись]"}],
        "tables": [DATA, RESULTS, _table([["[а]", "[б]", "[в]"], ["1", "2", "3"]])],
    }
    (acq / "[статья].docling.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(
        W,
        "kbrag_get",
        lambda path, params, token, timeout_s=20: {"documents": []} if params.get("kb") == "esg.experiments" else {
            "documents": [
                {"doc_id": "[статья]", "title": "[название]", "url": "https://doi.org/10.0000/[x]"},
                {"doc_id": "[без разметки]", "title": "[название 2]", "url": ""},
            ]
        },
    )
    return tmp_path


def test_tables_asks_model_only_about_new_data_tables(
    kbrag: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def fake(prompt: str, max_tokens: int, system: str, schema: dict[str, Any]) -> dict[str, Any]:
        asked.append(prompt)
        return {
            "row_is": "[объект]",
            "observations": True,
            "why": "",
            "title": "[датасет]",
            "description": "[столбцы]",
        }

    monkeypatch.setattr(W, "ask_json", fake)
    out = W.job_tables(
        {"id": 1, "payload": {}}, {"platform": Platform([]), "kbrag": kbrag, "kbrag_token": ""}
    )
    assert len(asked) == 1  # таблица результатов (звёздочки) и короткая — без модели
    d = out["drafts"][0]
    assert d["table_number"] == 1 and d["doi"] == "10.0000/[x]" and d["page"] == 2
    assert d["description"] == "Строка — [объект]. [столбцы]" and len(d["rows"]) == 12
    assert any("нет разметки" in s for s in out["skipped"])
    again = W.job_tables(
        {"id": 2, "payload": {"doc_id": "[статья]"}},
        {"platform": Platform([["[статья]", 1]]), "kbrag": kbrag, "kbrag_token": ""},
    )
    assert again["drafts"] == [] and len(asked) == 1  # уже разобранная — не спрашивать снова


def _ok(*a: Any, **k: Any) -> dict[str, Any]:
    return {"row_is": "[объект]", "observations": True, "why": "", "title": "[название]", "description": "[столбцы]"}


def test_lab_reports_are_not_scanned(kbrag: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(W, "_own_reports", lambda token: {"[статья]"})
    monkeypatch.setattr(W, "ask_json", _ok)
    out = W.job_tables({"id": 1, "payload": {}}, {"platform": Platform([]), "kbrag": kbrag, "kbrag_token": ""})
    assert out["drafts"] == [] and out["docs"] == 1


def test_all_tables_failed_fails_the_job(kbrag: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*a: Any, **k: Any) -> dict[str, Any]:
        raise TimeoutError("[нет ответа]")

    monkeypatch.setattr(W, "ask_json", down)
    with pytest.raises(RuntimeError, match="ни по одной"):
        W.job_tables({"id": 1, "payload": {}}, {"platform": Platform([]), "kbrag": kbrag, "kbrag_token": ""})


def test_model_says_not_observations(kbrag: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        W,
        "ask_json",
        lambda *a, **k: {
            "row_is": "[x]",
            "observations": False,
            "why": "[веса метода]",
            "title": "",
            "description": "",
        },
    )
    out = W.job_tables(
        {"id": 1, "payload": {}}, {"platform": Platform([]), "kbrag": kbrag, "kbrag_token": ""}
    )
    assert out["drafts"] == [] and any("[веса метода]" in s for s in out["skipped"])


def test_edit_rows_are_one_based_in_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    draft = {
        "title": "[т]",
        "article_title": "[с]",
        "caption": "",
        "description": "",
        "columns": ["[а]"],
        "rows": [["[x]"], ["[y]"]],
        "row_count": 2,
        "history": [],
    }
    seen: dict[str, str] = {}

    def fake(prompt: str, max_tokens: int, system: str, schema: dict[str, Any]) -> dict[str, Any]:
        seen["prompt"] = prompt
        return {
            "explanation": "[пояснение]",
            "ops": [
                {"op": "drop_rows", "rows": [2]},
                {"op": "set_cell", "rows": [1], "column": "[а]", "value": "[z]"},
                {"op": "transpose", "column": "", "columns": []},
            ],
        }

    monkeypatch.setattr(W, "ask_json", fake)
    out = W.job_table_edit(
        {"id": 1, "payload": {"draft": 7, "command": "[команда]"}},
        {"platform": Platform([], draft)},
    )
    assert "1. [x]" in seen["prompt"] and "КОМАНДА: [команда]" in seen["prompt"]
    assert out["ops"] == [
        {"op": "drop_rows", "rows": [1]},
        {"op": "set_cell", "column": "[а]", "value": "[z]", "row": 0},
        {"op": "transpose"},
    ]
    assert out["draft"] == 7
