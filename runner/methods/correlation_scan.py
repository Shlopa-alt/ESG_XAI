"""Метод «Поиск связей»: все пары столбцов среза — монотонные и немонотонные связи, с подтверждением.

Правка по совещанию «Экономика — правки и идеи по сайту»: «новые корреляции с проверкой всего».
Найти связь в куче столбцов легко — трудно не найти случайную. Поэтому:

  (1) строки делятся случайно (seed) на две части: поиск и подтверждение (holdout — доля второй);
      у панели (компания × год) — по группам (group): одна компания целиком в одной части, иначе
      подтверждение не независимо;
  (2) на части поиска для каждой пары — ρ Спирмена (монотонная связь) и ξ Чаттерджи (любая
      зависимость, в том числе немонотонная: U-образная, пороговая); p пары — меньший из двух,
      с поправкой Бонферрони на два теста. Асимптотика p для ξ выведена для непрерывных данных:
      на столбцах с повторами (рейтинги, счётчики, да/нет) она завышает значимость, поэтому там
      считается только ρ (DISCRETE);
  (3) поправка на множественное сравнение по всем парам — Бенджамини — Хохберг (fdr — доля ложных
      находок, которую допускаем);
  (4) каждая находка проверяется на отложенной части: тот же тест, порог 0,05 / число находок,
      у ρ — тот же знак. Подтверждённая связь — кандидат в идею для проверки, не вывод;
  (5) плацебо: этап поиска на данных, где каждый столбец перемешан отдельно (связей нет по
      построению) — сколько ложных находок даёт сам поиск; подтверждение на нём не прогоняется.

Неподтверждённые находки и пары без связи тоже пишутся в результаты: это отрицательный результат
(правило 4), с причиной: не подтвердилась (скорее всего, случайность) или на отложенной части не
хватило строк. Пары, почти совпадающие на поиске (|ρ| ≥ 0,98), помечаются «почти совпадают» —
возможно, это один показатель (или соседние годы одного); связи второго столбца пары (в порядке
файла) не ищутся, он перечислен в итогах (excluded_columns), сами пары — в same_pairs. Немонотонные дубли (y = f(x) при |ρ| < 0,98) псевдонимами не считаются и идут в находки.

Параметры (--params): columns — столбцы (пусто — все числовые; больше MAX_COLUMNS — отказ, а у
«все числовые» — первые MAX_COLUMNS, остальные перечислены в итогах), group — столбец-группа
(необязательно), holdout, fdr, seed, placebo (сколько раз повторить плацебо), sheet.
Действующие значения всех параметров пишутся в summary.params.
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
MIN_PART = 20  # строк в каждой части; меньше — асимптотика грубая и подтверждать не на чем
MIN_ROWS = 2 * MIN_PART
MIN_PAIR_ROWS = MIN_PART  # у пары в части меньше строк без пропусков — пара не считается
SAME = 0.98  # |ρ| не меньше — два названия одного показателя
CONFIRM_ALPHA = 0.05
DISCRETE = (20, 0.2)  # меньше max(20, 20 % строк) разных значений — столбец с повторами: без ξ


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
    few = max(DISCRETE[0], DISCRETE[1] * n)
    if len(np.unique(a)) < few or len(np.unique(b)) < few:
        # повторы значений: асимптотика ξ завышает значимость — пара проверяется только по ρ
        return {"n": n, "rho": rho, "p_rho": p_rho, "xi": x, "p_xi": 1.0, "xi_used": False,
                "p": p_rho}
    p_xi = min(1.0, 2 * xi_p(x, n))  # два направления — поправка Бонферрони
    return {"n": n, "rho": rho, "p_rho": p_rho, "xi": x, "p_xi": p_xi, "xi_used": True,
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


def split(data: pd.DataFrame, groups: pd.Series | None, holdout: float,
          rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Поиск и подтверждение: по строкам или, с group, по группам — одна группа целиком в одной части."""
    if groups is None:
        idx = rng.permutation(len(data))
        n_conf = round(len(data) * holdout)
        return data.iloc[idx[n_conf:]], data.iloc[idx[:n_conf]]
    names = rng.permutation(np.array(sorted(groups.dropna().astype(str).unique()), dtype=object))
    n_conf = round(len(names) * holdout)
    conf = set(names[:n_conf])
    key = groups.astype(str)
    in_conf = key.isin(conf) & groups.notna()
    return data[~in_conf & groups.notna()], data[in_conf]


