"""Метод «Предсказательная проверка» (протокол CR-01): предсказывают ли признаки цель лучше среднего.

Параметры (--params): target — целевой показатель, features — признаки, seed, splits.
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
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from common import event, fmt, load_table, numeric, parse_args, results_dir, write_run

warnings.filterwarnings("ignore")


def models(seed: int) -> dict:
    return {
        "Линейная (Ridge)": lambda: make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "LightGBM": lambda: LGBMRegressor(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=10,
                                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                                          random_state=seed, n_jobs=2, verbose=-1),
    }


def scores(x: np.ndarray, y: np.ndarray, seed: int, splits: int, label: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {name: [] for name in models(seed)}
    for i in range(splits):
        xtr, xte, ytr, yte = train_test_split(x, y, test_size=0.2, random_state=seed + i)
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
    t0, started = time.time(), datetime.now(UTC).isoformat()
    out = results_dir(args.results_root)
    df = load_table(args.data)
    data = pd.DataFrame({c: numeric(df, c) for c in [target, *features]}).dropna()
    if len(data) < 30:
        raise SystemExit(f"Строк без пропусков — {len(data)}, для 30 разбиений нужно хотя бы 30")
    x, y = data[features].to_numpy(float), data[target].to_numpy(float)
    real = scores(x, y, seed, splits, "реальная цель")
    placebo = scores(x, np.random.default_rng(seed).permutation(y), seed, splits, "плацебо")
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
            "subtitle": f"{splits} случайных разбиений 80/20, {len(data)} строк, признаков {len(features)}; "
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
    write_run(args, out, "predictive_check", started, t0, data, {"split": seed, "splits": splits},
              {"best_model": best, "best_r2_mean": b["mean"], "placebo_r2_max": pl["max"], "rows": len(data)}, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
