"""Методология лаборатории (с. 84–86, «Формализация задачи»), прогнанная на данных Hsu et al.

п. 2   входы: X_t — ESG-показатели и производственные характеристики, Z_t — отраслевые/макро параметры;
п. 3.1 R_t = f(X_t): MLP с одним скрытым слоем, h = σ(W1·X + b1), RI = W2·h + b2, σ ∈ {ReLU, tanh};
п. 4   обучение — MSE, Adam или RMSProp.
Сеть g(Z_t) для ставки дисконтирования и ЧДД (п. 3.2, 5) на этих данных не обучаемы: нет проектов,
инвестиций IC и целевой переменной для ставки — это фиксируется в отчёте, а не подменяется.

Наборы входов:
  esg      — те же 15 признаков, что у Hsu (прямое сравнение с LSTMOPT/CNNOPT);
  esg_xz   — + размер компании (log активов) и отрасль (Z_t, one-hot);
  esg_xz_lag — + ROA/ROE прошлого года (финансовая история как «производственная характеристика»).
Объяснимость: SHAP (permutation) для MLP, чтобы получить вклад каждого фактора (задача «ключевых факторов» плана).
"""
import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
from sklearn.model_selection import KFold, StratifiedKFold, train_test_split
from sklearn.preprocessing import StandardScaler

from models import LabMLP, clf_metrics, fit_torch, predict_torch, reg_metrics

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)
ESG = [f"X{i}" for i in range(1, 16)]


def design(df, variant, tgt):
    cols = list(ESG)
    X = df[ESG].copy()
    if variant in ("esg_xz", "esg_xz_lag"):
        X["log_assets"] = np.log(df["assets_2021"])
        ind = pd.get_dummies(df["industry"].fillna("NA"), prefix="ind", dtype=float)
        ind = ind.loc[:, ind.sum() >= 5]          # редкие отрасли -> базовая категория
        X = pd.concat([X, ind], axis=1)
    if variant == "esg_xz_lag":
        X[f"{tgt}_2021"] = df[f"{tgt}_2021"]
    return X


def mlp_trial(trial, Xa, ya, Xb, yb, classif, ret_model=False):
    sc = StandardScaler().fit(Xa)
    m = LabMLP(Xa.shape[1], trial.suggest_int("hidden", 4, 256, log=True), trial.suggest_categorical("act", ["relu", "tanh"]),
               trial.suggest_float("dropout", 0.0, 0.5))
    fit_torch(m, sc.transform(Xa), ya.astype(np.float32), opt=trial.suggest_categorical("optimizer", ["Adam", "RMSprop"]),
              lr=trial.suggest_float("lr", 1e-4, 3e-2, log=True), epochs=trial.suggest_int("epochs", 50, 400),
              batch=trial.suggest_categorical("batch", [16, 32, 64]), wd=trial.suggest_float("weight_decay", 1e-6, 1e-1, log=True),
              loss="bce" if classif else "mse")
    if ret_model:
        return m, sc
    p = predict_torch(m, sc.transform(Xb))
    if classif:
        return 1 - clf_metrics(yb, (p > 0).astype(int))["Accuracy"]
    return reg_metrics(yb, p)["RMSE"] if np.isfinite(p).all() else 1e9


def tune(Xtr, ytr, Xte, yte, protocol, classif, trials):
    def obj(t):
        if protocol == "paper":
            return mlp_trial(t, Xtr, ytr, Xte, yte, classif)
        kf = StratifiedKFold(5, shuffle=True, random_state=0) if classif else KFold(5, shuffle=True, random_state=0)
        return float(np.mean([mlp_trial(t, Xtr[a], ytr[a], Xtr[b], ytr[b], classif) for a, b in kf.split(Xtr, ytr)]))
    st = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=0))
    st.optimize(obj, n_trials=trials)
    m, sc = mlp_trial(optuna.trial.FixedTrial(st.best_params), Xtr, ytr, Xte, yte, classif, ret_model=True)
    return m, sc, st.best_params


def shap_importance(m, sc, Xtr, Xte, names):
    import shap
    f = lambda Z: predict_torch(m, sc.transform(Z))
    bg = shap.sample(Xtr, 50, random_state=0)
    ex = shap.PermutationExplainer(f, bg)
    sv = ex(Xte, silent=True).values
    imp = pd.Series(np.abs(sv).mean(0), index=names)
    sign = pd.Series([np.corrcoef(Xte[:, j], sv[:, j])[0, 1] if Xte[:, j].std() > 0 else 0 for j in range(len(names))], index=names)
    return imp, sign


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data"); ap.add_argument("out")
    ap.add_argument("--protocol", choices=["paper", "honest"], default="honest")
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--variants", default="esg,esg_xz,esg_xz_lag")
    ap.add_argument("--shap", action="store_true")
    a = ap.parse_args()
    df = pd.read_csv(a.data, index_col=0, dtype={0: str})
    if a.n:
        df = df.sample(a.n, random_state=a.seed)
    res = []
    for variant in a.variants.split(","):
        for tgt in ["roa", "roe"]:
            Xdf = design(df, variant, tgt)
            X = Xdf.to_numpy(float)
            for classif in (False, True):
                y = df[f"{tgt}_up" if classif else f"{tgt}_2022"].to_numpy(float)
                Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=a.seed, stratify=y if classif else None)
                m, sc, bp = tune(Xtr, ytr, Xte, yte, a.protocol, classif, a.trials)
                p = predict_torch(m, sc.transform(Xte))
                met = clf_metrics(yte.astype(int), (p > 0).astype(int)) if classif else reg_metrics(yte, p)
                r = {"variant": variant, "target": tgt.upper(), "task": "clf" if classif else "reg", "model": "LAB_MLP",
                     "protocol": a.protocol, "seed": a.seed, **met, "best_params": bp}
                if a.shap and not classif:
                    imp, sign = shap_importance(m, sc, Xtr, Xte, list(Xdf.columns))
                    r["shap"] = {k: [round(float(imp[k]), 4), round(float(sign[k]), 3)] for k in imp.sort_values(ascending=False).index}
                res.append(r)
                print(json.dumps({k: v for k, v in r.items() if k not in ("best_params", "shap")}, ensure_ascii=False), flush=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
