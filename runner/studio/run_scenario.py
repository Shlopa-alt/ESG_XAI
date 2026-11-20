"""Расчёт сценария Студии на исполнителе (тот же порядок, что у методов runner/methods):

    python studio/run_scenario.py <каталог результатов> --scenario scenario.json
        --inputs inputs.json [--until <узел>] [--rows 100]

inputs.json — какие файлы читают узлы импорта: {"<узел>": {"path": "...", "sheet": ""}} (sha256
файлов исполнитель сверил до запуска). Пишет в каталог результатов:
  summary.json             — по каждому узлу: посчитан ли, ошибка, строк и столбцов, время;
  nodes/<узел>.json        — «Таблица» (первые строки) и «Статистика» по результату узла;
  files/<имя>.csv|.xlsx    — то, что сохранили узлы «Экспорт: Файл».
С --until считается только то, от чего зависит узел (предпросмотр в редакторе).
Ход — строками `@event {...}`, как у методов.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "methods")]

# после sys.path: common — из runner/methods, studio — из runner
import pandas as pd  # noqa: E402, I001
from common import LOCK, event, git_commit, load_table, sha256  # noqa: E402
from studio import engine, stats  # noqa: E402


def safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" ._")
    return cleaned[:80] or "результат"


def export(out: Path, node: dict[str, Any], df: pd.DataFrame) -> str:
    params = node.get("params") or {}
    fmt = params.get("format") or "csv"
    path = out / "files" / f"{safe_name(str(params.get('name') or node['id']))}.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "xlsx":
        df.to_excel(path, index=False)
    else:
        df.to_csv(path, index=False, encoding="utf-8-sig")
    return path.name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Расчёт сценария Студии")
    ap.add_argument("out")
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--until")
    ap.add_argument("--rows", type=int, default=stats.PREVIEW_ROWS)
    a = ap.parse_args(argv)
    out = Path(a.out)
    (out / "nodes").mkdir(parents=True, exist_ok=True)
    scenario = json.loads(Path(a.scenario).read_text(encoding="utf-8"))
    inputs: dict[str, dict[str, str]] = json.loads(Path(a.inputs).read_text(encoding="utf-8"))

    def load(node: dict[str, Any]) -> pd.DataFrame:
        src = inputs.get(node["id"])
        if not src:
            raise engine.ScenarioError(node["id"], "Не выбрана версия набора данных")
        return load_table(Path(src["path"]), src.get("sheet") or "")

    nodes = {n["id"]: n for n in scenario.get("nodes") or []}
    # для повтора расчёта (правило 3): код runner и окружение
    summary: dict[str, Any] = {"nodes": {}, "files": [], "runner_commit": git_commit(),
                               "env_lock_sha256": sha256(LOCK) if LOCK.is_file() else "",
                               "python": sys.version.split()[0]}

    def done(r: engine.NodeResult) -> None:
        info: dict[str, Any] = {"ok": r.frame is not None, "error": r.error, "seconds": r.seconds,
                                "skipped": r.skipped}
        if r.frame is not None:
            info.update(rows=int(len(r.frame)), cols=int(r.frame.shape[1]))
            view = {"table": stats.table(r.frame, a.rows), "statistics": stats.statistics(r.frame),
                    "quality": stats.quality(r.frame)}
            if a.until == r.node:  # предпросмотр: выборка для «Диаграммы» — только у выбранного узла
                view["sample"] = stats.sample(r.frame)
            (out / "nodes" / f"{r.node}.json").write_text(json.dumps(view, ensure_ascii=False),
                                                          encoding="utf-8")
            if nodes[r.node]["type"] == "export.file" and not a.until:
                summary["files"].append(export(out, nodes[r.node], r.frame))
        summary["nodes"][r.node] = info
        event("node", node=r.node, ok=info["ok"], error=r.error, rows=info.get("rows"))

    try:
        results = engine.run(scenario, load, until=a.until, on_node=done)
    except engine.ScenarioError as exc:
        summary["error"] = {"node": exc.node, "message": exc.message}
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        print(f"Сценарий не запущен: {exc.message}", file=sys.stderr)
        return 2
    failed = [n for n, r in results.items() if r.frame is None]
    summary["ok"] = not failed
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Узлов посчитано: {len(results) - len(failed)} из {len(results)}"
          + (f"; с ошибкой: {', '.join(failed)}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
