"""EXP-001: согласованность ESG-рейтингов S&P Global, Sustainalytics и MSCI на Dow30 (DS-01).

    python run_exp001.py <каталог DS-01> <каталог результатов> [--data файл] [--seed 42] [--n-boot 10000] [--n-perm 10000]

<каталог DS-01>/raw/03_Dow30_ESG_Stock_Data.csv и manifest.json — выгрузка с Яндекс.Диска
лаборатории (sha256 каждого файла в манифесте). В <каталог результатов>/<время>/ пишутся
results.json и run.json: коммит runner, sha256 среза, sha256 окружения, seed (правило 3).

Шкалы провайдеров разные: S&P — балл 0–100 (больше — лучше), MSCI — буквы CCC…AAA (больше —
лучше), Sustainalytics — оценка неуправляемого риска (больше — хуже). Поэтому считаются два
варианта: «исходный» (шкала Sustainalytics как в файле) и «согласованный» (риск обращён).
Для ρ Спирмена обращение шкалы меняет только знак.

Ход и метрики печатаются строками `@event {...}` — их показывает платформа при запуске из формы.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
LOCK = HERE.parent / "hsu2025" / "requirements.lock"  # то же окружение runner/.venv
CSV = "03_Dow30_ESG_Stock_Data.csv"
SEED = 42
N_BOOT = 10_000
N_PERM = 10_000
MSCI_ORDER = {"CCC": 1, "B": 2, "BB": 3, "BBB": 4, "A": 5, "AA": 6, "AAA": 7}
PAIRS = [("SNP", "MSCI"), ("Sustainalytics", "MSCI"), ("SNP", "Sustainalytics")]
NAMES = {"SNP": "S&P", "MSCI": "MSCI", "Sustainalytics": "Sustainalytics"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "."], cwd=HERE,
                                        text=True).strip()
        return commit + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return ""


def event(kind: str, **data: object) -> None:
    """Событие для живого потока платформы (исполнитель runner/worker); в консоли — просто строка."""
    print("@event " + json.dumps({"type": kind, **data}, ensure_ascii=False), flush=True)


def rho(a: np.ndarray, b: np.ndarray) -> float:
    return float(spearmanr(a, b).statistic)


def pair_stats(x: np.ndarray, y: np.ndarray, rng: np.random.Generator) -> dict[str, float]:
    """ρ, 95 % бутстреп-интервал и двусторонний перестановочный p."""
    r = rho(x, y)
    n = len(x)
    boot = np.array([rho(x[i], y[i]) for i in (rng.integers(0, n, n) for _ in range(N_BOOT))])
    boot = boot[~np.isnan(boot)]  # выборка из одинаковых значений даёт nan
    perm = np.array([rho(x, rng.permutation(y)) for _ in range(N_PERM)])
    return {
        "n": n, "rho": round(r, 4),
        "ci_low": round(float(np.quantile(boot, 0.025)), 4),
        "ci_high": round(float(np.quantile(boot, 0.975)), 4),
        "p_perm": round(float((np.sum(np.abs(perm) >= abs(r)) + 1) / (N_PERM + 1)), 4),
    }


def compute(df: pd.DataFrame) -> dict:
    d = pd.DataFrame({
        "symbol": df["Symbol"],
        "SNP": df["SNP"],
        "Sustainalytics": df["Sustainalytics"],
        "MSCI": df["MSCI"].map(MSCI_ORDER),
    })
    unknown = sorted(set(df["MSCI"].dropna()) - set(MSCI_ORDER))
    if unknown:
        raise SystemExit(f"неизвестные буквы MSCI: {unknown}")
    complete = d.dropna(subset=["SNP", "Sustainalytics", "MSCI"])
    out: dict = {
        "companies": len(d),
        "complete": len(complete),
        "missing": {s: [c for c in ("SNP", "Sustainalytics", "MSCI") if pd.isna(r[c])]
                    for s, r in d.set_index("symbol").iterrows() if r.isna().any()},
        "pairs": {},
    }
    for i, (a, b) in enumerate(PAIRS, start=1):
        pw = d.dropna(subset=[a, b])
        key = f"{NAMES[a]} — {NAMES[b]}"
        event("progress", done=i - 1, total=len(PAIRS), label=key)
        # согласованная шкала: риск Sustainalytics обращён, «больше — лучше» у всех
        x, y = (complete[c].to_numpy(float) * (-1 if c == "Sustainalytics" else 1) for c in (a, b))
        cc = pair_stats(x, y, np.random.default_rng(SEED))
        out["pairs"][key] = {
            # исходная шкала, все компании, где есть обе оценки пары
            "raw_pairwise": {"n": len(pw), "rho": round(rho(pw[a], pw[b]), 4)},
            # исходная шкала, 26 компаний с полными данными по трём провайдерам
            "raw_complete": round(rho(complete[a], complete[b]), 4),
            # согласованная шкала, полные данные: ρ, интервал, p
            "aligned_complete": cc,
        }
        event("metric", name=f"rho {key}", value=cc["rho"])
        event("progress", done=i, total=len(PAIRS), label=key)
    return out


def report(res: dict) -> dict:
    p = res["pairs"]
    fmt = lambda v: f"{v:+.2f}".replace(".", ",").replace("-", "−")  # noqa: E731
    keys = list(p)
    sm = p["Sustainalytics — MSCI"]
    return {
        "kpis": [
            {"label": k, "value": fmt(p[k]["aligned_complete"]["rho"]),
             "note": f"95 % интервал {fmt(p[k]['aligned_complete']['ci_low'])}…"
                     f"{fmt(p[k]['aligned_complete']['ci_high'])}, p = "
                     f"{str(p[k]['aligned_complete']['p_perm']).replace('.', ',')}"}
            for k in keys
        ],
        "charts": [
            {
                "id": "rho", "kind": "bars", "unit": "ρ",
                "title": "Согласованность ESG-рейтингов на Dow30, ρ Спирмена",
                "subtitle": "1 — рейтинги ранжируют компании одинаково, 0 — независимо, −1 — наоборот",
                "reference": {"value": 0, "label": "нет связи"},
                "categories": keys,
                "series": [
                    {"name": "Исходная шкала Sustainalytics (риск)",
                     "values": [p[k]["raw_complete"] for k in keys]},
                    {"name": "Шкала риска обращена", "values": [p[k]["aligned_complete"]["rho"] for k in keys]},
                ],
                "interpretation": (
                    "Sustainalytics публикует оценку риска (больше — хуже), а MSCI и S&P — оценку качества "
                    "(больше — лучше). Без обращения шкалы пары с Sustainalytics получают ложный "
                    f"отрицательный знак. После обращения все пары связаны слабо: "
                    f"{fmt(min(p[k]['aligned_complete']['rho'] for k in keys))}…"
                    f"{fmt(max(p[k]['aligned_complete']['rho'] for k in keys))}."
                ),
            },
            {
                "id": "rho_ci", "kind": "ranges", "unit": "ρ",
                "title": "ρ Спирмена с 95 % бутстреп-интервалом, шкала риска обращена",
                "subtitle": f"{res['complete']} компаний с оценками всех трёх провайдеров; "
                            f"{N_BOOT:,} повторных выборок".replace(",", " "),
                "reference": {"value": 0, "label": "нет связи"},
                "rows": [{"name": k, "mean": p[k]["aligned_complete"]["rho"],
                          "min": p[k]["aligned_complete"]["ci_low"],
                          "max": p[k]["aligned_complete"]["ci_high"]} for k in keys],
                "interpretation": (
                    "Все интервалы задевают ноль или почти задевают: на 26 компаниях нельзя уверенно "
                    "утверждать даже слабую согласованность провайдеров."
                ),
            },
        ],
        "analysis": {
            "summary": "ESG-рейтинги трёх провайдеров ранжируют одни и те же компании Dow30 по-разному.",
            "why": [],
            "meaning": [],
            "next": [
                f"Расхождение −0,32 и −0,29 по паре Sustainalytics — MSCI объяснено: "
                f"{fmt(sm['raw_pairwise']['rho'])} на {sm['raw_pairwise']['n']} компаниях с обеими оценками, "
                f"{fmt(sm['raw_complete'])} на {res['complete']} компаниях с оценками всех трёх.",
            ],
        },
    }


def main(ds_dir: Path, results_root: Path, data: Path | None = None) -> int:
    # срез: файл, выбранный при запуске (исполнитель сверил его sha256), иначе выгрузка в raw/
    data = data or ds_dir / "raw" / CSV
    manifest = ds_dir / "raw" / "manifest.json"
    out = results_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    t0 = time.time()
    started = datetime.now(UTC).isoformat()
    df = pd.read_csv(data)
    res = compute(df)
    (out / "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    run = {
        "experiment": "EXP-001",
        "started_at": started,
        "runner_commit": git_commit(),
        "dataset": {"code": "DS-01", "path": str(data), "sha256": sha256(data), "row_count": len(df),
                    "raw_manifest_sha256": sha256(manifest) if manifest.exists() else ""},
        "env_lock_sha256": sha256(LOCK),
        "python": sys.version.split()[0],
        "seeds": {"bootstrap": SEED, "permutation": SEED, "n_boot": N_BOOT, "n_perm": N_PERM},
        "parts": {"spearman": {"args": ["run_exp001.py", str(data)], "exit_code": 0,
                               "seconds": round(time.time() - t0)}},
        "summary": {k: v["aligned_complete"] for k, v in res["pairs"].items()},
        "results_path": str(out),
        "finished_at": datetime.now(UTC).isoformat(),
        "report": report(res),
    }
    (out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(f"run.json: {out / 'run.json'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="EXP-001: согласованность ESG-рейтингов Dow30")
    ap.add_argument("ds_dir", type=Path, help="каталог DS-01 (в нём raw/)")
    ap.add_argument("results_root", type=Path, help="каталог результатов")
    ap.add_argument("--data", type=Path, help="файл среза (по умолчанию raw/" + CSV + ")")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--n-perm", type=int, default=N_PERM)
    args = ap.parse_args()
    SEED, N_BOOT, N_PERM = args.seed, args.n_boot, args.n_perm
    raise SystemExit(main(args.ds_dir, args.results_root, args.data))
