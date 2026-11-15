"""Библиотека методов: встроенные (app/services/run_templates.py) и методы из статей банка (Method).

Метод из статьи пишет Qwen (задача `method`, runner/qwen/worker.py) — только модель, протокол общий
(runner/methods/protocol.py). Здесь:
  - check_code — проверка кода: одна для обработчика Qwen (он исправляет код по её замечаниям) и для
    платформы, которая принимает метод. Код — из модели, а модель читала текст статьи: всё, что ей
    могли «подсказать», должно упереться в эту проверку. Разрешены только вычисления: библиотеки из
    списка, функции и классы, константы и запуск протокола; файлов, сети, процессов и обходных путей
    к ним (eval, __import__, getattr, атрибуты-«дандеры») нет;
  - template_of / templates / template — метод из статьи как шаблон расчёта: те же параметры
    прогноза (цель, входы, столбец-группа, seed, разбиения) и его гиперпараметры;
  - метод запускается, только когда его включил администратор (status = enabled).
"""

import ast
import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Method
from app.services.run_templates import SEED, SHEET, TEMPLATES, Param, Template

PREFIX = "method:"
ALLOWED_IMPORTS = frozenset({
    "numpy", "torch", "sklearn", "scipy", "pandas", "lightgbm", "statsmodels",
    "math", "random", "itertools", "functools", "collections", "dataclasses", "typing", "protocol",
})
FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "open", "__import__", "input", "breakpoint", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "memoryview", "exit", "quit", "help",
})
# чтение и запись файлов, сеть, процессы: у метода их быть не должно — данные даёт протокол
FORBIDDEN_ATTRS = frozenset({
    "load", "loads", "save", "savez", "loadtxt", "savetxt", "genfromtxt", "fromfile", "tofile", "memmap",
    "read_csv", "read_excel", "read_json", "read_pickle", "read_parquet", "read_sql", "to_csv", "to_pickle",
    "to_parquet", "to_json", "to_excel", "hub", "download", "system", "popen", "Popen", "spawn", "fork",
    "remove", "unlink", "rmtree", "write_text", "write_bytes", "read_text", "read_bytes", "urlopen",
})
# модули, которые умеют читать файлы или ходить в сеть, — даже внутри разрешённых библиотек
FORBIDDEN_MODULES = ("sklearn.datasets", "scipy.io", "pandas.io", "numpy.lib.npyio", "torch.hub",
                     "torch.utils.model_zoo", "torch.package", "torch.distributed", "torch.multiprocessing")
# служебные атрибуты, без которых не написать модель (super().__init__()); остальные — путь в обход
SAFE_DUNDERS = frozenset({"__init__", "__call__", "__len__", "__iter__", "__next__", "__getitem__"})
TOP_LEVEL = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)
MAX_CODE = 40_000


def sha256(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _main_guard(node: ast.If) -> bool:
    """if __name__ == "__main__": import protocol; raise SystemExit(protocol.run(make_model, TITLE))"""
    t = node.test
    return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
            and len(t.comparators) == 1 and isinstance(t.comparators[0], ast.Constant)
            and t.comparators[0].value == "__main__" and not node.orelse
            and all(isinstance(s, (ast.Import, ast.ImportFrom, ast.Raise, ast.Expr)) for s in node.body))


