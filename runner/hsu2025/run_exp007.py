"""Полный повтор EXP-007 с фиксацией воспроизводимости (CLAUDE.md, правило 3).

    python run_exp007.py <каталог DS-04> <каталог результатов> [--seed 42] [--trials 100]

<каталог DS-04>/build/hsu_dataset.csv — срез (build_dataset.py из raw/ после fetch_mops.py).
В <каталог результатов>/<время>/ пишутся результаты частей и run.json: коммит runner,
sha256 среза, sha256 окружения (requirements.lock), seed и конфиг каждой части.
Части идут параллельно, у каждой — свои потоки, чтобы не делить ядра.
Ход печатается строками `@event {...}` — их показывает платформа при запуске из формы.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
THREADS = "3"

# Части расчёта: имя → аргументы скрипта (пути подставляются ниже)
PARTS = {
    "hsu_paper": ["replicate_hsu.py", "{data}", "{out}/hsu_paper.json", "--protocol", "paper",
                  "--trials", "{trials}", "--seed", "{seed}"],
    "hsu_honest": ["replicate_hsu.py", "{data}", "{out}/hsu_honest.json", "--protocol", "honest",
                   "--trials", "{trials}", "--seed", "{seed}"],
    "splits": ["robustness.py", "{data}", "{out}/splits.csv", "splits"],
    "placebo": ["robustness.py", "{data}", "{out}/placebo.csv", "placebo"],
    "lab_honest": ["lab_method.py", "{data}", "{out}/lab_honest.json", "--protocol", "honest",
                   "--trials", "60", "--seed", "{seed}", "--shap"],
}


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


def main(ds_dir: Path, results_root: Path, seed: int = 42, trials: int = 100) -> int:
    data = ds_dir / "build" / "hsu_dataset.csv"
    out = results_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    lock = HERE / "requirements.lock"
    manifest = ds_dir / "raw" / "manifest.json"
    run = {
        "experiment": "EXP-007",
        "started_at": datetime.now(UTC).isoformat(),
        "runner_commit": git_commit(),
        "dataset": {"code": "DS-04", "path": str(data), "sha256": sha256(data),
                    "raw_manifest_sha256": sha256(manifest) if manifest.exists() else ""},
        "env_lock_sha256": sha256(lock),
        "python": sys.version.split()[0],
        "seeds": {"split": seed, "optuna_tpe": 0, "repeats": "0..29"},
        "parts": {},
    }
    env = {**os.environ, "OMP_NUM_THREADS": THREADS, "MKL_NUM_THREADS": THREADS,
           "PYTHONIOENCODING": "utf-8"}
    procs = {}
    for name, argv in PARTS.items():
        args = [a.format(data=data, out=out, seed=seed, trials=trials) for a in argv]
        log = (out / f"{name}.log").open("w", encoding="utf-8")
        procs[name] = (subprocess.Popen([PY, *args], cwd=HERE, env=env, stdout=log,
                                        stderr=subprocess.STDOUT), log, args, time.time())
        print(f"запущено: {name}", flush=True)
    event("progress", done=0, total=len(procs), label="части запущены")
    for i, (name, (p, log, args, t0)) in enumerate(procs.items(), start=1):
        code = p.wait()
        log.close()
        run["parts"][name] = {"args": args, "exit_code": code, "seconds": round(time.time() - t0)}
        print(f"готово: {name} — код {code}, {round((time.time() - t0) / 60)} мин", flush=True)
        event("progress", done=i, total=len(procs), label=f"{name}: код {code}")
    run["finished_at"] = datetime.now(UTC).isoformat()
    (out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    if all(v["exit_code"] == 0 for v in run["parts"].values()):
        # ключевые цифры и графики для страницы эксперимента — в run.json["report"]
        subprocess.run([PY, "make_report.py", str(out)], cwd=HERE, env=env, check=False)
    print(f"ИТОГ: {out}", flush=True)
    return 0 if all(v["exit_code"] == 0 for v in run["parts"].values()) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="EXP-007: повтор Hsu et al. (2025)")
    ap.add_argument("ds_dir", type=Path, help="каталог DS-04 (в нём build/hsu_dataset.csv)")
    ap.add_argument("results_root", type=Path, help="каталог результатов")
    ap.add_argument("--seed", type=int, default=42, help="разбиение и подбор")
    ap.add_argument("--trials", type=int, default=100, help="испытаний Optuna в протоколах Hsu")
    a = ap.parse_args()
    sys.exit(main(a.ds_dir, a.results_root, a.seed, a.trials))
