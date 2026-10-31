from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.db import get_db
from app.models import (
    Dataset,
    DatasetSnapshot,
    Experiment,
    ExperimentLink,
    Hypothesis,
    KbRef,
    Review,
    User,
)
from app.services.codes import next_code
from app.services.experiments import DomainError, set_status
from app.services.report import Report

router = APIRouter(tags=["experiments"])

Researcher = Depends(require_role("researcher"))
ReviewerRole = Depends(require_role("reviewer"))

Status = Literal["draft", "planned", "running", "review", "done", "failed"]
Outcome = Literal["confirmed", "rejected", "inconclusive"]


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reviewer: str
    verdict: str
    text: str
    created_at: datetime


class LinkOut(BaseModel):
    relation: str
    kind: str
    kbrag_id: str
    title: str
    doi: str
    quote: str


class ExperimentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    hypothesis: str
    direction: str
    status: str
    outcome: str | None
    method: str
    data_summary: str
    dataset_snapshot_id: int | None
    seed: int | None
    runner_commit: str
    env_lock: str
    setup: list[str]
    results: list[str]
    result_summary: str
    conclusion: str
    limitations: list[str]
    reproducibility: list[str]
    report_path: str
    report: dict[str, Any] = {}
    created_at: datetime
    finished_at: datetime | None


class ExperimentDetail(ExperimentOut):
    reviews: list[ReviewOut] = []
    links: list[LinkOut] = []
    dataset_snapshot: str = ""  # «DS-01 · 2026-10-30» — срез из воспроизводимости


class ExperimentIn(BaseModel):
    code: str | None = Field(default=None, pattern=r"^EXP-\d{3}$")  # нет — следующий свободный
    title: str = Field(min_length=3)
    hypothesis: str = ""
    direction: str = ""
    method: str = ""
    data_summary: str = ""
    setup: list[str] = []


class ExperimentPatch(BaseModel):
    title: str | None = None
    hypothesis: str | None = None
    direction: str | None = None
    method: str | None = None
    data_summary: str | None = None
    setup: list[str] | None = None
    reproducibility: list[str] | None = None
    report: Report | None = None
    status: Status | None = None
    outcome: Outcome | None = None
    dataset_snapshot_id: int | None = None
    seed: int | None = None
    runner_commit: str | None = None
    env_lock: str | None = None
    results: list[str] | None = None
    result_summary: str | None = None
    conclusion: str | None = None
    limitations: list[str] | None = None


class ReviewIn(BaseModel):
    target_code: str
    verdict: Literal["approve", "changes", "reject"]
    text: str = ""


class LinkIn(BaseModel):
    relation: Literal["tests", "uses_method", "replicates", "motivated_by"]
    kind: Literal["article", "fact", "entity"]
    kbrag_id: str = Field(min_length=1)
    kb_path: str = ""
    title: str = ""
    doi: str = ""
    quote: str = ""
    page: int | None = None


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    description: str
    source_url: str
    access_level: str


def _get(db: Session, code: str) -> Experiment:
    exp = db.scalar(select(Experiment).where(Experiment.code == code))
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет эксперимента {code}")
    return exp


def _detail(db: Session, exp: Experiment) -> ExperimentDetail:
    reviews = db.execute(
        select(Review, User.login)
        .join(User, User.id == Review.reviewer_id)
        .where(Review.target_type == "experiment", Review.target_id == exp.id)
        .order_by(Review.created_at)
    ).all()
    links = db.execute(
        select(ExperimentLink.relation, KbRef)
        .join(KbRef, KbRef.id == ExperimentLink.kb_ref_id)
        .where(ExperimentLink.experiment_id == exp.id)
    ).all()
    snap = db.get(DatasetSnapshot, exp.dataset_snapshot_id) if exp.dataset_snapshot_id else None
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    return ExperimentDetail(
        **ExperimentOut.model_validate(exp).model_dump(),
        dataset_snapshot=f"{ds.code} · {snap.version}" if snap and ds else "",
        reviews=[
            ReviewOut(id=r.id, reviewer=login, verdict=r.verdict, text=r.text, created_at=r.created_at)
            for r, login in reviews
        ],
        links=[
            LinkOut(relation=rel, kind=k.kind, kbrag_id=k.kbrag_id, title=k.title, doi=k.doi, quote=k.quote)
            for rel, k in links
        ],
    )


