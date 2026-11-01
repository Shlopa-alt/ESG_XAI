"""Отчёт EXP-007 из результатов запуска: ключевые цифры и графики для страницы эксперимента.

    python make_report.py <каталог запуска>

Читает hsu_paper.json, hsu_honest.json, splits.csv, placebo.csv и дописывает в run.json
поле report (схема — backend/app/services/report.py). Цифры статьи — из её таблиц
(Hsu et al., Electronics 2025, 14, 417); всё остальное — из этого запуска.
"""

import json
import sys
from pathlib import Path

import pandas as pd

# Таблицы статьи: R² регрессии и точность классификации, %
PAPER_R2 = {"ROA": {"MLR": -0.28, "R_XGBOPT": 0.27, "R_LGBMOPT": 0.28, "LSTMOPT": 0.71},
            "ROE": {"MLR": 0.07, "R_XGBOPT": 0.25, "R_LGBMOPT": 0.42, "LSTMOPT": 0.72}}
PAPER_ACC = {"ROA": {"C_DTOPT": 55.56, "C_RFOPT": 58.33, "C_LGBMOPT": 77.78, "CNNOPT": 80.56},
             "ROE": {"C_DTOPT": 66.67, "C_RFOPT": 69.44, "C_LGBMOPT": 77.78, "CNNOPT": 80.56}}
REG = [("MLR", "MLR"), ("R_XGBOPT", "XGBoost"), ("R_LGBMOPT", "LightGBM"), ("LSTMOPT", "LSTM")]
CLF = [("C_DTOPT", "Дерево"), ("C_RFOPT", "Лес"), ("C_LGBMOPT", "LightGBM"), ("CNNOPT", "CNN")]
SERIES = ["Статья Hsu et al.", "Повтор: подбор по тесту, как в статье", "Повтор: честная проверка"]
SPLIT_NAMES = {"last_year": "Наивный: прошлый год", "mean_train": "Прогноз средним", "MLR": "Линейная регрессия",
               "LGBM_default": "LightGBM", "LAB_MLP_fixed": "Нейросеть (MLP)"}
r2 = lambda v: round(float(v), 3)  # noqa: E731
ru = lambda v: f"{v:.2f}".replace(".", ",").replace("-", "−")  # noqa: E731


def metric(rows: list[dict], task: str, target: str, model: str, key: str) -> float:
    for r in rows:
        if r["task"] == task and r["target"] == target and r["model"] == model:
            return float(r[key])
    raise KeyError(f"{task}/{target}/{model}")


