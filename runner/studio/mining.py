"""Студия, этап 3: Data Mining (как группа «Data Mining» Loginom) и валидация моделей.

Модель учится на входе «in». Есть столбец множеств (узел «Разбиение на множества») — учится на
обучающем, метрики — отдельно на обучающем и тестовом; можно и кросс-валидацию по k частям.
Подключён вход «Новые данные» — модель применяется к ним, иначе — к строкам входа.
Итог модели (коэффициенты, метрики, профили, ROC) — отчёт узла: df.attrs["report"] (движок
переносит его в визуализатор «Отчёт», дальше по цепочке он не идёт).

Всё случайное — с seed из настроек: расчёт повторяется (правило 3).
"""

from collections.abc import Callable
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy import optimize
from scipy import stats as st
from sklearn import metrics as skm
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.mixture import GaussianMixture
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.neural_network import MLPClassifier, MLPRegressor

from studio.base import Component, NodeError, Param

Frame = pd.DataFrame
Params = dict[str, Any]
GROUP = "Data Mining"
SEED = 42
TRAIN, TEST = "обучающее", "тестовое"


def _need(df: Frame, cols: list[str], where: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise NodeError(f"{where}: нет столбцов {', '.join(missing)}")


def _r(v: Any, d: int = 4) -> Any:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return None
    return round(float(v), d) if isinstance(v, (float, np.floating)) else v


def _report(df: Frame, report: dict[str, Any]) -> Frame:
    df.attrs["report"] = report
    return df


# --- матрица признаков ----------------------------------------------------------------------------

class Design:
    """Признаки → числа: числовые как есть, текстовые — столбцы 0/1 (первое значение — база).
    Запоминает столбцы, чтобы так же разобрать «Новые данные»."""

    def __init__(self, df: Frame, features: list[str], scale: bool = False) -> None:
        self.features = features
        self.categorical = [c for c in features if not pd.api.types.is_numeric_dtype(df[c])
                            or pd.api.types.is_bool_dtype(df[c])]
        self.levels = {c: sorted(df[c].dropna().astype("string").unique().tolist()) for c in self.categorical}
        too_many = [c for c, v in self.levels.items() if len(v) > 50]
        if too_many:
            raise NodeError(f"Признаки {', '.join(too_many)}: больше 50 разных значений — это не категория "
                            "(уберите или приведите к числу в «Параметрах полей»)")
        self.names: list[str] = []
        for c in features:
            if c in self.categorical:
                self.names += [f"{c}={v}" for v in self.levels[c][1:]]
            else:
                self.names.append(c)
        self.scale = scale
        x = self._raw(df)
        self.mean = np.nanmean(x, axis=0) if scale else np.zeros(x.shape[1])
        sd = np.nanstd(x, axis=0) if scale else np.ones(x.shape[1])
        self.sd = np.where(sd > 0, sd, 1.0)

    def _raw(self, df: Frame) -> np.ndarray:
        cols = []
        for c in self.features:
            if c in self.categorical:
                s = df[c].astype("string")
                for v in self.levels[c][1:]:
                    cols.append((s == v).astype(float).where(s.notna()).to_numpy(dtype=float))
            else:
                cols.append(pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float))
        return np.column_stack(cols) if cols else np.empty((len(df), 0))

    def matrix(self, df: Frame) -> np.ndarray:
        return (self._raw(df) - self.mean) / self.sd


def _features(df: Frame, p: Params, exclude: list[str]) -> list[str]:
    feats: list[str] = p.get("features") or [
        c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])
        and not pd.api.types.is_bool_dtype(df[c])]
    feats = [f for f in feats if f not in exclude]
    _need(df, feats, "Признаки")
    if not feats:
        raise NodeError("Нет признаков: выберите столбцы-признаки")
    return feats


def _sets(df: Frame, p: Params) -> tuple[pd.Series, pd.Series]:
    """Маски обучающих и тестовых строк по столбцу множеств (нет столбца — всё обучающее)."""
    col = p.get("set_column")
    if not col:
        return pd.Series(True, index=df.index), pd.Series(False, index=df.index)
    _need(df, [col], "Столбец множеств")
    s = df[col].astype("string")
    train = s == (p.get("train_value") or TRAIN)
    if not train.any():
        raise NodeError(f"В столбце «{col}» нет строк «{p.get('train_value') or TRAIN}»")
    return train.fillna(False), (s == TEST).fillna(False)


# --- метрики --------------------------------------------------------------------------------------

def reg_metrics(y: np.ndarray, f: np.ndarray) -> dict[str, float]:
    if len(y) == 0:
        return {}
    ss = float(((y - y.mean()) ** 2).sum())
    return {"R²": 1 - float(((y - f) ** 2).sum()) / ss if ss else float("nan"),
            "RMSE": float(np.sqrt(((y - f) ** 2).mean())), "MAE": float(np.abs(y - f).mean()), "n": len(y)}


def cls_metrics(y: np.ndarray, prob: np.ndarray, thr: float) -> dict[str, float]:
    if len(y) == 0:
        return {}
    pred = (prob >= thr).astype(int)
    out = {"точность (accuracy)": skm.accuracy_score(y, pred),
           "precision": skm.precision_score(y, pred, zero_division=0),
           "recall": skm.recall_score(y, pred, zero_division=0), "F1": skm.f1_score(y, pred, zero_division=0),
           "n": len(y)}
    if len(np.unique(y)) == 2:
        out["AUC"] = skm.roc_auc_score(y, prob)
    return out


