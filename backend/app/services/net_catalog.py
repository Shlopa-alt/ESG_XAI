"""Классификация «тип задачи → рекомендуемые сети» и поиск сети, которой пользовались авторы статьи.

Каталог — знание о задачах, а не расчёт: считается в платформе только то, у чего есть метод
библиотеки (template). Остальные сети показываются честно — «в библиотеке пока нет» — с ближайшей
доступной заменой. Сеть статьи находится по названиям в её тексте (MLP, трансформер, LSTM, бустинг…),
без модели: каждое совпадение — с цитатой, по которой человек проверит вывод.
"""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Net:
    key: str
    title: str  # на экране
    family: str  # нейросеть | без нейросети
    template: str = ""  # метод библиотеки; пусто — в платформе пока не считается
    params: dict[str, Any] = field(default_factory=dict)  # что подставить в параметры метода
    nearest: str = ""  # нет в библиотеке — чем заменить
    pattern: str = ""  # как её называют в статьях (регулярное выражение, без учёта регистра)


NETS: dict[str, Net] = {
    n.key: n
    for n in (
        Net(
            "mlp",
            "Перцептрон (MLP)",
            "нейросеть",
            "lab-mlp",
            {"architecture": "mlp"},
            pattern=r"\bmlp\b|multi-?layer perceptron|perceptron|перцептрон|feed-?forward neural|"
            r"полносвязн\w* (?:нейрон|сет)|artificial neural network|\bann\b|"
            r"искусственн\w* нейронн\w* сет|back-?propagation neural|\bbpnn\b",
        ),
        Net(
            "transformer",
            "Трансформер для таблиц (FT-Transformer)",
            "нейросеть",
            "lab-mlp",
            {"architecture": "transformer"},
            pattern=r"transformer|трансформер|self-attention|самовнимани|tabnet|attention mechanism",
        ),
        Net(
            "lstm",
            "Рекуррентная сеть (LSTM, GRU)",
            "нейросеть",
            nearest="transformer",
            pattern=r"\blstm\b|long short-term memory|\bgru\b|\brnn\b|recurrent neural|рекуррентн",
        ),
        Net(
            "cnn",
            "Свёрточная сеть (CNN)",
            "нейросеть",
            nearest="mlp",
            pattern=r"\bcnn\b|convolutional neural|св[её]рточн",
        ),
        Net(
            "gnn",
            "Графовая сеть (GNN)",
            "нейросеть",
            nearest="mlp",
            pattern=r"\bgnn\b|graph neural|graph convolutional|графов\w* нейрон",
        ),
        Net(
            "bert",
            "Языковая модель (BERT и подобные)",
            "нейросеть",
            pattern=r"\bbert\b|finbert|roberta|large language model|\bllm\b|языков\w* модел",
        ),
        Net(
            "gbm",
            "Градиентный бустинг (XGBoost, CatBoost)",
            "без нейросети",
            "predictive-check",
            pattern=r"xgboost|catboost|lightgbm|gradient boost|градиентн\w* бустинг",
        ),
        Net(
            "rf",
            "Случайный лес",
            "без нейросети",
            nearest="gbm",
            pattern=r"random forest|случайн\w* лес",
        ),
        Net(
            "linear",
            "Линейная регрессия",
            "без нейросети",
            "predictive-check",
            pattern=r"linear regression|\bols\b|линейн\w* регресс|panel regression|панельн\w* регресс",
        ),
        Net(
            "rank",
            "Ранговая корреляция",
            "без нейросети",
            "rank-agreement",
            pattern=r"spearman|kendall|спирмен|кендалл|rank correlation|рангов\w* корреляц",
        ),
    )
}


@dataclass(frozen=True)
class TaskType:
    key: str
    title: str
    example: str
    nets: tuple[str, ...]  # по порядку рекомендации


TASKS: dict[str, TaskType] = {
    t.key: t
    for t in (
        TaskType(
            "predict",
            "Прогноз числового показателя",
            "ROA, выручка, налоги по ESG-входам: R = f(X, Z)",
            ("mlp", "transformer", "gbm", "linear"),
        ),
        TaskType(
            "agreement",
            "Согласованность показателей",
            "рейтинги разных агентств об одних компаниях",
            ("rank",),
        ),
        TaskType(
            "classify",
            "Отнесение к классу",
            "буква рейтинга, дефолт, нарушение",
            ("mlp", "gbm", "rf"),
        ),
        TaskType(
            "timeseries",
            "Прогноз по годам",
            "ряд показателя компании за несколько лет",
            ("lstm", "transformer"),
        ),
        TaskType("text", "Анализ текстов", "отчёты компаний, поиск гринвошинга", ("bert",)),
        TaskType("graph", "Связи между компаниями", "цепочки поставок, владение", ("gnn",)),
    )
}

# в задаче прогноза сеть статьи заменяется в пределах этих сетей; остальное — ближайшая доступная
NEURAL = ("mlp", "transformer", "lstm", "cnn", "gnn", "bert")
MAX_QUOTE = 300


def runnable(key: str) -> bool:
    return bool(NETS[key].template)


def catalog() -> dict[str, Any]:
    """Для экрана: типы задач с сетями и что из них считается в платформе."""
    return {
        "tasks": [
            {"key": t.key, "title": t.title, "example": t.example, "nets": list(t.nets)}
            for t in TASKS.values()
        ],
        "nets": [
            {
                "key": n.key,
                "title": n.title,
                "family": n.family,
                "runnable": bool(n.template),
                "template": n.template,
                "nearest": n.nearest,
            }
            for n in NETS.values()
        ],
    }


def _sentence(text: str, start: int, end: int) -> str:
    """Предложение вокруг совпадения — цитата для человека."""
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    right_dot, right_nl = text.find(". ", end), text.find("\n", end)
    rights = [r for r in (right_dot, right_nl) if r != -1]
    right = min(rights) if rights else len(text)
    quote = " ".join(text[left + 1 if left >= 0 else 0 : right + 1].split())
    if len(quote) > MAX_QUOTE:
        mid = start - (left + 1 if left >= 0 else 0)
        quote = "…" + quote[max(0, mid - MAX_QUOTE // 2) : mid + MAX_QUOTE // 2] + "…"
    return quote


def detect(text: str) -> list[dict[str, Any]]:
    """Какие сети и методы упоминает текст: [{net, count, quote}] — сначала нейросети, потом по
    числу упоминаний (сеть, о которой пишут чаще, — скорее всего, основная у авторов)."""
    found: list[dict[str, Any]] = []
    for n in NETS.values():
        matches = list(re.finditer(n.pattern, text, flags=re.IGNORECASE))
        if matches:
            m = matches[0]
            found.append(
                {
                    "net": n.key,
                    "title": n.title,
                    "count": len(matches),
                    "quote": _sentence(text, m.start(), m.end()),
                }
            )
    found.sort(key=lambda f: (f["net"] not in NEURAL, -f["count"]))
    return found


def authors_net(text: str) -> dict[str, Any] | None:
    """Сеть авторов: самая упоминаемая нейросеть, иначе самый упоминаемый метод; нет — None."""
    found = detect(text)
    if not found:
        return None
    top = found[0]
    net = NETS[top["net"]]
    nearest = net.nearest or ""
    return {
        **top,
        "runnable": bool(net.template),
        "template": net.template,
        "params": dict(net.params),
        "nearest": nearest,
        "nearest_title": NETS[nearest].title if nearest else "",
        "also": [f["net"] for f in found[1:4]],
    }
