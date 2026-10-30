"""Собирает датасет Hsu et al. (2025) из открытых данных TWSE/MOPS.

ESG (X1..X15) — сводные таблицы MOPS t214sb02, отчётный год 110 (2021).
ROA/ROE — MOPS t163sb04/t163sb05 (годовая отчётность, 4 квартал) за 110 (2021) и 111 (2022).
Цель регрессии: ROA/ROE 2022 (лаг 1 год к ESG 2021), классификации: рост ROA/ROE 2022 vs 2021.
Скоринг признаков — как в статье: доли * 100, остальное — децили 10..100 (для «плохих» показателей инвертировано).
"""
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(sys.argv[1])          # каталог с html из MOPS
OUT = Path(sys.argv[2])          # куда писать csv
ESG_YEAR = 110


def read_main_table(path):
    html = path.read_text(encoding="utf-8", errors="ignore")
    t = max(pd.read_html(io.StringIO(html)), key=len)
    if isinstance(t.columns, pd.MultiIndex):
        t.columns = [a if a == b else f"{a}|{b}" for a, b in t.columns]
    t = t.rename(columns={c: "code" for c in t.columns if "代號" in c})
    t["code"] = t["code"].astype(str).str.strip()
    return t[t["code"].str.fullmatch(r"\d{4}")]


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.replace("%", "").str.strip(),
                         errors="coerce")


def col(t, *keys):
    for c in t.columns:
        if all(k in c for k in keys):
            return c
    raise KeyError(keys)


def esg_raw():
    g = read_main_table(RAW / f"esg_{ESG_YEAR}_1.html")
    e = read_main_table(RAW / f"esg_{ESG_YEAR}_2.html")
    w = read_main_table(RAW / f"esg_{ESG_YEAR}_3.html")
    ws = read_main_table(RAW / f"esg_{ESG_YEAR}_4.html")
    hr = read_main_table(RAW / f"esg_{ESG_YEAR}_5.html")
    bd = read_main_table(RAW / f"esg_{ESG_YEAR}_6.html")
    ir = read_main_table(RAW / f"esg_{ESG_YEAR}_7.html")
    d = pd.DataFrame({"code": g["code"],
                      "name": g[col(g, "名稱")],
                      "ghg1": num(g[col(g, "範疇一", "排放量")]),
                      "ghg2": num(g[col(g, "範疇二", "排放量")])}).set_index("code")
    d["renew_pct"] = num(e.set_index("code")[col(e, "再生能源")])
    d["water"] = num(w.set_index("code")[col(w, "用水量")])
    d["waste"] = num(ws.set_index("code")[col(ws, "總重量", "數據")])
    h = hr.set_index("code")
    d["female_exec_pct"] = num(h[col(h, "女性主管")])
    d["accidents"] = num(h[col(h, "職業災害", "人數")])
    d["salary_avg"] = num(h[col(h, "員工薪資平均數")])
    d["salary_nonexec"] = num(h[col(h, "非擔任主管職務之全時員工薪資平均數")])
    d["benefit_avg"] = num(h[col(h, "員工福利平均數")])
    b = bd.set_index("code")
    seats = num(b[col(b, "董事席次")])
    d["indep_ratio"] = num(b[col(b, "獨立董事席次")]) / seats * 100
    d["female_dir_pct"] = num(b[next(c for c in b.columns if "女性董事" in c and c.endswith("比率"))])
    d["attendance_pct"] = num(b[col(b, "出席率")])
    d["training_pct"] = num(b[col(b, "進修")])
    i = ir.set_index("code")
    d["investor_conf"] = num(i[[c for c in i.columns if c != "code" and "名稱" not in c][0]])
    return d


