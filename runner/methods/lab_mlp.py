"""Метод лаборатории: R = f(X, Z) — MLP из постановки задачи (с. 84–86), по протоколу CR-01, с SHAP.

Параметры (--params):
  target   — результат R (показатель, который предсказываем: ROA, выручка, налоги в бюджет…);
  features — входы X: ESG-показатели или объёмы ESG-инвестиций по статьям затрат;
  context  — параметры Z (необязательно): размер, отрасль, регион, макропоказатели; текстовые
             столбцы (отрасль) — one-hot, редкие значения (< 5 строк) — в «прочее»;
  lag      — R прошлого периода (необязательно): наивный прогноз «как в прошлом году»;
  seed, splits (разбиений 80/20, по CR-01 — не меньше 30), trials (испытаний Optuna на разбиение).

Модель — п. 3.1 методики: h = σ(W1·[X, Z] + b1), R = W2·h + b2, σ ∈ {ReLU, tanh}; обучение — MSE,
Adam или RMSProp (п. 4). Та же сеть, что в EXP-007 (runner/hsu2025/models.py: LabMLP), — здесь копия,
чтобы код повтора EXP-007 не менялся.

Протокол CR-01:
  (1) гиперпараметры подбираются только на обучающей части (Optuna, перекрёстная проверка внутри
      неё) — отложенная 20 % в подборе не участвует;
  (2) `splits` случайных разбиений, отчёт — среднее и разброс R² на отложенной части;
  (3) плацебо: та же процедура на перемешанной цели;
  (4) сравнение с прогнозом средним (R² = 0), с линейной моделью (Ridge) и, если задан lag, с
      прогнозом «как в прошлом году»;
  (5) контроль размера и отрасли — через context (Z).
Вклад факторов — SHAP (permutation) модели, обученной на всех строках с тем же подбором; вклад
one-hot столбцов отрасли складывается обратно в один фактор. Вклад показывается всегда, но смысл
имеет, только если модель предсказывает лучше среднего и плацебо, — так и пишется в отчёте.
"""

import json
import time
import warnings
from datetime import UTC, datetime
from typing import Any

import numpy as np
import optuna
import pandas as pd
import torch
from common import event, fmt, load_table, numeric, parse_args, results_dir, write_run
from sklearn.linear_model import Ridge
from sklearn.metrics import r2_score
from sklearn.model_selection import KFold, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from torch import nn

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)
torch.set_num_threads(2)  # исполнитель считает два запуска сразу (-c 2)
MIN_ROWS = 20
RARE = 5
OPT = {"Adam": torch.optim.Adam, "RMSprop": torch.optim.RMSprop}