def _metric_rows(train: dict[str, float], test: dict[str, float], cv: dict[str, float]) -> list[dict[str, Any]]:
    names = list(train) or list(test)
    return [{"name": n, "train": _r(train.get(n)), "test": _r(test.get(n)), "cv": _r(cv.get(n))} for n in names]


def _cv(x: np.ndarray, y: np.ndarray, k: int, fit_score: Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
        dict[str, float]], stratify: bool, seed: int) -> dict[str, float]:
    if k < 2:
        return {}
    if len(y) < 2 * k:
        raise NodeError(f"Кросс-валидация: строк {len(y)} — мало для {k} частей")
    split = StratifiedKFold(k, shuffle=True, random_state=seed) if stratify else KFold(k, shuffle=True, random_state=seed)
    scores = [fit_score(x[tr], y[tr], x[te], y[te]) for tr, te in split.split(x, y)]
    return {n: float(np.mean([s[n] for s in scores if n in s])) for n in scores[0] if n != "n"}


def _target_new(inp: dict[str, Frame], df: Frame) -> Frame:
    return inp["new"] if "new" in inp else df


# --- линейная регрессия ---------------------------------------------------------------------------

def _ols(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    a = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(a, y, rcond=None)
    return beta


def linreg(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    target = p["target"]
    _need(df, [target], "Линейная регрессия")
    feats = _features(df, p, [target, p.get("set_column") or ""])
    d = Design(df, feats)
    x, y = d.matrix(df), pd.to_numeric(df[target], errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
    train, test = _sets(df, p)
    tr, te = ok & train.to_numpy(), ok & test.to_numpy()
    n, k = int(tr.sum()), x.shape[1]
    if n <= k + 1:
        raise NodeError(f"Линейная регрессия: полных строк для обучения {n} — мало для {k} признаков")
    beta = _ols(x[tr], y[tr])
    a = np.column_stack([np.ones(n), x[tr]])
    resid = y[tr] - a @ beta
    dof = n - k - 1
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.pinv(a.T @ a)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    t = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    pv = 2 * st.t.sf(np.abs(t), dof)
    fit = np.full(len(df), np.nan)
    fit[ok] = np.column_stack([np.ones(ok.sum()), x[ok]]) @ beta
    m_tr = reg_metrics(y[tr], fit[tr])
    m_te = reg_metrics(y[te], fit[te])
    r2 = m_tr["R²"]
    adj = 1 - (1 - r2) * (n - 1) / dof if dof > 0 else float("nan")
    f_stat = (r2 / k) / ((1 - r2) / dof) if k and dof and r2 < 1 else float("nan")
    cv = _cv(x[tr], y[tr], int(p.get("cv") or 0),
             lambda xa, ya, xb, yb: reg_metrics(yb, np.column_stack([np.ones(len(xb)), xb]) @ _ols(xa, ya)),
             False, int(p.get("seed") or SEED))
    new = _target_new(inp, df)
    if "new" in inp:
        _need(new, feats, "Новые данные")
        xn = d.matrix(new)
        pred = np.where(np.isfinite(xn).all(axis=1), np.column_stack([np.ones(len(xn)), xn]) @ beta, np.nan)
    else:
        pred = fit
    out = new.copy()
    out[f"{target}_прогноз"] = pred
    if "new" not in inp:
        out[f"{target}_остаток"] = y - pred
    rows = [["(свободный член)", *[_r(v) for v in (beta[0], se[0], t[0], pv[0])]]]
    rows += [[nm, *[_r(v) for v in (beta[i + 1], se[i + 1], t[i + 1], pv[i + 1])]] for i, nm in enumerate(d.names)]
    return _report(out, {
        "kind": "regression", "title": f"Линейная регрессия: {target}",
        "metrics": _metric_rows(m_tr, m_te, cv),
        "summary": [["R² скорректированный", _r(adj)], ["F", _r(f_stat)],
                    ["p-значение F", _r(st.f.sf(f_stat, k, dof)) if np.isfinite(f_stat) else None],
                    ["остаточная ст. ошибка", _r(np.sqrt(sigma2))]],
        "tables": [{"title": "Коэффициенты", "columns": ["признак", "коэффициент", "ст. ошибка", "t", "p-значение"],
                    "rows": rows}],
        "notes": [f"Обучение: {n} полных строк из {len(df)}."]})


# --- логистическая регрессия и нейросети ----------------------------------------------------------

def _binary(df: Frame, target: str, event: str | None) -> tuple[np.ndarray, str]:
    y = df[target]
    values = sorted(y.dropna().astype("string").unique().tolist())
    if len(values) != 2:
        raise NodeError(f"Целевой «{target}» должен иметь два значения, а их {len(values)}")
    ev = str(event) if event else values[-1]
    if ev not in values:
        raise NodeError(f"В «{target}» нет значения «{ev}»")
    return np.where(y.isna(), np.nan, (y.astype("string") == ev).astype(float)), ev


def _classifier(inp: dict[str, Frame], p: Params, make: Callable[[], Any], title: str,
                with_coefs: bool) -> Frame:
    df = inp["in"]
    target = p["target"]
    _need(df, [target], title)
    feats = _features(df, p, [target, p.get("set_column") or ""])
    d = Design(df, feats, scale=True)
    x = d.matrix(df)
    y, event = _binary(df, target, p.get("event"))
    ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
    train, test = _sets(df, p)
    tr, te = ok & train.to_numpy(), ok & test.to_numpy()
    if tr.sum() < 10 or len(np.unique(y[tr])) < 2:
        raise NodeError(f"{title}: для обучения нужно хотя бы 10 полных строк с обоими значениями целевого")
    thr = float(p.get("threshold") or 0.5)
    model = make().fit(x[tr], y[tr].astype(int))
    prob = np.full(len(df), np.nan)
    prob[ok] = model.predict_proba(x[ok])[:, 1]
    m_tr, m_te = cls_metrics(y[tr].astype(int), prob[tr], thr), cls_metrics(y[te].astype(int), prob[te], thr)

    def fit_score(xa: np.ndarray, ya: np.ndarray, xb: np.ndarray, yb: np.ndarray) -> dict[str, float]:
        return cls_metrics(yb.astype(int), make().fit(xa, ya.astype(int)).predict_proba(xb)[:, 1], thr)

    cv = _cv(x[tr], y[tr], int(p.get("cv") or 0), fit_score, True, int(p.get("seed") or SEED))
    rep_y, rep_p = (y[te], prob[te]) if te.any() else (y[tr], prob[tr])
    fpr, tpr, _ = skm.roc_curve(rep_y.astype(int), rep_p)
    step = max(1, len(fpr) // 100)
    cm = skm.confusion_matrix(rep_y.astype(int), (rep_p >= thr).astype(int), labels=[0, 1])
    new = _target_new(inp, df)
    if "new" in inp:
        _need(new, feats, "Новые данные")
        xn = d.matrix(new)
        okn = np.isfinite(xn).all(axis=1)
        pn = np.full(len(new), np.nan)
        if okn.any():
            pn[okn] = model.predict_proba(xn[okn])[:, 1]
    else:
        pn = prob
    out = new.copy()
    out[f"{target}_вероятность"] = pn
    out[f"{target}_прогноз"] = pd.Series(np.where(np.isnan(pn), np.nan, (pn >= thr).astype(float)),
                                         index=out.index).map({1.0: event, 0.0: f"не {event}"})
    on = "тестовом" if te.any() else "обучающем"
    tables = [{"title": f"Матрица ошибок (на {on})", "columns": ["", f"прогноз: не {event}", f"прогноз: {event}"],
               "rows": [[f"факт: не {event}", int(cm[0, 0]), int(cm[0, 1])],
                        [f"факт: {event}", int(cm[1, 0]), int(cm[1, 1])]]}]
    if with_coefs:
        tables.insert(0, {"title": "Коэффициенты (признаки стандартизованы)",
                          "columns": ["признак", "коэффициент", "отношение шансов", "ст. ошибка", "p-значение"],
                          "rows": _logit_table(model, d, x[tr])})
    return _report(out, {
        "kind": "classification", "title": f"{title}: {target} = {event}",
        "metrics": _metric_rows(m_tr, m_te, cv),
        "roc": [{"fpr": _r(fpr[i], 4), "tpr": _r(tpr[i], 4)} for i in range(0, len(fpr), step)] + [{"fpr": 1.0, "tpr": 1.0}],
        "tables": tables,
        "notes": [f"Обучение: {int(tr.sum())} полных строк; порог класса {thr}."]})


def _logit_table(model: LogisticRegression, d: Design, x: np.ndarray) -> list[list[Any]]:
    beta = np.concatenate([model.intercept_, model.coef_[0]])
    a = np.column_stack([np.ones(len(x)), x])
    pr = 1 / (1 + np.exp(-(a @ beta)))
    cov = np.linalg.pinv(a.T @ (a * (pr * (1 - pr))[:, None]))
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    z = np.divide(beta, se, out=np.full_like(beta, np.nan), where=se > 0)
    pv = 2 * st.norm.sf(np.abs(z))
    names = ["(свободный член)", *d.names]
    return [[nm, _r(beta[i]), _r(float(np.exp(beta[i]))), _r(se[i]), _r(pv[i])] for i, nm in enumerate(names)]


def logreg(inp: dict[str, Frame], p: Params) -> Frame:
    return _classifier(inp, p, lambda: LogisticRegression(C=1e6, max_iter=2000), "Логистическая регрессия",
                       with_coefs=True)


def _layers(p: Params) -> tuple[int, ...]:
    try:
        layers = tuple(int(v) for v in str(p.get("hidden") or "10").replace(";", ",").split(",") if v.strip())
    except ValueError as exc:
        raise NodeError("Нейросеть: скрытые слои — числа через запятую, например 10 или 16, 8") from exc
    if not layers or any(n < 1 or n > 512 for n in layers) or len(layers) > 5:
        raise NodeError("Нейросеть: от 1 до 5 скрытых слоёв, в каждом от 1 до 512 нейронов")
    return layers


def mlp_cls(inp: dict[str, Frame], p: Params) -> Frame:
    layers, seed, it = _layers(p), int(p.get("seed") or SEED), int(p.get("max_iter") or 500)
    return _classifier(inp, p, lambda: MLPClassifier(hidden_layer_sizes=layers, max_iter=it, random_state=seed, early_stopping=False),
                       "Нейросеть (классификация)", with_coefs=False)


def mlp_reg(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    target = p["target"]
    _need(df, [target], "Нейросеть (регрессия)")
    feats = _features(df, p, [target, p.get("set_column") or ""])
    d = Design(df, feats, scale=True)
    x, y = d.matrix(df), pd.to_numeric(df[target], errors="coerce").to_numpy(dtype=float)
    ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
    train, test = _sets(df, p)
    tr, te = ok & train.to_numpy(), ok & test.to_numpy()
    if tr.sum() < 10:
        raise NodeError("Нейросеть (регрессия): для обучения нужно хотя бы 10 полных строк")
    layers, seed, it = _layers(p), int(p.get("seed") or SEED), int(p.get("max_iter") or 500)
    ym, ys = y[tr].mean(), y[tr].std() or 1.0  # цель тоже в z — сеть учится устойчивее

    def make() -> MLPRegressor:
        return MLPRegressor(hidden_layer_sizes=layers, max_iter=it, random_state=seed)

    model = make().fit(x[tr], (y[tr] - ym) / ys)
    fit = np.full(len(df), np.nan)
    fit[ok] = model.predict(x[ok]) * ys + ym

    def fit_score(xa: np.ndarray, ya: np.ndarray, xb: np.ndarray, yb: np.ndarray) -> dict[str, float]:
        m, s = ya.mean(), ya.std() or 1.0
        return reg_metrics(yb, make().fit(xa, (ya - m) / s).predict(xb) * s + m)

    cv = _cv(x[tr], y[tr], int(p.get("cv") or 0), fit_score, False, seed)
    new = _target_new(inp, df)
    if "new" in inp:
        _need(new, feats, "Новые данные")
        xn = d.matrix(new)
        okn = np.isfinite(xn).all(axis=1)
        pred = np.full(len(new), np.nan)
        if okn.any():
            pred[okn] = model.predict(xn[okn]) * ys + ym
    else:
        pred = fit
    out = new.copy()
    out[f"{target}_прогноз"] = pred
    return _report(out, {
        "kind": "regression", "title": f"Нейросеть (регрессия): {target}",
        "metrics": _metric_rows(reg_metrics(y[tr], fit[tr]), reg_metrics(y[te], fit[te]), cv),
        "summary": [["слои", ", ".join(map(str, layers))], ["итераций", int(model.n_iter_)]],
        "tables": [], "notes": [f"Обучение: {int(tr.sum())} полных строк; признаки стандартизованы."]})


# --- кластеризация --------------------------------------------------------------------------------

def _cluster_frame(df: Frame, p: Params, where: str) -> tuple[Design, np.ndarray, np.ndarray]:
    feats = _features(df, p, [])
    d = Design(df, feats, scale=True)
    x = d.matrix(df)
    ok = np.isfinite(x).all(axis=1)
    if ok.sum() < 4:
        raise NodeError(f"{where}: полных строк {int(ok.sum())} — мало")
    return d, x, ok


def _profiles(df: Frame, labels: pd.Series, feats: list[str]) -> dict[str, Any]:
    rows = []
    for c in sorted(labels.dropna().unique()):
        part = df[labels == c]
        row: list[Any] = [int(c), len(part)]
        for f in feats:
            s = part[f]
            row.append(_r(pd.to_numeric(s, errors="coerce").mean()) if pd.api.types.is_numeric_dtype(df[f])
                       else (s.astype("string").mode().iloc[0] if s.notna().any() else None))
        rows.append(row)
    total: list[Any] = ["все", int(labels.notna().sum())] + [
        _r(pd.to_numeric(df[f], errors="coerce").mean()) if pd.api.types.is_numeric_dtype(df[f]) else "" for f in feats]
    return {"title": "Профили кластеров (средние; для текстовых — частое значение)",
            "columns": ["кластер", "строк", *feats], "rows": [*rows, total]}


def _choose_k(x: np.ndarray, p: Params, seed: int) -> tuple[int, list[list[Any]]]:
    k = int(p.get("k") or 0)
    if k:
        if not 2 <= k <= 50:
            raise NodeError("Кластеров — от 2 до 50")
        return k, []
    tried = []
    for kk in range(2, min(10, len(x) - 1) + 1):
        lab = KMeans(kk, n_init=10, random_state=seed).fit_predict(x)
        tried.append([kk, _r(skm.silhouette_score(x, lab, random_state=seed))])
    best = max(tried, key=lambda r: r[1] if r[1] is not None else -1)
    return int(best[0]), tried


def kmeans(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    d, x, ok = _cluster_frame(df, p, "Кластеризация")
    seed = int(p.get("seed") or SEED)
    k, tried = _choose_k(x[ok], p, seed)
    model = KMeans(k, n_init=10, random_state=seed).fit(x[ok])
    new = _target_new(inp, df)
    xn = d.matrix(new) if "new" in inp else x
    okn = np.isfinite(xn).all(axis=1)
    lab = np.full(len(new), np.nan)
    dist = np.full(len(new), np.nan)
    if okn.any():
        lab[okn] = model.predict(xn[okn]) + 1
        dist[okn] = np.min(model.transform(xn[okn]), axis=1)
    out = new.copy()
    name = p.get("as") or "кластер"
    out[name] = pd.Series(lab, index=out.index).astype("Int64")
    out[f"{name}_расстояние"] = dist
    sil = skm.silhouette_score(x[ok], model.labels_, random_state=seed) if k > 1 else float("nan")
    tables = [_profiles(new, out[name], d.features)]
    if tried:
        tables.append({"title": "Выбор числа кластеров (силуэт: чем ближе к 1, тем чище)",
                       "columns": ["кластеров", "силуэт"], "rows": tried})
    return _report(out, {"kind": "clusters", "title": f"Кластеризация k-средних, кластеров: {k}",
                         "summary": [["кластеров", k], ["силуэт", _r(sil)], ["инерция", _r(model.inertia_)]],
                         "tables": tables, "notes": ["Признаки стандартизованы; строки с пропусками — без кластера."]})


def em(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    d, x, ok = _cluster_frame(df, p, "EM-кластеризация")
    seed = int(p.get("seed") or SEED)
    k = int(p.get("k") or 0)
    tried: list[list[Any]] = []
    if not k:
        for kk in range(1, min(8, int(ok.sum()) - 1) + 1):
            gm = GaussianMixture(kk, random_state=seed).fit(x[ok])
            tried.append([kk, _r(gm.bic(x[ok]), 1)])
        k = int(min(tried, key=lambda r: r[1])[0])
    model = GaussianMixture(k, random_state=seed).fit(x[ok])
    new = _target_new(inp, df)
    xn = d.matrix(new) if "new" in inp else x
    okn = np.isfinite(xn).all(axis=1)
    lab, prob = np.full(len(new), np.nan), np.full(len(new), np.nan)
    if okn.any():
        pr = model.predict_proba(xn[okn])
        lab[okn], prob[okn] = pr.argmax(axis=1) + 1, pr.max(axis=1)
    out = new.copy()
    name = p.get("as") or "кластер"
    out[name] = pd.Series(lab, index=out.index).astype("Int64")
    out[f"{name}_вероятность"] = prob
    tables = [_profiles(new, out[name], d.features)]
    if tried:
        tables.append({"title": "Выбор числа кластеров (BIC: меньше — лучше)", "columns": ["кластеров", "BIC"],
                       "rows": tried})
    return _report(out, {"kind": "clusters", "title": f"EM-кластеризация (смесь нормальных), кластеров: {k}",
                         "summary": [["кластеров", k], ["BIC", _r(model.bic(x[ok]), 1)]], "tables": tables,
                         "notes": ["Признаки стандартизованы; вероятность — уверенность в кластере строки."]})


def som(inp: dict[str, Frame], p: Params) -> Frame:
    """Самоорганизующаяся карта Кохонена: строки — в ячейки сетки, похожие — в соседние."""
    df = inp["in"]
    d, x, ok = _cluster_frame(df, p, "Самоорганизующиеся сети")
    w, h = int(p.get("width") or 5), int(p.get("height") or 5)
    if not (2 <= w <= 30 and 2 <= h <= 30):
        raise NodeError("Карта: ширина и высота — от 2 до 30")
    rng = np.random.default_rng(int(p.get("seed") or SEED))
    data = x[ok]
    grid = np.array([(i, j) for j in range(h) for i in range(w)], dtype=float)
    weights = data[rng.integers(0, len(data), w * h)].copy()
    epochs = int(p.get("epochs") or 100)
    steps = epochs * len(data)
    sigma0, lr0 = max(w, h) / 2, 0.5
    t = 0
    for _ in range(epochs):
        for i in rng.permutation(len(data)):
            frac = t / steps
            sigma, lr = sigma0 * (1 - frac) + 0.5 * frac, lr0 * (1 - frac) + 0.01 * frac
            bmu = int(np.argmin(((weights - data[i]) ** 2).sum(axis=1)))
            g = np.exp(-((grid - grid[bmu]) ** 2).sum(axis=1) / (2 * sigma ** 2))
            weights += lr * g[:, None] * (data[i] - weights)
            t += 1
    new = _target_new(inp, df)
    xn = d.matrix(new) if "new" in inp else x
    okn = np.isfinite(xn).all(axis=1)
    cell = np.full(len(new), np.nan)
    if okn.any():
        cell[okn] = np.argmin(((xn[okn][:, None, :] - weights[None]) ** 2).sum(axis=2), axis=1)
    out = new.copy()
    c = pd.Series(cell, index=out.index)
    out["ячейка_x"] = (c % w + 1).astype("Int64")
    out["ячейка_y"] = (c // w + 1).astype("Int64")
    out["ячейка"] = (c + 1).astype("Int64")
    counts = out.groupby(["ячейка_y", "ячейка_x"]).size()
    grid_rows = [[y, *[int(counts.get((y, xx), 0)) for xx in range(1, w + 1)]] for y in range(1, h + 1)]
    qe = float(np.mean(np.min(((data[:, None, :] - weights[None]) ** 2).sum(axis=2), axis=1) ** 0.5))
    return _report(out, {"kind": "clusters", "title": f"Самоорганизующаяся карта {w}×{h}",
                         "summary": [["ошибка квантования", _r(qe)], ["эпох", epochs]],
                         "tables": [{"title": "Строк в ячейках карты (строка — y, столбец — x)",
                                     "columns": ["y \\ x", *map(str, range(1, w + 1))], "rows": grid_rows},
                                    _profiles(new, out["ячейка"], d.features)],
                         "notes": ["Признаки стандартизованы."]})


# --- ассоциативные правила и кластеризация транзакций ---------------------------------------------

def _baskets(df: Frame, p: Params, where: str) -> dict[str, frozenset[str]]:
    tid, item = p["transaction"], p["item"]
    _need(df, [tid, item], where)
    data = df[[tid, item]].dropna().astype("string")
    return {str(t): frozenset(g[item].tolist()) for t, g in data.groupby(tid)}


def assoc(inp: dict[str, Frame], p: Params) -> Frame:
    """Ассоциативные правила (Apriori): «если в транзакции есть A, то часто есть и B»."""
    baskets = list(_baskets(inp["in"], p, "Ассоциативные правила").values())
    n = len(baskets)
    if n < 2:
        raise NodeError("Ассоциативные правила: нужно хотя бы две транзакции")
    min_sup, min_conf = float(p.get("min_support") or 0.05), float(p.get("min_confidence") or 0.5)
    max_len = int(p.get("max_length") or 3)
    support: dict[frozenset[str], float] = {}
    level = {frozenset([i]) for b in baskets for i in b}
    size = 1
    while level and size <= max_len:
        counts = {c: sum(1 for b in baskets if c <= b) / n for c in level}
        frequent = {c: s for c, s in counts.items() if s >= min_sup}
        support.update(frequent)
        size += 1
        items = sorted({i for c in frequent for i in c})
        level = {frozenset(c) for c in combinations(items, size)
                 if all(frozenset(s) in frequent for s in combinations(c, size - 1))}
        if len(level) > 200_000:
            raise NodeError("Ассоциативные правила: слишком много сочетаний — поднимите минимальную поддержку")
    rows = []
    for itemset, sup in support.items():
        if len(itemset) < 2:
            continue
        for r in range(1, len(itemset)):
            for lhs in map(frozenset, combinations(sorted(itemset), r)):
                conf = sup / support[lhs]
                if conf >= min_conf:
                    rhs = itemset - lhs
                    rows.append({"если": ", ".join(sorted(lhs)), "то": ", ".join(sorted(rhs)),
                                 "поддержка": sup, "достоверность": conf, "лифт": conf / support[rhs],
                                 "транзакций": round(sup * n)})
    out = pd.DataFrame(rows, columns=["если", "то", "поддержка", "достоверность", "лифт", "транзакций"])
    out = out.sort_values(["лифт", "достоверность"], ascending=False).reset_index(drop=True)
    return _report(out, {"kind": "rules", "title": "Ассоциативные правила",
                         "summary": [["транзакций", n], ["частых наборов", len(support)], ["правил", len(out)]],
                         "tables": [], "notes": ["Лифт > 1 — товары встречаются вместе чаще, чем случайно."]})


def tx_cluster(inp: dict[str, Frame], p: Params) -> Frame:
    """Кластеризация транзакций: похожие по составу транзакции — в один кластер (k-средних по 0/1)."""
    baskets = _baskets(inp["in"], p, "Кластеризация транзакций")
    items = sorted({i for b in baskets.values() for i in b})
    if len(baskets) < 4:
        raise NodeError("Кластеризация транзакций: нужно хотя бы 4 транзакции")
    ids = list(baskets)
    x = np.array([[1.0 if i in baskets[t] else 0.0 for i in items] for t in ids])
    seed = int(p.get("seed") or SEED)
    k, tried = _choose_k(x, p, seed)
    lab = KMeans(k, n_init=10, random_state=seed).fit_predict(x) + 1
    out = pd.DataFrame({p["transaction"]: ids, "кластер": lab, "позиций": x.sum(axis=1).astype(int)})
    rows = []
    for c in range(1, k + 1):
        share = x[lab == c].mean(axis=0)
        top = [f"{items[i]} ({round(100 * share[i])}%)" for i in np.argsort(-share)[:5] if share[i] > 0]
        rows.append([c, int((lab == c).sum()), ", ".join(top)])
    tables = [{"title": "Кластеры: частые позиции (доля транзакций кластера)", "columns": ["кластер", "транзакций",
               "частые позиции"], "rows": rows}]
    if tried:
        tables.append({"title": "Выбор числа кластеров (силуэт)", "columns": ["кластеров", "силуэт"], "rows": tried})
    return _report(out, {"kind": "clusters", "title": f"Кластеризация транзакций, кластеров: {k}",
                         "summary": [["транзакций", len(ids)], ["позиций", len(items)]], "tables": tables, "notes": []})


# --- ARIMAX ---------------------------------------------------------------------------------------

def _arima_resid(theta: np.ndarray, y: np.ndarray, xx: np.ndarray, p_: int, q: int) -> np.ndarray:
    c, phi, th, beta = theta[0], theta[1:1 + p_], theta[1 + p_:1 + p_ + q], theta[1 + p_ + q:]
    e = np.zeros(len(y))
    for t in range(len(y)):
        ar = sum(phi[i] * y[t - 1 - i] for i in range(p_) if t - 1 - i >= 0)
        ma = sum(th[j] * e[t - 1 - j] for j in range(q) if t - 1 - j >= 0)
        e[t] = y[t] - c - ar - ma - (xx[t] @ beta if len(beta) else 0.0)
    return e[max(p_, q):]


def arimax(inp: dict[str, Frame], p: Params) -> Frame:
    """ARIMAX(p, d, q) методом условных наименьших квадратов: ряд объясняется своими прошлыми
    значениями (p), прошлыми ошибками (q) и внешними факторами; d — разности. Прогноз — на
    горизонт; внешние факторы будущего берутся из строк, где ряд пустой."""
    df = inp["in"]
    col, order = p["column"], p.get("order_by")
    exog: list[str] = p.get("exog") or []
    _need(df, [col, *exog] + ([order] if order else []), "ARIMAX")
    data = df.sort_values(order, kind="stable").reset_index(drop=True) if order else df.reset_index(drop=True)
    y_all = pd.to_numeric(data[col], errors="coerce").to_numpy(dtype=float)
    x_all = data[exog].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float) if exog else np.empty((len(data), 0))
    known = np.where(np.isfinite(y_all))[0]
    if len(known) == 0:
        raise NodeError("ARIMAX: в ряду нет значений")
    last = known[-1]
    y, xx = y_all[:last + 1], x_all[:last + 1]
    if not np.isfinite(y).all() or (exog and not np.isfinite(xx).all()):
        raise NodeError("ARIMAX: в истории ряда и факторов есть пропуски — заполните их («Заполнение пропусков»)")
    p_, d, q = int(p.get("p") or 1), int(p.get("d") or 0), int(p.get("q") or 0)
    if not (0 <= p_ <= 10 and 0 <= d <= 2 and 0 <= q <= 10):
        raise NodeError("ARIMAX: p и q — от 0 до 10, d — от 0 до 2")
    yd, xd = y.copy(), xx.copy()
    for _ in range(d):
        yd, xd = np.diff(yd), (np.diff(xd, axis=0) if len(exog) else xd[1:])
    k = 1 + p_ + q + len(exog)
    if len(yd) < k + max(p_, q) + 5:
        raise NodeError(f"ARIMAX: значений {len(yd)} — мало для модели с {k} параметрами")
    theta0 = np.zeros(k)
    theta0[0] = yd.mean()
    res = optimize.least_squares(lambda th: _arima_resid(th, yd, xd, p_, q), theta0, method="trf")
    theta = res.x
    e = _arima_resid(theta, yd, xd, p_, q)
    n_eff = len(e)
    sse = float(e @ e)
    aic = n_eff * np.log(sse / n_eff) + 2 * k
    # подогнанные значения (на шаг вперёд) и прогноз на горизонт
    full_e = np.concatenate([np.zeros(max(p_, q)), e])
    horizon = int(p.get("horizon") or 0)
    future_x = x_all[last + 1:last + 1 + horizon] if exog else np.empty((horizon, 0))
    if exog and horizon and (len(future_x) < horizon or not np.isfinite(future_x).all()):
        raise NodeError(f"ARIMAX: для прогноза на {horizon} шагов нужны значения факторов в {horizon} строках после ряда")
    if d:
        fx = np.vstack([xx, future_x]) if exog else np.empty((len(y) + horizon, 0))
        for _ in range(d):
            fx = np.diff(fx, axis=0) if exog else fx[1:]
        future_xd = fx[len(yd):]
    else:
        future_xd = future_x
    c, phi, th, beta = theta[0], theta[1:1 + p_], theta[1 + p_:1 + p_ + q], theta[1 + p_ + q:]
    yd_ext, e_ext = list(yd), list(full_e)
    for h in range(horizon):
        t = len(yd_ext)
        val = c + sum(phi[i] * yd_ext[t - 1 - i] for i in range(p_) if t - 1 - i >= 0) \
            + sum(th[j] * e_ext[t - 1 - j] for j in range(q) if t - 1 - j >= 0) \
            + (future_xd[h] @ beta if len(beta) else 0.0)
        yd_ext.append(val)
        e_ext.append(0.0)
    fitted_d = yd - full_e
    # обратно из разностей
    fc = yd_ext[len(yd):]
    if d == 1:
        fc_levels = list(np.cumsum(fc) + y[-1])
        fit_levels = list(np.concatenate([[np.nan], y[:-1] + fitted_d]))
    elif d == 2:
        first = np.cumsum(np.cumsum(fc) + (y[-1] - y[-2])) + y[-1]
        fc_levels = list(first)
        fit_levels = list(np.concatenate([[np.nan, np.nan], 2 * y[1:-1] - y[:-2] + fitted_d]))
    else:
        fc_levels, fit_levels = list(fc), list(fitted_d)
    fit_levels[:max(p_, q) + d] = [np.nan] * (max(p_, q) + d)
    out = data.iloc[:last + 1 + horizon].copy()
    if len(out) < last + 1 + horizon:  # строк на горизонт не хватает — добавляем пустые
        out = pd.concat([out, pd.DataFrame(index=range(last + 1 + horizon - len(out)))], ignore_index=True)
    out[f"{col}_модель"] = list(fit_levels) + [np.nan] * horizon
    out[f"{col}_прогноз"] = [np.nan] * (last + 1) + fc_levels
    sigma = np.sqrt(sse / max(1, n_eff - k))
    names = ["константа", *[f"AR{i + 1}" for i in range(p_)], *[f"MA{j + 1}" for j in range(q)], *exog]
    jac = res.jac
    try:
        cov = np.linalg.pinv(jac.T @ jac) * sigma ** 2
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        se = np.full(k, np.nan)
    rows = [[nm, _r(theta[i]), _r(se[i])] for i, nm in enumerate(names)]
    return _report(out, {"kind": "timeseries", "title": f"ARIMAX({p_}, {d}, {q}): {col}",
                         "summary": [["AIC", _r(aic, 2)], ["ст. ошибка остатков", _r(sigma)], ["наблюдений", n_eff],
                                     ["горизонт", horizon]],
                         "tables": [{"title": "Коэффициенты", "columns": ["параметр", "оценка", "ст. ошибка"],
                                     "rows": rows}],
                         "notes": ["Оценка — условные наименьшие квадраты (CSS)."]})


# --- реестр ---------------------------------------------------------------------------------------

def _common(target: bool = True, target_label: str = "Целевой") -> tuple[Param, ...]:
    out: list[Param] = []
    if target:
        out.append(Param("target", target_label, "column"))
    out += [Param("features", "Признаки (пусто — все числовые)", "columns", required=False),
            Param("set_column", "Столбец множеств (из «Разбиения»)", "column", required=False),
            Param("cv", "Кросс-валидация: частей (0 — нет)", "number", required=False, default=0),
            Param("seed", "Seed", "number", required=False, default=SEED)]
    return tuple(out)


NEW = ("in", "new")
NEW_LABELS = ("Обучение", "Новые данные")
CLS_EXTRA = (Param("event", "Значение-«событие» (пусто — второе по алфавиту)", "text", required=False),
             Param("threshold", "Порог класса", "number", required=False, default=0.5))
NN = (Param("hidden", "Скрытые слои (например, 16, 8)", "text", required=False, default="10"),
      Param("max_iter", "Итераций обучения", "number", required=False, default=500))
CLUSTER = (Param("features", "Признаки (пусто — все числовые)", "columns", required=False),
           Param("k", "Кластеров (пусто — подобрать)", "number", required=False),
           Param("seed", "Seed", "number", required=False, default=SEED),
           Param("as", "Имя столбца кластера", "text", required=False))
TX = (Param("transaction", "Транзакция (id)", "column"), Param("item", "Позиция (товар, признак)", "column"))

COMPONENTS = [
    Component("mining.linreg", "Линейная регрессия", GROUP,
              "МНК: коэффициенты, p-значения, R², F; прогноз и остатки; применение к новым данным",
              NEW, _common(), linreg, input_labels=NEW_LABELS, optional=("new",)),
    Component("mining.logreg", "Логистическая регрессия", GROUP,
              "Вероятность события (да/нет): коэффициенты, отношения шансов, AUC, ROC, матрица ошибок",
              NEW, (*_common(), *CLS_EXTRA), logreg, input_labels=NEW_LABELS, optional=("new",)),
    Component("mining.mlp_cls", "Нейросеть (классификация)", GROUP,
              "Многослойный перцептрон для да/нет: вероятность, AUC, ROC",
              NEW, (*_common(), *CLS_EXTRA, *NN), mlp_cls, input_labels=NEW_LABELS, optional=("new",)),
    Component("mining.mlp_reg", "Нейросеть (регрессия)", GROUP,
              "Многослойный перцептрон для числового прогноза: R², RMSE, MAE",
              NEW, (*_common(), *NN), mlp_reg, input_labels=NEW_LABELS, optional=("new",)),
    Component("mining.kmeans", "Кластеризация", GROUP,
              "k-средних: кластер строки, профили кластеров, число кластеров — по силуэту",
              NEW, CLUSTER, kmeans, input_labels=("Данные", "Новые данные"), optional=("new",)),
    Component("mining.em", "EM-кластеризация", GROUP,
              "Смесь нормальных распределений: кластер и уверенность, число кластеров — по BIC",
              NEW, CLUSTER, em, input_labels=("Данные", "Новые данные"), optional=("new",)),
    Component("mining.som", "Самоорганизующиеся сети", GROUP,
              "Карта Кохонена: похожие строки — в соседние ячейки сетки",
              NEW, (Param("features", "Признаки (пусто — все числовые)", "columns", required=False),
                    Param("width", "Ширина карты", "number", required=False, default=5),
                    Param("height", "Высота карты", "number", required=False, default=5),
                    Param("epochs", "Эпох обучения", "number", required=False, default=100),
                    Param("seed", "Seed", "number", required=False, default=SEED)),
              som, input_labels=("Данные", "Новые данные"), optional=("new",)),
    Component("mining.assoc", "Ассоциативные правила", GROUP,
              "«Если A, то B» по транзакциям: поддержка, достоверность, лифт (Apriori)",
              ("in",), (*TX, Param("min_support", "Минимальная поддержка", "number", required=False, default=0.05),
                        Param("min_confidence", "Минимальная достоверность", "number", required=False, default=0.5),
                        Param("max_length", "Позиций в правиле не больше", "number", required=False, default=3)),
              assoc),
    Component("mining.tx_cluster", "Кластеризация транзакций", GROUP,
              "Похожие по составу транзакции — в кластеры; частые позиции кластера",
              ("in",), (*TX, Param("k", "Кластеров (пусто — подобрать)", "number", required=False),
                        Param("seed", "Seed", "number", required=False, default=SEED)), tx_cluster),
    Component("mining.arimax", "ARIMAX", GROUP,
              "Прогноз ряда: свои прошлые значения (p), разности (d), прошлые ошибки (q), внешние факторы",
              ("in",), (Param("column", "Ряд", "column"), Param("order_by", "Порядок (например, дата)", "column",
                                                                 required=False),
                        Param("exog", "Внешние факторы", "columns", required=False),
                        Param("p", "p (авторегрессия)", "number", required=False, default=1),
                        Param("d", "d (разности)", "number", required=False, default=0),
                        Param("q", "q (скользящее среднее ошибок)", "number", required=False, default=0),
                        Param("horizon", "Горизонт прогноза", "number", required=False, default=0)), arimax),
]
