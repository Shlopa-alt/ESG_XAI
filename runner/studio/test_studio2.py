"""Студия, этап 2: предобработка, нормализация, исследование, «Качество данных». Данные — заглушки
(сгенерированы с seed, не реальные)."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import stats  # noqa: E402
from studio.components import COMPONENTS, NodeError, catalog  # noqa: E402


def run(type_: str, params: dict, df: pd.DataFrame) -> pd.DataFrame:  # type: ignore[type-arg]
    return COMPONENTS[type_].run({"in": df}, params)


@pytest.fixture
def panel() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    n = 60
    firm = np.repeat(["A", "B", "C", "D", "E", "F"], 10)
    year = np.tile(np.arange(2015, 2025), 6)
    x = rng.normal(10, 2, n)
    y = 2 * x + rng.normal(0, 1, n)
    x[[3, 17]] = np.nan
    x[25] = 80.0  # выброс
    return pd.DataFrame({"фирма": firm, "год": year, "x": x, "y": y,
                         "дефолт": (y > np.median(y)).astype(int), "сектор": np.tile(["S1", "S2", "S3"], 20)})


def test_fill_missing(panel: pd.DataFrame) -> None:
    m = run("preprocess.fill", {"rules": [{"column": "x", "method": "median"}]}, panel)
    assert m["x"].isna().sum() == 0 and m.loc[3, "x"] == pytest.approx(panel["x"].median())
    prev = run("preprocess.fill", {"rules": [{"column": "x", "method": "previous"}],
                                   "group_by": ["фирма"], "order_by": "год"}, panel)
    assert prev.loc[3, "x"] == panel.loc[2, "x"]
    const = run("preprocess.fill", {"rules": [{"column": "x", "method": "value", "value": "0"}]}, panel)
    assert const.loc[17, "x"] == 0
    drop = run("preprocess.fill", {"rules": [{"column": "x", "method": "drop"}]}, panel)
    assert len(drop) == 58
    with pytest.raises(NodeError, match="числовой"):
        run("preprocess.fill", {"rules": [{"column": "x", "method": "value", "value": "нет"}]}, panel)


def test_binning_and_classes(panel: pd.DataFrame) -> None:
    q = run("preprocess.binning", {"column": "y", "method": "quantile", "bins": 4, "labels": "number"}, panel)
    assert sorted(q["y_интервал"].dropna().unique().tolist()) == [1, 2, 3, 4]
    assert q["y_интервал"].value_counts().tolist() == [15, 15, 15, 15]
    e = run("preprocess.binning", {"column": "y", "method": "edges", "edges": "15; 25"}, panel)
    assert e["y_интервал"].nunique() == 3
    c = run("preprocess.classes", {"column": "y", "target": "дефолт", "max_classes": 3}, panel)
    assert 1 < c["y_класс"].nunique() <= 3
    # дефолт определяется y — WoE монотонен: у класса с бóльшим y меньше WoE (больше «событий»)
    woe = c.groupby("y_класс")["y_woe"].first()
    assert woe.iloc[0] > 0 > woe.iloc[-1] and woe.is_monotonic_decreasing
    with pytest.raises(NodeError, match="два значения"):
        run("preprocess.classes", {"column": "y", "target": "сектор"}, panel)


def test_split_is_repeatable_and_keeps_groups(panel: pd.DataFrame) -> None:
    a = run("preprocess.split", {"test_share": 0.3, "seed": 7}, panel)
    b = run("preprocess.split", {"test_share": 0.3, "seed": 7}, panel)
    assert a["множество"].tolist() == b["множество"].tolist()
    assert (a["множество"] == "тестовое").sum() == 18
    g = run("preprocess.split", {"test_share": 0.34, "group": "фирма", "seed": 7}, panel)
    assert g.groupby("фирма")["множество"].nunique().max() == 1  # фирма целиком в одном множестве
    s = run("preprocess.split", {"test_share": 0.5, "stratify": "сектор"}, panel)
    assert s[s["множество"] == "тестовое"]["сектор"].value_counts().tolist() == [10, 10, 10]


def test_outliers_smooth_sample(panel: pd.DataFrame) -> None:
    clip = run("preprocess.outliers", {"columns": ["x"], "method": "iqr", "action": "clip"}, panel)
    assert clip["x"].max() < 80
    flag = run("preprocess.outliers", {"columns": ["x"], "action": "flag"}, panel)
    assert bool(flag.loc[25, "выброс"])
    assert len(run("preprocess.outliers", {"columns": ["x"], "action": "drop"}, panel)) < 60
    sm = run("preprocess.smooth", {"columns": ["y"], "window": 3, "group_by": ["фирма"], "order_by": "год"}, panel)
    a = sm[sm["фирма"] == "A"]
    assert a["y_сгл"].iloc[2] == pytest.approx(a["y"].iloc[:3].mean())
    s1 = run("preprocess.sample", {"method": "share", "size": 0.5, "seed": 3}, panel)
    s2 = run("preprocess.sample", {"method": "share", "size": 0.5, "seed": 3}, panel)
    assert len(s1) == 30 and s1.equals(s2)
    st = run("preprocess.sample", {"method": "share", "size": 0.5, "stratify": "сектор"}, panel)
    assert st["сектор"].value_counts().tolist() == [10, 10, 10] and "сектор" in st.columns
    boot = run("preprocess.sample", {"method": "count", "size": 100, "replace": True}, panel)
    assert len(boot) == 100


def test_normalize(panel: pd.DataFrame) -> None:
    n = run("preprocess.normalize", {"rules": [{"column": "y", "method": "zscore"},
                                               {"column": "y", "method": "minmax"},
                                               {"column": "сектор", "method": "onehot"}]}, panel)
    assert n["y_zscore"].mean() == pytest.approx(0, abs=1e-9) and n["y_minmax"].max() == 1
    assert {"сектор=S1", "сектор=S2", "сектор=S3"} <= set(n.columns)
    with pytest.raises(NodeError, match="неотрицательных"):
        run("preprocess.normalize", {"rules": [{"column": "y", "method": "log"}]}, panel.assign(y=-1.0))


def test_correlation(panel: pd.DataFrame) -> None:
    # Спирмен: выброс x=80 ранговую связь не ломает (Пирсона — ломает)
    pairs = run("research.correlation", {"columns": ["x", "y", "год"], "method": "spearman"}, panel)
    top = pairs.iloc[0]
    assert {top["показатель_1"], top["показатель_2"]} == {"x", "y"} and top["значима"] and top["n"] == 58
    m = run("research.correlation", {"columns": ["x", "y"], "method": "spearman", "output": "matrix"}, panel)
    assert m.shape == (2, 3) and m.loc[0, "x"] == 1
    t = run("research.correlation", {"columns": ["x", "год"], "target": "y"}, panel)
    assert set(t["показатель_2"]) == {"y"} and len(t) == 2


def test_factor_analysis() -> None:
    rng = np.random.default_rng(0)
    f1, f2 = rng.normal(size=200), rng.normal(size=200)
    df = pd.DataFrame({"a1": f1 + rng.normal(0, .3, 200), "a2": f1 + rng.normal(0, .3, 200),
                       "b1": f2 + rng.normal(0, .3, 200), "b2": f2 + rng.normal(0, .3, 200)})
    load = run("research.factor", {}, df)
    assert list(load.columns) == ["показатель", "фактор_1", "фактор_2", "общность"]
    body = load.iloc[:4].set_index("показатель")
    main = body[["фактор_1", "фактор_2"]].abs().idxmax(axis=1)
    assert main["a1"] == main["a2"] != main["b1"] == main["b2"]  # варимакс разводит группы
    assert load.iloc[4]["общность"] > 0.8
    scores = run("research.factor", {"output": "scores", "factors": 2}, df)
    assert scores.shape == (200, 6)


def test_autocorrelation_and_duplicates() -> None:
    t = np.arange(120)
    df = pd.DataFrame({"t": t, "v": np.sin(2 * np.pi * t / 12)})
    ac = run("research.autocorr", {"column": "v", "order_by": "t", "lags": 12}, df)
    assert ac.loc[12, "автокорреляция"] > 0.8 and ac.loc[6, "автокорреляция"] < -0.8
    assert ac.loc[1, "частная"] == pytest.approx(ac.loc[1, "автокорреляция"])
    d = pd.DataFrame({"фирма": ["A", "A", "B", "B", "C"], "год": [1, 1, 1, 1, 1], "рейтинг": ["AA", "AA", "A", "B", "C"]})
    st = run("research.duplicates", {"inputs": ["фирма", "год"], "outputs": ["рейтинг"]}, d)
    assert st["статус"].tolist() == ["дубликат", "дубликат", "противоречие", "противоречие", "уникальная"]
    clean = run("research.duplicates", {"inputs": ["фирма", "год"], "outputs": ["рейтинг"], "output": "clean"}, d)
    assert clean["фирма"].tolist() == ["A", "C"]


def test_quality_view(panel: pd.DataFrame) -> None:
    df = panel.assign(текст=["1 200,5"] * 60, пусто=[None] * 60, константа=1)
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    q = stats.quality(df)
    by = {c["name"]: c for c in q["columns"]}
    assert q["duplicate_rows"] == 1 and by["x"]["missing"] == 2 and by["x"]["outliers"] >= 1
    assert any("текстом" in p for p in by["текст"]["problems"])
    assert by["пусто"]["problems"] == ["пустой столбец"]
    assert "одно значение на весь столбец" in by["константа"]["problems"]
    s = stats.sample(pd.concat([panel] * 20, ignore_index=True))
    assert len(s["rows"]) == 500 and s["total"] == 1200
    json.dumps(q)


def test_catalog_has_stage_two() -> None:
    groups = {c["group"] for c in catalog()}
    assert {"Предобработка", "Исследование"} <= groups
    assert len([c for c in catalog() if c["group"] == "Предобработка"]) == 8
