"""Студия на платформе: каталог компонентов, проверка сценария до сохранения, постановка расчёта.

Сам расчёт — на исполнителе (runner/studio, очередь studio): на сервере нет pandas. Каталог
компонентов движок выгружает в runner/studio/catalog.json; платформа читает его из рабочей копии
репозитория (REPO_DIR) и проверяет по нему устройство сценария — компоненты, входы, связи, циклы.
Значения параметров против данных проверяет движок при расчёте.
"""

import copy
import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from app.config import Settings

FORMAT = 1
MAX_NODES = 300
STUDIO_QUEUE = "studio"
TASK = "runner.studio"
PREVIEW_ROWS, RUN_ROWS = 100, 50  # строк «Таблицы» в предпросмотре и в полном расчёте
LIMIT_MIN = 30
MAX_DEPTH = 5  # подмодель в подмодели… не глубже
NESTED = ("control.submodel", "control.loop")
PYTHON = "code.python"
DB_NODES = ("import.database", "export.database")


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
    for n in nodes:  # зависимости без связи: «Узел-ссылка», «Выполнение узла»
        comp = comps[n["type"]]
        for name in comp.get("dep_params") or []:
            v = (n.get("params") or {}).get(name)
            for ref in (v if isinstance(v, list) else [v] if v else []):
                if str(ref) not in types:
                    raise GraphError(n["id"], f"{comp['title']}: нет узла «{ref}»")
                deps[n["id"]].add(str(ref))
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


def needed(graph: dict[str, Any], target: str, settings: Settings | None = None) -> set[str]:
    """Узлы, от которых зависит target, и он сам."""
    ups: dict[str, list[str]] = {}
    for e in graph.get("edges") or []:
        ups.setdefault(str(e.get("to")), []).append(str(e.get("from")))
    if settings is not None:
        comps = components(settings)
        for n in graph.get("nodes") or []:
            for name in comps.get(n.get("type"), {}).get("dep_params") or []:
                v = (n.get("params") or {}).get(name)
                refs = v if isinstance(v, list) else [v] if v else []
                ups.setdefault(n["id"], []).extend(str(x) for x in refs)
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
            if comps[n["type"]].get("loads") and (only is None or n["id"] in only)]


@lru_cache
def _pycheck(path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location("studio_pycheck", path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def pycheck(settings: Settings) -> ModuleType:
    """Проверка кода узла «Python» — тот же модуль, что у исполнителя (runner/studio/pycheck.py)."""
    return _pycheck(str(Path(settings.repo_dir) / "runner" / "studio" / "pycheck.py"))


def python_state(settings: Settings, graph: dict[str, Any], approved: list[str]) -> dict[str, Any]:
    """Узлы «Python»: что не так в коде и одобрен ли он владельцем."""
    chk = pycheck(settings)
    out = {}
    for n in graph.get("nodes") or []:
        if n.get("type") == PYTHON:
            code = str((n.get("params") or {}).get("code") or "")
            out[n["id"]] = {"problems": chk.check(code), "approved": chk.sha256(code) in approved}
    return out


def nested_refs(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in graph.get("nodes") or [] if n.get("type") in NESTED]


def expand(graph: dict[str, Any], resolve: Any, chain: tuple[str, ...] = (), prefix: str = "",
           out: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Вложить сценарии подмоделей и циклов в их узлы (__graph__). resolve(код, версия) →
    (граф, версия, одобренный код). Возвращает граф и список всех узлов с префиксом пути
    (для входных наборов, кода Python и записи версий подмоделей)."""
    out = [] if out is None else out
    g = copy.deepcopy(graph)
    for n in g.get("nodes") or []:
        out.append({"id": prefix + n["id"], "node": n, "chain": chain})
        if n.get("type") not in NESTED:
            continue
        params = n.setdefault("params", {})
        code = str(params.get("scenario") or "").upper()
        if not code:
            raise GraphError(prefix + n["id"], "Подмодель: не выбран сценарий")
        if code in chain:
            path = " → ".join([*chain, code])
            raise GraphError(prefix + n["id"], f"Подмодель {code} вызывает сама себя: {path}")
        if len(chain) >= MAX_DEPTH:
            raise GraphError(prefix + n["id"], f"Подмодели вложены глубже {MAX_DEPTH}")
        version = params.get("version")
        sub, ver = resolve(code, int(version) if str(version or "").isdigit() else None)
        inner, _ = expand(sub, resolve, (*chain, code), f"{prefix}{n['id']}/", out)
        params["__graph__"] = inner
        params["__version__"] = ver
    return g, out
