"""Студия, этап 4: узел «Python» (группа «Программирование» Loginom).

Код видит df (первый вход), df2 (второй), vars (переменные), pd, np и должен положить таблицу в
out. Перед выполнением — та же проверка, что на платформе (pycheck); встроенные функции —
только безопасные, импорт — только разрешённых библиотек. Что код печатает — в «Отчёт».
"""

import builtins
import contextlib
import io
import traceback
from typing import Any

import numpy as np
import pandas as pd

from studio import pycheck
from studio.base import Component, NodeError, Param

Frame = pd.DataFrame
Params = dict[str, Any]

SAFE = ("abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "frozenset", "int",
        "isinstance", "len", "list", "map", "max", "min", "next", "pow", "print", "range", "reversed", "round",
        "set", "slice", "sorted", "str", "sum", "tuple", "zip", "iter", "hash", "repr", "format", "chr", "ord",
        "Exception", "ValueError", "KeyError", "TypeError", "IndexError", "ZeroDivisionError", "ArithmeticError",
        "StopIteration", "True", "False", "None")


def _guarded_import(name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    if level or name.split(".")[0] not in pycheck.ALLOWED_IMPORTS or any(
            name == f or name.startswith(f + ".") for f in pycheck.FORBIDDEN_MODULES):
        raise ImportError(f"библиотека «{name}» не разрешена")
    return builtins.__import__(name, globals_, locals_, fromlist, level)


def python(inp: dict[str, Frame], p: Params) -> Frame:
    code = str(p.get("code") or "")
    problems = pycheck.check(code)
    if problems:
        raise NodeError("Python: " + "; ".join(problems[:3]))
    safe = {n: getattr(builtins, n) for n in SAFE if hasattr(builtins, n)}
    safe["__import__"] = _guarded_import
    vars_in = dict(p.get("__vars__", {}))
    env: dict[str, Any] = {"__builtins__": safe, "pd": pd, "np": np, "df": inp.get("in"), "df2": inp.get("in2"),
                           "vars": dict(vars_in), "out": None}
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            exec(compile(code, "<узел Python>", "exec"), env)  # noqa: S102 — код проверен pycheck и одобрен
    except Exception as exc:  # noqa: BLE001 — ошибка кода человека: строка и текст
        line = next((f.lineno for f in reversed(traceback.extract_tb(exc.__traceback__))
                     if f.filename == "<узел Python>"), None)
        raise NodeError(f"Python{f', строка {line}' if line else ''}: {type(exc).__name__}: {exc}") from exc
    out = env.get("out")
    if not isinstance(out, pd.DataFrame):
        raise NodeError("Python: положите результат-таблицу в out (например, out = df.copy())")
    out = out.copy()
    changed = {k: v for k, v in (env.get("vars") or {}).items() if vars_in.get(k, object()) is not v}
    if changed:
        out.attrs["vars"] = changed
    text = printed.getvalue().strip()
    if text:
        out.attrs["report"] = {"kind": "python", "title": "Вывод кода", "notes": text.splitlines()[-50:]}
    return out


COMPONENTS = [
    Component("code.python", "Python", "Программирование",
              "Свой код на pandas / numpy / scipy / sklearn: df, df2, vars → out. Код одобряет владелец платформы",
              ("in", "in2"), (Param("code", "Код", "code",
                                    default="out = df.copy()\n# out['новое'] = out['a'] / out['b']\n"),),
              python, optional=("in", "in2"), input_labels=("df", "df2")),
]
