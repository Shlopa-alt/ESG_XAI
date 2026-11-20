"""Студия, этап 4: управление (группа «Управление» Loginom) и переменные.

Подмодель и Цикл считают другой сценарий: платформа вкладывает его граф в параметры узла
(__graph__) той версией, что была при запуске, — расчёт повторяем. Данные во вложенный сценарий
приходят через узлы «Вход подмодели», обратно — из «Выхода подмодели».

Переменные: у сценария — свои (graph["variables"]); узел видит переменные сценария и всех узлов
перед ним; узлы этой группы добавляют свои — через df.attrs["vars"] (движок забирает).
В выражениях переменная — $имя.
"""

from typing import Any

import pandas as pd

from studio.components import Component, NodeError, Param
from studio.expr import ExprError, column, evaluate

Frame = pd.DataFrame
Params = dict[str, Any]
GROUP = "Управление"
VARS = "Переменные"
MAX_LOOP = 1000


def _vars(df: Frame, new: dict[str, Any]) -> Frame:
    df.attrs["vars"] = new
    return df


def _scalar(v: Any) -> Any:
    if isinstance(v, pd.Series):
        v = v.iloc[0] if len(v) else None
    if hasattr(v, "item"):
        v = v.item()
    return None if v is pd.NA or (isinstance(v, float) and v != v) else v


def _one_row(vars_: dict[str, Any]) -> Frame:
    return pd.DataFrame(index=[0]) if not vars_ else pd.DataFrame([vars_])


# --- управление -----------------------------------------------------------------------------------

def condition(inp: dict[str, Frame], p: Params) -> Frame:
    """Условие: выполнено — таблица идёт дальше; нет — пустая таблица (или остановка ветки)."""
    df = inp["in"]
    vars_ = {**p.get("__vars__", {}), "СТРОК": len(df)}
    try:
        ok = _scalar(evaluate(str(p["expr"]), _one_row({}), vars_))
    except ExprError as exc:
        raise NodeError(f"Условие: {exc} (в условии — переменные: $СТРОК, $год…)") from exc
    if bool(ok):
        return df
    if p.get("otherwise") == "stop":
        raise NodeError(f"Условие не выполнено: {p['expr']} — ветка остановлена")
    return df.iloc[0:0].copy()


def node_ref(inp: dict[str, Frame], p: Params) -> Frame:
    """Узел-ссылка: результат другого узла без связи на схеме (удобно в больших сценариях)."""
    frame = p.get("__linked__", {}).get(p["node"])
    if frame is None:
        raise NodeError("Узел-ссылка: узел ещё не посчитан")
    return frame.copy()


def run_after(inp: dict[str, Frame], p: Params) -> Frame:
    """Выполнение узла: таблица проходит как есть, но только после указанных узлов."""
    return inp["in"]


def sub_input(inp: dict[str, Frame], p: Params) -> Frame:
    """Вход подмодели: данные от узла «Подмодель» / «Цикл»; при обычном запуске — пробные
    данные с его входа (так подмодель можно отлаживать саму по себе)."""
    port = p.get("port") or "in"
    given = p.get("__inject__", {}).get(port)
    if given is not None:
        return given.copy()
    if "in" in inp:
        return inp["in"]
    raise NodeError("Вход подмодели: данных нет — сценарий считается как подмодель или подключите пробные данные")


def sub_output(inp: dict[str, Frame], p: Params) -> Frame:
    return inp["in"]


def _run_sub(p: Params, frames: dict[str, Frame], extra_vars: dict[str, Any], tag: str) -> Frame:
    from studio import engine  # здесь: движок импортирует компоненты

    graph = p.get("__graph__")
    if not isinstance(graph, dict):
        raise NodeError("Подмодель: сценарий не вложен — запустите расчёт с платформы")
    outs = [n["id"] for n in graph.get("nodes") or [] if n.get("type") == "control.output"]
    if len(outs) != 1:
        raise NodeError(f"Подмодель {p.get('scenario')}: нужен ровно один «Выход подмодели», а их {len(outs)}")
    load = p["__load__"]
    prefix = f"{p['__node__']}/"

    def sub_load(n: dict[str, Any]) -> Frame:
        return load({**n, "id": prefix + n["id"]})

    res = engine.run(graph, sub_load, until=outs[0], inject=frames,
                     variables={**p.get("__vars__", {}), **extra_vars})
    out = res[outs[0]]
    if out.frame is None:
        bad = next((r for r in res.values() if r.error and not r.skipped), out)
        raise NodeError(f"Подмодель {p.get('scenario')}{tag}, узел {bad.node}: {bad.error}")
    return out.frame


