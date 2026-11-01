"""Проверки устойчивости к выводам Hsu et al. на восстановленных данных.

1. splits   — 30 случайных разбиений 80/20 без подбора по тесту: наивные бенчмарки, MLR, LGBM, MLP лаборатории.
2. placebo  — протокол статьи (Optuna 100 попыток, целевая функция на тесте) на ПЕРЕМЕШАННОЙ целевой переменной.
              Если R² на тесте выходит заметно > 0, значит «качество» создаётся подбором по тесту, а не сигналом.
"""
import json
import sys
import warnings

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from models import LabMLP, fit_torch, predict_torch, reg_metrics
from replicate_hsu import FEATS, lgb_reg, xgb_reg

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)


def splits(df, n_splits=30):
    rows = []
    X = df[FEATS].to_numpy(float)
    for tgt in ["roa", "roe"]:
        y = df[f"{tgt}_2022"].to_numpy(float)
        lag = df[f"{tgt}_2021"].to_numpy(float)
        for s in range(n_splits):
            itr, ite = train_test_split(np.arange(len(y)), test_size=0.2, random_state=s)
            preds = {
                "mean_train": np.full(len(ite), y[itr].mean()),
                "last_year": lag[ite],
                "MLR": LinearRegression().fit(X[itr], y[itr]).predict(X[ite]),
                "LGBM_default": lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, num_leaves=8, min_child_samples=10,
                                                  verbose=-1, random_state=0).fit(X[itr], y[itr]).predict(X[ite]),
            }
            sc = StandardScaler().fit(X[itr])
            m = fit_torch(LabMLP(15, 32, "tanh", 0.1), sc.transform(X[itr]), y[itr], opt="Adam", lr=3e-3, epochs=200,
                          batch=32, wd=1e-2, seed=s)
            preds["LAB_MLP_fixed"] = predict_torch(m, sc.transform(X[ite]))
            for k, p in preds.items():
                rows.append({"target": tgt.upper(), "split": s, "model": k, **reg_metrics(y[ite], p)})
    return pd.DataFrame(rows)


def placebo(df, n_perm=10, trials=100):
    rows = []
    X = df[FEATS].to_numpy(float)
    rng = np.random.default_rng(0)
    for tgt in ["roa", "roe"]:
        y0 = df[f"{tgt}_2022"].to_numpy(float)
        for k in range(n_perm):
            y = rng.permutation(y0)
            Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)
            for name, f in {"R_XGBOPT": xgb_reg, "R_LGBMOPT": lgb_reg}.items():
                st = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=k))
                st.optimize(lambda t: f(t, Xtr, ytr, Xte, yte), n_trials=trials)
                m = f(optuna.trial.FixedTrial(st.best_params), Xtr, ytr, Xte, yte, ret_model=True)
                rows.append({"target": tgt.upper(), "perm": k, "model": name, **reg_metrics(yte, m.predict(Xte))})
                print(json.dumps(rows[-1]), flush=True)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = pd.read_csv(sys.argv[1], index_col=0, dtype={0: str})
    out = sys.argv[2]
    mode = sys.argv[3]
    if mode == "splits":
        r = splits(df)
    else:
        r = placebo(df)
    r.to_csv(out, index=False)
    print(r.groupby(["target", "model"])[["RMSE", "MAE", "R2"]].agg(["mean", "std"]).round(3).to_string())
