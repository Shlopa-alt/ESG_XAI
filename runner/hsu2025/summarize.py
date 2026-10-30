"""Сводит результаты: статья vs повтор (два протокола) vs методология лаборатории."""
import json
import sys
from pathlib import Path

import pandas as pd

R = Path(sys.argv[1])
pd.set_option("display.width", 220)

PAPER_REG = {("ROA", "MLR"): (7.98, 5.84, -0.28), ("ROA", "R_XGBOPT"): (6.03, 4.42, 0.27), ("ROA", "R_LGBMOPT"): (6.00, 4.19, 0.28),
             ("ROA", "LSTMOPT"): (3.92, 3.23, 0.71), ("ROE", "MLR"): (13.19, 9.37, 0.07), ("ROE", "R_XGBOPT"): (11.81, 8.59, 0.25),
             ("ROE", "R_LGBMOPT"): (10.44, 7.93, 0.42), ("ROE", "LSTMOPT"): (7.43, 4.46, 0.72)}
PAPER_CLF = {("ROA", "C_DTOPT"): 55.56, ("ROA", "C_RFOPT"): 58.33, ("ROA", "C_LGBMOPT"): 77.78, ("ROA", "CNNOPT"): 80.56,
             ("ROE", "C_DTOPT"): 66.67, ("ROE", "C_RFOPT"): 69.44, ("ROE", "C_LGBMOPT"): 77.78, ("ROE", "CNNOPT"): 80.56}


def load(name):
    p = R / name
    return pd.DataFrame(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else pd.DataFrame()


hp, hh = load("hsu_paper.json"), load("hsu_honest.json")
lp, lh = load("lab_paper.json"), load("lab_honest.json")

rows = []
for (t, m), (rmse, mae, r2) in PAPER_REG.items():
    row = {"target": t, "model": m, "paper_RMSE": rmse, "paper_R2": r2}
    for tag, d in (("rep_paperproto", hp), ("rep_honest", hh)):
        x = d[(d.task == "reg") & (d.target == t) & (d.model == m)] if len(d) else d
        row[f"{tag}_RMSE"] = round(x.RMSE.iloc[0], 2) if len(x) else None
        row[f"{tag}_R2"] = round(x.R2.iloc[0], 2) if len(x) else None
    rows.append(row)
for t in ("ROA", "ROE"):
    for v in ("esg", "esg_xz", "esg_xz_lag"):
        row = {"target": t, "model": f"LAB_MLP[{v}]"}
        for tag, d in (("rep_paperproto", lp), ("rep_honest", lh)):
            x = d[(d.task == "reg") & (d.target == t) & (d.variant == v)] if len(d) else d
            row[f"{tag}_RMSE"] = round(x.RMSE.iloc[0], 2) if len(x) else None
            row[f"{tag}_R2"] = round(x.R2.iloc[0], 2) if len(x) else None
        rows.append(row)
print("РЕГРЕССИЯ (тест 20%)\n", pd.DataFrame(rows).to_string(index=False))

rows = []
for (t, m), acc in PAPER_CLF.items():
    row = {"target": t, "model": m, "paper_Acc": acc}
    for tag, d in (("rep_paperproto", hp), ("rep_honest", hh)):
        x = d[(d.task == "clf") & (d.target == t) & (d.model == m)] if len(d) else d
        row[f"{tag}_Acc"] = round(100 * x.Accuracy.iloc[0], 1) if len(x) else None
        row[f"{tag}_F1"] = round(100 * x.F1.iloc[0], 1) if len(x) else None
    rows.append(row)
for t in ("ROA", "ROE"):
    for v in ("esg", "esg_xz", "esg_xz_lag"):
        row = {"target": t, "model": f"LAB_MLP[{v}]"}
        for tag, d in (("rep_paperproto", lp), ("rep_honest", lh)):
            x = d[(d.task == "clf") & (d.target == t) & (d.variant == v)] if len(d) else d
            row[f"{tag}_Acc"] = round(100 * x.Accuracy.iloc[0], 1) if len(x) else None
            row[f"{tag}_F1"] = round(100 * x.F1.iloc[0], 1) if len(x) else None
        rows.append(row)
print("\nКЛАССИФИКАЦИЯ\n", pd.DataFrame(rows).to_string(index=False))

for name in ("splits.csv", "placebo.csv"):
    p = R / name
    if p.exists():
        d = pd.read_csv(p)
        key = ["target", "model"]
        print(f"\n{name}\n", d.groupby(key)[["RMSE", "R2"]].agg(["mean", "std", "min", "max"]).round(3).to_string())

for tag, d in (("paper-протокол", lp), ("honest", lh)):
    if len(d) and "shap" in d:
        for _, r in d[d.shap.notna()].iterrows():
            top = list(r.shap.items())[:8]
            print(f"\nSHAP {tag} {r.variant} {r.target}: " + ", ".join(f"{k}={v[0]:.2f}({'+' if v[1] > 0 else '-'})" for k, v in top))
