"""Разбор таблиц статей (runner/qwen/tables.py): сетка docling → наблюдения. Без KBRAG.

Таблицы — заглушки: подписи в скобках, числа — образцы записи (разряды, дроби, пропуски),
а не данные."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location(
    "article_tables", Path(__file__).resolve().parents[2] / "runner" / "qwen" / "tables.py"
)
T = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(T)  # type: ignore[union-attr]


def docling(rows: list[list[str]], header_rows: int = 1) -> dict[str, Any]:
    """Таблица в разметке docling: сетка текста и пометка строк шапки."""
    return {"data": {
        "grid": [[{"text": c} for c in r] for r in rows],
        "table_cells": [{"start_row_offset_idx": i, "column_header": True}
                        for i in range(header_rows)],
    }}


@pytest.mark.parametrize(("text", "value"), [
    ("12,5", 12.5), ("1 234,5", 1234.5), ("1,234,567.5", 1234567.5), ("1.234,5", 1234.5),
    ("0,25", 0.25), ("−2,5", -2.5), ("18 %", 18.0), ("-", None), ("н/д", None), ("[текст]", None),
])
def test_number_formats(text: str, value: float | None) -> None:
    assert T.number(text) == value


def test_rank_tie_is_midpoint_but_period_is_not() -> None:
    assert T.tie("7-8") == 7.5
    assert T.tie("2013-2014") is None


def test_groups_side_by_side_become_rows() -> None:
    t = T.parse(docling([
        ["[показатель а]", "[показатель а]", "[показатель б]", "[показатель б]"],
        ["[группа 1]", "[группа 2]", "[группа 1]", "[группа 2]"],
        ["1", "2", "3", "4"], ["5", "-", "7", "8"], ["9", "10", "11", "12"],
    ], header_rows=2))
    assert t.columns == ["группа", "[показатель а]", "[показатель б]"]
    assert t.rows[:3] == [
        ["[группа 1]", 1.0, 3.0], ["[группа 2]", 2.0, 4.0], ["[группа 1]", 5.0, 7.0]]
    assert ["[группа 2]", None, 8.0] in t.rows  # пропуск — пустая ячейка, строка не теряется
    assert any("группы рядом" in n for n in t.notes)


def test_indicators_by_years_are_transposed_and_totals_dropped() -> None:
    t = T.parse(docling([
        ["[показатель]", "2015", "2016", "2017"],
        ["[объём а]", "1 000,0", "1 100,0", "1 200,0"],
        ["[объём б]", "10", "11", "12"],
        ["Всего", "1 010", "1 111", "1 212"],
    ]))
    assert t.columns == ["год", "[объём а]", "[объём б]"]
    assert t.rows == [[2015.0, 1000.0, 10.0], [2016.0, 1100.0, 11.0], [2017.0, 1200.0, 12.0]]
    assert any("повёрнута" in n for n in t.notes) and any("«Всего»" in n for n in t.notes)


def test_sections_keep_periods_as_rows() -> None:
    t = T.parse(docling([
        ["", "[индекс а], %", "[индекс б], %"],
        ["[горизонт 1]", "[горизонт 1]", "[горизонт 1]"],
        ["2015", "1,5", "2,5"], ["2016", "3,5", "4,5"], ["2017", "5,5", "6,5"],
        ["[горизонт 2]", "[горизонт 2]", "[горизонт 2]"],
        ["2015-2016", "7,5", "8,5"], ["2016-2017", "9,5", "10,5"],
    ]))
    assert t.columns == ["период", "[индекс а], %", "[индекс б], %", "раздел"]
    assert len(t.rows) == 5
    assert t.rows[-1] == ["2016-2017", 9.5, 10.5, "[горизонт 2]"]
    assert set(t.numeric_columns()) == {"[индекс а], %", "[индекс б], %"}


def test_merged_cells_are_missing_not_guessed() -> None:
    t = T.parse(docling([["[объект]", "[а]", "[б]"], ["[x]", "100 1,5", "2"], ["[y]", "3", "4"]]))
    assert t.rows[0] == ["[x]", None, 2.0]
    assert any("слиплись" in n for n in t.notes)


def _data_table(n: int, cell: str = "1,5") -> Any:
    rows = [[f"[объект {i}]", cell, "2"] for i in range(n)]
    return T.parse(docling([["[объект]", "[а]", "[б]"], *rows]))


def test_looks_like_data() -> None:
    assert T.looks_like_data(_data_table(12), "")[0]
    assert not T.looks_like_data(_data_table(5), "")[0]  # мало строк
    assert not T.looks_like_data(_data_table(12, "0,5***"), "")[0]  # звёздочки значимости
    assert not T.looks_like_data(_data_table(12), "Table 3. Regression results")[0]
    matrix = T.parse(docling([["", "[а]", "[б]", "[в]"]] + [[x, "1", "0,5", "0,2"] for x in
                                                          ("[а]", "[б]", "[в]")] * 4))
    assert not T.looks_like_data(matrix, "")[0]
