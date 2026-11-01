"""Повтор Hsu et al. (2025): регрессия ROA/ROE и классификация роста ROA/ROE по 15 ESG-признакам.

Два протокола подбора гиперпараметров Optuna:
  paper  — целевая функция считается на тестовой выборке (так в статье: отдельной валидации не описано);
  honest — 5-fold CV только на обучающей выборке, тест используется один раз.
"""
import argparse
import json
import time
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold, StratifiedKFold, train_test_split
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier, XGBRegressor

from models import CNNClf, LSTMReg, clf_metrics, fit_torch, predict_torch, reg_metrics

warnings.filterwarnings("ignore")
optuna.logging.set_verbosity(optuna.logging.WARNING)
FEATS = [f"X{i}" for i in range(1, 16)]


def objective_factory(build_and_score, Xtr, ytr, Xte, yte, protocol, classif):
    def obj(trial):
        if protocol == "paper":
            return build_and_score(trial, Xtr, ytr, Xte, yte)
        kf = (StratifiedKFold(5, shuffle=True, random_state=0) if classif else KFold(5, shuffle=True, random_state=0))
        return float(np.mean([build_and_score(trial, Xtr[a], ytr[a], Xtr[b], ytr[b]) for a, b in kf.split(Xtr, ytr)]))
    return obj


# ---------- регрессия ----------
def xgb_reg(trial, Xa, ya, Xb, yb, ret_model=False):
    p = dict(reg_lambda=trial.suggest_float("lambda", 1e-5, 10, log=True),
             reg_alpha=trial.suggest_float("alpha", 1e-5, 10, log=True),
             colsample_bytree=trial.suggest_float("colsample_bytree", 0.2, 0.6),
             subsample=trial.suggest_float("subsample", 0.4, 0.8),
             learning_rate=trial.suggest_float("learning_rate", 1e-4, 0.2, log=True),
             n_estimators=trial.suggest_int("n_estimators", 50, 2000),
             max_depth=trial.suggest_int("max_depth", 2, 12),
             min_child_weight=trial.suggest_int("min_child_weight", 1, 300))
    m = XGBRegressor(**p, n_jobs=4, random_state=0).fit(Xa, ya)
    return m if ret_model else reg_metrics(yb, m.predict(Xb))["RMSE"]


def lgb_reg(trial, Xa, ya, Xb, yb, ret_model=False):
    p = dict(colsample_bytree=trial.suggest_float("feature_fraction", 0.01, 1.0),
             learning_rate=trial.suggest_float("learning_rate", 1e-3, 0.1, log=True),
             max_depth=trial.suggest_int("max_depth", 2, 12),
             num_leaves=trial.suggest_int("num_leaves", 2, 2048, log=True),
             n_estimators=trial.suggest_int("n_estimators", 100, 1000),
             min_child_samples=trial.suggest_int("min_data_in_leaf", 1, 100),
             reg_alpha=trial.suggest_float("lambda_l1", 1e-8, 10, log=True),
             reg_lambda=trial.suggest_float("lambda_l2", 1e-8, 10, log=True),
             min_split_gain=trial.suggest_float("min_gain_to_split", 0, 15),
             subsample=trial.suggest_float("bagging_fraction", 0.3, 1.0),
             subsample_freq=trial.suggest_int("bagging_freq", 1, 7),
             extra_trees=trial.suggest_categorical("extra_trees", [True, False]))
    m = lgb.LGBMRegressor(**p, verbose=-1, n_jobs=4, random_state=0).fit(Xa, ya)
    return m if ret_model else reg_metrics(yb, m.predict(Xb))["RMSE"]


def lstm_reg(trial, Xa, ya, Xb, yb, ret_model=False):
    units = trial.suggest_int("units", 50, LSTM_MAX_UNITS)
    m = LSTMReg(units, trial.suggest_float("dropout_rate", 0.1, 0.6))
    fit_torch(m, Xa[:, :, None] / 100, ya, opt=trial.suggest_categorical("optimizer", ["Adam", "Adagrad", "Adamax", "NAdam", "RMSprop", "SGD"]),
              lr=trial.suggest_float("learning_rate", 1e-3, 1e-1, log=True),
              epochs=trial.suggest_int("epochs", 100, LSTM_MAX_EPOCHS),
              batch=trial.suggest_categorical("batch_size", [16, 32, 64, 128, 256, 512]))
    if ret_model:
        return m
    p = predict_torch(m, Xb[:, :, None] / 100)
    return reg_metrics(yb, p)["RMSE"] if np.isfinite(p).all() else 1e9


# ---------- классификация (Optuna максимизирует accuracy -> минимизируем 1-acc) ----------
def dt_clf(trial, Xa, ya, Xb, yb, ret_model=False):
    m = DecisionTreeClassifier(criterion=trial.suggest_categorical("criterion", ["gini", "entropy"]),
                               splitter=trial.suggest_categorical("splitter", ["best", "random"]),
                               max_depth=trial.suggest_int("max_depth", 1, 10),
                               min_samples_split=trial.suggest_int("min_samples_split", 2, 20),
                               min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 10),
                               max_features=trial.suggest_float("max_features", 0.1, 1.0), random_state=0).fit(Xa, ya)
    return m if ret_model else 1 - clf_metrics(yb, m.predict(Xb))["Accuracy"]


