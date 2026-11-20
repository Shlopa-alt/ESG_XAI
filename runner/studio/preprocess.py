"""Студия, этап 2: предобработка (как группа «Предобработка» Loginom) и нормализация.

Всё, где есть случайность (разбиение на множества, сэмплинг), берёт seed из настроек узла —
расчёт повторяется до строки (правило 3).
"""

from typing import Any

import numpy as np
import pandas as pd

from studio.base import Component, NodeError, Param

Frame = pd.DataFrame
Params = dict[str, Any]
GROUP = "Предобработка"
SEED = 42


def _need(df: Frame, cols: list[str], where: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise NodeError(f"{where}: нет столбцов {', '.join(missing)}")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _target(p: Params, col: str, suffix: str) -> str:
    return col if p.get("replace") else f"{col}_{suffix}"


# --- заполнение пропусков -------------------------------------------------------------------------

FILL = (("mean", "среднее"), ("median", "медиана"), ("mode", "самое частое"), ("value", "значение"),
        ("previous", "предыдущее"), ("next", "следующее"), ("interpolate", "линейная интерполяция"),
        ("drop", "удалить строку"))


def fill_missing(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"].copy()
    rules: list[Params] = p.get("rules") or []
    by: list[str] = p.get("group_by") or []
    order = p.get("order_by")
    _need(df, [r["column"] for r in rules] + by + ([order] if order else []), "Заполнение пропусков")
    if not rules:
        raise NodeError("Заполнение пропусков: добавьте хотя бы одно правило (столбец и способ)")
    if order:
        df = df.sort_values([*by, order], kind="stable")
    drop_mask = pd.Series(False, index=df.index)
    for r in rules:
        col, how = r["column"], r.get("method", "median")
        s = df[col]
        empty = s.isna() | (s.astype("string").str.strip() == "")
        s = s.mask(empty)
        groups = [df[b] for b in by]
        if how in ("mean", "median"):
            x = _num(s)
            fill = x.groupby(groups, dropna=False).transform(how) if by else getattr(x, how)()
            df[col] = x.fillna(fill)
        elif how == "mode":
            def mode(v: pd.Series) -> Any:
                m = v.dropna().mode()
                return m.iloc[0] if len(m) else np.nan
            fill = s.groupby(groups, dropna=False).transform(mode) if by else mode(s)
            df[col] = s.fillna(fill)
        elif how == "value":
            value: Any = r.get("value", "")
            if pd.api.types.is_numeric_dtype(df[col]):
                try:
                    value = float(str(value).replace(",", "."))
                except ValueError as exc:
                    raise NodeError(f"Заполнение пропусков: «{col}» числовой, а значение «{value}» — нет") from exc
            df[col] = s.fillna(value)
        elif how in ("previous", "next"):
            g = s.groupby(groups, dropna=False) if by else s
            df[col] = g.ffill() if how == "previous" else g.bfill()
        elif how == "interpolate":
            x = _num(s)
            df[col] = (x.groupby(groups, dropna=False).transform(lambda v: v.interpolate(limit_area="inside"))
                       if by else x.interpolate(limit_area="inside"))
        elif how == "drop":
            drop_mask |= empty
        else:
            raise NodeError(f"Заполнение пропусков: нет способа «{how}»")
    return df[~drop_mask].reset_index(drop=True)


# --- квантование ----------------------------------------------------------------------------------

def binning(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"].copy()
    col = p["column"]
    _need(df, [col], "Квантование")
    x = _num(df[col])
    how, n = p.get("method", "quantile"), int(p.get("bins") or 5)
    if not 2 <= n <= 100:
        raise NodeError("Квантование: интервалов — от 2 до 100")
    try:
        if how == "edges":
            edges = sorted(float(v.replace(",", ".")) for v in str(p.get("edges") or "").split(";") if v.strip())
            if len(edges) < 1:
                raise NodeError("Квантование: укажите границы через «;», например 0; 10; 100")
            cut = pd.cut(x, [-np.inf, *edges, np.inf], duplicates="drop")
        elif how == "width":
            cut = pd.cut(x, n, duplicates="drop")
        else:
            cut = pd.qcut(x, n, duplicates="drop")
    except ValueError as exc:
        raise NodeError(f"Квантование «{col}»: {exc}") from exc
    name = p.get("as") or f"{col}_интервал"
    if p.get("labels") == "number":
        df[name] = cut.cat.codes.astype("Int64").where(cut.notna()) + 1
    else:
        df[name] = cut.astype("string")
    return df


# --- конечные классы (оптимальное разбиение по целевому признаку) ---------------------------------

def _woe(bad: float, good: float, bad_all: float, good_all: float) -> float:
    return float(np.log(((good + 0.5) / (good_all + 0.5)) / ((bad + 0.5) / (bad_all + 0.5))))


def final_classes(inp: dict[str, Frame], p: Params) -> Frame:
    """Конечные классы: значения признака — в несколько классов, по-разному связанных с целевым
    (бинарным) признаком; соседние классы с близкой долей «событий» сливаются. Добавляются номер
    класса и WoE — вес доказательства, как в кредитном скоринге."""
    df = inp["in"].copy()
    col, target = p["column"], p["target"]
    _need(df, [col, target], "Конечные классы")
    y = df[target]
    values = sorted(y.dropna().unique().tolist(), key=str)
    if len(values) != 2:
        raise NodeError(f"Конечные классы: целевой «{target}» должен иметь два значения, а их {len(values)}")
    event = p.get("event") or values[-1]
    hit = (y.astype("string") == str(event)).astype(float).where(y.notna())
    max_classes, min_share = int(p.get("max_classes") or 5), float(p.get("min_share") or 0.05)
    x = _num(df[col])
    numeric = x.notna().sum() >= 0.9 * df[col].notna().sum()
    if numeric:
        start = pd.qcut(x, min(20, max(2, x.nunique())), duplicates="drop")
        cats = list(start.cat.categories)
        key = start
    else:
        key = df[col].astype("string")
        order = hit.groupby(key).mean().sort_values()
        cats = list(order.index)
    stats = pd.DataFrame({"k": key, "y": hit}).dropna()
    grp = stats.groupby("k", observed=True)["y"].agg(["sum", "count"]).reindex(cats).fillna(0)
    bins = [[c] for c in cats]
    sums, counts = grp["sum"].tolist(), grp["count"].tolist()
    total = sum(counts) or 1

    def rate(i: int) -> float:
        return sums[i] / counts[i] if counts[i] else 0.0

    while len(bins) > 1 and (len(bins) > max_classes or min(counts) / total < min_share):
        small = int(np.argmin(counts))
        if min(counts) / total < min_share:  # мелкий класс — к соседу с ближайшей долей событий
            if small == 0:
                j = 0
            elif small == len(bins) - 1:
                j = small - 1
            else:
                j = small - 1 if abs(rate(small) - rate(small - 1)) <= abs(rate(small) - rate(small + 1)) else small
        else:  # слишком много классов — сливаем самую похожую соседнюю пару
            # при равной разнице долей — самая маленькая пара: классы выходят ровнее
            j = min(range(len(bins) - 1),
                    key=lambda i: (round(abs(rate(i) - rate(i + 1)), 9), counts[i] + counts[i + 1]))
        bins[j:j + 2] = [bins[j] + bins[j + 1]]
        sums[j:j + 2] = [sums[j] + sums[j + 1]]
        counts[j:j + 2] = [counts[j] + counts[j + 1]]
    to_class = {c: i + 1 for i, b in enumerate(bins) for c in b}
    bad_all, good_all = sum(sums), total - sum(sums)
    woe = {i + 1: _woe(sums[i], counts[i] - sums[i], bad_all, good_all) for i in range(len(bins))}
    cls = key.astype(object).map(to_class).astype("Int64")
    df[p.get("as") or f"{col}_класс"] = cls
    df[f"{col}_woe"] = cls.map(woe).astype(float)
    return df


# --- разбиение на множества -----------------------------------------------------------------------

def split_sets(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"].copy()
    test, valid = float(p.get("test_share") or 0.2), float(p.get("valid_share") or 0)
    if not 0 < test < 1 or not 0 <= valid < 1 or test + valid >= 1:
        raise NodeError("Разбиение: доли тестового и валидационного — от 0 до 1, в сумме меньше 1")
    rng = np.random.default_rng(int(p.get("seed") or SEED))
    group, strat = p.get("group"), p.get("stratify")
    _need(df, [c for c in (group, strat) if c], "Разбиение на множества")
    labels = np.array(["обучающее"] * len(df), dtype=object)
    if group:  # все строки группы (например, компании) — в одном множестве, иначе утечка
        ids = np.array(df[group].astype("string").fillna("—").unique().tolist(), dtype=object)
        rng.shuffle(ids)
        n_t, n_v = round(len(ids) * test), round(len(ids) * valid)
        where = {g: "тестовое" for g in ids[:n_t]} | {g: "валидационное" for g in ids[n_t:n_t + n_v]}
        labels = df[group].astype("string").fillna("—").map(lambda g: where.get(g, "обучающее")).to_numpy()
    else:
        parts = [df.index] if not strat else [ix for _, ix in df.groupby(strat, dropna=False).groups.items()]
        pos = {ix: i for i, ix in enumerate(df.index)}
        for ix in parts:
            idx = np.array([pos[i] for i in ix])
            rng.shuffle(idx)
            n_t, n_v = round(len(idx) * test), round(len(idx) * valid)
            labels[idx[:n_t]] = "тестовое"
            labels[idx[n_t:n_t + n_v]] = "валидационное"
    df[p.get("as") or "множество"] = labels
    return df


# --- выбросы --------------------------------------------------------------------------------------

def outliers(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"].copy()
    cols: list[str] = p.get("columns") or []
    _need(df, cols, "Редактирование выбросов")
    if not cols:
        raise NodeError("Редактирование выбросов: выберите столбцы")
    how, action, k = p.get("method", "iqr"), p.get("action", "clip"), float(p.get("k") or 0)
    drop = pd.Series(False, index=df.index)
    flag = pd.Series(False, index=df.index)
    for c in cols:
        x = _num(df[c])
        if how == "zscore":
            k = k or 3.0
            mu, sd = x.mean(), x.std()
            lo, hi = mu - k * sd, mu + k * sd
        elif how == "quantile":
            q = k or 0.01
            lo, hi = x.quantile(q), x.quantile(1 - q)
        else:
            k = k or 1.5
            q1, q3 = x.quantile(0.25), x.quantile(0.75)
            lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
        out = (x < lo) | (x > hi)
        if action == "clip":
            df[c] = x.clip(lo, hi)
        elif action == "missing":
            df[c] = x.mask(out)
        elif action == "drop":
            drop |= out
        else:
            flag |= out
    if action == "flag":
        df[p.get("as") or "выброс"] = flag
    return df[~drop].reset_index(drop=True)


# --- сглаживание ----------------------------------------------------------------------------------

def smooth(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    cols: list[str] = p.get("columns") or []
    by: list[str] = p.get("group_by") or []
    order = p.get("order_by")
    _need(df, cols + by + ([order] if order else []), "Сглаживание")
    if not cols:
        raise NodeError("Сглаживание: выберите столбцы")
    out = df.sort_values([*by, order], kind="stable").reset_index(drop=True) if order else df.copy()
    how, w = p.get("method", "mean"), int(p.get("window") or 3)
    alpha = float(p.get("alpha") or 0.3)
    if w < 2 or not 0 < alpha <= 1:
        raise NodeError("Сглаживание: окно — от 2, коэффициент — от 0 до 1")
    for c in cols:
        x = _num(out[c])
        g = x.groupby([out[b] for b in by], dropna=False) if by else None

        def apply(s: pd.Series) -> pd.Series:
            if how == "exp":
                return s.ewm(alpha=alpha, adjust=False).mean()
            roll = s.rolling(w, min_periods=1, center=bool(p.get("center")))
            return roll.median() if how == "median" else roll.mean()

        out[_target(p, c, "сгл")] = g.transform(apply) if g is not None else apply(x)
    return out


# --- сэмплинг -------------------------------------------------------------------------------------

def sample(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    how = p.get("method", "share")
    seed = int(p.get("seed") or SEED)
    size = float(p.get("size") or (0.1 if how == "share" else 100))
    strat = p.get("stratify")
    replace = bool(p.get("replace"))
    _need(df, [strat] if strat else [], "Сэмплинг")
    if how == "share" and not 0 < size <= (10 if replace else 1):
        raise NodeError("Сэмплинг: доля — от 0 до 1 (с возвращением — до 10)")
    if how == "count" and size < 1:
        raise NodeError("Сэмплинг: число строк — от 1")

    def take(part: Frame) -> Frame:
        if how == "share":
            return part.sample(frac=size, replace=replace, random_state=seed)
        n = int(size) if replace else min(int(size), len(part))
        return part.sample(n=n, replace=replace, random_state=seed)

    if strat:
        if how == "count":
            raise NodeError("Сэмплинг: по слоям — только долей")
        out = pd.concat([take(part) for _, part in df.groupby(strat, dropna=False, sort=True)])
    else:
        out = take(df)
    return out.reset_index(drop=True)


# --- нормализация ---------------------------------------------------------------------------------

NORM = (("zscore", "стандартизация (z)"), ("minmax", "в диапазон 0…1"), ("robust", "по медиане и IQR"),
        ("log", "логарифм ln(1+x)"), ("onehot", "дискретный: столбцы 0/1"),
        ("ordinal", "дискретный: номер значения"), ("frequency", "дискретный: частота значения"))


def normalize(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"].copy()
    rules: list[Params] = p.get("rules") or []
    _need(df, [r["column"] for r in rules], "Нормализация")
    if not rules:
        raise NodeError("Нормализация: добавьте хотя бы одно правило")
    for r in rules:
        c, how = r["column"], r.get("method", "zscore")
        name = _target(p, c, how)
        if how in ("onehot", "ordinal", "frequency"):
            s = df[c].astype("string")
            if how == "onehot":
                dummies = pd.get_dummies(s, prefix=c, prefix_sep="=", dtype=int)
                if len(dummies.columns) > 200:
                    raise NodeError(f"Нормализация «{c}»: значений больше 200 — столбцов 0/1 будет слишком много")
                df = pd.concat([df.drop(columns=[c]) if p.get("replace") else df, dummies], axis=1)
            elif how == "ordinal":
                codes = {v: i + 1 for i, v in enumerate(sorted(s.dropna().unique()))}
                df[name] = s.map(codes).astype("Int64")
            else:
                df[name] = s.map(s.value_counts(normalize=True)).astype(float)
            continue
        x = _num(df[c])
        if how == "zscore":
            sd = x.std()
            df[name] = (x - x.mean()) / sd if sd else 0.0
        elif how == "minmax":
            span = x.max() - x.min()
            df[name] = (x - x.min()) / span if span else 0.0
        elif how == "robust":
            iqr = x.quantile(0.75) - x.quantile(0.25)
            df[name] = (x - x.median()) / iqr if iqr else 0.0
        elif how == "log":
            if (x < 0).any():
                raise NodeError(f"Нормализация «{c}»: логарифм — только для неотрицательных значений")
            df[name] = np.log1p(x)
        else:
            raise NodeError(f"Нормализация: нет способа «{how}»")
    return df


def _cols(name: str = "columns", label: str = "Столбцы", required: bool = True) -> Param:
    return Param(name, label, "columns", required=required)


REPLACE = Param("replace", "Заменить исходные столбцы (иначе — новые рядом)", "bool", required=False)

COMPONENTS = [
    Component("preprocess.fill", "Заполнение пропусков", GROUP,
              "Пустые значения — средним, медианой, соседним значением, константой; или удалить строки",
              ("in",), (Param("rules", "Правила", "rows", fields=(
                  Param("column", "Столбец", "column"),
                  Param("method", "Чем заполнить", "select", default="median", options=FILL),
                  Param("value", "Значение (для «значение»)", "text", required=False))),
                  _cols("group_by", "Внутри групп (например, компания)", required=False),
                  Param("order_by", "Порядок для «предыдущее/следующее»", "column", required=False)),
              fill_missing),
    Component("preprocess.binning", "Квантование", GROUP,
              "Число — в интервалы: равной ширины, равной наполненности или по своим границам",
              ("in",), (Param("column", "Столбец", "column"),
                        Param("method", "Интервалы", "select", default="quantile",
                              options=(("quantile", "равной наполненности"), ("width", "равной ширины"),
                                       ("edges", "свои границы"))),
                        Param("bins", "Сколько интервалов", "number", required=False, default=5),
                        Param("edges", "Границы через «;»", "text", required=False),
                        Param("labels", "Подпись", "select", required=False, default="interval",
                              options=(("interval", "интервал (a, b]"), ("number", "номер 1, 2, …"))),
                        Param("as", "Имя нового столбца", "text", required=False)), binning),
    Component("preprocess.classes", "Конечные классы", GROUP,
              "Признак — в несколько классов по связи с целевым (да/нет); номер класса и WoE",
              ("in",), (Param("column", "Признак", "column"), Param("target", "Целевой (два значения)", "column"),
                        Param("event", "Значение-«событие»", "text", required=False),
                        Param("max_classes", "Классов не больше", "number", required=False, default=5),
                        Param("min_share", "Доля строк в классе не меньше", "number", required=False, default=0.05),
                        Param("as", "Имя столбца класса", "text", required=False)), final_classes),
    Component("preprocess.split", "Разбиение на множества", GROUP,
              "Обучающее, тестовое и валидационное — столбцом «множество» (seed — повторяемо)",
              ("in",), (Param("test_share", "Доля тестового", "number", default=0.2),
                        Param("valid_share", "Доля валидационного", "number", required=False, default=0),
                        Param("group", "Группа целиком в одно множество (например, компания)", "column",
                              required=False),
                        Param("stratify", "Сохранить доли по столбцу (стратификация)", "column", required=False),
                        Param("seed", "Seed", "number", required=False, default=SEED),
                        Param("as", "Имя столбца", "text", required=False)), split_sets),
    Component("preprocess.outliers", "Редактирование выбросов", GROUP,
              "Выбросы по IQR, z-оценке или квантилям: обрезать, сделать пустыми, удалить или отметить",
              ("in",), (_cols(),
                        Param("method", "Как найти", "select", default="iqr",
                              options=(("iqr", "межквартильный размах (k·IQR)"), ("zscore", "z-оценка (k·σ)"),
                                       ("quantile", "квантили (k и 1−k)"))),
                        Param("k", "k (пусто — 1,5 / 3 / 0,01)", "number", required=False),
                        Param("action", "Что сделать", "select", default="clip",
                              options=(("clip", "обрезать до границы"), ("missing", "сделать пустыми"),
                                       ("drop", "удалить строки"), ("flag", "отметить столбцом")))), outliers),
    Component("preprocess.smooth", "Сглаживание", GROUP,
              "Скользящее среднее или медиана, экспоненциальное сглаживание — по ряду или внутри групп",
              ("in",), (_cols(),
                        Param("method", "Способ", "select", default="mean",
                              options=(("mean", "скользящее среднее"), ("median", "скользящая медиана"),
                                       ("exp", "экспоненциальное"))),
                        Param("window", "Окно", "number", required=False, default=3),
                        Param("alpha", "Коэффициент (для экспоненциального)", "number", required=False, default=0.3),
                        Param("center", "Окно по центру", "bool", required=False),
                        _cols("group_by", "Внутри групп", required=False),
                        Param("order_by", "Порядок (например, год)", "column", required=False), REPLACE), smooth),
    Component("preprocess.sample", "Сэмплинг", GROUP,
              "Случайная выборка строк: долей или числом, по слоям, с возвращением (бутстреп)",
              ("in",), (Param("method", "Размер", "select", default="share",
                              options=(("share", "долей"), ("count", "числом строк"))),
                        Param("size", "Доля или число", "number", default=0.1),
                        Param("stratify", "По слоям (столбец)", "column", required=False),
                        Param("replace", "С возвращением", "bool", required=False),
                        Param("seed", "Seed", "number", required=False, default=SEED)), sample),
    Component("preprocess.normalize", "Нормализация", GROUP,
              "Непрерывные: z, 0…1, медиана/IQR, логарифм; дискретные: столбцы 0/1, номер, частота",
              ("in",), (Param("rules", "Правила", "rows", fields=(
                  Param("column", "Столбец", "column"),
                  Param("method", "Способ", "select", default="zscore", options=NORM))), REPLACE), normalize),
]
