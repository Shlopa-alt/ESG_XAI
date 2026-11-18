"""Тесты метода «Поиск связей». Данные — синтетический шум с заданными связями (генератор с seed):
проверяется, что метод находит заложенное и не находит лишнего, а не какие-то настоящие записи.

Запуск в окружении runner: cd runner/methods && python -m pytest test_correlation_scan.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from correlation_scan import bh, pair_test, xi

HERE = Path(__file__).resolve().parent
UTF8 = {**os.environ, "PYTHONUTF8": "1"}  # сообщения метода — по-русски; на Windows иначе cp1251


def test_xi_sees_nonmonotone_dependence_that_rho_misses() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=300)
    u_shape = x**2
    t = pair_test(x, u_shape)
    assert t is not None
    assert abs(t["rho"]) < 0.2 and t["xi"] > 0.5 and t["p_xi"] < 1e-6
    assert xi(x, rng.normal(size=300)) < 0.15


def test_pair_test_skips_constant_and_short_columns() -> None:
    assert pair_test(np.ones(50), np.arange(50.0)) is None
    assert pair_test(np.arange(5.0), np.arange(5.0)) is None


def test_bh_controls_false_discoveries() -> None:
    assert bh([0.001, 0.002, 0.04, 0.5], 0.1) == [True, True, True, False]
    assert bh([0.04, 0.5, 0.6, 0.7], 0.1) == [False, False, False, False]


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    rng = np.random.default_rng(1)
    n = 400
    x = rng.normal(size=n)
    cols = {"[x]": x, "[y]": 0.6 * x + rng.normal(size=n), "[u]": x**2 + 0.5 * rng.normal(size=n),
            "[копия x]": x * 1.0001, **{f"[шум {i}]": rng.normal(size=n) for i in range(6)}}
    path = tmp_path / "srez.csv"
    pd.DataFrame(cols).to_csv(path, index=False)
    return path


def test_scan_end_to_end(synthetic: Path, tmp_path: Path) -> None:
    res = tmp_path / "res"
    done = subprocess.run(
        [sys.executable, "correlation_scan.py", str(tmp_path), str(res), "--data", str(synthetic),
         "--params", json.dumps({"seed": 3}), "--experiment", "EXP-000", "--dataset", "DS-00"],
        cwd=HERE, env=UTF8, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode == 0, done.stderr
    run = json.loads(next(res.glob("*/run.json")).read_text(encoding="utf-8"))
    s = run["summary"]
    # перемешанные данные: ложных находок поиска — единицы при допуске 10 %, не десятки
    assert len(s["placebo_found"]) == 5 and max(s["placebo_found"]) <= 1
    assert s["same"] == 1  # «[копия x]» почти совпадает с «[x]»: его связи не ищутся — и это видно
    assert s["excluded_columns"] == ["[копия x]"] and s["same_pairs"][0]["a"] == "[x]"
    confirmed = run["report"]["charts"][0]["categories"]
    assert "[x] — [y]" in confirmed and "[x] — [u]" in confirmed
    assert not any("копия" in c for c in confirmed)
    # связи — списком для страницы расчёта: подтверждённые и отдельно не подтвердившиеся
    assert {(x["a"], x["b"]) for x in s["links"]} >= {("[x]", "[y]"), ("[x]", "[u]")}
    assert all(x["rho_confirm"] is not None for x in s["links"])
    assert all((x["a"], x["b"]) not in {(y["a"], y["b"]) for y in s["links"]} for x in s["not_confirmed"])
    # всё для повтора расчёта (правило 3)
    assert run["dataset"]["sha256"] and run["seeds"]["split"] == 3 and run["env_lock_sha256"]
    assert s["params"] == {"columns": [], "group": "", "method": "rank", "holdout": 50, "fdr": 10, "placebo": 5, "seed": 3,
                           "sheet": ""}
    assert s["columns_used"][:2] == ["[x]", "[y]"] and s["columns_skipped"] == []


def test_ties_are_checked_by_rho_only() -> None:
    # повторы значений (рейтинг из 5 ступеней): асимптотика ξ завысила бы значимость
    rng = np.random.default_rng(2)
    t = pair_test(rng.integers(0, 5, 300).astype(float), rng.normal(size=300))
    assert t is not None and not t["xi_used"] and t["p_xi"] == 1.0 and t["p"] == t["p_rho"]


def test_by_group_gives_one_row_per_group() -> None:
    from correlation_scan import by_group

    data = pd.DataFrame({"[v]": [1.0, 3.0, 10.0, 20.0, 5.0]})
    groups = pd.Series(["[б]", "[б]", "[а]", "[а]", None])
    out = by_group(data, groups)
    assert out["[v]"].tolist() == [15.0, 2.0]  # [а], [б]; строка без группы не берётся


def _run(tmp_path: Path, data: Path, params: dict, tag: str) -> dict:
    res = tmp_path / tag
    done = subprocess.run(
        [sys.executable, "correlation_scan.py", str(tmp_path), str(res), "--data", str(data),
         "--params", json.dumps(params), "--experiment", "EXP-000", "--dataset", "DS-00"],
        cwd=HERE, env=UTF8, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(next(res.glob("*/run.json")).read_text(encoding="utf-8"))


def test_panel_noise_is_not_confirmed_with_group(tmp_path: Path) -> None:
    # панель «страна × год» из чистого шума: у каждой страны свой уровень, между столбцами связей нет.
    # Строки одной страны почти повторяют друг друга — без усреднения по стране связи
    # «подтверждались» бы десятками, а перемешанные данные показывали бы 0 ложных находок
    rng = np.random.default_rng(11)
    n_c, n_y = 80, 12
    country = np.repeat([f"[страна {i}]" for i in range(n_c)], n_y)
    cols = {f"[шум {j}]": np.repeat(rng.normal(size=n_c), n_y) + 0.3 * rng.normal(size=n_c * n_y)
            for j in range(8)}
    path = tmp_path / "panel.csv"
    pd.DataFrame({"[страна]": country, "[год]": np.tile(np.arange(2010, 2010 + n_y), n_c), **cols}).to_csv(
        path, index=False)

    run = _run(tmp_path, path, {"group": "[страна]", "seed": 1}, "grouped")
    s = run["summary"]
    assert s["unit"] == "group" and s["rows_find"] + s["rows_confirm"] == n_c
    assert s["confirmed"] == 0 and "[год]" not in s["columns_used"]
    assert run["dataset"]["row_count"] == n_c * n_y  # в run.json — строки среза, не группы
    assert any(k["label"] == "Наблюдение — группа" for k in run["report"]["kpis"])

    plain = _run(tmp_path, path, {"seed": 1}, "plain")
    assert plain["summary"]["panel_hint"] == "[страна]"
    assert any(k["label"] == "Похоже на панель" for k in plain["report"]["kpis"])


def test_no_panel_hint_without_year(synthetic: Path, tmp_path: Path) -> None:
    run = _run(tmp_path, synthetic, {"seed": 3}, "flat")
    assert run["summary"]["panel_hint"] == "" and run["summary"]["unit"] == "row"


def test_noise_only_gives_no_links_and_says_so(tmp_path: Path) -> None:
    # только шум: подтверждённых связей нет — и это записано как результат, а не пустота
    rng = np.random.default_rng(5)
    path = tmp_path / "shum.csv"
    pd.DataFrame({f"[шум {i}]": rng.normal(size=200) for i in range(6)}).to_csv(path, index=False)
    res = tmp_path / "res"
    done = subprocess.run(
        [sys.executable, "correlation_scan.py", str(tmp_path), str(res), "--data", str(path),
         "--params", "{}", "--experiment", "EXP-000", "--dataset", "DS-00"],
        cwd=HERE, env=UTF8, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode == 0, done.stderr
    run = json.loads(next(res.glob("*/run.json")).read_text(encoding="utf-8"))
    assert run["summary"]["links"] == [] and run["summary"]["links_total"] == 0
    assert not any(c["id"] == "confirmed" for c in run["report"]["charts"])
    assert {k["label"] for k in run["report"]["kpis"]} >= {"Подтверждено на отложенной части"}


def test_scan_refuses_too_few_rows(tmp_path: Path) -> None:
    path = tmp_path / "malo.csv"
    pd.DataFrame({"[a]": range(10), "[b]": range(10)}).to_csv(path, index=False)
    done = subprocess.run(
        [sys.executable, "correlation_scan.py", str(tmp_path), str(tmp_path / "res"), "--data", str(path),
         "--params", "{}", "--experiment", "EXP-000", "--dataset", "DS-00"],
        cwd=HERE, env=UTF8, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode != 0 and "нужно хотя бы 40" in done.stderr


def test_id_column_is_not_an_indicator(tmp_path: Path) -> None:
    # номер компании идёт по порядку и случайно растёт вместе с показателем — связью это не считается
    rng = np.random.default_rng(7)
    n = 200
    x = np.sort(rng.normal(size=n))
    path = tmp_path / "ids.csv"
    pd.DataFrame({"code": np.arange(n), "[x]": x, "[y]": x + rng.normal(size=n)}).to_csv(path, index=False)
    run = _run(tmp_path, path, {"seed": 1}, "ids")
    assert "code" not in run["summary"]["columns_used"]
    assert all("code" not in (x["a"], x["b"]) for x in run["summary"]["links"])


def test_linear_method_misses_u_shape_that_rank_finds(synthetic: Path, tmp_path: Path) -> None:
    # способ «линейная связь»: прямую связь находит, U-образную — нет; так и сказано в итогах
    lin = _run(tmp_path, synthetic, {"seed": 3, "method": "linear"}, "lin")
    pairs = {(x["a"], x["b"]) for x in lin["summary"]["links"]}
    assert ("[x]", "[y]") in pairs and ("[x]", "[u]") not in pairs
    assert lin["summary"]["method"] == "linear" and lin["summary"]["params"]["method"] == "linear"
    assert all(x["kind"] == "линейная" for x in lin["summary"]["links"])
    assert lin["report"]["kpis"][0] == {"label": "Способ поиска", "value": "r Пирсона",
                                        "note": "только прямолинейные связи"}
    assert "r Пирсона" in lin["report"]["charts"][0]["title"]


def test_partial_method_drops_link_explained_by_third_column(tmp_path: Path) -> None:
    # [доход] и [выбросы] связаны только через [размер]: обычный поиск связь находит,
    # частный — нет, а связи с самим [размером] остаются
    rng = np.random.default_rng(4)
    n = 400
    size = rng.normal(size=n)
    path = tmp_path / "conf.csv"
    pd.DataFrame({"[размер]": size, "[доход]": size + 0.6 * rng.normal(size=n),
                  "[выбросы]": size + 0.6 * rng.normal(size=n),
                  **{f"[шум {i}]": rng.normal(size=n) for i in range(3)}}).to_csv(path, index=False)
    plain = {(x["a"], x["b"]) for x in _run(tmp_path, path, {"seed": 2}, "plain")["summary"]["links"]}
    assert ("[доход]", "[выбросы]") in plain
    part = _run(tmp_path, path, {"seed": 2, "method": "partial"}, "part")["summary"]
    links = {(x["a"], x["b"]) for x in part["links"]}
    assert ("[доход]", "[выбросы]") not in links
    assert {("[размер]", "[доход]"), ("[размер]", "[выбросы]")} <= links
    assert part["without_xi"] == 0 and all(x["kind"] == "частная" for x in part["links"])


def test_partial_needs_rows_without_gaps(tmp_path: Path) -> None:
    rng = np.random.default_rng(6)
    path = tmp_path / "wide.csv"
    pd.DataFrame({f"[x{i}]": rng.normal(size=60) for i in range(30)}).to_csv(path, index=False)
    done = subprocess.run(
        [sys.executable, "correlation_scan.py", str(tmp_path), str(tmp_path / "res"), "--data", str(path),
         "--params", json.dumps({"method": "partial"}), "--experiment", "EXP-000", "--dataset", "DS-00"],
        cwd=HERE, env=UTF8, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode != 0 and "Для частных связей" in done.stderr


def test_unknown_method_is_refused(synthetic: Path, tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, "correlation_scan.py", str(tmp_path), str(tmp_path / "res"), "--data", str(synthetic),
         "--params", json.dumps({"method": "[нет такого]"}), "--experiment", "EXP-000", "--dataset", "DS-00"],
        cwd=HERE, env=UTF8, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode != 0 and "Нет способа поиска" in done.stderr
