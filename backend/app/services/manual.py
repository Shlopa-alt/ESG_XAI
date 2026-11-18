"""Ручной режим (п. 9–10 фидбека): в любой момент взять работу в свои руки — архив с ноутбуком Jupyter.

Архив расчёта: ноутбук, файл среза данных (если человеку видны файлы датасета — правило 6), код
метода из runner/ (тот же, что считал исполнитель; у метода из статьи — записанный в платформе код со
сверкой sha256) и то, что записала платформа: параметры, seed, коммит, итоги. Ноутбук проверяет
sha256 данных, повторяет расчёт той же командой, что исполнитель, сверяет итоги с платформой и
оставляет место для своего кода. Архив версии данных — то же без расчёта: загрузить и смотреть.

Повтор вне репозитория — не запуск реестра: коммит runner у него пустой, и платформа такой run.json
в реестр не возьмёт (правило 3). Чтобы результат попал в реестр, расчёт повторяют в клоне
репозитория на нужном коммите и загружают командой `esg upload-run` (cli/README.md).
"""

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from pprint import pformat
from typing import Any

from app.config import Settings
from app.models import Dataset, DatasetSnapshot, Experiment, Run
from app.services.data_files import EXCEL, to_container
from app.services.run_templates import Template

SKIP = ("test_", "__pycache__")
MAX_DATA_MB = 200  # больше — в архив не кладём: файл берут командой esg download


def _md(*lines: str) -> dict[str, Any]:
    return {"cell_type": "markdown", "metadata": {}, "source": "\n".join(lines)}


def _code(*lines: str) -> dict[str, Any]:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": "\n".join(lines)}


