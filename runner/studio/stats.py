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