def submodel(inp: dict[str, Frame], p: Params) -> Frame:
    return _run_sub(p, {k: v for k, v in inp.items() if k in ("in", "in2")}, {}, "")


def loop(inp: dict[str, Frame], p: Params) -> Frame:
    """Цикл: подмодель — для каждого значения столбца (например, каждой отрасли); результаты —
    одной таблицей, со столбцом значения. Внутри значение — переменная $ЦИКЛ."""
    df = inp["in"]
    col = p["by"]
    if col not in df.columns:
        raise NodeError(f"Цикл: нет столбца {col}")
    values = df[col].dropna().unique().tolist()
    if len(values) > MAX_LOOP:
        raise NodeError(f"Цикл: значений {len(values)} — больше {MAX_LOOP}")
    name = p.get("as") or col
    parts = []
    for v in sorted(values, key=str):
        part = df[df[col] == v]
        out = _run_sub(p, {"in": part, **({"in2": inp["in2"]} if "in2" in inp else {})},
                       {"ЦИКЛ": _scalar(v)}, f" (значение {v})").copy()
        if name in out.columns:
            out = out.drop(columns=[name])
        out.insert(0, name, v)
        parts.append(out)
    return pd.concat(parts, ignore_index=True) if parts else df.iloc[0:0].copy()


# --- переменные -----------------------------------------------------------------------------------

def table_to_vars(inp: dict[str, Frame], p: Params) -> Frame:
    df = inp["in"]
    row = int(p.get("row") or 1)
    if not 1 <= row <= len(df):
        raise NodeError(f"Таблица в переменные: строки {row} нет (строк {len(df)})")
    cols: list[str] = p.get("columns") or list(df.columns)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise NodeError(f"Таблица в переменные: нет столбцов {', '.join(missing)}")
    return _vars(df, {str(c): _scalar(df[c].iloc[row - 1]) for c in cols})


def vars_to_table(inp: dict[str, Frame], p: Params) -> Frame:
    v = p.get("__vars__", {})
    return pd.DataFrame({"переменная": list(v), "значение": [str(x) for x in v.values()]})


def vars_calc(inp: dict[str, Frame], p: Params) -> Frame:
    new: dict[str, Any] = {}
    seen = dict(p.get("__vars__", {}))
    for f in p.get("fields") or []:
        name = str(f.get("name") or "").strip().lstrip("$")
        if not name:
            raise NodeError("Калькулятор переменных: у переменной нет имени")
        try:
            val = _scalar(column(str(f.get("expr") or ""), _one_row({}), seen))
        except ExprError as exc:
            raise NodeError(f"Калькулятор переменных, ${name}: {exc}") from exc
        seen[name] = new[name] = val
    df = inp["in"] if "in" in inp else pd.DataFrame({"переменная": list(new), "значение": list(new.values())})
    return _vars(df, new)


def vars_replace(inp: dict[str, Frame], p: Params) -> Frame:
    name = str(p["variable"]).lstrip("$")
    seen = p.get("__vars__", {})
    if name not in seen:
        raise NodeError(f"Замена переменной: нет переменной ${name}")
    cur = str(seen[name])
    mapping = {str(r["find"]): r.get("to", "") for r in p.get("rules") or []}
    val = mapping.get(cur, cur if p.get("others_mode", "keep") == "keep" else p.get("others", ""))
    df = inp["in"] if "in" in inp else pd.DataFrame({"переменная": [name], "значение": [val]})
    return _vars(df, {name: val})


def vars_join(inp: dict[str, Frame], p: Params) -> Frame:
    """Соединение переменных: таблица — с первого входа; переменные обоих входов (при совпадении
    имён — по выбору)."""
    seen = p.get("__vars__", {})
    # движок уже слил переменные входов (второй поверх первого); «первый важнее» — первый сверху
    first = p.get("__port_vars__", {}).get("in", {})
    if p.get("prefer") == "first":
        return _vars(inp["in"], {**seen, **first})
    return _vars(inp["in"], dict(seen))


