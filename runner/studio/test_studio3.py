"""Студия, этап 3: Data Mining. Данные — синтетические, с известным ответом (seed), не реальные."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import engine  # noqa: E402
from studio.components import COMPONENTS, NodeError  # noqa: E402


def run(type_: str, params: dict, df: pd.DataFrame, new: pd.DataFrame | None = None) -> pd.DataFrame:  # type: ignore[type-arg]
    return COMPONENTS[type_].run({"in": df, **({"new": new} if new is not None else {})}, params)


@pytest.fixture
def reg() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 300
    a, b = rng.normal(size=n), rng.normal(size=n)
    sector = rng.choice(["S1", "S2"], n)
    y = 3 + 2 * a - b + np.where(sector == "S2", 1.5, 0) + rng.normal(0, 0.3, n)
    sets = np.where(rng.random(n) < 0.25, "тестовое", "обучающее")
    return pd.DataFrame({"a": a, "b": b, "сектор": sector, "y": y, "множество": sets})


def test_linear_regression(reg: pd.DataFrame) -> None:
    out = run("mining.linreg", {"target": "y", "features": ["a", "b", "сектор"], "set_column": "множество", "cv": 5},
              reg)
    rep = out.attrs["report"]
    coef = {r[0]: r[1] for r in rep["tables"][0]["rows"]}
    assert coef["(свободный член)"] == pytest.approx(3, abs=0.1) and coef["a"] == pytest.approx(2, abs=0.1)
    assert coef["b"] == pytest.approx(-1, abs=0.1) and coef["сектор=S2"] == pytest.approx(1.5, abs=0.15)
    m = {r["name"]: r for r in rep["metrics"]}
    assert m["R²"]["train"] > 0.95 and m["R²"]["test"] > 0.95 and m["R²"]["cv"] > 0.95
    assert np.abs(out["y_остаток"]).mean() < 0.4
    new = reg.head(3).drop(columns=["y"])
    pred = run("mining.linreg", {"target": "y", "features": ["a", "b", "сектор"]}, reg, new)
    assert list(pred.columns) == [*new.columns, "y_прогноз"] and pred["y_прогноз"].notna().all()


def test_logistic_and_networks(reg: pd.DataFrame) -> None:
    rng = np.random.default_rng(1)
    prob = 1 / (1 + np.exp(-(2 * reg["a"] - reg["b"])))
    df = reg.assign(дефолт=np.where(rng.random(len(reg)) < prob, "да", "нет"))
    out = run("mining.logreg", {"target": "дефолт", "event": "да", "features": ["a", "b"], "set_column": "множество"}, df)
    rep = out.attrs["report"]
    m = {r["name"]: r for r in rep["metrics"]}
    assert m["AUC"]["test"] > 0.7 and len(rep["roc"]) > 5  # шум Бернулли: потолок AUC около 0,8
    coef = {r[0]: r for r in rep["tables"][0]["rows"]}
    assert coef["a"][1] > 0 > coef["b"][1] and coef["a"][4] < 0.001  # знак и значимость
    assert out["дефолт_вероятность"].between(0, 1).all() and set(out["дефолт_прогноз"]) <= {"да", "не да"}
    nn = run("mining.mlp_cls", {"target": "дефолт", "event": "да", "features": ["a", "b"], "hidden": "8",
                                "set_column": "множество"}, df)
    assert {r["name"]: r for r in nn.attrs["report"]["metrics"]}["AUC"]["test"] > 0.7
    nr = run("mining.mlp_reg", {"target": "y", "features": ["a", "b"], "hidden": "16, 8", "set_column": "множество"},
             reg)
    assert {r["name"]: r for r in nr.attrs["report"]["metrics"]}["R²"]["test"] > 0.8
    with pytest.raises(NodeError, match="два значения"):
        run("mining.logreg", {"target": "y"}, reg)
    with pytest.raises(NodeError, match="скрытых слоёв"):
        run("mining.mlp_reg", {"target": "y", "hidden": "0"}, reg)


def test_clustering() -> None:
    rng = np.random.default_rng(2)
    centers = np.array([[0, 0], [6, 6], [0, 6]])
    pts = np.vstack([c + rng.normal(0, 0.6, (60, 2)) for c in centers])
    df = pd.DataFrame(pts, columns=["x", "y"]).assign(группа=np.repeat(["A", "B", "C"], 60))
    km = run("mining.kmeans", {"features": ["x", "y"]}, df)
    assert km.attrs["report"]["summary"][0] == ["кластеров", 3]
    assert pd.crosstab(km["группа"], km["кластер"]).max(axis=1).tolist() == [60, 60, 60]  # группы не смешаны
    assert len(km.attrs["report"]["tables"][0]["rows"]) == 4  # 3 профиля + «все»
    em = run("mining.em", {"features": ["x", "y"]}, df)
    assert em.attrs["report"]["summary"][0] == ["кластеров", 3] and em["кластер_вероятность"].min() > 0.5
    som = run("mining.som", {"features": ["x", "y"], "width": 4, "height": 3, "epochs": 20}, df)
    grid = som.attrs["report"]["tables"][0]["rows"]
    assert sum(sum(r[1:]) for r in grid) == 180 and som["ячейка"].between(1, 12).all()
    new = run("mining.kmeans", {"features": ["x", "y"], "k": 3}, df, pd.DataFrame({"x": [0.1, 6.2], "y": [0.2, 5.9]}))
    assert new["кластер"].nunique() == 2


def test_association_rules_and_transactions() -> None:
    rows = []
    for t in range(100):
        items = ["хлеб", "масло"] if t % 2 == 0 else ["пиво", "чипсы"]
        if t % 5 == 0:
            items.append("молоко")
        rows += [{"чек": t, "товар": i} for i in items]
    df = pd.DataFrame(rows)
    rules = run("mining.assoc", {"transaction": "чек", "item": "товар", "min_support": 0.1}, df)
    r = rules[(rules["если"] == "хлеб") & (rules["то"] == "масло")].iloc[0]
    assert r["достоверность"] == 1 and r["лифт"] == pytest.approx(2) and r["поддержка"] == 0.5
    tx = run("mining.tx_cluster", {"transaction": "чек", "item": "товар", "k": 2}, df)
    assert len(tx) == 100 and tx.groupby(tx["чек"].astype(int) % 2)["кластер"].nunique().max() == 1


def test_arimax() -> None:
    rng = np.random.default_rng(3)
    n = 300
    x = rng.normal(size=n + 5)
    y = np.zeros(n)
    for t in range(1, n):
        y[t] = 0.7 * y[t - 1] + 1.5 * x[t] + rng.normal(0, 0.2)
    df = pd.DataFrame({"t": range(n + 5), "y": [*y, *[None] * 5], "x": x})
    out = run("mining.arimax", {"column": "y", "order_by": "t", "exog": ["x"], "p": 1, "horizon": 5}, df)
    coef = {r[0]: r[1] for r in out.attrs["report"]["tables"][0]["rows"]}
    assert coef["AR1"] == pytest.approx(0.7, abs=0.05) and coef["x"] == pytest.approx(1.5, abs=0.05)
    assert out["y_прогноз"].notna().sum() == 5 and len(out) == n + 5
    assert out["y_прогноз"].iloc[n] == pytest.approx(0.7 * y[-1] + 1.5 * x[n], abs=0.1)
    d1 = run("mining.arimax", {"column": "y", "order_by": "t", "p": 1, "d": 1, "q": 1, "horizon": 3},
             df.drop(columns=["x"]))
    assert d1["y_прогноз"].notna().sum() == 3
    with pytest.raises(NodeError, match="значения факторов"):
        run("mining.arimax", {"column": "y", "order_by": "t", "exog": ["x"], "horizon": 10}, df)


def test_report_stays_on_its_node(reg: pd.DataFrame) -> None:
    sc = {"format": 1, "nodes": [
        {"id": "src", "type": "import.dataset", "params": {"snapshot_id": 1}},
        {"id": "lr", "type": "mining.linreg", "params": {"target": "y", "features": ["a", "b"]}},
        {"id": "s", "type": "transform.sort", "params": {"by": [{"column": "y_прогноз"}]}}],
        "edges": [{"from": "src", "to": "lr"}, {"from": "lr", "to": "s"}]}
    res = engine.run(sc, lambda _n: reg)
    assert res["lr"].report is not None and res["lr"].report["kind"] == "regression"
    assert res["s"].report is None and res["s"].frame is not None and not res["s"].frame.attrs