def shuffled(data: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    return pd.DataFrame({c: rng.permutation(data[c].to_numpy()) for c in data.columns})


def main() -> int:
    args = parse_args("Поиск связей (ρ Спирмена и ξ Чаттерджи, с подтверждением на отложенной части)")
    p = args.params
    seed, holdout, q = int(p.get("seed", 42)), float(p.get("holdout", 50)) / 100, float(p.get("fdr", 10)) / 100
    n_placebo = int(p.get("placebo", 5))
    group = str(p.get("group") or "")
    t0, started = time.time(), datetime.now(UTC).isoformat()
    out = results_dir(args.results_root)
    df = load_table(args.data, p.get("sheet", ""))
    asked = list(p.get("columns") or [])
    if len(asked) > MAX_COLUMNS:
        raise SystemExit(f"Столбцов — {len(asked)}, не больше {MAX_COLUMNS}: иначе пар слишком много")
    if group and group not in df.columns:
        raise SystemExit(f"В срезе нет столбца-группы «{group}»")
    cols = asked or [c for c in df.columns if c != group
                     and numeric(df, c).notna().sum() >= max(2, len(df) // 2)]
    skipped = cols[MAX_COLUMNS:]  # «все числовые» — первые MAX_COLUMNS в порядке файла
    cols = [c for c in cols[:MAX_COLUMNS] if c != group]
    data = pd.DataFrame({c: numeric(df, c) for c in cols})
    data = data.loc[:, data.nunique() > 1]
    if data.shape[1] < 2:
        raise SystemExit("Нужно хотя бы два числовых столбца с разными значениями")
    if len(data) < MIN_ROWS:
        raise SystemExit(f"Строк — {len(data)}, нужно хотя бы {MIN_ROWS}: иначе не на чем подтверждать")
    rng = np.random.default_rng(seed)
    find, confirm = split(data, df[group] if group else None, holdout, rng)
    if min(len(find), len(confirm)) < MIN_PART:
        raise SystemExit(f"В части поиска {len(find)} строк, в отложенной — {len(confirm)}: нужно в каждой "
                         f"хотя бы {MIN_PART}. Измените долю на подтверждение или возьмите больше данных")
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
        by_rho = r["p_rho"] <= r["p_xi"]  # подтверждаем тем тестом, которым нашли
        r["kind"] = "монотонная" if by_rho else "немонотонная"
        t = pair_test(confirm[r["a"]].to_numpy(float), confirm[r["b"]].to_numpy(float))
        r["confirm"] = t
        if t is None:  # на отложенной части мало строк без пропусков — не на чем проверить
            r["confirmed"], r["reason"] = False, "no_data"
            continue
        same_sign = bool(np.sign(t["rho"]) == np.sign(r["rho"]))
        r["confirmed"] = (t["p_rho"] <= alpha and same_sign) if by_rho else t["p_xi"] <= alpha
        r["reason"] = "" if r["confirmed"] else "not_confirmed"
    confirmed = [r for r in found if r["confirmed"]]
    event("metric", name="подтверждено на отложенной части", value=len(confirmed))

    placebo = []
    for i in range(n_placebo):
        event("progress", done=2 + i, total=3 + n_placebo, label=f"плацебо {i + 1} из {n_placebo}")
        fake = scan(shuffled(find, np.random.default_rng([seed, i + 1])), pairs, q)
        placebo.append(sum(1 for r in fake if r.get("found")))
    event("metric", name="ложных находок поиска на перемешанных данных (среднее)",
          value=float(np.mean(placebo)) if placebo else 0)
    event("progress", done=3 + n_placebo, total=3 + n_placebo, label="готово")

    clean = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "confirm"}
             | ({"confirm": {k: round(v, 4) if isinstance(v, float) else v for k, v in r["confirm"].items()}}
                if r.get("confirm") else {}) for r in rows]
    (out / "results.json").write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    def brief(r: dict) -> dict:
        c = r.get("confirm") or {}
        return {"a": r["a"], "b": r["b"], "kind": r.get("kind", ""), "rho": round(r["rho"], 3),
                "xi": round(r["xi"], 3), "rho_confirm": round(c["rho"], 3) if c else None,
                "xi_confirm": round(c["xi"], 3) if c else None, "n": r["n"],
                "reason": r.get("reason", "")}

    missed_all = [r for r in found if not r["confirmed"]]

    summary = {"columns": data.shape[1], "pairs": len(pairs), "rows_find": len(find), "rows_confirm": len(confirm),
               "found": len(found), "confirmed": len(confirmed), "same": sum(1 for r in rows if r["same"]),
               "placebo_found": placebo, "fdr": q, "holdout": holdout,
               "columns_used": list(data.columns), "columns_skipped": skipped,
               "without_xi": sum(1 for r in rows if "xi_used" in r and not r["xi_used"]),
               # действующие значения: при запуске без платформы умолчания иначе не видны
               "params": {"columns": asked, "group": group, "holdout": round(holdout * 100),
                          "fdr": round(q * 100), "placebo": n_placebo, "seed": seed,
                          "sheet": p.get("sheet", "")},
               # для страницы расчёта: «проверить сетями» и «сделать идеей» по каждой связи
               "links": [brief(r) for r in confirmed][:50], "links_total": len(confirmed),
               "not_confirmed": [brief(r) for r in missed_all][:50], "not_confirmed_total": len(missed_all),
               "same_pairs": [{"a": r["a"], "b": r["b"], "rho": round(r["rho"], 3)} for r in rows if r["same"]],
               "excluded_columns": sorted(aliases)}
    top = sorted(confirmed, key=lambda r: -abs(r["confirm"]["rho"]))
    missed = sorted(missed_all, key=lambda r: -abs(r["rho"] if r["kind"] == "монотонная" else r["xi"]))
    report = {
        "kpis": [
            {"label": "Пар проверено", "value": str(len(pairs)), "note": f"{data.shape[1]} столбцов"},
            {"label": "Найдено на части поиска", "value": str(len(found)),
             "note": f"{len(find)} строк, доля ложных находок не больше {round(q * 100)} %"},
            {"label": "Подтверждено на отложенной части", "value": str(len(confirmed)),
             "note": f"{len(confirm)} строк, порог p ≤ {fmt(alpha)}"},
            {"label": "Ложных находок поиска на перемешанных данных",
             "value": fmt(float(np.mean(placebo))) if placebo else "—",
             "note": "в среднем за повторы, только этап поиска; связей там нет по построению"},
            *([{"label": "Столбцов не вошло", "value": str(len(skipped)),
                "note": f"берутся первые {MAX_COLUMNS} числовых в порядке файла; не вошли: "
                        + ", ".join(map(str, skipped))[:300]}] if skipped else []),
            *([{"label": "Пар только по ρ", "value": str(summary["without_xi"]),
                "note": "столбцы с повторами значений (рейтинги, счётчики, да/нет): немонотонная связь "
                        "там не ищется — оценка её значимости была бы завышена"}] if summary["without_xi"] else []),
            *([{"label": "Почти совпадают", "value": str(summary["same"]),
                "note": f"|ρ| ≥ {fmt(SAME)} — возможно, один показатель; связи второго столбца пары не "
                        "искались: " + ", ".join(name(r) for r in rows if r["same"])[:300]}]
              if summary["same"] else []),
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
                "id": "not_confirmed", "kind": "bars", "unit": "",
                "title": "Находки, которые не подтвердились на отложенной части",
                "subtitle": "сила связи на части поиска: ρ Спирмена у монотонных, ξ Чаттерджи у немонотонных",
                "reference": {"value": 0, "label": "нет связи"},
                "categories": [f"{name(r)} ({'ρ' if r['kind'] == 'монотонная' else 'ξ'})" for r in missed[:20]],
                "series": [{"name": "на части поиска",
                            "values": [r["rho"] if r["kind"] == "монотонная" else r["xi"] for r in missed[:20]]}],
                "interpretation": ("Связь была видна на части поиска и не подтвердилась на отложенной — чаще всего "
                                   "это случайность"
                                   + (f"; у {sum(1 for r in missed_all if r['reason'] == 'no_data')} на отложенной "
                                      "части не хватило строк, чтобы проверить"
                                      if any(r["reason"] == "no_data" for r in missed_all) else "")
                                   + ". Это тоже результат: брать такие связи в идеи не стоит."),
            }] if missed else []),
        ],
    }
    write_run(args, out, "scan", started, t0, data,
              {"split": seed, "placebo": [[seed, i + 1] for i in range(n_placebo)], "group": group},
              summary, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
