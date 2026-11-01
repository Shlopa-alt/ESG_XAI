"""Предложения экспериментов от Qwen (app/models/proposal.py): контекст для модели, проверка,
эксперимент из гипотезы.

Гипотезу приняли к проверке — платформа ставит задачу Qwen `experiment`. Обработчик
(runner/qwen/worker.py) берёт контекст (гипотеза и её опоры, задание методики с разделами,
библиотека методов, срезы со столбцами) и просит Qwen предложить эксперимент. Предложение
проверяется здесь: метод есть в библиотеке, срез ему подходит, параметры — столбцы из заголовка
среза. Найденное записывается в problems: человек видит, что поправить, прежде чем одобрять.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Dataset,
    DatasetSnapshot,
    Experiment,
    ExperimentLink,
    ExperimentProposal,
    Hypothesis,
    HypothesisRef,
    KbRef,
    MethodologySection,
    QwenJob,
)
from app.services.codes import next_code
from app.services.data_files import table_columns, to_container
from app.services.run_templates import TEMPLATES, ParamError, check_params


def _columns(settings: Settings, snap: DatasetSnapshot) -> tuple[list[str], set[str]] | None:
    path = to_container(settings, snap.storage_path) if snap.storage_path else None
    if path is None or not path.is_file():
        return None
    try:
        return table_columns(path)
    except ValueError:
        return None


def context(db: Session, settings: Settings, code: str) -> dict[str, Any]:
    h = db.scalar(select(Hypothesis).where(Hypothesis.code == code))
    if h is None:
        raise LookupError(f"Нет гипотезы {code}")
    node = db.get(MethodologySection, h.methodology_node_id) if h.methodology_node_id else None
    nodes = {n.id: n for n in db.scalars(select(MethodologySection))}
    chain: list[MethodologySection] = []
    cur = node
    while cur is not None:
        chain.append(cur)
        cur = nodes.get(cur.parent_id) if cur.parent_id else None
    ids = {c.id for c in chain}
    sections = [n for n in nodes.values() if n.kind == "section" and (n.parent_id is None or n.parent_id in ids)]
    refs = db.scalars(select(KbRef).join(HypothesisRef, HypothesisRef.kb_ref_id == KbRef.id)
                      .where(HypothesisRef.hypothesis_id == h.id))
    snapshots = []
    for snap, ds in db.execute(select(DatasetSnapshot, Dataset).join(Dataset).order_by(Dataset.code)).all():
        if ds.access_level == "nda":
            continue  # модель не видит даже столбцов NDA
        table = _columns(settings, snap)
        snapshots.append({
            "id": snap.id, "dataset": ds.code, "title": ds.title, "description": ds.description[:500],
            "version": snap.version, "rows": snap.row_count,
            "numeric_columns": [c for c in table[0] if c in table[1]][:80] if table else [],
            "table": table is not None,
        })
    methods = [{"key": t.key, "title": t.title, "description": t.description, "scope": t.scope,
                "dataset": t.dataset, "params": [{"name": p.name, "label": p.label, "kind": p.kind,
                                                  "default": p.default, "min": p.min, "max": p.max}
                                                 for p in t.params]} for t in TEMPLATES.values()]
    return {
        "hypothesis": {"code": h.code, "title": h.title, "statement": h.statement, "rationale": h.rationale,
                       "suggested": h.suggested or {}, "refs": [{"title": r.title, "quote": r.quote} for r in refs]},
        "task": ({"number": node.number, "title": node.title, "content": node.content} if node else None),
        "sections": [{"number": s.number, "title": s.title, "content": s.content} for s in sections],
        "methods": methods, "snapshots": snapshots,
    }


def problems(db: Session, settings: Settings, p: ExperimentProposal) -> str:
    """Что не так с предложением — пусто, если его можно одобрять как есть."""
    t = TEMPLATES.get(p.method)
    if t is None:
        return "Метод не из библиотеки — выберите метод" if p.method else "Подходящего метода нет — выберите метод"
    snap = db.get(DatasetSnapshot, p.snapshot_id) if p.snapshot_id else None
    if snap is None:
        return "Не выбран срез данных"
    ds = db.get(Dataset, snap.dataset_id)
    if t.scope == "replication" and (ds is None or ds.code != t.dataset):
        return f"Метод «{t.title}» считается только на {t.dataset}"
    table = _columns(settings, snap) if any(x.kind != "int" for x in t.params) else None
    if any(x.kind != "int" for x in t.params) and table is None:
        return "Метод читает таблицу CSV, а файл среза — не таблица или не найден"
    try:
        check_params(t, dict(p.params or {}), table[0] if table else None, table[1] if table else None)
    except ParamError as exc:
        return str(exc)
    return ""


def create_from_result(db: Session, settings: Settings, job: QwenJob, result: dict[str, Any]) -> ExperimentProposal | None:
    code = str((job.payload or {}).get("hypothesis") or "")
    h = db.scalar(select(Hypothesis).where(Hypothesis.code == code))
    if h is None or h.status != "accepted":
        return None  # гипотезу уже проверяют или отклонили — предлагать поздно
    proposal = result.get("proposal") or {}
    snapshot_id = proposal.get("snapshot_id")
    p = ExperimentProposal(
        hypothesis_id=h.id, qwen_job_id=job.id, status="proposed",
        title=str(proposal.get("title") or h.title)[:512], method=str(proposal.get("method") or "")[:64],
        snapshot_id=snapshot_id if isinstance(snapshot_id, int) and db.get(DatasetSnapshot, snapshot_id) else None,
        params=proposal.get("params") if isinstance(proposal.get("params"), dict) else {},
        setup=[str(x)[:500] for x in proposal.get("setup") or [] if str(x).strip()][:10],
        expected=str(proposal.get("expected") or "")[:2000], rationale=str(proposal.get("rationale") or "")[:3000],
    )
    db.add(p)
    db.flush()
    p.problems = problems(db, settings, p)
    return p


def experiment_from_hypothesis(db: Session, h: Hypothesis, user_id: int, title: str = "", method: str = "",
                               data_summary: str = "", setup: list[str] | None = None) -> Experiment:
    """Эксперимент из принятой гипотезы: текст гипотезы, задание методики, опоры как
    ExperimentLink(motivated_by); гипотеза — «проверяется»."""
    exp = Experiment(code=next_code(db, Experiment.code, "EXP", 3), title=title or h.title,
                     hypothesis=h.statement, direction=h.direction, status="planned",
                     author_id=user_id, config={}, setup=setup or [], results=[], limitations=[],
                     reproducibility=[], data_summary=data_summary, method=method,
                     methodology_node_id=h.methodology_node_id)
    db.add(exp)
    db.flush()
    for (ref_id,) in db.execute(select(HypothesisRef.kb_ref_id).where(HypothesisRef.hypothesis_id == h.id)):
        db.add(ExperimentLink(experiment_id=exp.id, kb_ref_id=ref_id, relation="motivated_by"))
    h.experiment_id, h.status = exp.id, "testing"
    return exp
