"""Студия на платформе: каталог компонентов, проверка сценария до сохранения, постановка расчёта.

Сам расчёт — на исполнителе (runner/studio, очередь studio): на сервере нет pandas. Каталог
компонентов движок выгружает в runner/studio/catalog.json; платформа читает его из рабочей копии
репозитория (REPO_DIR) и проверяет по нему устройство сценария — компоненты, входы, связи, циклы.
Значения параметров против данных проверяет движок при расчёте.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import Settings

FORMAT = 1
MAX_NODES = 300
STUDIO_QUEUE = "studio"
TASK = "runner.studio"
PREVIEW_ROWS, RUN_ROWS = 100, 50  # строк «Таблицы» в предпросмотре и в полном расчёте
LIMIT_MIN = 30


class GraphError(ValueError):
    def __init__(self, node: str, message: str) -> None:
        super().__init__(message)
        self.node = node


@lru_cache
def _catalog(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def catalog(settings: Settings) -> dict[str, Any]:
    path = Path(settings.repo_dir) / "runner" / "studio" / "catalog.json"
    if not path.is_file():
        raise FileNotFoundError(f"Нет каталога компонентов Студии: {path}")
    return _catalog(str(path))


def components(settings: Settings) -> dict[str, dict[str, Any]]:
    return {c["type"]: c for c in catalog(settings)["components"]}


def empty_graph() -> dict[str, Any]:
    return {"format": FORMAT, "nodes": [], "edges": []}


def check_graph(settings: Settings, graph: dict[str, Any]) -> list[str]:
    """Устройство сценария: формат, компоненты, входы, связи без циклов. Возвращает порядок узлов.
    Незаполненные параметры не мешают сохранить — о них скажет расчёт на узле."""
    if not isinstance(graph, dict) or graph.get("format") != FORMAT:
        raise GraphError("", f"Неизвестный формат сценария (нужен {FORMAT})")
    comps = components(settings)
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise GraphError("", "В сценарии нет списков узлов и связей")
    if len(nodes) > MAX_NODES:
        raise GraphError("", f"Узлов больше {MAX_NODES}")
    types: dict[str, str] = {}
    for n in nodes:
        nid = str(n.get("id") or "") if isinstance(n, dict) else ""
        if not nid or nid in types or len(nid) > 64:
            raise GraphError(nid, "У узла нет id, он длиннее 64 знаков или повторяется")
        if n.get("type") not in comps:
            raise GraphError(nid, f"Неизвестный компонент «{n.get('type')}»")
        if not isinstance(n.get("params") or {}, dict):
            raise GraphError(nid, "Параметры узла — не набор полей")
        types[nid] = str(n["type"])
    deps: dict[str, set[str]] = {nid: set() for nid in types}
    taken: set[tuple[str, str]] = set()
    for e in edges:
        src, dst = str(e.get("from")), str(e.get("to"))
        port = str(e.get("port") or "in")
        if src not in types or dst not in types:
            raise GraphError(dst if dst in types else "", "Связь ведёт к несуществующему узлу")
        comp = comps[types[dst]]
        if port not in [i["name"] for i in comp["inputs"]]:
            raise GraphError(dst, f"{comp['title']}: нет входа «{port}»")
        if (dst, port) in taken:
            raise GraphError(dst, f"{comp['title']}: во вход «{port}» уже приходит связь")
        taken.add((dst, port))
        deps[dst].add(src)
    order: list[str] = []
    ready = [n for n, d in deps.items() if not d]
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for other, d in deps.items():
            if nid in d:
                d.discard(nid)
                if not d:
                    ready.append(other)
    if len(order) != len(types):
        raise GraphError(next(n for n in types if n not in order),
                         "Связи образуют цикл — данные не могут течь по кругу")
    return order


def needed(graph: dict[str, Any], target: str) -> set[str]:
    """Узлы, от которых зависит target, и он сам."""
    ups: dict[str, list[str]] = {}
    for e in graph.get("edges") or []:
        ups.setdefault(str(e.get("to")), []).append(str(e.get("from")))
    need: set[str] = set()
    stack = [target]
    while stack:
        nid = stack.pop()
        if nid not in need:
            need.add(nid)
            stack.extend(ups.get(nid, []))
    return need


def import_nodes(settings: Settings, graph: dict[str, Any], only: set[str] | None = None,
                 ) -> list[dict[str, Any]]:
    comps = components(settings)
    return [n for n in graph.get("nodes") or []
            if not comps[n["type"]]["inputs"] and (only is None or n["id"] in only)]
