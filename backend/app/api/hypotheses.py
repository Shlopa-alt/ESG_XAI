"""Гипотезы: предложить может любой вошедший; принять или отклонить — reviewer/owner;
проверить экспериментом — researcher/owner."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.db import get_db
from app.models import Experiment, ExperimentLink, Hypothesis, HypothesisRef, KbRef, User
from app.services.codes import next_code

router = APIRouter(prefix="/hypotheses", tags=["hypotheses"])

Researcher = Depends(require_role("researcher"))
ReviewerRole = Depends(require_role("reviewer"))


class RefIn(BaseModel):
    kind: Literal["article", "fact", "entity"] = "article"
    kbrag_id: str = Field(min_length=1)
    kb_path: str = ""
    title: str = ""
    doi: str = ""
    quote: str = ""
    page: int | None = None


class RefOut(BaseModel):
    kind: str
    kbrag_id: str
    title: str
    doi: str
    quote: str


class HypothesisIn(BaseModel):
    title: str = Field(min_length=5, max_length=512)
    statement: str = Field(min_length=10)
    rationale: str = ""
    direction: Literal["Напр. 1", "Напр. 2", "Методы", ""] = ""
    refs: list[RefIn] = []


class HypothesisOut(BaseModel):
    code: str
    title: str
    statement: str
    rationale: str
    direction: str
    status: str
    decision_note: str
    author: str
    decided_by: str
    experiment: str
    created_at: datetime
    refs: list[RefOut]


class DecisionIn(BaseModel):
    status: Literal["accepted", "rejected"]
    note: str = ""


def _get(db: Session, code: str) -> Hypothesis:
    h = db.scalar(select(Hypothesis).where(Hypothesis.code == code))
    if h is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет гипотезы {code}")
    return h


def _login(db: Session, uid: int | None) -> str:
    u = db.get(User, uid) if uid else None
    return u.login if u else ""


def _out(db: Session, h: Hypothesis) -> HypothesisOut:
    refs = db.scalars(
        select(KbRef).join(HypothesisRef, HypothesisRef.kb_ref_id == KbRef.id)
        .where(HypothesisRef.hypothesis_id == h.id)
    )
    exp = db.get(Experiment, h.experiment_id) if h.experiment_id else None
    return HypothesisOut(
        code=h.code, title=h.title, statement=h.statement, rationale=h.rationale,
        direction=h.direction, status=h.status, decision_note=h.decision_note,
        author=_login(db, h.author_id), decided_by=_login(db, h.decided_by),
        experiment=exp.code if exp else "", created_at=h.created_at,
        refs=[RefOut(kind=r.kind, kbrag_id=r.kbrag_id, title=r.title, doi=r.doi, quote=r.quote)
              for r in refs],
    )


def _add_ref(db: Session, h: Hypothesis, ref: RefIn) -> None:
    kb = KbRef(**ref.model_dump())
    db.add(kb)
    db.flush()
    db.add(HypothesisRef(hypothesis_id=h.id, kb_ref_id=kb.id))


@router.get("", response_model=list[HypothesisOut], dependencies=[Depends(current_user)])
def list_hypotheses(db: Annotated[Session, Depends(get_db)]) -> list[HypothesisOut]:
    return [_out(db, h) for h in db.scalars(select(Hypothesis).order_by(Hypothesis.id.desc()))]


@router.get("/{code}", response_model=HypothesisOut, dependencies=[Depends(current_user)])
def get_hypothesis(code: str, db: Annotated[Session, Depends(get_db)]) -> HypothesisOut:
    return _out(db, _get(db, code))


@router.post("", response_model=HypothesisOut, status_code=status.HTTP_201_CREATED)
def propose(
    body: HypothesisIn, db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> HypothesisOut:
    """Предложить гипотезу может любой вошедший пользователь, в том числе reader."""
    h = Hypothesis(code=next_code(db, Hypothesis.code, "H", 3), title=body.title,
                   statement=body.statement, rationale=body.rationale, direction=body.direction,
                   status="proposed", author_id=user.id)
    db.add(h)
    db.flush()
    for ref in body.refs:
        _add_ref(db, h, ref)
    db.commit()
    return _out(db, h)


@router.post("/{code}/refs", response_model=HypothesisOut)
def add_ref(
    code: str, body: RefIn, db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> HypothesisOut:
    """Опору добавляет автор гипотезы или researcher и выше."""
    h = _get(db, code)
    if h.author_id != user.id and user.role == "reader":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Добавить опору может автор или researcher")
    _add_ref(db, h, body)
    db.commit()
    return _out(db, h)


@router.patch("/{code}", response_model=HypothesisOut)
def decide(
    code: str, body: DecisionIn, db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, ReviewerRole],
) -> HypothesisOut:
    h = _get(db, code)
    if h.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{h.code} уже разобрана")
    if body.status == "rejected" and not body.note.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Отклоняя гипотезу, напишите почему — это увидит автор")
    h.status, h.decision_note, h.decided_by = body.status, body.note, user.id
    db.commit()
    return _out(db, h)


@router.post("/{code}/experiment", response_model=HypothesisOut)
def start_experiment(
    code: str, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Researcher],
) -> HypothesisOut:
    """Эксперимент из принятой гипотезы: гипотеза и опоры переносятся, код — следующий EXP."""
    h = _get(db, code)
    if h.status != "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Проверять экспериментом можно принятую гипотезу")
    exp = Experiment(code=next_code(db, Experiment.code, "EXP", 3), title=h.title,
                     hypothesis=h.statement, direction=h.direction, status="planned",
                     author_id=user.id, config={}, setup=[], results=[], limitations=[],
                     reproducibility=[], data_summary="", method="")
    db.add(exp)
    db.flush()
    for (ref_id,) in db.execute(
        select(HypothesisRef.kb_ref_id).where(HypothesisRef.hypothesis_id == h.id)
    ):
        db.add(ExperimentLink(experiment_id=exp.id, kb_ref_id=ref_id, relation="motivated_by"))
    h.experiment_id, h.status = exp.id, "testing"
    db.commit()
    return _out(db, h)
