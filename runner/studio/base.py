"""Студия: общее для всех компонентов — описание параметра, компонента и ошибка узла.

Здесь, а не в components.py: модули компонентов (database, mining, …) импортируют только это,
и порядок их импорта не важен (без циклов).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

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
    optional: tuple[str, ...] = ()  # входы, которые можно не подключать (например, «Новые данные»)
    loads: bool = False  # узел импорта: данные ему даёт движок (inputs["data"])
    dep_params: tuple[str, ...] = ()  # параметры с id узлов, от которых он зависит без связи

    def schema(self) -> dict[str, Any]:
        labels = self.input_labels or tuple("Вход" for _ in self.inputs)
        return {"type": self.type, "title": self.title, "group": self.group,
                "description": self.description,
                "inputs": [{"name": n, "label": lbl, **({"optional": True} if n in self.optional else {})}
                           for n, lbl in zip(self.inputs, labels, strict=True)],
                "params": [p.schema() for p in self.params],
                **({"loads": True} if self.loads else {}),
                **({"dep_params": list(self.dep_params)} if self.dep_params else {})}
