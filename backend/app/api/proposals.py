"""Предложения экспериментов от Qwen: смотреть может любой вошедший, править, одобрять и
отклонять — researcher+. Одобрение создаёт эксперимент из гипотезы и сразу ставит запуск метода."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.api.runs import start_run
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Dataset, DatasetSnapshot, Experiment, ExperimentProposal, Hypothesis, User
from app.services.qwen_experiments import experiment_from_hypothesis, problems
from app.services.run_templates import TEMPLATES

router = APIRouter(prefix="/experiment-proposals", tags=["proposals"])

Researcher = Depends(require_role("researcher"))


class ProposalOut(BaseModel):
    id: int
    hypothesis: str
    status: str
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


class RejectIn(BaseModel):
    note: str = Field(min_length=3)


def _out(db: Session, p: ExperimentProposal) -> ProposalOut:
    h = db.get(Hypothesis, p.hypothesis_id)
    snap = db.get(DatasetSnapshot, p.snapshot_id) if p.snapshot_id else None
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    exp = db.get(Experiment, p.experiment_id) if p.experiment_id else None
    user = db.get(User, p.decided_by) if p.decided_by else None
    t = TEMPLATES.get(p.method)
    return ProposalOut(
        id=p.id, hypothesis=h.code if h else "", status=p.status, title=p.title, method=p.method,
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
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "setup" and value is not None:
            value = [str(x)[:500] for x in value if str(x).strip()][:10]
        setattr(p, key, value)
    p.problems = problems(db, settings, p)


@router.get("", response_model=list[ProposalOut], dependencies=[Depends(current_user)])
def list_proposals(db: Annotated[Session, Depends(get_db)], hypothesis: str = "") -> list[ProposalOut]:
    q = select(ExperimentProposal).order_by(ExperimentProposal.id.desc())
    if hypothesis:
        q = q.join(Hypothesis, Hypothesis.id == ExperimentProposal.hypothesis_id).where(Hypothesis.code == hypothesis)
    return [_out(db, p) for p in db.scalars(q)]


@router.patch("/{pid}", response_model=ProposalOut)
def edit_proposal(pid: int, body: ProposalEdit, db: Annotated[Session, Depends(get_db)],
                  settings: Annotated[Settings, Depends(get_settings)],
                  _user: Annotated[User, Researcher]) -> ProposalOut:
    p = _get(db, pid)
    _edit(db, settings, p, body)
    db.commit()
    return _out(db, p)


@router.post("/{pid}/approve", response_model=ProposalOut)
def approve(pid: int, body: ProposalEdit, db: Annotated[Session, Depends(get_db)],
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
