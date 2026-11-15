"""Протокол CR-01 для методов из статей (библиотека методов): модель — из файла метода, всё остальное — здесь.

Метод библиотеки, который Qwen пишет по статье банка, — это только модель:

    TITLE = "LSTM (Hsu et al., 2025)"

    def make_model(params: dict, seed: int):
        # объект с fit(x, y) и predict(x); x — numpy (строки × входы), y — numpy (строки)
        ...

    if __name__ == "__main__":
        import protocol
        raise SystemExit(protocol.run(make_model, TITLE))

Всё, от чего зависит честность итога, делает этот файл, а не код из статьи:
  (1) входы и цель — числовые столбцы среза, строки с пропусками не берутся;
  (2) `splits` разбиений на обучение и проверку (20 %); у панели (group) — компании целиком в
      одной части (common.holdout), иначе модель узнаёт компанию, а не связь;
  (3) входы и цель стандартизуются по обучающей части каждого разбиения — модели из статей
      обычно ждут масштабированные данные; прогноз возвращается в единицы цели;
  (4) плацебо: та же процедура на перемешанной цели — сколько «качества» даёт протокол без связи;
  (5) сравнение с линейной моделью (Ridge) на тех же разбиениях: нужна ли сложная модель;
  (6) run.json — коммит, sha256 среза, окружение, seed, параметры (правило 3); код самого метода и
      его sha256 исполнитель кладёт рядом (method.py) и записывает в расчёт.

Итоги — в summary с теми же ключами, что у метода лаборатории (model_r2_mean, ridge_r2_mean,
placebo_r2_max), чтобы вкладка «Нейросети» сравнивала метод из статьи с остальными сетями.
"""

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
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
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score

MIN_ROWS = 20
BASE = ("target", "features", "group", "seed", "splits", "sheet")  # остальное — гиперпараметры метода


class _Scaled:
    """Стандартизация по обучающей части: модель видит масштабированные x и y."""

    def __init__(self, x: np.ndarray, y: np.ndarray) -> None:
        self.xm, self.xs = x.mean(0), x.std(0) + 1e-9
        self.ym, self.ys = float(y.mean()), float(y.std() + 1e-9)

    def x(self, x: np.ndarray) -> np.ndarray:
        return (x - self.xm) / self.xs

    def y(self, y: np.ndarray) -> np.ndarray:
        return (y - self.ym) / self.ys

    def back(self, p: np.ndarray) -> np.ndarray:
        return np.asarray(p, dtype=float).reshape(-1) * self.ys + self.ym


def _r2(y: np.ndarray, p: np.ndarray) -> float:
    return float(r2_score(y, p)) if p.shape == y.shape and np.isfinite(p).all() else float("nan")


def _fit_predict(make: Callable[[dict[str, Any], int], Any], hyper: dict[str, Any], seed: int,
                 x: np.ndarray, y: np.ndarray, tr: np.ndarray, te: np.ndarray) -> np.ndarray:
    sc = _Scaled(x[tr], y[tr])
    model = make(dict(hyper), seed)
    model.fit(sc.x(x[tr]), sc.y(y[tr]))
    return sc.back(model.predict(sc.x(x[te])))


def _stats(vals: list[float]) -> dict[str, float]:
    a = np.array([v for v in vals if np.isfinite(v)])
    if not len(a):
        return {"mean": float("nan"), "min": float("nan"), "max": float("nan"), "share_above_zero": 0.0}
    return {"mean": round(float(a.mean()), 4), "min": round(float(a.min()), 4), "max": round(float(a.max()), 4),
            "share_above_zero": round(float((a > 0).mean()), 3)}