class LabMLP(nn.Module):
    """Модель лаборатории, п. 3.1: h = σ(W1 X + b1), R = W2 h + b2."""

    def __init__(self, n_in: int, hidden: int, act: str, dropout: float = 0.0) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(n_in, hidden), {"relu": nn.ReLU(), "tanh": nn.Tanh()}[act],
                                 nn.Dropout(dropout), nn.Linear(hidden, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


class Fitted:
    """Обученная сеть со своими нормировками X и y (обе — только по обучающей части)."""

    def __init__(self, x: np.ndarray, y: np.ndarray, hp: dict, seed: int) -> None:
        self.sx = StandardScaler().fit(x)
        self.my, self.sy = float(y.mean()), float(y.std() or 1.0)
        torch.manual_seed(seed)
        self.m = LabMLP(x.shape[1], hp["hidden"], hp["act"], hp["dropout"])
        xt = torch.tensor(self.sx.transform(x), dtype=torch.float32)
        yt = torch.tensor((y - self.my) / self.sy, dtype=torch.float32)
        opt = OPT[hp["optimizer"]](self.m.parameters(), lr=hp["lr"], weight_decay=hp["weight_decay"])
        loss = nn.MSELoss()
        g = torch.Generator().manual_seed(seed)
        batch = min(hp["batch"], len(xt))
        for _ in range(hp["epochs"]):
            self.m.train()
            perm = torch.randperm(len(xt), generator=g)
            for i in range(0, len(xt), batch):
                idx = perm[i:i + batch]
                opt.zero_grad()
                loss(self.m(xt[idx]), yt[idx]).backward()
                opt.step()
        self.m.eval()

    def predict(self, x: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            p = self.m(torch.tensor(self.sx.transform(x), dtype=torch.float32)).numpy()
        return p * self.sy + self.my


def space(trial: optuna.Trial) -> dict:
    return {"hidden": trial.suggest_int("hidden", 2, 128, log=True),
            "act": trial.suggest_categorical("act", ["relu", "tanh"]),
            "dropout": trial.suggest_float("dropout", 0.0, 0.3),
            "optimizer": trial.suggest_categorical("optimizer", ["Adam", "RMSprop"]),
            "lr": trial.suggest_float("lr", 1e-4, 3e-2, log=True),
            "epochs": trial.suggest_int("epochs", 30, 200),
            "batch": trial.suggest_categorical("batch", [8, 16, 32, 64]),
            "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-1, log=True)}


def tune(x: np.ndarray, y: np.ndarray, trials: int, seed: int) -> dict:
    """Подбор только на (x, y) — обучающей части: среднее MSE перекрёстной проверки."""
    folds = KFold(3 if len(x) < 60 else 5, shuffle=True, random_state=seed)

    def objective(trial: optuna.Trial) -> float:
        hp = space(trial)
        errs = []
        for a, b in folds.split(x):
            p = Fitted(x[a], y[a], hp, seed).predict(x[b])
            errs.append(float(np.mean((p - y[b]) ** 2)) if np.isfinite(p).all() else 1e18)
        return float(np.mean(errs))

    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=trials)
    return space(optuna.trial.FixedTrial(study.best_params))


def r2(y: np.ndarray, p: np.ndarray) -> float:
    return float(r2_score(y, p)) if np.isfinite(p).all() else float("nan")


def one_split(x: np.ndarray, y: np.ndarray, lag: np.ndarray | None, seed: int, trials: int) -> dict[str, float]:
    idx = np.arange(len(y))
    tr, te = train_test_split(idx, test_size=0.2, random_state=seed)
    hp = tune(x[tr], y[tr], trials, seed)
    out = {"MLP лаборатории": r2(y[te], Fitted(x[tr], y[tr], hp, seed).predict(x[te])),
           "Линейная (Ridge)": r2(y[te], make_pipeline(StandardScaler(), Ridge(alpha=1.0)).fit(x[tr], y[tr])
                                  .predict(x[te]))}
    if lag is not None:
        out["Как в прошлом году"] = r2(y[te], lag[te])
    return out


def design(df: pd.DataFrame, features: list[str], context: list[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Матрица входов [X, Z] и для каждого её столбца — исходный фактор (one-hot → столбец Z)."""
    cols, owner = {}, {}
    for c in features:
        cols[c], owner[c] = numeric(df, c), c
    for c in context:
        num = numeric(df, c)
        if num.notna().sum() >= df[c].notna().sum() * 0.9 and df[c].notna().any():
            cols[c], owner[c] = num, c
            continue
        text = df[c].astype("string").fillna("нет данных").str.strip()
        counts = text.value_counts()
        text = text.where(text.map(counts) >= RARE, "прочее")
        levels = sorted(text.unique())
        # две категории — знак вклада читается: «группа: DEC против DC (−)»; больше — один фактор без знака
        factor = f"{c}: {levels[1]} против {levels[0]}" if len(levels) == 2 else c
        for v in levels[1:]:  # первое значение — базовая категория
            name = f"{c} = {v}"
            cols[name], owner[name] = (text == v).astype(float), factor
    return pd.DataFrame(cols), owner


def shap_contrib(fit: Fitted, x: np.ndarray, names: list[str], owner: dict[str, str], seed: int
                 ) -> list[tuple[str, float, float]]:
    """(фактор, средний |вклад| в единицах R, знак связи вклада с фактором) — по убыванию вклада."""
    import shap

    rows = x if len(x) <= 300 else x[np.random.default_rng(seed).choice(len(x), 300, replace=False)]
    bg = shap.sample(x, min(50, len(x)), random_state=seed)
    values = shap.PermutationExplainer(fit.predict, bg, seed=seed)(rows, silent=True).values
    by: dict[str, np.ndarray] = {}
    for j, n in enumerate(names):
        by[owner[n]] = by.get(owner[n], 0) + values[:, j]
    out = []
    for factor, v in by.items():
        cols = [j for j, n in enumerate(names) if owner[n] == factor]
        sign = 0.0
        if len(cols) == 1 and rows[:, cols[0]].std() > 0 and np.std(v) > 0:
            sign = float(np.corrcoef(rows[:, cols[0]], v)[0, 1])
        out.append((factor, float(np.abs(v).mean()), sign))
    return sorted(out, key=lambda t: -t[1])


def stats(vals: list[float]) -> dict[str, float]:
    a = np.array([v for v in vals if np.isfinite(v)])
    if not len(a):
        return {"mean": float("nan"), "min": float("nan"), "max": float("nan"), "share_above_zero": 0.0}
    return {"mean": round(float(a.mean()), 4), "min": round(float(a.min()), 4), "max": round(float(a.max()), 4),
            "share_above_zero": round(float((a > 0).mean()), 3)}


def main() -> int:
    args = parse_args("Метод лаборатории: MLP по протоколу CR-01, SHAP")
    p = args.params
    target, features = str(p["target"]), list(p["features"])
    context, lag_col = list(p.get("context") or []), str(p.get("lag") or "")
    seed, splits, trials = int(p.get("seed", 42)), int(p.get("splits", 30)), int(p.get("trials", 10))
    if target in features or target in context or (lag_col and lag_col in features):
        raise SystemExit("Целевой показатель (и его прошлый год) не может быть признаком")
    t0, started = time.time(), datetime.now(UTC).isoformat()
    out = results_dir(args.results_root)
    df = load_table(args.data, p.get("sheet", ""))
    xdf, owner = design(df, features, context)
    frame = pd.concat([xdf, numeric(df, target).rename("__y")]
                      + ([numeric(df, lag_col).rename("__lag")] if lag_col else []), axis=1).dropna()
    if len(frame) < MIN_ROWS:
        raise SystemExit(f"Строк без пропусков — {len(frame)}, нужно хотя бы {MIN_ROWS}")
    names = list(xdf.columns)
    x, y = frame[names].to_numpy(float), frame["__y"].to_numpy(float)
    lag = frame["__lag"].to_numpy(float) if lag_col else None
    y_placebo = np.random.default_rng(seed).permutation(y)
    real: dict[str, list[float]] = {}
    placebo: list[float] = []
    for i in range(splits):
        for k, v in one_split(x, y, lag, seed + i, trials).items():
            real.setdefault(k, []).append(v)
        placebo.append(one_split(x, y_placebo, None, seed + i, trials)["MLP лаборатории"])
        event("progress", done=i + 1, total=splits, label="разбиения 80/20 и плацебо")
    res: dict[str, Any] = {"rows": len(frame), "target": target, "features": features, "context": context, "lag": lag_col,
           "real": {k: stats(v) for k, v in real.items()}, "placebo": stats(placebo),
           "r2_by_split": {k: [round(v, 4) for v in vs] for k, vs in real.items()}}
    for k, s in res["real"].items():
        event("metric", name=f"R² {k}", value=s["mean"])
    hp_all = tune(x, y, trials, seed)
    contrib = shap_contrib(Fitted(x, y, hp_all, seed), x, names, owner, seed)
    res["shap"] = [{"factor": f, "mean_abs": round(m, 6), "sign": round(s, 3)} for f, m, s in contrib]
    res["hyperparameters_all_rows"] = hp_all
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float),
                                      encoding="utf-8")
    m, pl = res["real"]["MLP лаборатории"], res["placebo"]
    lin = res["real"]["Линейная (Ridge)"]
    works = m["mean"] > 0.05 and m["share_above_zero"] >= 0.8 and m["mean"] > pl["max"]
    verdict = ("предсказывает лучше среднего и плацебо" if works else
               "не лучше среднего" if m["mean"] <= 0.02 else "даёт слабый и неустойчивый сигнал")
    small = f" Строк всего {len(frame)} — на отложенную часть приходится {round(len(frame) * 0.2)}, " \
            "оценка R² шумная." if len(frame) < 100 else ""
    # главный вопрос к методике: нужна ли нейросеть — сравнение с линейной моделью по тем же разбиениям
    gain = [a - b for a, b in zip(real["MLP лаборатории"], real["Линейная (Ridge)"], strict=True)
            if np.isfinite(a) and np.isfinite(b)]
    beats = float(np.mean([g > 0 for g in gain])) if gain else 0.0
    if not works:
        vs_linear = ""
    elif m["mean"] > lin["mean"] + 0.02 and beats >= 0.7:
        vs_linear = (f" Нейросеть лучше линейной модели в {round(100 * beats)} % разбиений — нелинейность "
                     "связи здесь видна.")
    else:
        vs_linear = (f" Линейная модель не хуже (нейросеть лучше лишь в {round(100 * beats)} % разбиений): "
                     "нелинейность сети на этих данных не нужна — для методики это довод за простую модель.")
    if works and "Как в прошлом году" in res["real"] and res["real"]["Как в прошлом году"]["mean"] >= m["mean"]:
        vs_linear += " Прогноз «как в прошлом году» не хуже нейросети — ESG-входы к нему ничего не добавляют."
    top = ", ".join(f"{f} ({'+' if s > 0.1 else '−' if s < -0.1 else '±'})" for f, _, s in contrib[:3])
    report = {
        "kpis": [
            {"label": "R² модели лаборатории (MLP)", "value": fmt(m["mean"], True),
             "note": f"среднее на {splits} разбиениях; разброс {fmt(m['min'], True)}…{fmt(m['max'], True)}"},
            {"label": "Доля разбиений с R² > 0", "value": f"{round(100 * m['share_above_zero'])} %",
             "note": "0 — прогноз не лучше среднего"},
            {"label": "R² на перемешанной цели (плацебо)", "value": f"до {fmt(pl['max'], True)}",
             "note": "сколько «качества» даёт протокол без связи"},
            {"label": "R² линейной модели (Ridge)", "value": fmt(lin["mean"], True),
             "note": "та же задача без нейросети — с чем сравнивать MLP"},
        ],
        "charts": [
            {"id": "r2_splits", "kind": "ranges", "unit": "R²",
             "title": f"Качество прогноза «{target}», R² на отложенной выборке",
             "subtitle": f"{splits} случайных разбиений 80/20, {len(frame)} строк; гиперпараметры MLP — только по "
                         "обучающей части; точка — среднее, отрезок — от минимума до максимума",
             "reference": {"value": 0, "label": "прогноз средним"},
             "rows": [{"name": k, **{q: v[q] for q in ("mean", "min", "max")}} for k, v in res["real"].items()]
                     + [{"name": "MLP лаборатории · плацебо", **{q: pl[q] for q in ("mean", "min", "max")}}],
             "interpretation": f"Модель лаборатории {verdict}: средний R² {fmt(m['mean'], True)}, у линейной "
                               f"{fmt(lin['mean'], True)}, на перемешанной цели — до {fmt(pl['max'], True)}."
                               f"{vs_linear}{small}"},
            {"id": "shap", "kind": "bars", "unit": target,
             "title": f"Вклад факторов в прогноз «{target}» (SHAP)",
             "subtitle": "средний модуль вклада в единицах результата; знак в подписи — как растёт прогноз с "
                         "ростом фактора (+ / − / ± — нет ясной связи)",
             "categories": [f"{f} ({'+' if s > 0.1 else '−' if s < -0.1 else '±'})" for f, _, s in contrib[:12]],
             "series": [{"name": "средний |вклад|", "values": [round(v, 6) for _, v, _ in contrib[:12]]}],
             "interpretation": (f"Больше всего прогноз зависит от: {top}. " if contrib else "") + (
                 "Модель предсказывает лучше среднего — вклады можно читать как ключевые факторы." if works else
                 "Модель не предсказывает лучше среднего и плацебо — вклады описывают подгонку, а не связь; "
                 "ключевыми факторами их не считать.")},
        ],
    }
    write_run(args, out, "lab_mlp", started, t0, frame, {"split": seed, "splits": splits, "optuna": seed},
              {"verdict": verdict, "mlp_r2_mean": m["mean"], "ridge_r2_mean": lin["mean"],
               "placebo_r2_max": pl["max"], "mlp_beats_linear_share": round(beats, 3), "rows": len(frame),
               "top_factors": [f for f, _, _ in contrib[:5]]},
              report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