def main(run_dir: Path) -> int:
    paper = json.loads((run_dir / "hsu_paper.json").read_text(encoding="utf-8"))
    honest = json.loads((run_dir / "hsu_honest.json").read_text(encoding="utf-8"))
    splits = pd.read_csv(run_dir / "splits.csv")
    placebo = pd.read_csv(run_dir / "placebo.csv")
    charts = []
    for tgt in ("ROA", "ROE"):
        charts.append({
            "id": f"r2_{tgt.lower()}", "kind": "bars", "unit": "R²",
            "title": f"Качество прогноза {tgt} 2022 г., R² на тесте",
            "subtitle": "Чем правее, тем лучше; 0 — уровень прогноза средним",
            "reference": {"value": 0, "label": "прогноз средним"},
            "categories": [name for _, name in REG],
            "series": [
                {"name": SERIES[0], "values": [PAPER_R2[tgt][m] for m, _ in REG]},
                {"name": SERIES[1], "values": [r2(metric(paper, "reg", tgt, m, "R2")) for m, _ in REG]},
                {"name": SERIES[2], "values": [r2(metric(honest, "reg", tgt, m, "R2")) for m, _ in REG]},
            ],
            "interpretation": (
                f"LSTM: {ru(PAPER_R2[tgt]['LSTMOPT'])} в статье против "
                f"{ru(metric(paper, 'reg', tgt, 'LSTMOPT', 'R2'))} в повторе тем же протоколом и "
                f"{ru(metric(honest, 'reg', tgt, 'LSTMOPT', 'R2'))} при честной проверке. "
                "Нейросеть не лучше бустинга, а бустинг близок к статье только при подборе по тесту."),
        })
    cats = [f"{name}, {t}" for t in ("ROA", "ROE") for _, name in CLF]
    acc = lambda rows, t, m: round(100 * metric(rows, "clf", t, m, "Accuracy"), 1)  # noqa: E731
    hon_acc = [acc(honest, t, m) for t in ("ROA", "ROE") for m, _ in CLF]
    charts.append({
        "id": "acc", "kind": "bars", "unit": "%",
        "title": "Точность классификации роста ROA/ROE, %",
        "subtitle": "50% — уровень угадывания",
        "reference": {"value": 50, "label": "угадывание"},
        "categories": cats,
        "series": [
            {"name": SERIES[0], "values": [PAPER_ACC[t][m] for t in ("ROA", "ROE") for m, _ in CLF]},
            {"name": SERIES[1], "values": [acc(paper, t, m) for t in ("ROA", "ROE") for m, _ in CLF]},
            {"name": SERIES[2], "values": hon_acc},
        ],
        "interpretation": (
            "При подборе по тестовой выборке простые модели легко дают 70–80%, CNN не лучше их. "
            f"При честной проверке точность всех моделей — {min(hon_acc):.0f}–{max(hon_acc):.0f}%, "
            "то есть около уровня угадывания."),
    })
    g = splits[splits.target == "ROA"].groupby("model")["R2"].agg(["mean", "min", "max"])
    order = [m for m in SPLIT_NAMES if m in g.index]
    charts.append({
        "id": "splits", "kind": "ranges", "unit": "R²",
        "title": "30 случайных разбиений: средний R² и разброс, ROA",
        "subtitle": "Точка — среднее по 30 разбиениям, линия — от худшего до лучшего",
        "reference": {"value": 0, "label": "прогноз средним"},
        "rows": [{"name": SPLIT_NAMES[m], "mean": r2(g.loc[m, "mean"]), "min": r2(g.loc[m, "min"]),
                  "max": r2(g.loc[m, "max"])} for m in order],
        "interpretation": (
            "Одно удачное разбиение может дать заметный R², но в среднем модели на ESG-признаках хуже "
            "прогноза средним. Положительное среднее — только у наивного прогноза «как в прошлом году»."),
    })
    pg = placebo.groupby(["model", "target"])["R2"].agg(["mean", "min", "max"])
    names = {"R_XGBOPT": "XGBoost", "R_LGBMOPT": "LightGBM"}
    charts.append({
        "id": "placebo", "kind": "ranges", "unit": "R²",
        "title": "Плацебо: R² на перемешанной целевой переменной",
        "subtitle": "Связи с целью нет по построению; подбор по тесту, как в статье",
        "reference": {"value": 0, "label": "нет связи"},
        "rows": [{"name": f"{names.get(m, m)}, {t}", "mean": r2(row["mean"]), "min": r2(row["min"]),
                  "max": r2(row["max"])} for (m, t), row in pg.iterrows()],
        "interpretation": (
            f"При подборе по тесту модель находит «качество» там, где связи нет: R² до "
            f"{ru(placebo['R2'].max())}. Высокие метрики, полученные таким протоколом, ничего не доказывают."),
    })
    best_honest = max((metric(honest, "reg", t, m, "R2"), t, n) for t in ("ROA", "ROE") for m, n in REG)
    naive = g.loc["last_year", "mean"] if "last_year" in g.index else None
    kpis = [
        {"label": "R² LSTM по ROA", "value": ru(metric(paper, "reg", "ROA", "LSTMOPT", "R2")),
         "was": f"{ru(PAPER_R2['ROA']['LSTMOPT'])} в статье", "note": "тот же протокол, что в статье"},
        {"label": "Лучший честный R² на ESG-признаках", "value": ru(best_honest[0]),
         "note": f"{best_honest[2]}, {best_honest[1]}"},
        {"label": "R² на перемешанной цели (плацебо)", "value": f"до {ru(placebo['R2'].max())}",
         "note": "связи нет, а «качество» есть"},
    ]
    if naive is not None:
        kpis.append({"label": "Наивный прогноз «как в прошлом году»", "value": ("+" if naive > 0 else "") + ru(naive),
                     "note": "средний R² на 30 разбиениях"})
    run_json = run_dir / "run.json"
    run = json.loads(run_json.read_text(encoding="utf-8"))
    run["report"] = {"kpis": kpis, "charts": charts}
    run_json.write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"отчёт: {len(kpis)} цифр, {len(charts)} графиков → {run_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
