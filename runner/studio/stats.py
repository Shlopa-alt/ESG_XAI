"""Визуализаторы «Таблица» и «Статистика»: что показать по результату узла (JSON для сайта)."""

import math
from typing import Any

import numpy as np
import pandas as pd

PREVIEW_ROWS = 100
TOP = 5
BINS = 10


def _plain(v: Any) -> Any:
    """Значение ячейки для JSON: без NaN, numpy-типов и дат-объектов."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        ts = pd.Timestamp(v)
        return None if pd.isna(ts) else ts.isoformat()
    if isinstance(v, np.generic):
        v = v.item()
    if not isinstance(v, (str, int, float, bool)):  # Decimal, UUID, bytes… — чтобы JSON не падал
        if hasattr(v, "isoformat"):
            return v.isoformat()
        try:
            return float(v)
        except (TypeError, ValueError):
            return str(v)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def kind(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_numeric_dtype(s):
        return "integer" if pd.api.types.is_integer_dtype(s) else "number"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    return "string"


def table(df: pd.DataFrame, rows: int = PREVIEW_ROWS) -> dict[str, Any]:
    """Визуализатор «Таблица»: первые строки и типы столбцов."""
    head = df.head(rows)
    return {
        "columns": [{"name": str(c), "kind": kind(df[c])} for c in df.columns],
        "rows": [[_plain(v) for v in r] for r in head.itertuples(index=False, name=None)],
        "total": int(len(df)),
    }


def _column(s: pd.Series) -> dict[str, Any]:
    k = kind(s)
    n = int(len(s))
    missing = int(s.isna().sum()) if k != "string" else int((s.isna() | (s.astype("string").str.strip() == "")).sum())
    out: dict[str, Any] = {"name": str(s.name), "kind": k, "count": n - missing, "missing": missing,
                           "unique": int(s.nunique(dropna=True))}
    if k in ("number", "integer") and n - missing:
        x = pd.to_numeric(s, errors="coerce").dropna().astype(float)
        q = x.quantile([0.25, 0.5, 0.75])
        out.update({"min": _plain(x.min()), "max": _plain(x.max()), "mean": _plain(x.mean()),
                    "std": _plain(x.std()) if len(x) > 1 else None,
                    "q1": _plain(q.loc[0.25]), "median": _plain(q.loc[0.5]), "q3": _plain(q.loc[0.75]),
                    "skew": _plain(x.skew()) if len(x) > 2 else None})
        if x.max() > x.min():
            counts, edges = np.histogram(x, bins=BINS)
            out["histogram"] = [{"from": _plain(edges[i]), "to": _plain(edges[i + 1]), "count": int(c)}
                                for i, c in enumerate(counts)]
    elif k == "date" and n - missing:
        out.update({"min": _plain(s.min()), "max": _plain(s.max())})
    if k in ("string", "bool", "integer") and n - missing:
        top = s.dropna().astype("string").value_counts().head(TOP)
        out["top"] = [{"value": str(v), "count": int(c)} for v, c in top.items()]
    return out


def statistics(df: pd.DataFrame) -> dict[str, Any]:
    """Визуализатор «Статистика»: по каждому столбцу — заполненность, разброс, частые значения."""
    return {"rows": int(len(df)), "columns": [_column(df[c]) for c in df.columns]}


SAMPLE_ROWS = 500


def _problems(s: pd.Series, k: str, n: int, missing: int, unique: int) -> list[str]:
    out = []
    if n and missing == n:
        out.append("пустой столбец")
    elif n and missing / n > 0.3:
        out.append(f"пусто {round(100 * missing / n)}%")
    if unique == 1 and n - missing > 1:
        out.append("одно значение на весь столбец")
    if k == "string" and n - missing:
        text = s.dropna().astype("string").str.strip()
        as_num = pd.to_numeric(text.str.replace(",", ".", regex=False).str.replace(r"\s", "", regex=True),
                               errors="coerce")
        share = float(as_num.notna().mean())
        if share >= 0.8:
            out.append(f"числа записаны текстом ({round(100 * share)}%) — «Параметры полей» → число")
        if unique > 0.9 * (n - missing) and n - missing > 20:
            out.append("почти все значения разные (идентификатор?)")
    return out


def quality(df: pd.DataFrame) -> dict[str, Any]:
    """Визуализатор «Качество данных»: что поправить до анализа — пропуски, выбросы, числа текстом,
    постоянные столбцы, повторяющиеся строки."""
    n = int(len(df))
    cols = []
    for c in df.columns:
        s = df[c]
        k = kind(s)
        empty = s.isna() | (s.astype("string").str.strip() == "") if k == "string" else s.isna()
        missing, unique = int(empty.sum()), int(s.nunique(dropna=True))
        item: dict[str, Any] = {"name": str(c), "kind": k, "missing": missing,
                                "missing_share": round(missing / n, 4) if n else 0.0, "unique": unique}
        if k in ("number", "integer"):
            x = pd.to_numeric(s, errors="coerce").dropna()
            q1, q3 = (x.quantile(0.25), x.quantile(0.75)) if len(x) else (0.0, 0.0)
            iqr = q3 - q1
            item["zeros"] = int((x == 0).sum())
            item["negative"] = int((x < 0).sum())
            item["outliers"] = int(((x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr)).sum()) if iqr else 0
        item["problems"] = _problems(s, k, n, missing, unique)
        cols.append(item)
    dup = int(df.astype("string").duplicated().sum()) if n else 0
    return {"rows": n, "duplicate_rows": dup, "columns": cols,
            "issues": sum(len(c["problems"]) for c in cols) + (1 if dup else 0)}


def sample(df: pd.DataFrame, rows: int = SAMPLE_ROWS) -> dict[str, Any]:
    """Выборка строк для «Диаграммы» (случайная, но одна и та же при повторе)."""
    part = df.sample(n=rows, random_state=0).sort_index() if len(df) > rows else df
    return {"columns": [{"name": str(c), "kind": kind(df[c])} for c in df.columns],
            "rows": [[_plain(v) for v in r] for r in part.itertuples(index=False, name=None)],
            "total": int(len(df))}


CUBE_DIMS, CUBE_MEASURES, CUBE_CELLS, DIM_MAX = 6, 10, 20_000, 50


def cube(df: pd.DataFrame) -> dict[str, Any] | None:
    """Визуализатор «Куб»: ячейки по сочетаниям измерений (столбцы с 2–50 значениями) с суммой,
    числом, минимумом и максимумом каждой меры. Из ячеек сайт точно собирает любую сводную:
    по строкам и столбцам, сумма, среднее (сумма / число), количество, минимум, максимум."""
    if df.empty:
        return None
    card = {c: int(df[c].nunique(dropna=True)) for c in df.columns}
    # идентификатор (все значения разные) — ни измерение, ни мера: сумма кодов смысла не имеет
    ident = {c for c in df.columns if card[c] == len(df) and len(df) > 2
             and not pd.api.types.is_float_dtype(df[c])}
    dims = sorted([c for c in df.columns if 2 <= card[c] <= DIM_MAX and c not in ident
                   and not pd.api.types.is_float_dtype(df[c])], key=lambda c: card[c])[:CUBE_DIMS]
    measures = [c for c in df.columns if c not in dims and c not in ident
                and pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])
                ][:CUBE_MEASURES]
    if not dims:
        return None
    while dims and df[dims].drop_duplicates().shape[0] > CUBE_CELLS:
        dims.pop()  # самое многозначное измерение — прочь, пока ячеек не станет разумно
    keys = df[dims].astype("string").fillna("(пусто)")
    data = pd.concat([keys, df[measures].apply(pd.to_numeric, errors="coerce")], axis=1)
    g = data.groupby(dims, sort=True, dropna=False)
    agg = g.size().rename("__n").to_frame()
    for m in measures:
        agg[f"{m}|sum"] = g[m].sum(min_count=1)
        agg[f"{m}|cnt"] = g[m].count()
        agg[f"{m}|min"] = g[m].min()
        agg[f"{m}|max"] = g[m].max()
    agg = agg.reset_index()
    return {"dims": [str(d) for d in dims], "measures": [str(m) for m in measures],
            "cells": [[_plain(v) for v in r] for r in agg.itertuples(index=False, name=None)]}
