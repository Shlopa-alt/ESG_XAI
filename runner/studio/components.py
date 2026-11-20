"""Компоненты Студии: узлы сценария, как в Loginom (группы «Трансформация», импорт, экспорт).

Компонент — описание для редактора (название, группа, входы, параметры) и функция над таблицами
pandas. Параметры описаны схемой PARAMS: по ней редактор рисует форму, а движок проверяет
значения до расчёта, чтобы ошибка говорила, какой узел и какое поле не так.

Виды параметров:
  column / columns — столбец / столбцы входа «in» (или указанного в from_port);
  text, number, bool, select (options) — значения;
  rows — список строк-настроек, поля строки — в fields (тот же формат).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from studio.expr import ExprError, column, mask


class NodeError(ValueError):
    """Ошибка в настройке или данных узла — человеку понятным текстом."""


Frame = pd.DataFrame
Params = dict[str, Any]


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    kind: str
    required: bool = True
    default: Any = None
    options: tuple[tuple[str, str], ...] = ()
    fields: tuple["Param", ...] = ()
    from_port: str = "in"
    hint: str = ""

    def schema(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "label": self.label, "kind": self.kind,
                               "required": self.required}
        if self.default is not None:
            out["default"] = self.default
        if self.options:
            out["options"] = [{"value": v, "label": lbl} for v, lbl in self.options]
        if self.fields:
            out["fields"] = [f.schema() for f in self.fields]
        if self.kind in ("column", "columns"):
            out["from_port"] = self.from_port
        if self.hint:
            out["hint"] = self.hint
        return out


@dataclass(frozen=True)
class Component:
    type: str
    title: str
    group: str
    description: str
    inputs: tuple[str, ...]
    params: tuple[Param, ...]
    run: Callable[[dict[str, Frame], Params], Frame] = field(repr=False)
    input_labels: tuple[str, ...] = ()

    def schema(self) -> dict[str, Any]:
        labels = self.input_labels or tuple("Вход" for _ in self.inputs)
        return {"type": self.type, "title": self.title, "group": self.group,
                "description": self.description,
                "inputs": [{"name": n, "label": lbl} for n, lbl in zip(self.inputs, labels, strict=True)],
                "params": [p.schema() for p in self.params]}


AGG = (("sum", "сумма"), ("mean", "среднее"), ("median", "медиана"), ("min", "минимум"),
       ("max", "максимум"), ("count", "количество"), ("nunique", "различных"),
       ("std", "ст. отклонение"), ("var", "дисперсия"), ("first", "первое"), ("last", "последнее"))
AGG_NAMES = dict(AGG)


def _need(df: Frame, cols: list[str], where: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise NodeError(f"{where}: нет столбцов {', '.join(missing)}")


def _agg_name(row: Params) -> str:
    return str(row.get("as") or f"{row['column']}_{row['func']}")


# --- трансформация -------------------------------------------------------------------------------


def group(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    keys: list[str] = p.get("keys") or []
    aggs: list[Params] = p.get("aggregations") or []
    _need(df, keys + [a["column"] for a in aggs], "Группировка")
    if not aggs:
        raise NodeError("Группировка: добавьте хотя бы одно вычисление (столбец и функцию)")
    named = {_agg_name(a): pd.NamedAgg(column=a["column"], aggfunc=a["func"]) for a in aggs}
    data = df.copy()
    for a in aggs:
        if a["func"] not in ("count", "nunique", "first", "last"):
            data[a["column"]] = pd.to_numeric(data[a["column"]], errors="coerce")
    if not keys:  # без полей группы — одна строка итогов по всей таблице
        return pd.DataFrame({n: [data[a.column].agg(a.aggfunc)] for n, a in named.items()})
    return data.groupby(keys, dropna=False, sort=True).agg(**named).reset_index()


def ungroup(inp: dict[str, Frame], p: Params) -> Frame:
    """Разгруппировка: итоги по группам — в каждую строку исходной таблицы."""
    df = inp["in"]
    keys: list[str] = p.get("keys") or []
    aggs: list[Params] = p.get("aggregations") or []
    _need(df, keys + [a["column"] for a in aggs], "Разгруппировка")
    if not keys or not aggs:
        raise NodeError("Разгруппировка: нужны поля группы и хотя бы одно вычисление")
    out = df.copy()
    for a in aggs:
        src = out[a["column"]] if a["func"] in ("count", "nunique", "first", "last") \
            else pd.to_numeric(out[a["column"]], errors="coerce")
        out[_agg_name(a)] = src.groupby([out[k] for k in keys], dropna=False).transform(a["func"])
    return out


def date_time(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"].copy()
    col = p["column"]
    _need(df, [col], "Дата и время")
    d = pd.to_datetime(df[col], errors="coerce", dayfirst=bool(p.get("dayfirst", True)))
    parts = {
        "year": ("год", lambda s: s.dt.year.astype("Int64")),
        "quarter": ("квартал", lambda s: s.dt.quarter.astype("Int64")),
        "month": ("месяц", lambda s: s.dt.month.astype("Int64")),
        "week": ("неделя", lambda s: s.dt.isocalendar().week.astype("Int64")),
        "day": ("день", lambda s: s.dt.day.astype("Int64")),
        "weekday": ("день_недели", lambda s: (s.dt.weekday + 1).astype("Int64")),
        "date": ("дата", lambda s: s.dt.normalize()),
        "year_month": ("год_месяц", lambda s: s.dt.strftime("%Y-%m")),
        "year_quarter": ("год_квартал", lambda s: s.dt.year.astype("Int64").astype("string") + "-Q"
                         + s.dt.quarter.astype("Int64").astype("string")),
    }
    chosen: list[str] = p.get("parts") or ["year", "month"]
    for part in chosen:
        if part not in parts:
            raise NodeError(f"Дата и время: нет части «{part}»")
        suffix, fn = parts[part]
        df[f"{col}_{suffix}"] = fn(d)
    return df


def lookup(inp: dict[str, Frame], p: Params) -> Frame:
    """Дополнение данных: к строкам таблицы — поля справочника по ключу (первое совпадение)."""
    df, ref = inp["in"], inp["ref"]
    key, ref_key = p["key"], p.get("ref_key") or p["key"]
    _need(df, [key], "Дополнение данных (таблица)")
    _need(ref, [ref_key], "Дополнение данных (справочник)")
    cols: list[str] = p.get("columns") or [c for c in ref.columns if c != ref_key]
    _need(ref, cols, "Дополнение данных (справочник)")
    r = ref[[ref_key, *[c for c in cols if c != ref_key]]].drop_duplicates(subset=[ref_key], keep="first")
    r = r.rename(columns={c: (f"{c}_спр" if c in df.columns and c != key else c) for c in r.columns
                          if c != ref_key})
    if ref_key != key:
        r = r.rename(columns={ref_key: key})
    return df.merge(r, on=key, how="left", validate="many_to_one")


def replace(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"].copy()
    col = p["column"]
    _need(df, [col], "Замена")
    mode = p.get("mode", "exact")
    rules: list[Params] = p.get("rules") or []
    if not rules:
        raise NodeError("Замена: добавьте хотя бы одно правило «что → на что»")
    src = df[col]
    if mode == "regex":
        out = src.astype("string")
        for r in rules:
            try:
                out = out.str.replace(str(r["find"]), str(r.get("to", "")), regex=True)
            except Exception as exc:  # noqa: BLE001 — re.error и родственные
                raise NodeError(f"Замена: неверное регулярное выражение «{r['find']}»: {exc}") from exc
    else:
        mapping = {str(r["find"]): r.get("to", "") for r in rules}
        as_text = src.astype("string")
        hit = as_text.isin(mapping.keys())
        out = src.astype(object).where(~hit, as_text.map(mapping))
        if p.get("others_mode") == "value":
            out = out.where(hit, p.get("others", ""))
    target = p.get("as") or col
    df[target] = pd.Series(out, index=df.index).infer_objects()
    return df


def calculator(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"].copy()
    fields: list[Params] = p.get("fields") or []
    if not fields:
        raise NodeError("Калькулятор: добавьте хотя бы одно поле (имя и выражение)")
    for f in fields:
        name = str(f.get("name") or "").strip()
        if not name:
            raise NodeError("Калькулятор: у поля нет имени")
        try:
            df[name] = column(str(f.get("expr") or ""), df)  # следующие поля видят предыдущие
        except ExprError as exc:
            raise NodeError(f"Калькулятор, поле «{name}»: {exc}") from exc
    return df


def crosstab(inp: dict[str, Frame], p: Params) -> Frame:
    """Кросс-таблица: строки — поля строк, столбцы — значения поля столбцов, в ячейках — итог."""
    df = inp["in"]
    rows: list[str] = p.get("rows") or []
    col, val, func = p["columns_field"], p.get("value"), p.get("func", "sum")
    _need(df, rows + [col] + ([val] if val else []), "Кросс-таблица")
    if not rows:
        raise NodeError("Кросс-таблица: выберите поля строк")
    data = df.copy()
    if val is None or func == "count":
        data["_n"] = 1
        val, func = "_n", "sum"
    else:
        data[val] = pd.to_numeric(data[val], errors="coerce")
    out = data.pivot_table(index=rows, columns=col, values=val, aggfunc=func, dropna=False)
    out.columns = [str(c) for c in out.columns]
    return out.reset_index()


def union(inp: dict[str, Frame], p: Params) -> Frame:
    """Объединение: строки второй таблицы — под строками первой (столбцы — по именам)."""
    a, b = inp["in"], inp["in2"]
    how = p.get("columns", "all")
    if how == "common":
        common = [c for c in a.columns if c in b.columns]
        if not common:
            raise NodeError("Объединение: у таблиц нет общих столбцов")
        a, b = a[common], b[common]
    out = pd.concat([a, b], ignore_index=True, sort=False)
    if p.get("source"):
        out[p["source"]] = ["1"] * len(a) + ["2"] * len(b)
    return out


def field_params(inp: dict[str, Frame], p: Params) -> Frame:
    """Параметры полей: какие столбцы оставить, как назвать, какой тип."""
    df = inp["in"]
    fields: list[Params] = p.get("fields") or []
    _need(df, [f["column"] for f in fields], "Параметры полей")
    out = df.copy()
    for f in fields:
        c = f["column"]
        kind = f.get("type") or "keep"
        try:
            if kind == "number":
                out[c] = pd.to_numeric(out[c].astype("string").str.replace(",", ".", regex=False)
                                       .str.replace(r"\s", "", regex=True), errors="coerce")
            elif kind == "integer":
                out[c] = pd.to_numeric(out[c], errors="coerce").round().astype("Int64")
            elif kind == "string":
                out[c] = out[c].astype("string")
            elif kind == "date":
                out[c] = pd.to_datetime(out[c], errors="coerce", dayfirst=True)
            elif kind == "bool":
                truth = {"1": True, "true": True, "да": True, "истина": True,
                         "0": False, "false": False, "нет": False, "ложь": False}
                out[c] = out[c].astype("string").str.strip().str.lower().map(truth).astype("boolean")
        except (TypeError, ValueError) as exc:
            raise NodeError(f"Параметры полей: столбец «{c}» не приводится к типу {kind}: {exc}") from exc
    drop = [f["column"] for f in fields if f.get("drop")]
    out = out.drop(columns=drop)
    renames = {f["column"]: f["rename"] for f in fields if f.get("rename") and not f.get("drop")}
    names = [renames.get(c, c) for c in out.columns]
    clash = sorted({n for n in names if names.count(n) > 1})
    if clash:
        raise NodeError(f"Параметры полей: имя встречается дважды: {', '.join(map(str, clash))}")
    out = out.rename(columns=renames)
    if p.get("only_listed"):
        keep = [renames.get(f["column"], f["column"]) for f in fields if not f.get("drop")]
        out = out[keep]
    return out


def unpivot(inp: dict[str, Frame], p: Params) -> Frame:
    """Свёртка столбцов: много столбцов-показателей → пары «показатель — значение»."""
    df = inp["in"]
    ids: list[str] = p.get("keep") or []
    vals: list[str] = p.get("columns") or [c for c in df.columns if c not in ids]
    _need(df, ids + vals, "Свёртка столбцов")
    return df.melt(id_vars=ids, value_vars=vals, var_name=p.get("name_as") or "показатель",
                   value_name=p.get("value_as") or "значение")


def window(inp: dict[str, Frame], p: Params) -> Frame:
    """Скользящее окно: прошлые (и будущие) значения столбцов в той же строке — для рядов и панелей."""
    df = inp["in"]
    cols: list[str] = p.get("columns") or []
    by: list[str] = p.get("group_by") or []
    order: str | None = p.get("order_by")
    depth, horizon = int(p.get("depth", 1)), int(p.get("horizon", 0))
    _need(df, cols + by + ([order] if order else []), "Скользящее окно")
    if not cols:
        raise NodeError("Скользящее окно: выберите столбцы")
    if depth < 0 or horizon < 0 or depth + horizon == 0 or depth + horizon > 100:
        raise NodeError("Скользящее окно: глубина и горизонт — от 0, в сумме от 1 до 100")
    out = df.sort_values([*by, order], kind="stable") if order else df.copy()
    g = out.groupby(by, dropna=False, sort=False) if by else None
    for c in cols:
        for k in range(1, depth + 1):
            out[f"{c}-{k}"] = g[c].shift(k) if g is not None else out[c].shift(k)
        for k in range(1, horizon + 1):
            out[f"{c}+{k}"] = g[c].shift(-k) if g is not None else out[c].shift(-k)
    return out.reset_index(drop=True)


JOIN_HOW = (("inner", "внутреннее"), ("left", "левое"), ("right", "правое"), ("outer", "полное"),
            ("anti", "разность (строки первой без пары)"))


def merge(inp: dict[str, Frame], p: Params) -> Frame:
    """Слияние: таблицы по ключевым полям, как SQL JOIN."""
    a, b = inp["in"], inp["in2"]
    keys: list[Params] = p.get("keys") or []
    if not keys:
        raise NodeError("Слияние: укажите хотя бы одну пару ключевых полей")
    left = [k["left"] for k in keys]
    right = [k.get("right") or k["left"] for k in keys]
    _need(a, left, "Слияние (первая таблица)")
    _need(b, right, "Слияние (вторая таблица)")
    how = p.get("how", "inner")
    if how == "anti":
        m = a.merge(b[right].drop_duplicates(), left_on=left, right_on=right, how="left", indicator=True)
        out = m[m["_merge"] == "left_only"]
        return out[list(a.columns)].reset_index(drop=True)
    if how not in dict(JOIN_HOW):
        raise NodeError(f"Слияние: нет способа «{how}»")
    return a.merge(b, left_on=left, right_on=right, how=how, suffixes=("", "_2"))


def side_by_side(inp: dict[str, Frame], p: Params) -> Frame:
    """Соединение: столбцы второй таблицы — справа от первой, строка к строке по порядку."""
    a, b = inp["in"].reset_index(drop=True), inp["in2"].reset_index(drop=True)
    if len(a) != len(b) and not p.get("allow_unequal"):
        raise NodeError(f"Соединение: в таблицах разное число строк ({len(a)} и {len(b)})")
    b = b.rename(columns={c: f"{c}_2" for c in b.columns if c in a.columns})
    return pd.concat([a, b], axis=1)


def sort(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    by: list[Params] = p.get("by") or []
    _need(df, [b["column"] for b in by], "Сортировка")
    if not by:
        raise NodeError("Сортировка: выберите столбцы")
    return df.sort_values([b["column"] for b in by], ascending=[not b.get("desc") for b in by],
                          kind="stable", na_position="last").reset_index(drop=True)


FILTER_OPS = (("=", "равно"), ("!=", "не равно"), (">", "больше"), (">=", "не меньше"),
              ("<", "меньше"), ("<=", "не больше"), ("contains", "содержит"),
              ("starts", "начинается с"), ("empty", "пусто"), ("not_empty", "не пусто"),
              ("in", "одно из (через ;)"))


def _condition(df: Frame, c: Params) -> pd.Series:
    col, op, raw = c["column"], c.get("op", "="), c.get("value", "")
    _need(df, [col], "Фильтр строк")
    s = df[col]
    text = s.astype("string")
    if op == "empty":
        return s.isna() | (text.str.strip() == "")
    if op == "not_empty":
        return ~(s.isna() | (text.str.strip() == ""))
    if op == "contains":
        return text.str.contains(str(raw), case=False, regex=False).fillna(False)
    if op == "starts":
        return text.str.lower().str.startswith(str(raw).lower()).fillna(False)
    if op == "in":
        return text.isin([v.strip() for v in str(raw).split(";")]).fillna(False)
    num = pd.to_numeric(s, errors="coerce")
    try:
        value: Any = float(str(raw).replace(",", "."))
        left: pd.Series = num
    except ValueError:
        value, left = str(raw), text
    ops = {"=": left == value, "!=": left != value, ">": left > value, ">=": left >= value,
           "<": left < value, "<=": left <= value}
    if op not in ops:
        raise NodeError(f"Фильтр строк: нет условия «{op}»")
    return ops[op].fillna(False).astype(bool)


def filter_rows(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    expr = str(p.get("expr") or "").strip()
    conds: list[Params] = p.get("conditions") or []
    if expr:
        try:
            m = mask(expr, df)
        except ExprError as exc:
            raise NodeError(f"Фильтр строк: {exc}") from exc
    elif conds:
        parts = [_condition(df, c) for c in conds]
        m = parts[0]
        for x in parts[1:]:
            m = (m & x) if p.get("join", "and") == "and" else (m | x)
    else:
        raise NodeError("Фильтр строк: задайте условия или выражение")
    if p.get("invert"):
        m = ~m
    return df[m.to_numpy()].reset_index(drop=True)


# --- импорт и экспорт -----------------------------------------------------------------------------


def import_dataset(inp: dict[str, Frame], p: Params) -> Frame:
    """Таблица версии набора данных платформы: движок получает её готовой (inputs["data"])."""
    if "data" not in inp:
        raise NodeError("Импорт: данные версии набора не загружены")
    return inp["data"]


def export_file(inp: dict[str, Frame], p: Params) -> Frame:
    """Экспорт: таблица уходит в файл результатов расчёта (CSV или Excel); сама — дальше без изменений."""
    return inp["in"]


# --- реестр ---------------------------------------------------------------------------------------

AGG_FIELDS = (Param("column", "Столбец", "column"), Param("func", "Функция", "select", options=AGG),
              Param("as", "Имя результата", "text", required=False))
TRANSFORM = "Трансформация"

COMPONENTS: dict[str, Component] = {c.type: c for c in [
    Component("import.dataset", "Набор данных", "Импорт", "Версия набора данных платформы", (),
              (Param("snapshot_id", "Версия набора", "snapshot"),
               Param("sheet", "Лист", "text", required=False)), import_dataset),
    Component("export.file", "Файл", "Экспорт", "Сохранить таблицу файлом среди результатов расчёта",
              ("in",), (Param("name", "Имя файла", "text", default="результат"),
                        Param("format", "Формат", "select", default="csv",
                              options=(("csv", "CSV"), ("xlsx", "Excel")))), export_file),
    Component("transform.group", "Группировка", TRANSFORM, "Итоги по группам: сумма, среднее, количество…",
              ("in",), (Param("keys", "Поля группы", "columns", required=False),
                        Param("aggregations", "Вычисления", "rows", fields=AGG_FIELDS)), group),
    Component("transform.ungroup", "Разгруппировка", TRANSFORM,
              "Итог по группе — в каждую строку исходной таблицы",
              ("in",), (Param("keys", "Поля группы", "columns"),
                        Param("aggregations", "Вычисления", "rows", fields=AGG_FIELDS)), ungroup),
    Component("transform.datetime", "Дата и время", TRANSFORM, "Год, квартал, месяц, день недели… из даты",
              ("in",), (Param("column", "Столбец с датой", "column"),
                        Param("parts", "Что выделить", "multiselect", default=["year", "month"],
                              options=(("year", "год"), ("quarter", "квартал"), ("month", "месяц"),
                                       ("week", "неделя"), ("day", "день"), ("weekday", "день недели"),
                                       ("date", "дата без времени"), ("year_month", "год-месяц"),
                                       ("year_quarter", "год-квартал"))),
                        Param("dayfirst", "День перед месяцем (31.12.2025)", "bool", required=False,
                              default=True)), date_time),
    Component("transform.lookup", "Дополнение данных", TRANSFORM,
              "Поля из справочника по ключу (первое совпадение)", ("in", "ref"),
              (Param("key", "Ключ в таблице", "column"),
               Param("ref_key", "Ключ в справочнике", "column", required=False, from_port="ref"),
               Param("columns", "Какие поля добавить", "columns", required=False, from_port="ref")),
              lookup, input_labels=("Таблица", "Справочник")),
    Component("transform.replace", "Замена", TRANSFORM, "Замена значений по списку или регулярному выражению",
              ("in",), (Param("column", "Столбец", "column"),
                        Param("mode", "Как искать", "select", default="exact",
                              options=(("exact", "точное совпадение"), ("regex", "регулярное выражение"))),
                        Param("rules", "Правила", "rows",
                              fields=(Param("find", "Что", "text"), Param("to", "На что", "text", required=False))),
                        Param("others_mode", "Остальные значения", "select", required=False, default="keep",
                              options=(("keep", "оставить"), ("value", "заменить на…"))),
                        Param("others", "…на что", "text", required=False),
                        Param("as", "Записать в новый столбец", "text", required=False)), replace),
    Component("transform.calculator", "Калькулятор", TRANSFORM,
              "Новые поля по формулам: выручка / сотрудники, ЕСЛИ(…), ГОД(дата)…",
              ("in",), (Param("fields", "Поля", "rows",
                              fields=(Param("name", "Имя", "text"), Param("expr", "Выражение", "expr"))),), calculator),
    Component("transform.crosstab", "Кросс-таблица", TRANSFORM,
              "Сводная: значения поля — в столбцы, в ячейках — итог",
              ("in",), (Param("rows", "Поля строк", "columns"),
                        Param("columns_field", "Поле столбцов", "column"),
                        Param("value", "Поле значений", "column", required=False),
                        Param("func", "Итог", "select", default="sum", options=AGG[:7])), crosstab),
    Component("transform.union", "Объединение", TRANSFORM, "Строки второй таблицы — под первой",
              ("in", "in2"), (Param("columns", "Столбцы", "select", default="all",
                                    options=(("all", "все"), ("common", "только общие"))),
                              Param("source", "Столбец «откуда строка»", "text", required=False)),
              union, input_labels=("Таблица 1", "Таблица 2")),
    Component("transform.fields", "Параметры полей", TRANSFORM, "Тип, имя, удаление столбцов",
              ("in",), (Param("fields", "Поля", "rows",
                              fields=(Param("column", "Столбец", "column"),
                                      Param("type", "Тип", "select", required=False, default="keep",
                                            options=(("keep", "как есть"), ("number", "число"),
                                                     ("integer", "целое"), ("string", "строка"),
                                                     ("date", "дата"), ("bool", "да/нет"))),
                                      Param("rename", "Новое имя", "text", required=False),
                                      Param("drop", "Удалить", "bool", required=False))),
                        Param("only_listed", "Оставить только перечисленные", "bool", required=False)),
              field_params),
    Component("transform.unpivot", "Свёртка столбцов", TRANSFORM,
              "Столбцы-показатели → строки «показатель — значение»",
              ("in",), (Param("keep", "Поля-идентификаторы", "columns", required=False),
                        Param("columns", "Свернуть столбцы", "columns", required=False),
                        Param("name_as", "Имя столбца показателя", "text", required=False),
                        Param("value_as", "Имя столбца значения", "text", required=False)), unpivot),
    Component("transform.window", "Скользящее окно", TRANSFORM,
              "Прошлые и будущие значения в строке (лаги) — по всей таблице или внутри групп",
              ("in",), (Param("columns", "Столбцы", "columns"),
                        Param("group_by", "Внутри групп (например, компания)", "columns", required=False),
                        Param("order_by", "Порядок (например, год)", "column", required=False),
                        Param("depth", "Глубина (сколько прошлых)", "number", default=1),
                        Param("horizon", "Горизонт (сколько будущих)", "number", required=False, default=0)),
              window),
    Component("transform.merge", "Слияние", TRANSFORM, "Две таблицы по ключевым полям (как JOIN)",
              ("in", "in2"), (Param("keys", "Ключевые поля", "rows",
                                    fields=(Param("left", "В первой", "column"),
                                            Param("right", "Во второй", "column", required=False,
                                                  from_port="in2"))),
                              Param("how", "Способ", "select", default="inner", options=JOIN_HOW)),
              merge, input_labels=("Таблица 1", "Таблица 2")),
    Component("transform.join", "Соединение", TRANSFORM, "Столбцы второй таблицы — справа, строка к строке",
              ("in", "in2"), (Param("allow_unequal", "Разрешить разное число строк", "bool", required=False),),
              side_by_side, input_labels=("Таблица 1", "Таблица 2")),
    Component("transform.sort", "Сортировка", TRANSFORM, "Порядок строк по столбцам",
              ("in",), (Param("by", "По столбцам", "rows",
                              fields=(Param("column", "Столбец", "column"),
                                      Param("desc", "По убыванию", "bool", required=False))),), sort),
    Component("transform.filter", "Фильтр строк", TRANSFORM, "Оставить строки по условиям или выражению",
              ("in",), (Param("conditions", "Условия", "rows", required=False,
                              fields=(Param("column", "Столбец", "column"),
                                      Param("op", "Условие", "select", default="=", options=FILTER_OPS),
                                      Param("value", "Значение", "text", required=False))),
                        Param("join", "Условия связать", "select", required=False, default="and",
                              options=(("and", "все выполняются (И)"), ("or", "хотя бы одно (ИЛИ)"))),
                        Param("expr", "Или выражение", "expr", required=False,
                              hint="Например: roe > 0.1 И ГОД(дата) >= 2020"),
                        Param("invert", "Наоборот — убрать такие строки", "bool", required=False)),
              filter_rows),
]}


def catalog() -> list[dict[str, Any]]:
    """Описание всех компонентов для редактора."""
    return [c.schema() for c in COMPONENTS.values()]
