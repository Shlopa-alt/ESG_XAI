"""Выражения Студии («Калькулятор», «Фильтр строк»): формулы над столбцами, как в Excel.

    выручка / сотрудники
    ЕСЛИ(roe > 0.1; "высокая"; "низкая")
    ГОД(дата) >= 2020 И НЕ ПУСТО(отрасль)
    `доля, %` * 100

Разбирается своим разборщиком на модуле ast с белым списком: столбцы, числа, строки, арифметика,
сравнения, И / ИЛИ / НЕ и функции из FUNCS. Произвольный Python не выполняется: атрибуты, индексы,
лямбды, вызовы чего-то кроме FUNCS — ошибка. Столбец с пробелами или знаками — в обратных кавычках.
Считается сразу по всему столбцу (pandas), строка таблицы — одно значение.
"""

import ast
import math
import re
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd


class ExprError(ValueError):
    pass


Value = Any  # pd.Series или скаляр


def _num(v: Value) -> Value:
    return pd.to_numeric(v, errors="coerce") if isinstance(v, pd.Series) else v


def _dt(v: Value) -> pd.Series:
    if not isinstance(v, pd.Series):
        raise ExprError("Функции даты применяются к столбцу")
    if pd.api.types.is_datetime64_any_dtype(v):
        return v
    text = v.astype("string").str.strip()
    # ГГГГ-ММ-ДД — как есть; остальное по-русски: день перед месяцем (31.12.2021)
    iso = text.str.match(r"^\d{4}-\d{2}-\d{2}").fillna(False)
    out = pd.to_datetime(text.where(iso), errors="coerce", format="ISO8601")
    return out.fillna(pd.to_datetime(text.where(~iso), errors="coerce", dayfirst=True, format="mixed"))


def _where(cond: Value, a: Value, b: Value, index: pd.Index) -> pd.Series:
    c = cond if isinstance(cond, pd.Series) else pd.Series(cond, index=index)
    a = a if isinstance(a, pd.Series) else pd.Series([a] * len(index), index=index, dtype=object)
    b = b if isinstance(b, pd.Series) else pd.Series([b] * len(index), index=index, dtype=object)
    out = a.where(c.fillna(False).astype(bool), b)
    return out.infer_objects()


def _round(v: Value, digits: Value = 0) -> Value:
    return _num(v).round(int(digits)) if isinstance(v, pd.Series) else round(v, int(digits))


def _str(v: Value) -> Value:
    return v.astype("string") if isinstance(v, pd.Series) else str(v)


def _concat(*parts: Value) -> Value:
    out: Value = ""
    for p in parts:
        out = out + _str(p).fillna("") if isinstance(p, pd.Series) else out + str(p)
    return out


def _math(fn: Callable[[Any], Any]) -> Callable[[Value], Value]:
    def apply(v: Value) -> Value:
        if isinstance(v, pd.Series):
            with np.errstate(all="ignore"):
                return pd.Series(fn(_num(v).astype(float).to_numpy()), index=v.index)
        return fn(float(v))
    return apply


def _rowwise(fn: str) -> Callable[..., Value]:
    def apply(*vals: Value) -> Value:
        series = [v for v in vals if isinstance(v, pd.Series)]
        if not series:
            return max(vals) if fn == "max" else min(vals)
        frame = pd.concat([_num(v) if isinstance(v, pd.Series) else pd.Series(v, index=series[0].index)
                           for v in vals], axis=1)
        return frame.max(axis=1) if fn == "max" else frame.min(axis=1)
    return apply


def _isnull(v: Value) -> Value:
    if isinstance(v, pd.Series):
        return v.isna() | (v.astype("string").str.strip() == "")
    return v is None or (isinstance(v, float) and math.isnan(v))


def _coalesce(*vals: Value) -> Value:
    out = vals[0]
    for v in vals[1:]:
        out = out.where(~_isnull(out), v) if isinstance(out, pd.Series) else (v if _isnull(out) else out)
    return out