COMPONENTS = [
    Component("control.condition", "Условие", GROUP,
              "Ветка идёт дальше, только если условие выполнено: $СТРОК > 0, $год >= 2020…",
              ("in",), (Param("expr", "Условие", "expr", hint="Например: $СТРОК > 10 И $год >= 2020"),
                        Param("otherwise", "Если не выполнено", "select", required=False, default="empty",
                              options=(("empty", "дальше — пустая таблица"), ("stop", "остановить ветку с ошибкой")))),
              condition),
    Component("control.ref", "Узел-ссылка", GROUP, "Результат другого узла — без линии через всю схему",
              (), (Param("node", "Узел", "node"),), node_ref, dep_params=("node",)),
    Component("control.exec", "Выполнение узла", GROUP,
              "Таблица идёт дальше только после того, как посчитаны указанные узлы",
              ("in",), (Param("after", "После узлов", "nodes"),), run_after, dep_params=("after",)),
    Component("control.input", "Вход подмодели", GROUP,
              "Сюда подмодель получает данные; свой вход — пробные данные для отладки",
              ("in",), (Param("port", "Какой вход подмодели", "select", required=False, default="in",
                              options=(("in", "первый"), ("in2", "второй"))),), sub_input, optional=("in",),
              input_labels=("Пробные данные",)),
    Component("control.output", "Выход подмодели", GROUP, "Отсюда подмодель отдаёт результат",
              ("in",), (), sub_output),
    Component("control.submodel", "Подмодель", GROUP,
              "Другой сценарий как один узел: данные — в его «Вход подмодели», результат — из «Выхода»",
              ("in", "in2"), (Param("scenario", "Сценарий", "scenario"),
                              Param("version", "Версия (пусто — текущая на момент запуска)", "number",
                                    required=False)),
              submodel, optional=("in", "in2"), input_labels=("Вход 1", "Вход 2")),
    Component("control.loop", "Цикл", GROUP,
              "Подмодель — для каждого значения столбца (например, каждой отрасли), итог — одной таблицей",
              ("in", "in2"), (Param("scenario", "Сценарий-подмодель", "scenario"),
                              Param("version", "Версия (пусто — текущая)", "number", required=False),
                              Param("by", "Для каждого значения столбца", "column"),
                              Param("as", "Имя столбца значения", "text", required=False)),
              loop, optional=("in2",), input_labels=("Данные", "Вход 2 (общий)")),
    Component("vars.from_table", "Таблица в переменные", VARS,
              "Значения строки таблицы — в переменные $столбец; таблица идёт дальше как есть",
              ("in",), (Param("row", "Номер строки", "number", required=False, default=1),
                        Param("columns", "Столбцы (пусто — все)", "columns", required=False)), table_to_vars),
    Component("vars.to_table", "Переменные в таблицу", VARS, "Все видимые переменные — таблицей «имя — значение»",
              ("in",), (), vars_to_table, optional=("in",)),
    Component("vars.calc", "Калькулятор (переменные)", VARS, "Новые переменные по формулам из других: $год - 1",
              ("in",), (Param("fields", "Переменные", "rows",
                              fields=(Param("name", "Имя", "text"), Param("expr", "Выражение", "expr"))),),
              vars_calc, optional=("in",)),
    Component("vars.replace", "Замена (переменные)", VARS, "Значение переменной по списку замен",
              ("in",), (Param("variable", "Переменная", "text"),
                        Param("rules", "Правила", "rows",
                              fields=(Param("find", "Что", "text"), Param("to", "На что", "text", required=False))),
                        Param("others_mode", "Остальные значения", "select", required=False, default="keep",
                              options=(("keep", "оставить"), ("value", "заменить на…"))),
                        Param("others", "…на что", "text", required=False)),
              vars_replace, optional=("in",)),
    Component("vars.join", "Соединение (переменные)", VARS,
              "Переменные двух ветвей вместе; таблица — с первого входа",
              ("in", "in2"), (Param("prefer", "При совпадении имён", "select", required=False, default="second",
                                    options=(("second", "важнее второй вход"), ("first", "важнее первый вход"))),),
              vars_join, input_labels=("Вход 1", "Вход 2")),
]