def fin(year):
    """ROA, ROE (%) = чистая прибыль / активы (капитал) на конец года."""
    def tables(kind):
        html = (RAW / f"{kind}_{year}.html").read_text(encoding="utf-8", errors="ignore")
        out = []
        for t in pd.read_html(io.StringIO(html)):
            if len(t) < 3 or not any("代號" in str(c) for c in t.columns):
                continue
            t.columns = [str(c) for c in t.columns]
            t = t.rename(columns={c: "code" for c in t.columns if "代號" in c})
            t["code"] = t["code"].astype(str).str.strip()
            out.append(t)
        return out

    ni = {}
    for t in tables("t163sb04"):
        c = next(c for c in t.columns if c.startswith("本期") and ("淨利" in c) and "綜合" not in c)
        ni.update(dict(zip(t["code"], num(t[c]))))
    assets, equity = {}, {}
    for t in tables("t163sb05"):
        ca = next(c for c in t.columns if c in ("資產總計", "資產總額"))
        ce = next(c for c in t.columns if c in ("權益總計", "權益總額"))
        assets.update(dict(zip(t["code"], num(t[ca]))))
        equity.update(dict(zip(t["code"], num(t[ce]))))
    f = pd.DataFrame({"ni": pd.Series(ni), "assets": pd.Series(assets), "equity": pd.Series(equity)})
    f["roa"] = f["ni"] / f["assets"] * 100
    f["roe"] = f["ni"] / f["equity"] * 100
    return f


def decile_score(s, higher_is_better=True):
    r = s.rank(pct=True, method="average")
    dec = np.ceil(r * 10).clip(1, 10)
    return dec * 10 if higher_is_better else (11 - dec) * 10


def main():
    raw = esg_raw()
    f21, f22 = fin(110), fin(111)
    d = raw.join(f21[["roa", "roe"]].add_suffix("_2021")).join(f22[["roa", "roe"]].add_suffix("_2022"))
    feats = ["ghg1", "ghg2", "renew_pct", "water", "waste", "female_exec_pct", "accidents",
             "salary_avg", "salary_nonexec", "benefit_avg", "indep_ratio", "female_dir_pct",
             "attendance_pct", "training_pct", "investor_conf"]
    targets = ["roa_2021", "roe_2021", "roa_2022", "roe_2022"]
    d = d.replace([np.inf, -np.inf], np.nan)
    print("сырых компаний:", len(d))
    print("пропуски по столбцам:\n", d[feats + targets].isna().sum().to_string())
    full = d.dropna(subset=feats + targets).copy()
    print("полных наблюдений:", len(full))

    # скоринг как в статье (по выборке полных наблюдений)
    pct_items = ["renew_pct", "female_exec_pct", "indep_ratio", "female_dir_pct", "attendance_pct", "training_pct"]
    bad_items = ["ghg1", "ghg2", "water", "waste", "accidents"]
    sc = pd.DataFrame(index=full.index)
    for i, c in enumerate(feats, 1):
        if c in pct_items:
            sc[f"X{i}"] = full[c]
        else:
            sc[f"X{i}"] = decile_score(full[c], higher_is_better=c not in bad_items)
    sc["name"] = full["name"]
    for t in targets:
        sc[t] = full[t]
    sc["roa_up"] = (full["roa_2022"] > full["roa_2021"]).astype(int)
    sc["roe_up"] = (full["roe_2022"] > full["roe_2021"]).astype(int)
    # для методики лаборатории: размер (X_t) и отрасль (Z_t); в признаки модели Hsu не входят
    sc["assets_2021"] = f21["assets"].reindex(sc.index)
    import json
    info = json.loads((RAW / "company_info.json").read_text(encoding="utf-8"))
    sc["industry"] = pd.Series({r["公司代號"]: r["產業別"] for r in info}).reindex(sc.index)
    OUT.mkdir(parents=True, exist_ok=True)
    d.to_csv(OUT / "raw_esg_fin.csv", encoding="utf-8-sig")
    sc.to_csv(OUT / "hsu_dataset.csv", encoding="utf-8-sig")
    print(sc.describe().T.to_string())


if __name__ == "__main__":
    main()