# Имена функций — по-русски и по-английски (как в Excel); аргументы — через «;» или «,»
FUNCS: dict[str, Callable[..., Value]] = {}
for names, fn in [
    (("ABS", "МОДУЛЬ"), _math(np.abs)),
    (("SQRT", "КОРЕНЬ"), _math(np.sqrt)),
    (("LN",), _math(np.log)),
    (("LOG10",), _math(np.log10)),
    (("EXP",), _math(np.exp)),
    (("ROUND", "ОКРУГЛ"), _round),
    (("MAX", "МАКС"), _rowwise("max")),
    (("MIN", "МИН"), _rowwise("min")),
    (("ISNULL", "ПУСТО"), _isnull),
    (("COALESCE", "ПЕРВОЕНЕПУСТОЕ"), _coalesce),
    (("YEAR", "ГОД"), lambda v: _dt(v).dt.year.astype("Int64")),
    (("QUARTER", "КВАРТАЛ"), lambda v: _dt(v).dt.quarter.astype("Int64")),
    (("MONTH", "МЕСЯЦ"), lambda v: _dt(v).dt.month.astype("Int64")),
    (("DAY", "ДЕНЬ"), lambda v: _dt(v).dt.day.astype("Int64")),
    (("STR", "ТЕКСТ"), _str),
    (("NUM", "ЧИСЛО"), _num),
    (("LEN", "ДЛСТР"), lambda v: _str(v).str.len() if isinstance(v, pd.Series) else len(str(v))),
    (("UPPER", "ПРОПИСН"), lambda v: _str(v).str.upper() if isinstance(v, pd.Series) else str(v).upper()),
    (("LOWER", "СТРОЧН"), lambda v: _str(v).str.lower() if isinstance(v, pd.Series) else str(v).lower()),
    (("TRIM", "СЖПРОБЕЛЫ"), lambda v: _str(v).str.strip() if isinstance(v, pd.Series) else str(v).strip()),
    (("CONCAT", "СЦЕП"), _concat),
]:
    for n in names:
        FUNCS[n] = fn
IF_NAMES = {"IF", "ЕСЛИ"}

_WORDS = [(r"\bИЛИ\b", " or "), (r"\bИ\b", " and "), (r"\bНЕ\b", " not "),
          (r"\bOR\b", " or "), (r"\bAND\b", " and "), (r"\bNOT\b", " not "),
          (r"<>", "!="), (r"(?<![<>!=])=(?!=)", "==")]


VAR = re.compile(r"\$([A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*)")


def _prepare(text: str) -> tuple[str, dict[str, str]]:
    """Столбцы в `обратных кавычках` → имена-заглушки; русские И/ИЛИ/НЕ, «=» и «<>» → Python;
    «;» между аргументами → «,». Строки в кавычках не трогаем."""
    quoted: dict[str, str] = {}

    def keep(m: re.Match[str]) -> str:
        key = f"__c{len(quoted)}"
        quoted[key] = m.group(1)
        return key

    def var(m: re.Match[str]) -> str:  # $имя → заглушка; «$» в начале — признак переменной
        key = f"__c{len(quoted)}"
        quoted[key] = "$" + m.group(1)
        return key

    parts = re.split(r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')', text)
    out = []
    for i, part in enumerate(parts):
        if i % 2:  # строковый литерал
            out.append(part)
            continue
        part = re.sub(r"`([^`]+)`", keep, part)
        part = VAR.sub(var, part)
        part = part.replace(";", ",")
        for pat, rep in _WORDS:
            part = re.sub(pat, rep, part, flags=re.IGNORECASE)
        out.append(part)
    return "".join(out), quoted


