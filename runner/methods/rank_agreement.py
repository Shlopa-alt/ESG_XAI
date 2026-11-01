"""Метод «Согласованность показателей»: ρ Спирмена для каждой пары столбцов среза.

Параметры (--params): columns — сравниваемые столбцы (≥ 2), invert — те из них, где больше — хуже
(шкала риска: знак обращается, чтобы у всех было «больше — лучше»), seed, n_boot, n_perm.
Считается на строках, где есть все выбранные столбцы; для каждой пары — ρ, 95 % бутстреп-интервал
и двусторонний перестановочный p. Обобщение расчёта EXP-001 (runner/dow30/run_exp001.py).
"""

import json
import time
from datetime import UTC, datetime
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from common import event, fmt, load_table, numeric, parse_args, results_dir, write_run


def rho(a: np.ndarray, b: np.ndarray) -> float:
    return float(spearmanr(a, b).statistic)


def pair_stats(x: np.ndarray, y: np.ndarray, rng: np.random.Generator, n_boot: int, n_perm: int) -> dict:
    r = rho(x, y)
    n = len(x)
    boot = np.array([rho(x[i], y[i]) for i in (rng.integers(0, n, n) for _ in range(n_boot))])
    boot = boot[~np.isnan(boot)]
    perm = np.array([rho(x, rng.permutation(y)) for _ in range(n_perm)])
    return {"n": n, "rho": round(r, 4), "ci_low": round(float(np.quantile(boot, 0.025)), 4),
            "ci_high": round(float(np.quantile(boot, 0.975)), 4),
            "p_perm": round(float((np.sum(np.abs(perm) >= abs(r)) + 1) / (n_perm + 1)), 4)}


def main() -> int:
    args = parse_args("Согласованность показателей (ρ Спирмена)")
    p = args.params
    cols, invert = list(p["columns"]), set(p.get("invert") or [])
    seed, n_boot, n_perm = int(p.get("seed", 42)), int(p.get("n_boot", 10_000)), int(p.get("n_perm", 10_000))
    t0, started = time.time(), datetime.now(UTC).isoformat()
    out = results_dir(args.results_root)
    df = load_table(args.data, p.get("sheet", ""))
    data = pd.DataFrame({c: numeric(df, c) * (-1 if c in invert else 1) for c in cols}).dropna()
    if len(data) < 5:
        raise SystemExit(f"Строк со всеми выбранными столбцами — {len(data)}, нужно хотя бы 5")
    pairs = list(combinations(cols, 2))
    res: dict[str, dict] = {}
    for i, (a, b) in enumerate(pairs, start=1):
        event("progress", done=i - 1, total=len(pairs), label=f"{a} — {b}")
        st = pair_stats(data[a].to_numpy(float), data[b].to_numpy(float), np.random.default_rng(seed), n_boot, n_perm)
        res[f"{a} — {b}"] = st
        event("metric", name=f"rho {a} — {b}", value=st["rho"])
    event("progress", done=len(pairs), total=len(pairs), label="готово")
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    keys = list(res)
    rhos = [res[k]["rho"] for k in keys]
    note = (f"{len(data)} строк со всеми столбцами" + (f"; знак обращён: {', '.join(sorted(invert))}" if invert else ""))
    report = {
        "kpis": [{"label": k[:120], "value": fmt(res[k]["rho"], True),
                  "note": f"95 % интервал {fmt(res[k]['ci_low'], True)}…{fmt(res[k]['ci_high'], True)}, "
                          f"p = {str(res[k]['p_perm']).replace('.', ',')}"} for k in keys[:4]],
        "charts": [
            {"id": "rho", "kind": "bars", "unit": "ρ", "title": "Согласованность показателей, ρ Спирмена",
             "subtitle": note, "reference": {"value": 0, "label": "нет связи"}, "categories": keys,
             "series": [{"name": "ρ Спирмена", "values": rhos}],
             "interpretation": f"Сильнее всего согласованы {keys[int(np.argmax(rhos))]} ({fmt(max(rhos), True)}), "
                               f"слабее всего — {keys[int(np.argmin(rhos))]} ({fmt(min(rhos), True)})."},
            {"id": "rho_ci", "kind": "ranges", "unit": "ρ", "title": "ρ Спирмена с 95 % бутстреп-интервалом",
             "subtitle": f"{n_boot:,} повторных выборок".replace(",", " "), "reference": {"value": 0, "label": "нет связи"},
             "rows": [{"name": k, "mean": res[k]["rho"], "min": res[k]["ci_low"], "max": res[k]["ci_high"]} for k in keys],
             "interpretation": ("Интервал, задевающий ноль, — согласованность не доказана на этих данных. "
                                f"Таких пар: {sum(1 for k in keys if res[k]['ci_low'] <= 0 <= res[k]['ci_high'])} из {len(keys)}.")},
        ],
    }
    write_run(args, out, "spearman", started, t0, data, {"bootstrap": seed, "permutation": seed, "n_boot": n_boot,
              "n_perm": n_perm}, res, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
