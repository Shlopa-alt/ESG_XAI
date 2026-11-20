"""Движок сценариев Студии: проверить сценарий, посчитать узлы по связям, отдать результат.

Сценарий (format 1) — JSON:

    {"format": 1,
     "nodes": [{"id": "n1", "type": "import.dataset", "title": "...", "params": {...},
                "x": 0, "y": 0}],
     "edges": [{"from": "n1", "to": "n2", "port": "in"}]}

У компонента входы-порты (components.Component.inputs); у каждого узла один выход — таблица.
В порт приходит ровно одна связь. Узлы считаются в порядке зависимостей; для предпросмотра
считается только то, от чего зависит выбранный узел. Ошибка узла — ScenarioError с id узла,
чтобы редактор показал её на нём; остальные узлы, которые от него не зависят, досчитываются.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from studio.components import COMPONENTS, Component, NodeError, Param
from studio.expr import ExprError

FORMAT = 1
MAX_NODES = 300


class ScenarioError(ValueError):
    def __init__(self, node: str, message: str) -> None:
        super().__init__(message)
        self.node, self.message = node, message


@dataclass
class NodeResult:
    node: str
    frame: pd.DataFrame | None = None
    error: str = ""
    seconds: float = 0.0
    skipped: bool = False  # не считался: упал узел, от которого он зависит
    report: dict[str, Any] | None = None  # визуализатор «Отчёт» модели (коэффициенты, метрики…)
    vars: dict[str, Any] = field(default_factory=dict)  # переменные после узла (видны тем, кто после)


@dataclass
class Plan:
    nodes: dict[str, dict[str, Any]]
    inputs: dict[str, dict[str, str]]  # узел → порт → узел-источник
    order: list[str] = field(default_factory=list)
    extra: dict[str, list[str]] = field(default_factory=dict)  # зависимости без связи (Узел-ссылка…)


def _missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def _check_params(node_id: str, comp: Component, params: dict[str, Any]) -> None:
    def check(p: Param, value: Any, where: str) -> None:
        if p.required and _missing(value):
            raise ScenarioError(node_id, f"{comp.title}: не заполнено «{where}»")
        if _missing(value):
            return
        if p.kind == "rows":
            if not isinstance(value, list):
                raise ScenarioError(node_id, f"{comp.title}: «{where}» — список")
            for i, row in enumerate(value, 1):
                if not isinstance(row, dict):
                    raise ScenarioError(node_id, f"{comp.title}: «{where}», строка {i} — не настройка")
                for f in p.fields:
                    check(f, row.get(f.name), f"{where}, строка {i}: {f.label}")
        elif p.kind in ("columns", "multiselect", "nodes") and not isinstance(value, list):
            raise ScenarioError(node_id, f"{comp.title}: «{where}» — список")
        elif p.kind == "number":
            try:
                float(value)
            except (TypeError, ValueError) as exc:
                raise ScenarioError(node_id, f"{comp.title}: «{where}» — число") from exc
        elif p.kind == "select" and p.options and value not in dict(p.options):
            raise ScenarioError(node_id, f"{comp.title}: в «{where}» нет варианта «{value}»")

    for p in comp.params:
        check(p, params.get(p.name, p.default), p.label)


def plan(scenario: dict[str, Any]) -> Plan:
    """Проверка устройства сценария (без данных): компоненты, обязательные поля, связи, циклы."""
    if not isinstance(scenario, dict) or scenario.get("format") != FORMAT:
        raise ScenarioError("", f"Неизвестный формат сценария (нужен {FORMAT})")
    raw_nodes = scenario.get("nodes") or []
    if len(raw_nodes) > MAX_NODES:
        raise ScenarioError("", f"Узлов больше {MAX_NODES}")
    nodes: dict[str, dict[str, Any]] = {}
    for n in raw_nodes:
        nid = str(n.get("id") or "")
        if not nid or nid in nodes:
            raise ScenarioError(nid, "У узла нет id или id повторяется")
        comp = COMPONENTS.get(str(n.get("type")))
        if comp is None:
            raise ScenarioError(nid, f"Неизвестный компонент «{n.get('type')}»")
        nodes[nid] = n
    inputs: dict[str, dict[str, str]] = {nid: {} for nid in nodes}
    for e in scenario.get("edges") or []:
        src, dst, port = str(e.get("from")), str(e.get("to")), str(e.get("port") or "in")
        if src not in nodes or dst not in nodes:
            raise ScenarioError(dst if dst in nodes else "", "Связь ведёт к несуществующему узлу")
        comp = COMPONENTS[nodes[dst]["type"]]
        if port not in comp.inputs:
            raise ScenarioError(dst, f"{comp.title}: нет входа «{port}»")
        if port in inputs[dst]:
            raise ScenarioError(dst, f"{comp.title}: во вход «{port}» уже приходит связь")
        inputs[dst][port] = src
    extra: dict[str, list[str]] = {}
    for nid, n in nodes.items():
        comp = COMPONENTS[n["type"]]
        refs: list[str] = []
        for name in comp.dep_params:
            v = (n.get("params") or {}).get(name)
            refs += [str(x) for x in (v if isinstance(v, list) else [v] if v else [])]
        for r in refs:
            if r not in nodes:
                raise ScenarioError(nid, f"{comp.title}: нет узла «{r}»")
        extra[nid] = refs
    # порядок: Кан — без циклов
    remaining = {nid: set(inputs[nid].values()) | set(extra[nid]) for nid in nodes}
    order: list[str] = []
    ready = [nid for nid in nodes if not remaining[nid]]
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for other, deps in remaining.items():
            if nid in deps:
                deps.discard(nid)
                if not deps and other not in order and other not in ready:
                    ready.append(other)
    if len(order) != len(nodes):
        stuck = next(n for n in nodes if n not in order)
        raise ScenarioError(stuck, "Связи образуют цикл — данные не могут течь по кругу")
    return Plan(nodes=nodes, inputs=inputs, order=order, extra=extra)


def needed(p: Plan, target: str) -> list[str]:
    """Узлы, от которых зависит target (и он сам), в порядке счёта."""
    need: set[str] = set()
    stack = [target]
    while stack:
        nid = stack.pop()
        if nid in need:
            continue
        need.add(nid)
        stack.extend(p.inputs[nid].values())
        stack.extend(p.extra.get(nid, []))
    return [n for n in p.order if n in need]


Loader = Callable[[dict[str, Any]], pd.DataFrame]


def scenario_vars(scenario: dict[str, Any]) -> dict[str, Any]:
    """Переменные сценария: [{"name", "value"}]; числа — числами."""
    out: dict[str, Any] = {}
    for v in scenario.get("variables") or []:
        name = str(v.get("name") or "").strip().lstrip("$")
        if not name:
            continue
        val = v.get("value")
        if isinstance(val, str):
            try:
                val = float(val.replace(",", ".")) if any(c in val for c in ".,") else int(val)
            except ValueError:
                pass
        out[name] = val
    return out


def run(scenario: dict[str, Any], load: Loader, until: str | None = None,
        on_node: Callable[[NodeResult], None] | None = None,
        inject: dict[str, pd.DataFrame] | None = None,
        variables: dict[str, Any] | None = None) -> dict[str, NodeResult]:
    """Посчитать сценарий (или только то, что нужно узлу until). load(узел импорта) → таблица.
    inject — таблицы для «Входов подмодели», variables — переменные снаружи (подмодель, цикл)."""
    p = plan(scenario)
    base_vars = {**scenario_vars(scenario), **(variables or {})}
    if until is not None and until not in p.nodes:
        raise ScenarioError(until, "Нет такого узла")
    order = needed(p, until) if until else p.order
    results: dict[str, NodeResult] = {}
    for nid in order:
        node = p.nodes[nid]
        comp = COMPONENTS[node["type"]]
        res = NodeResult(nid)
        t0 = time.monotonic()
        try:
            params = dict(node.get("params") or {})
            _check_params(nid, comp, params)
            for port in comp.inputs:
                if port not in p.inputs[nid] and port not in comp.optional:
                    raise ScenarioError(nid, f"{comp.title}: не подключён вход «{_label(comp, port)}»")
            upstream = {port: results[src] for port, src in p.inputs[nid].items()}
            linked = [results[d] for d in p.extra.get(nid, [])]
            # переменные: сценария, затем входов по порядку портов и узлов-ссылок
            seen_vars = dict(base_vars)
            for port in comp.inputs:
                if port in upstream:
                    seen_vars.update(upstream[port].vars)
            for u in linked:
                seen_vars.update(u.vars)
            res.vars = seen_vars
            if any(u.frame is None for u in [*upstream.values(), *linked]):
                res.skipped = True
                res.error = "Не посчитан: ошибка в узле перед ним"
            else:
                frames = {port: u.frame for port, u in upstream.items() if u.frame is not None}
                if comp.loads:  # импорт
                    frames["data"] = load(node)
                for prm in comp.params:
                    params.setdefault(prm.name, prm.default)
                # служебное для управления и переменных: кто я, что видно, как грузить вложенное
                params.update({"__node__": nid, "__vars__": seen_vars, "__load__": load,
                               "__inject__": inject or {},
                               "__port_vars__": {port: u.vars for port, u in upstream.items()},
                               "__linked__": {d: results[d].frame for d in p.extra.get(nid, [])}})
                out = comp.run(frames, params)
                if not isinstance(out, pd.DataFrame):
                    raise NodeError(f"{comp.title}: результат — не таблица")
                # отчёт модели — к этому узлу; дальше по цепочке таблица идёт без него
                report = out.attrs.get("report")
                new_vars = out.attrs.get("vars")
                out.attrs = {}
                res.frame = out
                res.report = report if isinstance(report, dict) else None
                if isinstance(new_vars, dict):
                    res.vars = {**seen_vars, **new_vars}
        except (ScenarioError, NodeError, ExprError) as exc:
            res.error = str(exc)
        except (KeyError, TypeError, ValueError) as exc:  # данные не того вида — без трассировки
            res.error = f"{comp.title}: {type(exc).__name__}: {exc}"
        res.seconds = round(time.monotonic() - t0, 3)
        results[nid] = res
        if on_node is not None:
            on_node(res)
    return results


def _label(comp: Component, port: str) -> str:
    labels = comp.input_labels or tuple("Вход" for _ in comp.inputs)
    return dict(zip(comp.inputs, labels, strict=True)).get(port, port)