def notebook(cells: list[dict[str, Any]]) -> str:
    nb = {"cells": cells, "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    return json.dumps(nb, ensure_ascii=False, indent=1)


def repo_commit(settings: Settings) -> str:
    """Коммит рабочей копии, из которой взят код методов (без git: читаем .git)."""
    git = Path(settings.repo_dir) / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        if (git / ref).is_file():
            return (git / ref).read_text(encoding="utf-8").strip()
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split()[0]
    except OSError:
        pass
    return ""


def _runner_files(settings: Settings, workdir: str) -> dict[str, bytes]:
    """Код каталога метода и общий модуль methods/common.py, без тестов; окружение — requirements.lock."""
    root = Path(settings.repo_dir) / "runner"
    out: dict[str, bytes] = {}
    for rel in {workdir, "methods"}:
        d = root / rel
        if d.is_dir():
            for f in sorted(d.glob("*.py")):
                if not f.name.startswith(SKIP):
                    out[f"runner/{rel}/{f.name}"] = f.read_bytes()
    lock = root / "hsu2025" / "requirements.lock"
    if lock.is_file():
        out["runner/hsu2025/requirements.lock"] = lock.read_bytes()
    return out


def _data(settings: Settings, snap: DatasetSnapshot, ds: Dataset, can_see: bool) -> tuple[str, Path | None, str]:
    """Путь файла среза в архиве, сам файл и почему его нет."""
    path = to_container(settings, snap.storage_path) if snap.storage_path else None
    name = Path(snap.storage_path.replace("\\", "/")).name if snap.storage_path else "data.csv"
    rel = f"data/{ds.code}/{snap.version}/{name}"
    if not can_see:
        return rel, None, "данные под NDA: файл — только допущенным (правило 6)"
    if path is None or not path.is_file():
        return rel, None, "файла среза нет на сервере"
    if path.stat().st_size > MAX_DATA_MB * 2**20:
        return rel, None, f"файл больше {MAX_DATA_MB} МБ — возьмите его командой esg download {snap.id}"
    return rel, path, ""


def _load_cells(rel: str, sha: str, sheet: str) -> list[dict[str, Any]]:
    excel = rel.lower().endswith(EXCEL)
    return [
        _md("## Данные", "Файл среза лежит рядом с ноутбуком. Сначала — тот ли это файл, что записан в платформе "
            "(sha256): иначе расчёт уже не тот."),
        _code("import hashlib, json, subprocess, sys",
              "from pathlib import Path",
              "import pandas as pd",
              "",
              "HERE = Path.cwd()",
              f"DATA = HERE / {rel!r}",
              f"SHA256 = {sha!r}  # записано в платформе",
              "if not DATA.is_file():",
              "    raise SystemExit(f'Нет файла данных {DATA} — см. README.txt')",
              "actual = hashlib.sha256(DATA.read_bytes()).hexdigest()",
              "print('sha256 совпадает' if actual == SHA256 else f'ВНИМАНИЕ: sha256 другой: {actual}')"),
        _code(*([f"df = pd.read_excel(DATA, sheet_name={sheet or 0!r})"] if excel
                else ["df = pd.read_csv(DATA, sep=None, engine='python')"]),
              "print(df.shape)",
              "df.head(20)"),
        _code("df.describe(include='all').T"),
    ]


def _manual_cells(template: str) -> list[dict[str, Any]]:
    """С чего начать свою работу — по методу."""
    hints = {
        "correlation-scan": ["from scipy.stats import spearmanr",
                             "num = df.select_dtypes('number')",
                             "num.corr(method='spearman').round(2)"],
        "rank-agreement": ["num = df.select_dtypes('number')",
                           "num.corr(method='spearman').round(2)"],
        "predictive-check": ["from sklearn.linear_model import RidgeCV",
                             "from sklearn.model_selection import cross_val_score",
                             "target, features = PARAMS.get('target'), PARAMS.get('features') or []",
                             "X, y = df[features].apply(pd.to_numeric, errors='coerce'), pd.to_numeric(df[target], errors='coerce')",
                             "ok = X.notna().all(axis=1) & y.notna()",
                             "cross_val_score(RidgeCV(), X[ok], y[ok], cv=5, scoring='r2')"],
    }
    lines = hints.get(template, ["# ваш код: df — таблица, PARAMS — параметры расчёта"])
    return [
        _md("## Дальше — вручную",
            "Здесь начинается ваша работа: меняйте параметры, пробуйте другие модели, стройте графики. "
            "Код метода — в папке `runner/`, его можно читать и импортировать."),
        _code(*lines),
    ]


def _readme(title: str, files: list[str], missing: str, run: bool = True) -> str:
    env = (["  2. Окружение: Python 3.11+ и пакеты из runner/hsu2025/requirements.lock",
            "       python -m pip install -r runner/hsu2025/requirements.lock jupyter",
            "     (для перцептрона и трансформера нужен torch — он в том же списке)."] if run
           else ["  2. Окружение: Python 3.11+ и пакеты для таблиц:",
                 "       python -m pip install pandas openpyxl jupyter"])
    return "\n".join([
        title, "=" * len(title), "",
        "Как открыть:",
        "  1. Распакуйте архив в отдельную папку.",
        *env,
        "  3. В этой папке: jupyter notebook — и откройте ноутбук.",
        "",
        "Что внутри:", *[f"  {f}" for f in files], "",
        *([f"Данных в архиве нет: {missing}.", ""] if missing else []),
        *(["Расчёт, повторённый здесь, в реестр платформы сам не попадёт: у него нет коммита репозитория",
           "(правило 3). Чтобы результат вошёл в реестр — повторите в клоне репозитория и загрузите",
           "командой esg upload-run (cli/README.md в репозитории)."] if run else []),
    ])


def _zip(files: dict[str, bytes], data: tuple[str, Path | None]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
        rel, path = data
        if path is not None:
            z.write(path, rel)
    return buf.getvalue()


def run_bundle(settings: Settings, run: Run, exp: Experiment, t: Template | None, snap: DatasetSnapshot,
               ds: Dataset, can_see: bool, author: str) -> tuple[str, bytes]:
    """Архив «взять расчёт в свои руки». Возвращает имя файла и содержимое."""
    raw = (run.config or {}).get("params")
    params: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    rel, path, missing = _data(settings, snap, ds, can_see)
    commit = repo_commit(settings)
    files: dict[str, bytes] = {}
    workdir, script = (t.workdir, t.script) if t is not None else ("methods", "")
    if t is not None:
        files.update(_runner_files(settings, t.workdir))
        if t.method_code:  # метод из статьи: ровно записанный код (sha256 — в platform_run.json)
            script = "method.py"
            files[f"runner/{workdir}/method.py"] = t.method_code.encode("utf-8")
    recorded = {
        "run": run.id, "experiment": exp.code, "template": run.template, "status": run.status,
        "dataset": ds.code, "version": snap.version, "sha256": snap.sha256, "params": params,
        "seeds": run.seeds or {}, "runner_commit": run.runner_commit, "env_lock_sha256": run.env_lock_sha256,
        "python": run.python, "summary": run.summary or {}, "method": (run.config or {}).get("method"),
        "code_from_commit": commit, "author": author,
        "bundled_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    files["platform_run.json"] = json.dumps(recorded, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    replication = t is not None and t.scope == "replication"
    title = f"Расчёт № {run.id} · {exp.code} · {t.title if t else run.template}"
    cells = [
        _md(f"# {title}",
            f"Данные: **{ds.code} · {snap.version}**. Статус в платформе: **{run.status}**. "
            f"Код метода — из репозитория на коммите `{commit[:12] or 'неизвестно'}`"
            + (f", считал коммит `{run.runner_commit[:12]}`." if run.runner_commit else "."),
            "",
            "Ноутбук повторяет расчёт той же командой, что исполнитель платформы, сверяет итоги и оставляет "
            "место для вашей работы. Платформа ничего не знает о том, что вы здесь делаете."),
        *_load_cells(rel, snap.sha256, str(params.get("sheet") or "")),
        _md("## Параметры", "Те же, что у расчёта в платформе. Поменяйте и запустите ячейки ниже заново."),
        _code(f"PARAMS = {pformat(params, width=100, sort_dicts=False)}  # Python, не JSON: True, None",
              "RECORDED = json.loads((HERE / 'platform_run.json').read_text(encoding='utf-8'))"),
    ]
    if t is not None and not replication:
        cells += [
            _md("## Повторить расчёт, как в платформе",
                f"Метод `{workdir}/{script}`: та же команда, что у исполнителя. Результаты — в папке `results/`."),
            _code(f"METHOD = HERE / 'runner' / {workdir!r} / {script!r}",
                  "RESULTS = HERE / 'results'",
                  "cmd = [sys.executable, '-u', str(METHOD), str(DATA.parent), str(RESULTS), '--data', str(DATA),",
                  f"       '--params', json.dumps(PARAMS, ensure_ascii=False), '--experiment', {exp.code!r}, '--dataset', {ds.code!r}]",
                  "done = subprocess.run(cmd, cwd=METHOD.parent, capture_output=True, text=True, encoding='utf-8')",
                  "print(done.stdout[-3000:], done.stderr[-3000:])"),
            _md("### Сверить с платформой"),
            _code("run_json = sorted(RESULTS.glob('*/run.json'))[-1]",
                  "mine = json.loads(run_json.read_text(encoding='utf-8'))['summary']",
                  "theirs = RECORDED['summary']",
                  "same = 0",
                  "for k in sorted(theirs):  # что записала платформа",
                  "    a, b = mine.get(k), theirs[k]",
                  "    if isinstance(b, (int, float, str, bool)):",
                  "        same += a == b",
                  "        print(('совпадает  ' if a == b else 'ОТЛИЧАЕТСЯ ') + k, '| здесь:', a, '| в платформе:', b)",
                  "print(f'Совпало чисел: {same}')"),
        ]
    elif replication:
        cells.append(_md("## Повторить расчёт",
                         f"Это повтор опубликованного расчёта ({t.title if t else ''}): код — в `runner/{workdir}/`, "
                         f"запуск — `python runner/{workdir}/{t.script if t else ''}` с параметрами PARAMS "
                         "ключами командной строки (--seed, --n-boot …)."))
    cells += _manual_cells(run.template)
    name = f"run-{run.id}"
    files[f"{name}.ipynb"] = notebook(cells).encode("utf-8")
    listing = sorted([*files, *([rel] if path else [])])
    files["README.txt"] = _readme(title, listing, missing).encode("utf-8")
    return f"esg-{name}-{exp.code}.zip", _zip(files, (rel, path))


def snapshot_bundle(settings: Settings, snap: DatasetSnapshot, ds: Dataset, can_see: bool) -> tuple[str, bytes]:
    """Архив версии данных: файл и ноутбук, чтобы смотреть и обрабатывать данные вручную."""
    rel, path, missing = _data(settings, snap, ds, can_see)
    title = f"{ds.code} · {snap.version} · {ds.title}"
    meta = {"dataset": ds.code, "title": ds.title, "version": snap.version, "sha256": snap.sha256,
            "rows": snap.row_count, "snapshot": snap.id, "access_level": ds.access_level}
    cells = [
        _md(f"# {title}", "Версия данных платформы — чтобы смотреть и обрабатывать её вручную. Ссылайтесь на "
            f"неё как **{ds.code} · {snap.version}** (sha256 `{snap.sha256[:12]}…`)."),
        *_load_cells(rel, snap.sha256, ""),
        _md("## Дальше — вручную", "Таблица — в `df`. Любые преобразования, графики, модели."),
        _code("df.select_dtypes('number').corr(method='spearman').round(2)"),
    ]
    files = {f"{ds.code}-{snap.version}.ipynb": notebook(cells).encode("utf-8"),
             "dataset.json": json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")}
    files["README.txt"] = _readme(title, sorted([*files, *([rel] if path else [])]), missing, run=False).encode("utf-8")
    return f"esg-{ds.code}-{snap.version}.zip", _zip(files, (rel, path))
