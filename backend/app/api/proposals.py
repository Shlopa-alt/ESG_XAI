"""Предложения экспериментов от Qwen: смотреть может любой вошедший, править, одобрять и
отклонять — researcher+. Одобрение создаёт эксперимент из гипотезы и сразу ставит запуск метода.
Проверку можно настроить и самому (/manual): эксперимент и запуск появляются вместе или не
появляются вовсе, критерий записывается до расчёта."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.api.qwen import worker_online
from app.api.runs import start_run
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    Dataset,
    DatasetSnapshot,
    Experiment,
    ExperimentProposal,
    Hypothesis,
    QwenJob,
    User,
)
from app.services.qwen_experiments import close_open_proposals, experiment_from_hypothesis, problems
from app.services.qwen_queue import enqueue
from app.services.run_templates import TEMPLATES

router = APIRouter(prefix="/experiment-proposals", tags=["proposals"])

Researcher = Depends(require_role("researcher"))


class ProposalOut(BaseModel):
    id: int
    hypothesis: str
    status: str
    from_qwen: bool  # False — проверку настроил человек
    title: str
    method: str
    method_title: str
    snapshot_id: int | None
    snapshot: str  # «DS-04 · 2026-10-30»
    params: dict[str, Any]
    setup: list[str]
    expected: str
    rationale: str
    problems: str
    note: str
    decided_by: str
    experiment: str
    run_id: int | None
    created_at: datetime


class ProposalEdit(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    method: str | None = None
    snapshot_id: int | None = None
    params: dict[str, Any] | None = None
    setup: list[str] | None = None
    expected: str | None = None


class ApproveIn(ProposalEdit):
    # повтор расчёта как есть редко проверяет новую гипотезу, а идёт долго — человек подтверждает явно
    confirm_replication: bool = False


class RejectIn(BaseModel):
    note: str = Field(min_length=3)


class ManualIn(BaseModel):
    hypothesis: str
    title: str = Field(default="", max_length=512)
    template: str
    snapshot_id: int
    params: dict[str, Any] = Field(default_factory=dict)
    setup: list[str] = Field(default_factory=list)
    expected: str  # что подтвердит или опровергнет гипотезу: записывается до расчёта


class WaitIn(BaseModel):
    hypothesis: str


class WaitOut(BaseModel):
    # последняя задача Qwen на предложение; сообщение о сбое — служебное, его видит только owner
    job: Literal["none", "queued", "running", "done", "failed", "cancelled"]
    worker: bool  # обработчик Qwen на связи


def _out(db: Session, p: ExperimentProposal) -> ProposalOut:
    h = db.get(Hypothesis, p.hypothesis_id)
    snap = db.get(DatasetSnapshot, p.snapshot_id) if p.snapshot_id else None
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    exp = db.get(Experiment, p.experiment_id) if p.experiment_id else None
    user = db.get(User, p.decided_by) if p.decided_by else None
    t = TEMPLATES.get(p.method)
    return ProposalOut(
        id=p.id, hypothesis=h.code if h else "", status=p.status, from_qwen=p.qwen_job_id is not None,
        title=p.title, method=p.method,
        method_title=t.title if t else "", snapshot_id=p.snapshot_id,
        snapshot=f"{ds.code} · {snap.version}" if snap and ds else "", params=p.params or {},
        setup=list(p.setup or []), expected=p.expected, rationale=p.rationale, problems=p.problems, note=p.note,
        decided_by=user.login if user else "", experiment=exp.code if exp else "", run_id=p.run_id,
        created_at=p.created_at,
    )


def _get(db: Session, pid: int) -> ExperimentProposal:
    p = db.get(ExperimentProposal, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет предложения №{pid}")
    return p


def _edit(db: Session, settings: Settings, p: ExperimentProposal, body: ProposalEdit) -> None:
    if p.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Предложение уже рассмотрено")
    for key, value in body.model_dump(exclude_unset=True, exclude={"confirm_replication"}).items():
        if key == "setup" and value is not None:
            value = [str(x)[:500] for x in value if str(x).strip()][:10]
        setattr(p, key, value)
    p.problems = problems(db, settings, p)


def _hypothesis(db: Session, code: str) -> Hypothesis:
    h = db.scalar(select(Hypothesis).where(Hypothesis.code == code))
    if h is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет гипотезы {code}")
    return h


def _clean_setup(setup: list[str]) -> list[str]:
    return [str(x).strip()[:500] for x in setup if str(x).strip()][:10]


def _last_job(db: Session, code: str) -> QwenJob | None:
    return db.scalars(select(QwenJob).where(QwenJob.kind == "experiment",
                                            QwenJob.payload["hypothesis"].as_string() == code)
                      .order_by(QwenJob.id.desc()).limit(1)).first()


def _wait_out(db: Session, settings: Settings, code: str) -> WaitOut:
    job = _last_job(db, code)
    return WaitOut(job=job.status if job else "none", worker=worker_online(settings))


@router.get("", response_model=list[ProposalOut], dependencies=[Depends(current_user)])
def list_proposals(db: Annotated[Session, Depends(get_db)], hypothesis: str = "") -> list[ProposalOut]:
    q = select(ExperimentProposal).order_by(ExperimentProposal.id.desc())
    if hypothesis:
        q = q.join(Hypothesis, Hypothesis.id == ExperimentProposal.hypothesis_id).where(Hypothesis.code == hypothesis)
    return [_out(db, p) for p in db.scalars(q)]


@router.get("/wait", response_model=WaitOut, dependencies=[Researcher])
def wait(hypothesis: str, db: Annotated[Session, Depends(get_db)],
         settings: Annotated[Settings, Depends(get_settings)]) -> WaitOut:
    """Что с предложением, которого ещё нет: стоит в очереди, считается, сорвалось."""
    _hypothesis(db, hypothesis)
    return _wait_out(db, settings, hypothesis)


@router.post("/request", response_model=WaitOut)
def request_again(body: WaitIn, db: Annotated[Session, Depends(get_db)],
                  settings: Annotated[Settings, Depends(get_settings)],
                  user: Annotated[User, Researcher]) -> WaitOut:
    """Попросить Qwen ещё раз: прежняя задача сорвалась или предложение отклонили."""
    h = _hypothesis(db, body.hypothesis)
    if h.status != "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Предложение нужно только для принятой гипотезы")
    if db.scalar(select(ExperimentProposal.id).where(ExperimentProposal.hypothesis_id == h.id,
                                                     ExperimentProposal.status == "proposed")) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Предложение уже ждёт решения")
    job = _last_job(db, h.code)
    if job is not None and job.status in ("queued", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Qwen уже готовит предложение")
    enqueue(db, "experiment", {"hypothesis": h.code}, trigger="manual", user_id=user.id)
    db.commit()
    return _wait_out(db, settings, h.code)


@router.post("/manual", response_model=ProposalOut, status_code=status.HTTP_201_CREATED)
def manual(body: ManualIn, db: Annotated[Session, Depends(get_db)],
           settings: Annotated[Settings, Depends(get_settings)],
           user: Annotated[User, Researcher]) -> ProposalOut:
    """Проверка, настроенная человеком: эксперимент и запуск одним действием. Расчёт не поставился —
    нет и эксперимента: код не тратится, гипотеза остаётся принятой, можно поправить и повторить."""
    h = _hypothesis(db, body.hypothesis)
    if h.status != "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Гипотеза уже проверяется или не принята")
    t = TEMPLATES.get(body.template)
    if t is None or t.scope != "generic":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Для новой проверки нужен общий метод библиотеки: повтор считается в своём эксперименте")
    expected = body.expected.strip()
    if len(expected) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Запишите до расчёта, что подтвердит или опровергнет гипотезу")
    setup = _clean_setup(body.setup)
    snap = db.get(DatasetSnapshot, body.snapshot_id)
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    try:
        exp = experiment_from_hypothesis(db, h, user.id, title=body.title.strip(), method=t.title,
                                         data_summary=f"{ds.code} · срез {snap.version}" if ds and snap else "",
                                         setup=[*setup, f"Что подтвердит или опровергнет: {expected}"])
        exp.status = "running"
        close_open_proposals(db, h, user.id)
        run = start_run(db, settings, user, t.key, body.snapshot_id, dict(body.params), exp.code)
    except HTTPException:
        db.rollback()
        raise
    p = ExperimentProposal(hypothesis_id=h.id, status="approved", title=exp.title, method=t.key,
                           snapshot_id=body.snapshot_id, params=dict(body.params), setup=setup,
                           expected=expected, decided_by=user.id, decided_at=datetime.now(UTC),
                           experiment_id=exp.id, run_id=run.id)
    db.add(p)
    db.commit()
    return _out(db, p)


@router.patch("/{pid}", response_model=ProposalOut)
def edit_proposal(pid: int, body: ProposalEdit, db: Annotated[Session, Depends(get_db)],
                  settings: Annotated[Settings, Depends(get_settings)],
                  _user: Annotated[User, Researcher]) -> ProposalOut:
    p = _get(db, pid)
    _edit(db, settings, p, body)
    db.commit()
    return _out(db, p)


@router.post("/{pid}/approve", response_model=ProposalOut)
def approve(pid: int, body: ApproveIn, db: Annotated[Session, Depends(get_db)],
            settings: Annotated[Settings, Depends(get_settings)],
            user: Annotated[User, Researcher]) -> ProposalOut:
    """Одобрить (с правками): эксперимент из гипотезы и запуск метода — одним действием."""
    p = _get(db, pid)
    _edit(db, settings, p, body)
    if p.problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Сначала поправьте: {p.problems}")
    h = db.get(Hypothesis, p.hypothesis_id)
    if h is None or h.status != "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Гипотеза уже проверяется или не принята")
    t = TEMPLATES[p.method]
    if t.scope == "replication" and not body.confirm_replication:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"«{t.title}» — повтор расчёта как есть: подтвердите, что он проверяет эту гипотезу")
    snap = db.get(DatasetSnapshot, p.snapshot_id)
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    exp = experiment_from_hypothesis(db, h, user.id, title=p.title, method=t.title,
                                     data_summary=f"{ds.code} · срез {snap.version}" if ds and snap else "",
                                     setup=list(p.setup or []) + ([f"Что подтвердит или опровергнет: {p.expected}"]
                                                                  if p.expected else []))
    exp.status = "running"
    run = start_run(db, settings, user, t.key, p.snapshot_id or 0, dict(p.params or {}), exp.code)
    p.status, p.decided_by, p.decided_at = "approved", user.id, datetime.now(UTC)
    p.experiment_id, p.run_id = exp.id, run.id
    db.commit()
    return _out(db, p)


@router.post("/{pid}/reject", response_model=ProposalOut)
def reject(pid: int, body: RejectIn, db: Annotated[Session, Depends(get_db)],
           user: Annotated[User, Researcher]) -> ProposalOut:
    p = _get(db, pid)
    if p.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Предложение уже рассмотрено")
    p.status, p.note, p.decided_by, p.decided_at = "rejected", body.note.strip(), user.id, datetime.now(UTC)
    db.commit()
    return _out(db, p)
