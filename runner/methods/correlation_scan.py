"""Метод «Поиск связей»: все пары столбцов среза — монотонные и немонотонные связи, с подтверждением.

Правка по совещанию «Экономика — правки и идеи по сайту»: «новые корреляции с проверкой всего».
Найти связь в куче столбцов легко — трудно не найти случайную. Поэтому:

  (1) строки делятся случайно (seed) на две части: поиск и подтверждение (holdout — доля второй);
  (2) на части поиска для каждой пары — ρ Спирмена (монотонная связь) и ξ Чаттерджи (любая
      зависимость, в том числе немонотонная: U-образная, пороговая); p пары — меньший из двух,
      с поправкой Бонферрони на два теста;
  (3) поправка на множественное сравнение по всем парам — Бенджамини — Хохберг (fdr — доля ложных
      находок, которую допускаем);
  (4) каждая находка проверяется на отложенной части: тот же тест, порог 0,05 / число находок,
      у ρ — тот же знак. Подтверждённая связь — кандидат в идею для проверки, не вывод;
  (5) плацебо: та же процедура на данных, где каждый столбец перемешан отдельно (связей нет по
      построению) — сколько «находок» даёт сам поиск.

Неподтверждённые находки и пары без связи тоже пишутся в результаты: это отрицательный результат
(правило 4). Пары, почти совпадающие на поиске (|ρ| ≥ 0,98), помечаются «одно и то же»: это два
названия одного показателя, а не открытие.

Параметры (--params): columns — столбцы (пусто — все числовые, не больше MAX_COLUMNS), holdout,
fdr, seed, placebo (сколько раз повторить плацебо), sheet.
"""

import json
import time
from datetime import UTC, datetime
from itertools import combinations

import numpy as np
import pandas as pd
from common import event, fmt, load_table, numeric, parse_args, results_dir, write_run
from scipy.stats import norm, rankdata, spearmanr

MAX_COLUMNS = 40  # пар — до 780
MIN_ROWS = 40  # на каждую часть — хотя бы 20
MIN_PAIR_ROWS = 10  # у пары в части меньше строк без пропусков — пара не считается
SAME = 0.98  # |ρ| не меньше — два названия одного показателя
CONFIRM_ALPHA = 0.05


def xi(x: np.ndarray, y: np.ndarray) -> float:
    """ξ Чаттерджи (2021): насколько y — функция от x; 0 — независимы, 1 — y определяется x.
    Ловит и немонотонные связи. Без повторов в y: ξ = 1 − 3·Σ|r_{i+1} − r_i| / (n² − 1)."""
    n = len(x)
    order = np.argsort(x, kind="stable")
    r = rankdata(y[order], method="max")
    l_ = n - rankdata(y[order], method="min") + 1
    denom = 2 * float(np.sum(l_ * (n - l_)))
    return 1 - n * float(np.sum(np.abs(np.diff(r)))) / denom if denom else 0.0


def xi_p(value: float, n: int) -> float:
    """Односторонний p для ξ при независимости: √n·ξ ≈ N(0, 2/5)."""
    return float(norm.sf(value * np.sqrt(n) / np.sqrt(0.4)))


def pair_test(a: np.ndarray, b: np.ndarray) -> dict[str, float] | None:
    ok = ~(np.isnan(a) | np.isnan(b))
    a, b = a[ok], b[ok]
    n = len(a)
    if n < MIN_PAIR_ROWS or np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    sp = spearmanr(a, b)
    rho, p_rho = float(sp.statistic), float(sp.pvalue)
    x = max(xi(a, b), xi(b, a))  # связь в любую сторону: y от x или x от y
    p_xi = min(1.0, 2 * xi_p(x, n))  # два направления — поправка Бонферрони
    return {"n": n, "rho": rho, "p_rho": p_rho, "xi": x, "p_xi": p_xi,
            "p": min(1.0, 2 * min(p_rho, p_xi))}