def check_code(code: str) -> list[str]:
    """Замечания к коду метода; пусто — проверку прошёл."""
    if len(code) > MAX_CODE:
        return [f"Код длиннее {MAX_CODE} знаков"]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Синтаксическая ошибка, строка {exc.lineno}: {exc.msg}"]
    problems: list[str] = []
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if "make_model" not in names:
        problems.append("Нет функции make_model(params, seed)")
    if not any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TITLE" for t in n.targets)
               for n in tree.body):
        problems.append("Нет константы TITLE — название метода")
    guards = [n for n in tree.body if isinstance(n, ast.If)]
    if len(guards) != 1 or not _main_guard(guards[0]):
        problems.append('Нужен ровно один блок if __name__ == "__main__" с запуском protocol.run')
    for n in tree.body:
        if not isinstance(n, (*TOP_LEVEL, ast.If)) and not (
                isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)):
            problems.append(f"Строка {n.lineno}: на верхнем уровне — только импорты, функции, классы и константы")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names])
            for mod in mods:
                bad = (mod.split(".")[0] not in ALLOWED_IMPORTS or any(
                    mod == f or mod.startswith(f + ".") for f in FORBIDDEN_MODULES)
                       or (isinstance(node, ast.ImportFrom) and node.level > 0))
                if bad:
                    problems.append(f"Строка {node.lineno}: библиотека «{mod}» не разрешена")
                    break
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"Строка {node.lineno}: «{node.id}» нельзя — метод только считает")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__") and node.attr not in SAFE_DUNDERS:
                problems.append(f"Строка {node.lineno}: служебный атрибут «{node.attr}» нельзя")
            elif node.attr in FORBIDDEN_ATTRS or node.attr.startswith(("fetch_", "load_")) or node.attr in {
                    m.rsplit(".", 1)[1] for m in FORBIDDEN_MODULES}:
                problems.append(f"Строка {node.lineno}: «.{node.attr}» — файлы, сеть или процессы методу не нужны")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append(f"Строка {node.lineno}: global и nonlocal нельзя")
    return list(dict.fromkeys(problems))[:30]


# параметры прогноза — как у метода лаборатории; гиперпараметры метода — целые, с пределами
BASE_PARAMS = (
    SHEET,
    Param("target", "Целевой показатель", "", kind="column"),
    Param("features", "Входы", [], kind="columns", hint="показатели, по которым предсказываем"),
    Param("group", "Столбец-группа (панель)", "", kind="column", required=False, numeric=False,
          hint="у панели компания × год — компания: проверка на компаниях вне обучения"),
    SEED,
    Param("splits", "Разбиений", 30, 5, 200),
)
BASE_NAMES = frozenset(p.name for p in BASE_PARAMS)


def hyper_params(spec: Any) -> list[dict[str, Any]]:
    """Гиперпараметры метода из ответа Qwen: только целые с разумными пределами; лишнее — прочь."""
    out: list[dict[str, Any]] = []
    for p in spec if isinstance(spec, list) else []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        if not name.isidentifier() or name in BASE_NAMES or name in {q["name"] for q in out}:
            continue
        raw = p.get("default", 1)
        if isinstance(raw, bool) or not isinstance(raw, int):
            continue  # дробный (скорость обучения) — в коде метода: округление до целого сломало бы его
        try:
            lo, hi, default = int(p.get("min", 1)), int(p.get("max", 1000)), int(raw)
        except (TypeError, ValueError):
            continue
        lo, hi = max(0, min(lo, hi)), min(100_000, max(lo, hi))
        out.append({"name": name, "label": str(p.get("label") or name)[:120], "min": lo, "max": hi,
                    "default": min(hi, max(lo, default)), "hint": str(p.get("hint") or "")[:200]})
    return out[:10]


def template_of(m: Method) -> Template:
    hyper = tuple(Param(p["name"], p.get("label") or p["name"], p["default"], p["min"], p["max"],
                        hint=p.get("hint", "")) for p in hyper_params(m.params))
    source = f"по статье «{m.article_title}»" if m.article_title else "из банка статей"
    return Template(
        key=f"{PREFIX}{m.code}", title=f"{m.title} ({m.code}, {source})",
        description=(m.description or m.title) + " Протокол CR-01: разбиения, плацебо, сравнение с линейной моделью.",
        workdir="methods", script="", resource="cpu", limit_min=m.limit_min, params=(*BASE_PARAMS, *hyper),
        method_code=m.script, method_sha256=m.sha256, method=m.code, fit_s=m.fit_s, fit_rows=m.fit_rows,
    )


def enabled(db: Session) -> list[Method]:
    return list(db.scalars(select(Method).where(Method.status == "enabled").order_by(Method.code)))


def templates(db: Session) -> list[Template]:
    """Вся библиотека: встроенные методы и включённые методы из статей."""
    return [*TEMPLATES.values(), *(template_of(m) for m in enabled(db))]


def template(db: Session, key: str) -> Template | None:
    if not key.startswith(PREFIX):
        return TEMPLATES.get(key)
    m = db.scalar(select(Method).where(Method.code == key.removeprefix(PREFIX)))
    return template_of(m) if m is not None and m.status == "enabled" else None
