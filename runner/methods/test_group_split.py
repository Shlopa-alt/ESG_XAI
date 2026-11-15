"""Деление на обучение и проверку у панели (компания × год): компания целиком в одной части.
Данные — синтетический шум (генератор с seed), не данные компаний (правило 7).

Запуск в окружении runner: cd runner/methods && python -m pytest test_group_split.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from common import folds, holdout
from sklearn.model_selection import KFold, train_test_split

HERE = Path(__file__).resolve().parent
UTF8 = {**os.environ, "PYTHONUTF8": "1"}


def test_holdout_without_groups_is_the_old_split() -> None:
    # прежние расчёты с тем же seed повторяются: деление без группы не изменилось
    tr, te = holdout(50, None, 7)
    old_tr, old_te = train_test_split(np.arange(50), test_size=0.2, random_state=7)
    assert tr.tolist() == old_tr.tolist() and te.tolist() == old_te.tolist()
    assert [(a.tolist(), b.tolist()) for a, b in folds(30, None, 3, 1)] == [
        (a.tolist(), b.tolist()) for a, b in KFold(3, shuffle=True, random_state=1).split(np.arange(30))]


def test_holdout_and_folds_keep_each_group_whole() -> None:
    groups = np.repeat([f"[компания {i}]" for i in range(25)], 4)
    tr, te = holdout(len(groups), groups, 3)
    assert len(tr) + len(te) == len(groups) and not set(groups[tr]) & set(groups[te])
    assert len(set(groups[te])) == 5  # 20 % компаний
    parts = folds(len(groups), groups, 5, 3)
    assert len(parts) == 5
    for a, b in parts:
        assert not set(groups[a]) & set(groups[b])


def _panel(tmp_path: Path) -> Path:
    # у каждой страны свой уровень признака и цели, между ними связи нет
    rng = np.random.default_rng(4)
    n_c, n_y = 60, 10
    country = np.repeat([f"[страна {i}]" for i in range(n_c)], n_y)
    level = {c: rng.normal(size=2) for c in np.unique(country)}
    x = np.array([level[c][0] for c in country]) + 0.05 * rng.normal(size=n_c * n_y)
    y = np.array([level[c][1] for c in country]) + 0.05 * rng.normal(size=n_c * n_y)
    path = tmp_path / "panel.csv"
    pd.DataFrame({"[страна]": country, "[x]": x, "[y]": y}).to_csv(path, index=False)
    return path


def _check(tmp_path: Path, data: Path, params: dict, tag: str) -> dict:
    res = tmp_path / tag
    done = subprocess.run(
        [sys.executable, "predictive_check.py", str(tmp_path), str(res), "--data", str(data),
         "--params", json.dumps({"target": "[y]", "features": ["[x]"], "splits": 8, **params}),
         "--experiment", "EXP-000", "--dataset", "DS-00"],
        cwd=HERE, env=UTF8, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(next(res.glob("*/run.json")).read_text(encoding="utf-8"))


def test_panel_without_group_inflates_r2_and_group_fixes_it(tmp_path: Path) -> None:
    data = _panel(tmp_path)
    plain = _check(tmp_path, data, {}, "plain")["summary"]
    grouped = _check(tmp_path, data, {"group": "[страна]"}, "grouped")
    s = grouped["summary"]
    # без группы бустинг «узнаёт» страну по значению признака: R² высокий, хотя связи нет
    # по странам — на странах, которых не было в обучении: связи нет, и R² это показывает
    assert plain["r2_mean"]["LightGBM"] > 0.15, plain["r2_mean"]
    assert s["r2_mean"]["LightGBM"] < 0.05, s["r2_mean"]
    assert s["group"] == "[страна]" and s["groups"] == 60
    assert grouped["seeds"]["group"] == "[страна]"