def evaluate(text: str, df: pd.DataFrame, variables: dict[str, Any] | None = None) -> Value:
    """Значение выражения по таблице: столбец (pd.Series) или одно значение. $имя — переменная."""
    src, quoted = _prepare(text.strip())
    if not src.strip():
        raise ExprError("Пустое выражение")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"Не разобрать выражение «{text}»: проверьте скобки и кавычки") from exc
    columns = {str(c): c for c in df.columns}

    def col(name: str) -> Value:
        real = quoted.get(name, name)
        if real.startswith("$"):  # переменная сценария
            vname = real[1:]
            if variables is None or vname not in variables:
                raise ExprError(f"Нет переменной ${vname}")
            return variables[vname]
        if real not in columns:
            raise ExprError(f"Нет столбца «{real}»" + ("" if name in quoted else
                            " (имя с пробелами или знаками — в `обратных кавычках`)"))
        return df[columns[real]]

    def ev(node: ast.AST) -> Value:  # noqa: PLR0911, PLR0912 — по одной ветке на вид узла
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
            return node.value
        if isinstance(node, ast.Name):
            up = node.id.upper()
            if up in ("TRUE", "ИСТИНА"):
                return True
            if up in ("FALSE", "ЛОЖЬ"):
                return False
            return col(node.id)
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            if isinstance(node.op, ast.USub):
                return -_num(v)
            if isinstance(node.op, ast.UAdd):
                return _num(v)
            if isinstance(node.op, ast.Not):
                return ~v.fillna(False).astype(bool) if isinstance(v, pd.Series) else not v
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Add) and (isinstance(a, str) or isinstance(b, str)):
                return _concat(a, b)
            a, b = _num(a), _num(b)
            ops: dict[type, Callable[[Any, Any], Any]] = {
                ast.Add: lambda x, y: x + y, ast.Sub: lambda x, y: x - y,
                ast.Mult: lambda x, y: x * y, ast.Div: lambda x, y: x / y,
                ast.Pow: lambda x, y: x ** y, ast.Mod: lambda x, y: x % y,
            }
            fn = ops.get(type(node.op))
            if fn is not None:
                with np.errstate(all="ignore"):
                    out = fn(a, b)
                if isinstance(out, pd.Series):
                    out = out.replace([np.inf, -np.inf], np.nan)  # деление на ноль — пусто
                return out
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            out = vals[0]
            for v in vals[1:]:
                l = out.fillna(False).astype(bool) if isinstance(out, pd.Series) else bool(out)  # noqa: E741
                r = v.fillna(False).astype(bool) if isinstance(v, pd.Series) else bool(v)
                out = (l & r) if isinstance(node.op, ast.And) else (l | r)
            return out
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            result: Value = True
            for op, right_node in zip(node.ops, node.comparators, strict=True):
                right = ev(right_node)
                cmp = _compare(op, left, right)
                result = cmp if result is True else (result & cmp)
                left = right
            return result
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id.upper()
            if name in IF_NAMES:
                if len(node.args) != 3:
                    raise ExprError("ЕСЛИ(условие; если да; если нет) — три аргумента")
                cond, a, b = (ev(x) for x in node.args)
                if not isinstance(cond, pd.Series):
                    return a if cond else b
                return _where(cond, a, b, df.index)
            fn = FUNCS.get(name)
            if fn is None:
                raise ExprError(f"Нет функции {node.func.id}. Есть: ЕСЛИ, {', '.join(sorted(FUNCS))}")
            try:
                return fn(*[ev(x) for x in node.args])
            except TypeError as exc:
                raise ExprError(f"{node.func.id}: не те аргументы") from exc
        raise ExprError(f"В выражении «{text}» есть то, что Студия не считает: "
                        f"{ast.unparse(node) if hasattr(ast, 'unparse') else type(node).__name__}")

    return ev(tree)


def _compare(op: ast.cmpop, a: Value, b: Value) -> Value:
    if isinstance(a, pd.Series) and isinstance(b, (int, float)) and not isinstance(b, bool):
        a = _num(a)
    if isinstance(b, pd.Series) and isinstance(a, (int, float)) and not isinstance(a, bool):
        b = _num(b)
    ops: dict[type, Callable[[Any, Any], Any]] = {
        ast.Eq: lambda x, y: x == y, ast.NotEq: lambda x, y: x != y,
        ast.Lt: lambda x, y: x < y, ast.LtE: lambda x, y: x <= y,
        ast.Gt: lambda x, y: x > y, ast.GtE: lambda x, y: x >= y,
    }
    fn = ops.get(type(op))
    if fn is None:
        raise ExprError("Сравнения: =, <>, <, <=, >, >=")
    out = fn(a, b)
    return out.fillna(False) if isinstance(out, pd.Series) else out


def column(text: str, df: pd.DataFrame, variables: dict[str, Any] | None = None) -> pd.Series:
    """Выражение как столбец той же длины, что таблица."""
    v = evaluate(text, df, variables)
    if isinstance(v, pd.Series):
        return v
    return pd.Series([v] * len(df), index=df.index)


def mask(text: str, df: pd.DataFrame, variables: dict[str, Any] | None = None) -> pd.Series:
    """Условие как маска строк (пусто — ложь)."""
    v = column(text, df, variables)
    if v.dtype == object or str(v.dtype) not in ("bool", "boolean"):
        try:
            return v.fillna(False).astype(bool)
        except (TypeError, ValueError) as exc:
            raise ExprError("Условие фильтра должно давать да/нет") from exc
    return v.fillna(False).astype(bool)
