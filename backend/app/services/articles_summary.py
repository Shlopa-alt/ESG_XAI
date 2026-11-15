"""«Что говорят статьи» по пункту методики: сводка фактов банка статей о связи «фактор → результат».

Правка по совещанию «Экономика — правки и идеи по сайту»: «исходная задача — на основе всех статей
смотреть на результат». Этап 1 — сводка: сколько статей говорят «повышает», «снижает», «не влияет»,
насколько они согласны, с цитатами. Платформа ничего не копирует и не хранит: факты берутся из
KBRAG по запросу (/api/dataset — все факты о понятии с цитатами, правило 8). Здесь только счёт.

Какие понятия сопоставлять, выбирает человек; подсказку по тексту пункта даёт страница
(frontend/src/components/ArticlesSummary.tsx) — по карте связей и русским названиям понятий.
"""

from dataclasses import dataclass, field
from typing import Any

HEDGE = "предположительно"  # KBRAG ставит перед связью, если цитата осторожная (graph/facts.py)


def direction(relation: str) -> str:
    """up | down | none | other — те же группы, что у цвета стрелок на карте связей."""
    r = relation.lower().removeprefix(HEDGE).strip()
    if "не влияет" in r:
        return "none"
    if r.startswith("не "):
        return "other"
    if "повыша" in r or "увеличива" in r or "улучша" in r:
        return "up"
    if "снижа" in r or "уменьша" in r or "ухудша" in r or "сокраща" in r:
        return "down"
    return "other"


@dataclass
class Group:
    key: str
    documents: int = 0  # сумма по связям: одна статья с двумя формулировками считается дважды
    links: list[dict[str, Any]] = field(default_factory=list)


def summarize(factor: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    """Связи «фактор → результат» из датасетов двух понятий KBRAG.

    factor, outcome — ответы /api/dataset: name, includes (что входит в понятие), facts — строки
    {about, direction, relation, other, documents, quotes}. Берутся связи от фактора (или того, что
    в него входит) к результату (или тому, что входит в него)."""
    targets = {outcome.get("name"), *(outcome.get("includes") or [])}
    groups = {k: Group(k) for k in ("up", "down", "none", "other")}
    for row in factor.get("facts") or []:
        if row.get("direction") != "→" or row.get("other") not in targets:
            continue
        relation = str(row.get("relation") or "")
        g = groups[direction(relation)]
        g.documents += int(row.get("documents") or 0)
        g.links.append({
            "from": row.get("about"), "relation": relation, "to": row.get("other"),
            "hedged": relation.lower().startswith(HEDGE),
            "documents": int(row.get("documents") or 0), "quotes": row.get("quotes") or [],
        })
    said = {k: groups[k].documents for k in ("up", "down", "none")}
    total = sum(said.values())
    leader = max(said, key=lambda k: said[k]) if total else ""
    return {
        "factor": factor.get("name"), "outcome": outcome.get("name"),
        "groups": [{"key": g.key, "documents": g.documents, "links": g.links}
                   for g in groups.values()],
        "total": total,
        # согласие — доля самого частого ответа среди «повышает / снижает / не влияет»
        "leader": leader, "agreement": round(said[leader] / total, 2) if total else None,
    }