@router.get("/experiments", response_model=list[ExperimentOut], dependencies=[Depends(current_user)])
def list_experiments(
    db: Annotated[Session, Depends(get_db)],
    status_: Annotated[Status | None, Query(alias="status")] = None,
    direction: str | None = None,
) -> list[Experiment]:
    q = select(Experiment).order_by(Experiment.code)
    if status_:
        q = q.where(Experiment.status == status_)
    if direction:
        q = q.where(Experiment.direction == direction)
    return list(db.scalars(q))


@router.get("/experiments/compare", response_model=list[ExperimentDetail],
            dependencies=[Depends(current_user)])
def compare(codes: str, db: Annotated[Session, Depends(get_db)]) -> list[ExperimentDetail]:
    return [_detail(db, _get(db, c.strip())) for c in codes.split(",") if c.strip()]


@router.get("/experiments/{code}", response_model=ExperimentDetail,
            dependencies=[Depends(current_user)])
def get_experiment(code: str, db: Annotated[Session, Depends(get_db)]) -> ExperimentDetail:
    return _detail(db, _get(db, code))


@router.post("/experiments", response_model=ExperimentOut, status_code=status.HTTP_201_CREATED)
def create_experiment(
    body: ExperimentIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Researcher],
) -> Experiment:
    code = body.code or next_code(db, Experiment.code, "EXP", 3)
    if db.scalar(select(Experiment).where(Experiment.code == code)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Код {code} уже занят")
    exp = Experiment(**body.model_dump(exclude={"code"}), code=code, status="draft",
                     author_id=user.id, config={}, results=[], limitations=[],
                     reproducibility=[], report={})
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


@router.patch("/experiments/{code}", response_model=ExperimentDetail, dependencies=[Researcher])
def patch_experiment(
    code: str, body: ExperimentPatch, db: Annotated[Session, Depends(get_db)]
) -> ExperimentDetail:
    exp = _get(db, code)
    data = body.model_dump(exclude_unset=True)
    new_status = data.pop("status", None)
    if body.report is not None:
        data["report"] = body.report.model_dump()
    for key, value in data.items():
        setattr(exp, key, value)
    if new_status is not None:
        try:
            set_status(exp, new_status)
        except DomainError as exc:
            db.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        if new_status == "done":
            # завершённый эксперимент закрывает проверку своей гипотезы
            for h in db.scalars(select(Hypothesis).where(Hypothesis.experiment_id == exp.id,
                                                         Hypothesis.status == "testing")):
                h.status = "tested"
    db.commit()
    return _detail(db, exp)


@router.post("/experiments/{code}/links", response_model=ExperimentDetail, dependencies=[Researcher])
def add_link(code: str, body: LinkIn, db: Annotated[Session, Depends(get_db)]) -> ExperimentDetail:
    exp = _get(db, code)
    ref = KbRef(**body.model_dump(exclude={"relation"}))
    db.add(ref)
    db.flush()
    db.add(ExperimentLink(experiment_id=exp.id, kb_ref_id=ref.id, relation=body.relation))
    db.commit()
    return _detail(db, exp)


@router.post("/reviews", response_model=ExperimentDetail, status_code=status.HTTP_201_CREATED)
def add_review(
    body: ReviewIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, ReviewerRole],
) -> ExperimentDetail:
    exp = _get(db, body.target_code)
    db.add(Review(target_type="experiment", target_id=exp.id, reviewer_id=user.id,
                  verdict=body.verdict, text=body.text))
    db.commit()
    return _detail(db, exp)


@router.get("/datasets", response_model=list[DatasetOut], dependencies=[Depends(current_user)])
def list_datasets(db: Annotated[Session, Depends(get_db)]) -> list[Dataset]:
    return list(db.scalars(select(Dataset).order_by(Dataset.code)))


class GraphLinkOut(BaseModel):
    experiment: str
    title: str
    status: str
    relation: str
    kbrag_id: str


@router.get("/experiment-links", response_model=list[GraphLinkOut], dependencies=[Depends(current_user)])
def experiment_links(db: Annotated[Session, Depends(get_db)]) -> list[GraphLinkOut]:
    """Связи экспериментов со статьями и фактами KBRAG — узлы платформы на графе знаний."""
    rows = db.execute(
        select(Experiment.code, Experiment.title, Experiment.status, ExperimentLink.relation, KbRef.kbrag_id)
        .join(ExperimentLink, ExperimentLink.experiment_id == Experiment.id)
        .join(KbRef, KbRef.id == ExperimentLink.kb_ref_id)
    ).all()
    return [GraphLinkOut(experiment=c, title=t, status=s, relation=r, kbrag_id=k) for c, t, s, r, k in rows]
