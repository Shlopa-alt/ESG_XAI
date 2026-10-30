"""Полный повтор EXP-007 с фиксацией воспроизводимости (CLAUDE.md, правило 3).

    python run_exp007.py <каталог DS-04> <каталог результатов>

<каталог DS-04>/build/hsu_dataset.csv — срез (build_dataset.py из raw/ после fetch_mops.py).
В <каталог результатов>/<время>/ пишутся результаты частей и run.json: коммит runner,
sha256 среза, sha256 окружения (requirements.lock), seed и конфиг каждой части.
Части идут параллельно, у каждой — свои потоки, чтобы не делить ядра.
"""

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
                  "--trials", "100", "--seed", "42"],
    "hsu_honest": ["replicate_hsu.py", "{data}", "{out}/hsu_honest.json", "--protocol", "honest",
                   "--trials", "100", "--seed", "42"],
    "splits": ["robustness.py", "{data}", "{out}/splits.csv", "splits"],
    "placebo": ["robustness.py", "{data}", "{out}/placebo.csv", "placebo"],
    "lab_honest": ["lab_method.py", "{data}", "{out}/lab_honest.json", "--protocol", "honest",
                   "--trials", "60", "--seed", "42", "--shap"],
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


def main(ds_dir: Path, results_root: Path) -> int:
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
        "seeds": {"split": 42, "optuna_tpe": 0, "repeats": "0..29"},
        "parts": {},
    }
    env = {**os.environ, "OMP_NUM_THREADS": THREADS, "MKL_NUM_THREADS": THREADS,
           "PYTHONIOENCODING": "utf-8"}
    procs = {}
    for name, argv in PARTS.items():
        args = [a.format(data=data, out=out) for a in argv]
        log = (out / f"{name}.log").open("w", encoding="utf-8")
        procs[name] = (subprocess.Popen([PY, *args], cwd=HERE, env=env, stdout=log,
                                        stderr=subprocess.STDOUT), log, args, time.time())
        print(f"запущено: {name}", flush=True)
    for name, (p, log, args, t0) in procs.items():
        code = p.wait()
        log.close()
        run["parts"][name] = {"args": args, "exit_code": code, "seconds": round(time.time() - t0)}
        print(f"готово: {name} — код {code}, {round((time.time() - t0) / 60)} мин", flush=True)
    run["finished_at"] = datetime.now(UTC).isoformat()
    (out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ИТОГ: {out}", flush=True)
    return 0 if all(v["exit_code"] == 0 for v in run["parts"].values()) else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
