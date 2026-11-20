"""Студия, этап 2: исследование (как группа «Исследование» Loginom).

Результат узла — таблица, как у всех: корреляции — парами или матрицей, факторный анализ —
нагрузки или исходные строки с факторами, автокорреляция — лаг и коэффициенты, дубликаты —
исходные строки со статусом.
"""

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as st

from studio.components import Component, NodeError, Param

Frame = pd.DataFrame
Params = dict[str, Any]
GROUP = "Исследование"


def _need(df: Frame, cols: list[str], where: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise NodeError(f"{where}: нет столбцов {', '.join(missing)}")


def _numeric(df: Frame, cols: list[str], where: str) -> Frame:
    """Числовые столбцы: выбранные или все числовые."""
    if not cols:
        cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
                and not pd.api.types.is_bool_dtype(df[c])]
    _need(df, cols, where)
    out = df[cols].apply(pd.to_numeric, errors="coerce")
    if out.shape[1] < 2:
        raise NodeError(f"{where}: нужно хотя бы два числовых столбца")
    return out


# --- корреляционный анализ ------------------------------------------------------------------------

CORR = (("pearson", "Пирсон (линейная)"), ("spearman", "Спирмен (ранговая)"), ("kendall", "Кендалл (ранговая)"))


def correlation(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    x = _numeric(df, p.get("columns") or [], "Корреляционный анализ")
    how = p.get("method", "pearson")
    fn = {"pearson": st.pearsonr, "spearman": st.spearmanr, "kendall": st.kendalltau}.get(how)
    if fn is None:
        raise NodeError(f"Корреляционный анализ: нет способа «{how}»")
    target = p.get("target")
    if target:
        _need(df, [target], "Корреляционный анализ")
        x[target] = pd.to_numeric(df[target], errors="coerce")
    cols = list(x.columns)
    if p.get("output") == "matrix":
        m = x.corr(method=how)
        m.insert(0, "показатель", m.index.astype(str))
        return m.reset_index(drop=True)
    rows = []
    pairs = [(a, target) for a in cols if a != target] if target else \
        [(a, b) for i, a in enumerate(cols) for b in cols[i + 1:]]
    for a, b in pairs:
        both = x[[a, b]].dropna()
        if len(both) < 3 or both[a].nunique() < 2 or both[b].nunique() < 2:
            r, pv = np.nan, np.nan
        else:
            res = fn(both[a], both[b])
            r, pv = float(res[0]), float(res[1])
        rows.append({"показатель_1": a, "показатель_2": b, "r": r, "p_value": pv, "n": len(both)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["сила"] = pd.cut(out["r"].abs(), [-0.01, 0.1, 0.3, 0.5, 0.7, 1.01],
                         labels=["нет", "слабая", "умеренная", "заметная", "сильная"]).astype("string")
    alpha = float(p.get("alpha") or 0.05)
    out["значима"] = out["p_value"] < alpha
    return out.sort_values("r", key=lambda s: -s.abs(), na_position="last").reset_index(drop=True)


# --- факторный анализ -----------------------------------------------------------------------------

def _varimax(loadings: np.ndarray, iters: int = 100, tol: float = 1e-6) -> np.ndarray:
    p, k = loadings.shape
    rot = np.eye(k)
    d = 0.0
    for _ in range(iters):
        lam = loadings @ rot
        u, s, vt = np.linalg.svd(loadings.T @ (lam ** 3 - lam @ np.diag((lam ** 2).sum(axis=0)) / p))
        rot = u @ vt
        d_new = s.sum()
        if d and d_new / d < 1 + tol:
            break
        d = d_new
    return loadings @ rot


def factor(inp: dict[str, Frame], p: Params) -> Frame:
    """Факторы — главные компоненты стандартизованных показателей (число — по Кайзеру, если не
    задано), при желании с вращением варимакс. Строки с пропусками в показателях не участвуют."""
    df = inp["in"]
    x = _numeric(df, p.get("columns") or [], "Факторный анализ")
    full = x.dropna()
    if len(full) < x.shape[1] + 2:
        raise NodeError(f"Факторный анализ: полных строк {len(full)} — мало для {x.shape[1]} показателей")
    sd = full.std(ddof=0).replace(0, np.nan)
    if sd.isna().any():
        raise NodeError("Факторный анализ: у показателей " + ", ".join(sd[sd.isna()].index.astype(str))
                        + " одно значение — уберите их")
    z = (full - full.mean()) / sd
    corr = np.corrcoef(z.to_numpy(), rowvar=False)
    vals, vecs = np.linalg.eigh(corr)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    k = int(p.get("factors") or 0) or max(1, int((vals > 1).sum()))
    k = min(k, x.shape[1])
    loadings = vecs[:, :k] * np.sqrt(np.clip(vals[:k], 0, None))
    if p.get("rotation", "varimax") == "varimax" and k > 1:
        loadings = _varimax(loadings)
    names = [f"фактор_{i + 1}" for i in range(k)]
    if p.get("output") == "scores":
        # оценки факторов (регрессионный метод): z · R⁻¹ · нагрузки
        scores = z.to_numpy() @ np.linalg.pinv(corr) @ loadings
        out = df.copy()
        for i, n in enumerate(names):
            out[n] = pd.Series(scores[:, i], index=full.index)
        return out
    out = pd.DataFrame(loadings, columns=names)
    out.insert(0, "показатель", list(x.columns.astype(str)))
    out["общность"] = (loadings ** 2).sum(axis=1)
    share = vals[:k] / vals.sum()
    explained = pd.DataFrame([["доля дисперсии", *share, share.sum()]], columns=out.columns)
    return pd.concat([out, explained], ignore_index=True)


# --- автокорреляция -------------------------------------------------------------------------------

def _acf(x: np.ndarray, lags: int) -> np.ndarray:
    x = x - x.mean()
    denom = (x * x).sum()
    return np.array([1.0] + [float((x[k:] * x[:-k]).sum() / denom) for k in range(1, lags + 1)])


def _pacf(r: np.ndarray, lags: int) -> np.ndarray:
    """Частная автокорреляция по Дурбину — Левинсону."""
    out = [1.0]
    phi_prev: list[float] = []
    for k in range(1, lags + 1):
        if k == 1:
            phi = [r[1]]
        else:
            num = r[k] - sum(phi_prev[j] * r[k - 1 - j] for j in range(k - 1))
            den = 1 - sum(phi_prev[j] * r[j + 1] for j in range(k - 1))
            pk = num / den if den else 0.0
            phi = [phi_prev[j] - pk * phi_prev[k - 2 - j] for j in range(k - 1)] + [pk]
        out.append(phi[-1])
        phi_prev = phi
    return np.array(out)


def autocorrelation(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    col, order = p["column"], p.get("order_by")
    _need(df, [col] + ([order] if order else []), "Автокорреляция")
    data = df.sort_values(order, kind="stable") if order else df
    x = pd.to_numeric(data[col], errors="coerce").dropna().to_numpy(dtype=float)
    lags = int(p.get("lags") or 10)
    if len(x) < lags + 3:
        raise NodeError(f"Автокорреляция: значений {len(x)} — мало для {lags} лагов")
    if np.std(x) == 0:
        raise NodeError("Автокорреляция: у ряда одно значение")
    r = _acf(x, lags)
    bound = 1.96 / np.sqrt(len(x))
    out = pd.DataFrame({"лаг": range(lags + 1), "автокорреляция": r, "частная": _pacf(r, lags)})
    out["граница_95"] = bound
    out["значима"] = (out["автокорреляция"].abs() > bound) & (out["лаг"] > 0)
    return out


# --- дубликаты и противоречия ---------------------------------------------------------------------

def duplicates(inp: dict[str, Frame], p: Params) -> Frame:
    """По входным полям: одинаковые строки — дубликаты; одинаковые входы при разных выходах —
    противоречия (например, одна компания и год, а рейтинг разный)."""
    df = inp["in"]
    keys: list[str] = p.get("inputs") or []
    outs: list[str] = p.get("outputs") or []
    _need(df, keys + outs, "Дубликаты и противоречия")
    if not keys:
        raise NodeError("Дубликаты и противоречия: выберите входные поля")
    k = df[keys].astype("string").fillna("∅").agg("\x1f".join, axis=1)
    o = df[outs].astype("string").fillna("∅").agg("\x1f".join, axis=1) if outs else pd.Series("", index=df.index)
    size = k.map(k.value_counts())
    variants = pd.DataFrame({"k": k, "o": o}).groupby("k")["o"].transform("nunique")
    status = np.where(size == 1, "уникальная", np.where(variants > 1, "противоречие", "дубликат"))
    out = df.copy()
    out["статус"] = status
    out["группа"] = pd.Series(pd.factorize(k)[0] + 1, index=df.index).where(size > 1).astype("Int64")
    mode = p.get("output", "all")
    if mode == "problems":
        out = out[out["статус"] != "уникальная"]
    elif mode == "clean":  # дубликаты — первая строка, противоречия — убраны целиком
        out = out[(out["статус"] == "уникальная") | ((out["статус"] == "дубликат") & ~k.duplicated())]
        out = out.drop(columns=["статус", "группа"])
    return out.reset_index(drop=True)


COMPONENTS = [
    Component("research.correlation", "Корреляционный анализ", GROUP,
              "Связь числовых показателей: r, p-значение, сила — парами, с целевым или матрицей",
              ("in",), (Param("columns", "Показатели (пусто — все числовые)", "columns", required=False),
                        Param("method", "Коэффициент", "select", default="pearson", options=CORR),
                        Param("target", "Только с целевым", "column", required=False),
                        Param("output", "Вид", "select", required=False, default="pairs",
                              options=(("pairs", "парами"), ("matrix", "матрицей"))),
                        Param("alpha", "Уровень значимости", "number", required=False, default=0.05)),
              correlation),
    Component("research.factor", "Факторный анализ", GROUP,
              "Главные компоненты с вращением варимакс: нагрузки и доля дисперсии, или факторы в строки",
              ("in",), (Param("columns", "Показатели (пусто — все числовые)", "columns", required=False),
                        Param("factors", "Факторов (пусто — по Кайзеру)", "number", required=False),
                        Param("rotation", "Вращение", "select", required=False, default="varimax",
                              options=(("varimax", "варимакс"), ("none", "без вращения"))),
                        Param("output", "Результат", "select", required=False, default="loadings",
                              options=(("loadings", "нагрузки показателей"), ("scores", "строки + факторы")))),
              factor),
    Component("research.autocorr", "Автокорреляция", GROUP,
              "Связь ряда с самим собой со сдвигом: автокорреляция, частная, граница значимости",
              ("in",), (Param("column", "Ряд", "column"),
                        Param("order_by", "Порядок (например, дата)", "column", required=False),
                        Param("lags", "Лагов", "number", required=False, default=10)), autocorrelation),
    Component("research.duplicates", "Дубликаты и противоречия", GROUP,
              "Повторы строк и противоречия: одинаковые входы при разных выходах",
              ("in",), (Param("inputs", "Входные поля", "columns"),
                        Param("outputs", "Выходные поля", "columns", required=False),
                        Param("output", "Результат", "select", required=False, default="all",
                              options=(("all", "все строки со статусом"), ("problems", "только проблемные"),
                                       ("clean", "очищенная таблица")))), duplicates),
]
