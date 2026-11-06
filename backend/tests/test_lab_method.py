"""Метод лаборатории в библиотеке: параметры R, X, Z, прошлый период. Столбцы — заглушки."""

import pytest

from app.services.run_templates import TEMPLATES, ParamError, check_params

LAB = TEMPLATES["lab-mlp"]
COLS = ["[R]", "[R прошлый]", "[x1]", "[x2]", "[размер]", "[отрасль]"]
NUM = {"[R]", "[R прошлый]", "[x1]", "[x2]", "[размер]"}


def test_lab_method_is_generic_and_cr01_by_default() -> None:
    assert LAB.scope == "generic" and LAB.workdir == "methods" and LAB.script == "lab_mlp.py"
    ok = check_params(LAB, {"target": "[R]", "features": ["[x1]", "[x2]"]}, COLS, NUM)
    assert ok["splits"] == 30  # CR-01: не меньше 30 разбиений
    assert ok["context"] == [] and ok["lag"] == ""


def test_context_may_be_text_inputs_may_not() -> None:
    params = {"target": "[R]", "features": ["[x1]"], "context": ["[размер]", "[отрасль]"],
              "lag": "[R прошлый]"}
    ok = check_params(LAB, params, COLS, NUM)
    assert ok["context"] == ["[размер]", "[отрасль]"] and ok["lag"] == "[R прошлый]"
    with pytest.raises(ParamError, match="не числовые"):
        check_params(LAB, {"target": "[R]", "features": ["[отрасль]"]}, COLS, NUM)


@pytest.mark.parametrize("params", [
    {"target": "[R]", "features": ["[R]", "[x1]"]},
    {"target": "[R]", "features": ["[x1]"], "context": ["[R]"]},
    {"target": "[R]", "features": ["[x1]", "[R прошлый]"], "lag": "[R прошлый]"},
    {"target": "[R]", "features": ["[x1]"], "lag": "[R]"},
    {"target": "[R]", "features": ["[x1]"], "context": ["[x1]"]},
    {"target": "[R]", "features": []},
])
def test_target_and_lag_are_not_inputs(params: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ParamError):
        check_params(LAB, params, COLS, NUM)
