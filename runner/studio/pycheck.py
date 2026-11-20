"""Проверка кода узла «Python» Студии — только стандартная библиотека (её вызывает и платформа до
запуска, и исполнитель перед выполнением). Правила — как у методов библиотеки
(backend/app/services/method_library.py): только библиотеки расчётов, без файлов, сети,
процессов, eval/exec и служебных атрибутов. Код к тому же одобряет владелец платформы.
"""

import ast
import hashlib

ALLOWED_IMPORTS = frozenset({"numpy", "pandas", "scipy", "sklearn", "math", "statistics", "random", "re",
                             "datetime", "itertools", "functools", "collections", "decimal", "fractions"})
FORBIDDEN_NAMES = frozenset({"eval", "exec", "compile", "open", "__import__", "input", "breakpoint", "globals",
                             "locals", "getattr", "setattr", "delattr", "memoryview", "exit", "quit", "help",
                             "__builtins__", "type", "object", "super", "classmethod", "staticmethod", "property"})
FORBIDDEN_ATTRS = frozenset({
    "load", "loads", "save", "savez", "loadtxt", "savetxt", "genfromtxt", "fromfile", "tofile", "memmap",
    "read_csv", "read_excel", "read_json", "read_pickle", "read_parquet", "read_sql", "read_html", "read_table",
    "read_fwf", "read_clipboard", "read_hdf", "read_feather", "read_orc", "read_sas", "read_spss", "read_stata",
    "read_xml", "to_csv", "to_pickle", "to_parquet", "to_json", "to_excel", "to_hdf", "to_sql", "to_feather",
    "to_clipboard", "to_html", "to_latex", "to_markdown", "to_xml", "to_stata", "to_orc",
    "download", "system", "popen", "Popen", "spawn", "fork", "remove", "unlink", "rmtree", "write_text",
    "write_bytes", "read_text", "read_bytes", "urlopen", "eval", "query",
})
FORBIDDEN_MODULES = ("sklearn.datasets", "scipy.io", "pandas.io", "numpy.lib.npyio", "numpy.ctypeslib",
                     "numpy.distutils", "numpy.f2py", "scipy.datasets", "pandas.api")
MAX_CODE = 40_000


def sha256(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def check(code: str) -> list[str]:
    """Что в коде нельзя; пустой список — можно."""
    if len(code) > MAX_CODE:
        return [f"Код длиннее {MAX_CODE} знаков"]
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Строка {exc.lineno}: синтаксическая ошибка — {exc.msg}"]
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names])
            for mod in mods:
                if (mod.split(".")[0] not in ALLOWED_IMPORTS
                        or any(mod == f or mod.startswith(f + ".") for f in FORBIDDEN_MODULES)
                        or (isinstance(node, ast.ImportFrom) and node.level > 0)):
                    problems.append(f"Строка {node.lineno}: библиотека «{mod}» не разрешена")
                    break
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            problems.append(f"Строка {node.lineno}: «{node.id}» нельзя")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                problems.append(f"Строка {node.lineno}: служебный атрибут «{node.attr}» нельзя")
            elif node.attr in FORBIDDEN_ATTRS or node.attr.startswith(("fetch_", "load_")):
                problems.append(f"Строка {node.lineno}: «.{node.attr}» — файлы, сеть и процессы узлу не нужны")
        elif isinstance(node, (ast.Global, ast.Nonlocal, ast.ClassDef, ast.AsyncFunctionDef, ast.Await)):
            problems.append(f"Строка {node.lineno}: {type(node).__name__} нельзя")
    return list(dict.fromkeys(problems))[:30]