def run(make_model: Callable[[dict[str, Any], int], Any], title: str) -> int:
    args = parse_args(f"Метод из статьи: {title} (протокол CR-01)")
    p = args.params
    target, features = str(p["target"]), list(p["features"])
    group = str(p.get("group") or "")
    seed, splits = int(p.get("seed", 42)), int(p.get("splits", 30))
    hyper = {k: v for k, v in p.items() if k not in BASE}
    if not features:
        raise SystemExit("Нужен хотя бы один вход")
    if target in features or (group and group in (target, *features)):
        raise SystemExit("Цель, входы и столбец-группа должны быть разными столбцами")
    t0, started = time.time(), datetime.now(UTC).isoformat()
    out = results_dir(args.results_root)
    df = load_table(args.data, p.get("sheet", ""))
    gcol = group_values(df, group)
    frame = pd.DataFrame({c: numeric(df, c) for c in [*features, target]}
                         | ({"__group": gcol} if gcol is not None else {})).dropna()
    if len(frame) < MIN_ROWS:
        raise SystemExit(f"Строк без пропусков — {len(frame)}, нужно хотя бы {MIN_ROWS}")
    groups = frame["__group"].to_numpy(str) if gcol is not None else None
    n_groups = len(np.unique(groups)) if groups is not None else 0
    if groups is not None and n_groups < MIN_GROUPS:
        raise SystemExit(f"Групп «{group}» — {n_groups}, нужно хотя бы {MIN_GROUPS}")
    x, y = frame[features].to_numpy(float), frame[target].to_numpy(float)
    y_placebo = np.random.default_rng(seed).permutation(y)
    real: list[float] = []
    ridge: list[float] = []
    placebo: list[float] = []
    for i in range(splits):
        tr, te = holdout(len(y), groups, seed + i)
        real.append(_r2(y[te], _fit_predict(make_model, hyper, seed + i, x, y, tr, te)))
        ridge.append(_r2(y[te], Ridge(alpha=1.0).fit(x[tr], y[tr]).predict(x[te])))
        placebo.append(_r2(y_placebo[te], _fit_predict(make_model, hyper, seed + i, x, y_placebo, tr, te)))
        event("progress", done=i + 1, total=splits, label="разбиения и плацебо")
    m, lin, pl = _stats(real), _stats(ridge), _stats(placebo)
    works = m["mean"] > 0.05 and m["share_above_zero"] >= 0.8 and m["mean"] > pl["max"]
    verdict = ("предсказывает лучше среднего и плацебо" if works else
               "не лучше среднего" if not m["mean"] > 0.02 else "даёт слабый и неустойчивый сигнал")
    for name, s in (("R² метода", m), ("R² линейной", lin), ("R² плацебо (макс.)", pl)):
        event("metric", name=name, value=s["max"] if "плацебо" in name else s["mean"])
    part = (f"отложенная часть — {group} целиком ({n_groups} групп)" if groups is not None
            else "случайных разбиений 80/20")
    (out / "results.json").write_text(json.dumps(
        {"rows": len(frame), "target": target, "features": features, "hyperparameters": hyper,
         "r2_by_split": {"метод": real, "линейная": ridge, "плацебо": placebo}},
        ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    report = {
        "kpis": [
            {"label": f"R² метода ({title})", "value": fmt(m["mean"], True),
             "note": f"среднее на {splits} разбиениях; разброс {fmt(m['min'], True)}…{fmt(m['max'], True)}"},
            {"label": "R² линейной модели (Ridge)", "value": fmt(lin["mean"], True),
             "note": "та же задача без сложной модели"},
            {"label": "R² на перемешанной цели (плацебо)", "value": f"до {fmt(pl['max'], True)}",
             "note": "сколько «качества» даёт протокол без связи"},
        ],
        "charts": [{
            "id": "r2_splits", "kind": "ranges", "unit": "R²",
            "title": f"Качество прогноза «{target}», R² на отложенной части",
            "subtitle": f"{splits} разбиений, {part}; {len(frame)} строк; модель — метод из статьи, протокол — CR-01",
            "reference": {"value": 0, "label": "прогноз средним"},
            "rows": [{"name": n, **{q: s[q] for q in ("mean", "min", "max")}}
                     for n, s in ((title, m), ("Линейная (Ridge)", lin), (f"{title} · плацебо", pl))],
            "interpretation": f"Метод {verdict}: средний R² {fmt(m['mean'], True)}, у линейной "
                              f"{fmt(lin['mean'], True)}, на перемешанной цели — до {fmt(pl['max'], True)}.",
        }],
    }
    write_run(args, out, "method", started, t0, frame, {"split": seed, "splits": splits, "group": group},
              {"verdict": verdict, "method": title, "model_r2_mean": m["mean"], "ridge_r2_mean": lin["mean"],
               "placebo_r2_max": pl["max"], "share_above_zero": m["share_above_zero"], "rows": len(frame),
               "group": group, "groups": n_groups, "hyperparameters": hyper}, report)
    return 0