def rf_clf(trial, Xa, ya, Xb, yb, ret_model=False):
    m = RandomForestClassifier(n_estimators=trial.suggest_int("n_estimators", 10, 1000),
                               criterion=trial.suggest_categorical("criterion", ["gini", "entropy"]),
                               max_depth=trial.suggest_int("max_depth", 1, 24),
                               min_samples_split=trial.suggest_int("min_samples_split", 2, 20),
                               min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 10),
                               max_features=trial.suggest_float("max_features", 0.1, 1.0),
                               n_jobs=4, random_state=0).fit(Xa, ya)
    return m if ret_model else 1 - clf_metrics(yb, m.predict(Xb))["Accuracy"]


def lgb_clf(trial, Xa, ya, Xb, yb, ret_model=False):
    m = lgb.LGBMClassifier(boosting_type=trial.suggest_categorical("boosting_type", ["gbdt", "dart", "goss"]),
                           num_leaves=trial.suggest_int("num_leaves", 10, 200),
                           learning_rate=trial.suggest_float("learning_rate", 0.01, 0.5, log=True),
                           max_depth=trial.suggest_int("max_depth", 1, 20),
                           min_child_samples=trial.suggest_int("min_child_samples", 1, 20),
                           subsample=trial.suggest_float("subsample", 0.1, 1),
                           colsample_bytree=trial.suggest_float("colsample_bytree", 0.1, 1),
                           reg_alpha=trial.suggest_float("reg_alpha", 1e-8, 100, log=True),
                           reg_lambda=trial.suggest_float("reg_lambda", 1e-8, 100, log=True),
                           verbose=-1, n_jobs=4, random_state=0).fit(Xa, ya)
    return m if ret_model else 1 - clf_metrics(yb, m.predict(Xb))["Accuracy"]


def cnn_clf(trial, Xa, ya, Xb, yb, ret_model=False):
    m = CNNClf(trial.suggest_categorical("filters_1", [16, 32, 64, 128]), trial.suggest_categorical("filters_2", [16, 32, 64, 128]))
    fit_torch(m, Xa[:, None, :] / 100, ya.astype(np.float32), opt=trial.suggest_categorical("optimizer", ["Adam", "RMSprop", "SGD"]),
              lr=trial.suggest_float("learning_rate", 1e-4, 1e-1, log=True), epochs=100,
              batch=trial.suggest_categorical("batch_size", [16, 32, 64, 128]), loss="bce")
    if ret_model:
        return m
    p = (predict_torch(m, Xb[:, None, :] / 100) > 0).astype(int)
    return 1 - clf_metrics(yb, p)["Accuracy"]


def predict_any(name, m, X):
    if name == "LSTMOPT":
        return predict_torch(m, X[:, :, None] / 100)
    if name == "CNNOPT":
        return (predict_torch(m, X[:, None, :] / 100) > 0).astype(int)
    return m.predict(X)


REG = {"R_XGBOPT": xgb_reg, "R_LGBMOPT": lgb_reg, "LSTMOPT": lstm_reg}
CLF = {"C_DTOPT": dt_clf, "C_RFOPT": rf_clf, "C_LGBMOPT": lgb_clf, "CNNOPT": cnn_clf}


def run(df, protocol, trials, seed, log, targets=("roa", "roe")):
    res = []
    X = df[FEATS].to_numpy(float)
    for tgt in targets:
        y = df[f"{tgt}_2022"].to_numpy(float)
        Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=seed)
        res.append({"task": "reg", "target": tgt.upper(), "model": "MLR", **reg_metrics(yte, LinearRegression().fit(Xtr, ytr).predict(Xte))})
        for name, f in REG.items():
            t0 = time.time()
            st = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=0))
            st.optimize(objective_factory(f, Xtr, ytr, Xte, yte, protocol, False), n_trials=trials)
            m = f(optuna.trial.FixedTrial(st.best_params), Xtr, ytr, Xte, yte, ret_model=True)
            r = {"task": "reg", "target": tgt.upper(), "model": name, **reg_metrics(yte, predict_any(name, m, Xte)),
                 "best_params": st.best_params, "sec": round(time.time() - t0)}
            res.append(r); log(r)
        yc = df[f"{tgt}_up"].to_numpy(int)
        Xtr, Xte, ytr, yte = train_test_split(X, yc, test_size=0.2, random_state=seed, stratify=yc)
        for name, f in CLF.items():
            t0 = time.time()
            st = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=0))
            st.optimize(objective_factory(f, Xtr, ytr, Xte, yte, protocol, True), n_trials=trials)
            m = f(optuna.trial.FixedTrial(st.best_params), Xtr, ytr, Xte, yte, ret_model=True)
            r = {"task": "clf", "target": tgt.upper(), "model": name, **clf_metrics(yte, predict_any(name, m, Xte)),
                 "best_params": st.best_params, "sec": round(time.time() - t0)}
            res.append(r); log(r)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("data"); ap.add_argument("out")
    ap.add_argument("--protocol", choices=["paper", "honest"], default="paper")
    ap.add_argument("--trials", type=int, default=100)
    ap.add_argument("--n", type=int, default=0, help="подвыборка (0 = все наблюдения)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--lstm-max-units", type=int, default=1000)
    ap.add_argument("--lstm-max-epochs", type=int, default=500)
    ap.add_argument("--targets", default="roa,roe")
    a = ap.parse_args()
    LSTM_MAX_UNITS, LSTM_MAX_EPOCHS = a.lstm_max_units, a.lstm_max_epochs
    df = pd.read_csv(a.data, index_col=0, dtype={0: str})
    if a.n:
        df = df.sample(a.n, random_state=a.seed)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    print(f"N={len(df)} protocol={a.protocol} trials={a.trials} seed={a.seed}", flush=True)
    res = run(df, a.protocol, a.trials, a.seed, lambda r: print(json.dumps({k: v for k, v in r.items() if k != "best_params"}, ensure_ascii=False), flush=True), targets=a.targets.split(","))
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
