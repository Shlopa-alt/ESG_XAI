"""Гипотезы от Qwen: что модели нужно знать и как её предложения становятся гипотезами.

Задача `hypotheses` ставится сама после пополнения базы (импорт статьи, новый срез данных).
Обработчик (runner/qwen/worker.py) берёт контекст — задания методики с их разделами, датасеты,
методы, уже предложенные гипотезы, — ищет по каждому заданию фрагменты статей и факты графа в
KBRAG и просит Qwen предложить проверяемые гипотезы. Здесь предложения проверяются и
сохраняются: у гипотезы должна быть хотя бы одна опора-фрагмент из найденных, повторы
отсекаются, у задания — не больше PENDING_LIMIT нерассмотренных гипотез от Qwen (иначе после
каждого импорта рецензенту прибавляется работы). Гипотеза уходит на рецензию как обычная:
статус «предложена», источник qwen.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Dataset, DatasetSnapshot, Hypothesis, HypothesisRef, KbRef, MethodologySection, QwenJob
from app.services.codes import next_code
from app.services.run_templates import TEMPLATES

PENDING_LIMIT = 3  # нерассмотренных гипотез от Qwen на задание
PER_RUN = 3  # новых гипотез на задание за один проход


def _chain(nodes: dict[int, MethodologySection], node: MethodologySection) -> list[MethodologySection]:
    out = [node]
    while out[-1].parent_id is not None and out[-1].parent_id in nodes:
        out.append(nodes[out[-1].parent_id])
    return out[::-1]  # от корня к узлу


def targets(db: Session) -> list[MethodologySection]:
    """Для чего предлагать гипотезы: задания и направления, в которых заданий ещё нет.
    Варианты без заданий (вариант 3) пропускаются — их сначала расписывает лаборатория."""
    nodes = list(db.scalars(select(MethodologySection)))
    has_task_below: set[int] = set()
    by_id = {n.id: n for n in nodes}
    for n in nodes:
        if n.kind == "task":
            for anc in _chain(by_id, n)[:-1]:
                has_task_below.add(anc.id)
    return [n for n in nodes if n.kind == "task" or (n.kind == "direction" and n.id not in has_task_below)]


def context(db: Session) -> dict[str, Any]:
    nodes = list(db.scalars(select(MethodologySection)))
    by_id = {n.id: n for n in nodes}
    common = [n for n in nodes if n.parent_id is None and n.kind == "section"]
    out_targets = []
    for t in sorted(targets(db), key=lambda n: n.number):
        chain = _chain(by_id, t)
        ids = {c.id for c in chain}
        sections = common + [n for n in nodes if n.kind == "section" and n.parent_id in ids]
        hyps = list(db.scalars(select(Hypothesis).where(Hypothesis.methodology_node_id == t.id)))
        out_targets.append({
            "number": t.number, "kind": t.kind, "title": t.title, "content": t.content,
            "path": [{"number": c.number, "title": c.title, "content": c.content} for c in chain[:-1]],
            "sections": [{"number": s.number, "title": s.title, "content": s.content} for s in sections],
            "existing": [{"code": h.code, "title": h.title, "status": h.status} for h in hyps],
            "pending_qwen": sum(1 for h in hyps if h.source == "qwen" and h.status == "proposed"),
        })
    datasets = []
    for d in db.scalars(select(Dataset).order_by(Dataset.code)):
        snaps = db.scalar(select(func.count()).select_from(DatasetSnapshot).where(DatasetSnapshot.dataset_id == d.id))
        datasets.append({"code": d.code, "title": d.title, "description": d.description[:600],
                         "snapshots": snaps or 0})
    methods = [{"key": t.key, "title": t.title, "description": t.description,
                "dataset": t.dataset or "любой подходящий срез (CSV)"} for t in TEMPLATES.values()]
    return {"targets": out_targets, "datasets": datasets, "methods": methods,
            "limits": {"pending": PENDING_LIMIT, "per_run": PER_RUN}}


def _clean(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def create_from_result(db: Session, job: QwenJob, result: dict[str, Any]) -> list[str]:
    """Предложения Qwen → гипотезы на рецензию. Возвращает коды созданных."""
    nodes = {n.number: n for n in db.scalars(select(MethodologySection))}
    allowed = {t.number for t in targets(db)}
    datasets = {d.code for d in db.scalars(select(Dataset))}
    created: list[str] = []
    per_node: dict[str, int] = {}
    for item in result.get("hypotheses") or []:
        number = str(item.get("node") or "")
        node = nodes.get(number)
        title, statement = _clean(item.get("title"), 300), _clean(item.get("statement"), 2000)
        refs = [r for r in item.get("refs") or [] if isinstance(r, dict) and r.get("doc_id")]
        if node is None or number not in allowed or len(title) < 5 or len(statement) < 10 or not refs:
            continue
        pending = db.scalar(select(func.count()).select_from(Hypothesis).where(
            Hypothesis.methodology_node_id == node.id, Hypothesis.source == "qwen",
            Hypothesis.status == "proposed")) or 0
        if pending >= PENDING_LIMIT or per_node.get(number, 0) >= PER_RUN:
            continue
        same = db.scalar(select(Hypothesis.id).where(Hypothesis.methodology_node_id == node.id,
                                                     func.lower(Hypothesis.title) == title.lower()))
        if same is not None:
            continue
        dataset = str(item.get("dataset") or "")
        dataset = dataset if dataset in datasets else ""
        method = _clean(item.get("method"), 300)
        template = TEMPLATES.get(method)
        if template is not None and template.scope == "replication" and template.dataset != dataset:
            method = ""  # повтор считается только на своём датасете
        h = Hypothesis(
            code=next_code(db, Hypothesis.code, "H", 3), title=title, statement=statement,
            rationale=_clean(item.get("rationale"), 3000), direction="Напр. 2" if number.startswith("Н2") else "Напр. 1",
            status="proposed", source="qwen", qwen_job_id=job.id, methodology_node_id=node.id,
            suggested={"dataset": dataset, "method": method,
                       "data_needed": _clean(item.get("data_needed"), 600)},
        )
        db.add(h)
        db.flush()
        for r in refs[:5]:
            ref = KbRef(kind="article", kbrag_id=_clean(r["doc_id"], 512), kb_path=_clean(r.get("kb_path") or "esg", 256),
                        title=_clean(r.get("title"), 1024), doi=_clean(r.get("doi"), 256),
                        quote=_clean(r.get("quote"), 600), page=r.get("page") if isinstance(r.get("page"), int) else None)
            db.add(ref)
            db.flush()
            db.add(HypothesisRef(hypothesis_id=h.id, kb_ref_id=ref.id))
        created.append(h.code)
        per_node[number] = per_node.get(number, 0) + 1
    return created
