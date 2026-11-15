"""Метод «Предсказательная проверка» (протокол CR-01): предсказывают ли признаки цель лучше среднего.

Параметры (--params): target — целевой показатель, features — признаки, seed, splits, group —
столбец-группа панели (компания × год): тогда отложенная часть — компании целиком, которых не было
в обучении (common.holdout), иначе R² завышен — модель узнаёт компанию, а не связь.
Модели без подбора гиперпараметров по тесту: линейная (Ridge на стандартизированных признаках) и
градиентный бустинг (LightGBM с умеренными фиксированными настройками). Каждая — на `splits`
случайных разбиениях 80/20; метрика — R² на отложенной части (0 — уровень прогноза средним).
Плацебо: то же на перемешанной цели — показывает, сколько «качества» даёт сам протокол без связи.
Обобщение проверок EXP-007 (runner/hsu2025/robustness.py).
"""

import json
import time
import warnings
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import (
    MIN_GROUPS,
    event,
    fmt,
    group_values,
    holdout,
    load_table,
    numeric,
    parse_args,
    results_dir,
    write_run,
)

warnings.filterwarnings("ignore")


def models(seed: int) -> dict:
    return {
        "Линейная (Ridge)": lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "LightGBM": lambda: LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=10,
                                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                          random_state=seed, n_jobs=2, verbose=-1),
    }


def scores(x: np.ndarray, y: np.ndarray, groups: np.ndarray | None, seed: int, splits: int,
           label: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {name: [] for name in models(seed)}
    for i in range(splits):
        tr, te = holdout(len(y), groups, seed + i)
        xtr, xte, ytr, yte = x[tr], x[te], y[tr], y[te]
        for name, make in models(seed + i).items():
            out[name].append(float(r2_score(yte, make().fit(xtr, ytr).predict(xte))))
        if (i + 1) % 5 == 0 or i + 1 == splits:
            event("progress", done=i + 1, total=splits, label=label)
    return out


def summary(vals: list[float]) -> dict[str, float]:
    a = np.array(vals)
    return {"mean": round(float(a.mean()), 4), "min": round(float(a.min()), 4), "max": round(float(a.max()), 4),
            "share_above_zero": round(float((a > 0).mean()), 3)}


def main() -> int:
    args = parse_args("Предсказательная проверка (протокол CR-01)")
    p = args.params
    target, features = str(p["target"]), list(p["features"])
    seed, splits = int(p.get("seed", 42)), int(p.get("splits", 30))
    group = str(p.get("group") or "")
    if group and group in (target, *features):
        raise SystemExit("Столбец-группа делит строки на части — он не может быть целью или признаком")
    t0, started = time.time(), datetime.now(UTC).isoformat()
    out = results_dir(args.results_root)
    df = load_table(args.data, p.get("sheet", ""))
    gcol = group_values(df, group)
    data = pd.DataFrame({c: numeric(df, c) for c in [target, *features]}
                        | ({"__group": gcol} if gcol is not None else {})).dropna()
    if len(data) < 30:
        raise SystemExit(f"Строк без пропусков — {len(data)}, для 30 разбиений нужно хотя бы 30")
    groups = data["__group"].to_numpy(str) if gcol is not None else None
    n_groups = len(np.unique(groups)) if groups is not None else 0
    if groups is not None and n_groups < MIN_GROUPS:
        raise SystemExit(f"Групп «{group}» — {n_groups}, нужно хотя бы {MIN_GROUPS}: иначе в отложенной части "
                         "одна-две, и R² ни о чём не говорит")
    data = data.drop(columns=["__group"], errors="ignore")
    x, y = data[features].to_numpy(float), data[target].to_numpy(float)
    real = scores(x, y, groups, seed, splits, "реальная цель")
    placebo = scores(x, np.random.default_rng(seed).permutation(y), groups, seed, splits, "плацебо")
    part = (f"отложенная часть — {group} целиком ({n_groups} групп)" if groups is not None
            else "случайных разбиений 80/20")
    res = {"rows": len(data), "target": target, "features": features,
           "real": {k: summary(v) for k, v in real.items()}, "placebo": {k: summary(v) for k, v in placebo.items()}}
    for name, s in res["real"].items():
        event("metric", name=f"R² {name}", value=s["mean"])
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    best = max(res["real"], key=lambda k: res["real"][k]["mean"])
    b, pl = res["real"][best], max(res["placebo"].values(), key=lambda s: s["max"])
    verdict = ("лучше среднего" if b["mean"] > 0.05 and b["share_above_zero"] >= 0.8 else
               "не лучше среднего" if b["mean"] <= 0.02 else "слабый и неустойчивый сигнал")
    report = {
        "kpis": [
            {"label": f"R² лучшей модели ({best})", "value": fmt(b["mean"], True),
             "note": f"среднее на {splits} разбиениях; разброс {fmt(b['min'], True)}…{fmt(b['max'], True)}"},
            {"label": "Доля разбиений с R² > 0", "value": f"{round(100 * b['share_above_zero'])} %",
             "note": "0 — прогноз не лучше среднего"},
            {"label": "R² на перемешанной цели (плацебо)", "value": f"до {fmt(pl['max'], True)}",
             "note": "сколько «качества» даёт протокол без связи"},
        ],
        "charts": [{
            "id": "r2_splits", "kind": "ranges", "unit": "R²",
            "title": f"Качество прогноза «{target}», R² на отложенной выборке",
            "subtitle": f"{splits} разбиений, {part}; {len(data)} строк, признаков {len(features)}; "
                        "точка — среднее, отрезок — от минимума до максимума",
            "reference": {"value": 0, "label": "прогноз средним"},
            "rows": [{"name": k, **{m: v[m] for m in ("mean", "min", "max")}} for k, v in res["real"].items()]
                    + [{"name": f"{k} · плацебо", **{m: v[m] for m in ("mean", "min", "max")}}
                       for k, v in res["placebo"].items()],
            "interpretation": f"Признаки предсказывают «{target}» {verdict}: лучшая модель — {best}, средний R² "
                              f"{fmt(b['mean'], True)}. На перемешанной цели R² доходит до {fmt(pl['max'], True)} — "
                              "всё, что не выше этого, может быть случайностью.",
        }],
    }
    write_run(args, out, "predictive_check", started, t0, data, {"split": seed, "splits": splits, "group": group},
              {"best_model": best, "best_r2_mean": b["mean"], "placebo_r2_max": pl["max"], "rows": len(data),
               # R² каждой модели и плацебо — для сравнения сетей на вкладке «Нейросети»
               "r2_mean": {k: v["mean"] for k, v in res["real"].items()},
               "placebo_max": {k: v["max"] for k, v in res["placebo"].items()},
               "group": group, "groups": n_groups}, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