def bh(pvalues: list[float], q: float) -> list[bool]:
    """Бенджамини — Хохберг: какие гипотезы отвергаются при доле ложных находок q."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    cut = 0
    for k, i in enumerate(order, start=1):
        if pvalues[i] <= q * k / m:
            cut = k
    found = set(order[:cut])
    return [i in found for i in range(m)]


def scan(data: pd.DataFrame, pairs: list[tuple[str, str]], q: float) -> list[dict]:
    rows = []
    for a, b in pairs:
        t = pair_test(data[a].to_numpy(float), data[b].to_numpy(float))
        rows.append({"a": a, "b": b, **(t or {"n": int((data[a].notna() & data[b].notna()).sum())})})
    tested = [r for r in rows if "p" in r]
    for r, hit in zip(tested, bh([r["p"] for r in tested], q), strict=True):
        r["found"] = hit
    return rows


def name(r: dict) -> str:
    return f"{r['a']} — {r['b']}"


def shuffled(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    return pd.DataFrame({c: rng.permutation(data[c].to_numpy()) for c in data.columns})


def main() -> int:
    args = parse_args("Поиск связей (ρ Спирмена и ξ Чаттерджи, с подтверждением на отложенной части)")
    p = args.params
    seed, holdout, q = int(p.get("seed", 42)), float(p.get("holdout", 50)) / 100, float(p.get("fdr", 10)) / 100
    n_placebo = int(p.get("placebo", 5))
    t0, started = time.time(), datetime.now(UTC).isoformat()
    out = results_dir(args.results_root)
    df = load_table(args.data, p.get("sheet", ""))
    cols = list(p.get("columns") or [])
    if not cols:  # все числовые: больше половины значений — числа (или буквы рейтинга)
        cols = [c for c in df.columns if numeric(df, c).notna().sum() >= max(MIN_PAIR_ROWS, len(df) // 2)]
    cols = cols[:MAX_COLUMNS]
    data = pd.DataFrame({c: numeric(df, c) for c in cols})
    data = data.loc[:, data.nunique() > 1]
    if data.shape[1] < 2:
        raise SystemExit("Нужно хотя бы два числовых столбца с разными значениями")
    if len(data) < MIN_ROWS:
        raise SystemExit(f"Строк — {len(data)}, нужно хотя бы {MIN_ROWS}: иначе не на чем подтверждать")
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(data))
    n_conf = round(len(data) * holdout)
    find, confirm = data.iloc[idx[n_conf:]], data.iloc[idx[:n_conf]]
    pairs = list(combinations(data.columns, 2))

    event("progress", done=0, total=3 + n_placebo, label=f"поиск: {len(pairs)} пар на {len(find)} строках")
    rows = scan(find, pairs, q)
    for r in rows:
        r["same"] = bool("rho" in r and abs(r["rho"]) >= SAME)
    # почти-копия столбца (второй из пары «одно и то же») повторила бы все находки первого
    aliases = {r["b"] for r in rows if r["same"]}
    found = [r for r in rows if r.get("found") and not r["same"] and not {r["a"], r["b"]} & aliases]
    event("metric", name="найдено на части поиска", value=len(found))

    event("progress", done=1, total=3 + n_placebo, label=f"подтверждение: {len(found)} находок на {len(confirm)} строках")
    alpha = CONFIRM_ALPHA / max(1, len(found))
    for r in found:
        t = pair_test(confirm[r["a"]].to_numpy(float), confirm[r["b"]].to_numpy(float))
        r["confirm"] = t
        if t is None:
            r["confirmed"] = False
            continue
        by_rho = r["p_rho"] <= r["p_xi"]  # подтверждаем тем тестом, которым нашли
        same_sign = bool(np.sign(t["rho"]) == np.sign(r["rho"]))
        r["confirmed"] = (t["p_rho"] <= alpha and same_sign) if by_rho else t["p_xi"] <= alpha
        r["kind"] = "монотонная" if by_rho else "немонотонная"
    confirmed = [r for r in found if r["confirmed"]]
    event("metric", name="подтверждено на отложенной части", value=len(confirmed))

    placebo = []
    for i in range(n_placebo):
        event("progress", done=2 + i, total=3 + n_placebo, label=f"плацебо {i + 1} из {n_placebo}")
        fake = scan(shuffled(find, np.random.default_rng(seed + 1 + i)), pairs, q)
        placebo.append(sum(1 for r in fake if r.get("found")))
    event("metric", name="находок на перемешанных данных (среднее)", value=float(np.mean(placebo)) if placebo else 0)
    event("progress", done=3 + n_placebo, total=3 + n_placebo, label="готово")

    clean = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "confirm"}
             | ({"confirm": {k: round(v, 4) if isinstance(v, float) else v for k, v in r["confirm"].items()}}
                if r.get("confirm") else {}) for r in rows]
    (out / "results.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"columns": data.shape[1], "pairs": len(pairs), "rows_find": len(find), "rows_confirm": len(confirm),
               "found": len(found), "confirmed": len(confirmed), "same": sum(1 for r in rows if r["same"]),
               "placebo_found": placebo, "fdr": q, "holdout": holdout}
    top = sorted(confirmed, key=lambda r: -abs(r["confirm"]["rho"]))
    missed = sorted((r for r in found if not r["confirmed"]), key=lambda r: -abs(r["rho"]))
    report = {
        "kpis": [
            {"label": "Пар проверено", "value": str(len(pairs)), "note": f"{data.shape[1]} столбцов"},
            {"label": "Найдено на части поиска", "value": str(len(found)),
             "note": f"{len(find)} строк, доля ложных находок не больше {round(q * 100)} %"},
            {"label": "Подтверждено на отложенной части", "value": str(len(confirmed)),
             "note": f"{len(confirm)} строк, порог p ≤ {fmt(alpha)}"},
            {"label": "Находок на перемешанных данных", "value": fmt(float(np.mean(placebo))) if placebo else "—",
             "note": "в среднем за плацебо; связей там нет по построению"},
            *([{"label": "Почти одно и то же", "value": str(summary["same"]),
                "note": f"|ρ| ≥ {fmt(SAME)} — два названия одного показателя, второй в находки не берётся: "
                        + ", ".join(name(r) for r in rows if r["same"])[:300]}] if summary["same"] else []),
        ],
        "charts": [
            *([{
                "id": "confirmed", "kind": "bars", "unit": "ρ",
                "title": "Подтверждённые связи, ρ Спирмена на отложенной части",
                "subtitle": f"{len(confirmed)} из {len(found)} находок", "reference": {"value": 0, "label": "нет связи"},
                "categories": [name(r) for r in top[:20]],
                "series": [{"name": "ρ на отложенной части", "values": [r["confirm"]["rho"] for r in top[:20]]}],
                "interpretation": ("Каждая — кандидат в идею для проверки, не вывод: связь не говорит, что из чего "
                                   "следует, и может объясняться третьим показателем."),
            }] if top else []),
            # отрицательный результат — наравне с подтверждёнными (правило 4)
            *([{
                "id": "not_confirmed", "kind": "bars", "unit": "ρ",
                "title": "Находки, которые не подтвердились на отложенной части",
                "subtitle": "ρ Спирмена на части поиска", "reference": {"value": 0, "label": "нет связи"},
                "categories": [name(r) for r in missed[:20]],
                "series": [{"name": "ρ на части поиска", "values": [r["rho"] for r in missed[:20]]}],
                "interpretation": ("Связь была видна на одной половине строк и пропала на другой — скорее всего, "
                                   "случайность. Это тоже результат: брать её в идеи не стоит."),
            }] if missed else []),
        ],
    }
    write_run(args, out, "scan", started, t0, data,
              {"split": seed, "placebo": [seed + 1 + i for i in range(n_placebo)]}, summary, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
