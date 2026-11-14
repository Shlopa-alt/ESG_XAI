"""Гипотезы: предложить может любой вошедший; принять или отклонить — reviewer/owner;
проверить экспериментом — researcher/owner."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.api.experiments import node_id, node_number
from app.db import get_db
from app.models import Experiment, Hypothesis, HypothesisRef, KbRef, MethodologySection, User
from app.services.codes import next_code
from app.services.qwen_experiments import close_open_proposals, experiment_from_hypothesis
from app.services.qwen_hypotheses import PILLARS, idea
from app.services.qwen_queue import enqueue

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
    methodology_node: str = ""  # задание (или вариант, направление) методики
    # тип связи: как влияет и на какие показатели; пусто — автор не указал
    effect: Literal["increases", "decreases", "no_effect", "mixed", ""] = ""
    target_kind: Literal["financial", "nonfinancial", ""] = ""
    weight: Literal[1, 2, 3] | None = None  # вес связи: 1 слабая, 2 средняя, 3 сильная
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
    methodology_node: str
    methodology_node_title: str
    effect: str
    target_kind: str
    weight: int | None
    weight_set_by: str  # кто последним поставил вес: автор или рецензент
    source: str  # human | qwen
    suggested: dict[str, Any]  # от Qwen: датасет, метод, каких данных не хватает
    created_at: datetime
    refs: list[RefOut]


class SimilarIn(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    statement: str = ""


class SimilarOut(BaseModel):
    code: str
    title: str
    status: str
    source: str
    share: float  # доля общих содержательных слов от меньшей из двух идей


SIMILAR_SHARE = 0.4  # ниже повтора у Qwen (0,5): здесь только подсказка автору, решает он сам
SIMILAR_MAX = 5


def similar_ideas(db: Session, title: str, statement: str) -> list[SimilarOut]:
    """Уже предложенные идеи с теми же содержательными словами — подсказка до отправки новой.

    Сравниваются название и утверждение по основам слов (как повтор у Qwen); идеи о разных
    E, S, G при тех же остальных словах не считаются похожими."""
    new = idea(f"{title} {statement}")
    if not new:
        return []
    found: list[SimilarOut] = []
    for h in db.scalars(select(Hypothesis)):
        old = idea(f"{h.title} {h.statement}")
        if not old or (new & PILLARS and old & PILLARS and not new & old & PILLARS):
            continue
        share = len(new & old) / min(len(new), len(old))
        if share >= SIMILAR_SHARE:
            found.append(SimilarOut(code=h.code, title=h.title, status=h.status, source=h.source,
                                    share=round(share, 2)))
    found.sort(key=lambda s: (-s.share, s.code))
    return found[:SIMILAR_MAX]


class WeightIn(BaseModel):
    weight: Literal[1, 2, 3] | None


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


def _node_title(db: Session, nid: int | None) -> str:
    node = db.get(MethodologySection, nid) if nid else None
    return node.title if node else ""


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
        methodology_node=node_number(db, h.methodology_node_id),
        methodology_node_title=_node_title(db, h.methodology_node_id),
        effect=h.effect or "", target_kind=h.target_kind or "",
        weight=h.weight, weight_set_by=_login(db, h.weight_set_by),
        source=h.source, suggested=h.suggested or {},
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
                   status="proposed", author_id=user.id,
                   methodology_node_id=node_id(db, body.methodology_node),
                   effect=body.effect, target_kind=body.target_kind, weight=body.weight,
                   weight_set_by=user.id if body.weight else None)
    db.add(h)
    db.flush()
    for ref in body.refs:
        _add_ref(db, h, ref)
    db.commit()
    return _out(db, h)


@router.post("/similar", response_model=list[SimilarOut], dependencies=[Depends(current_user)])
def similar(body: SimilarIn, db: Annotated[Session, Depends(get_db)]) -> list[SimilarOut]:
    """Похожие уже предложенные идеи: показываются автору до отправки, ничего не меняют."""
    return similar_ideas(db, body.title, body.statement)


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


@router.put("/{code}/weight", response_model=HypothesisOut)
def set_weight(
    code: str, body: WeightIn, db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, ReviewerRole],
) -> HypothesisOut:
    """Вес связи меняет рецензент (или owner) при любом статусе; автор ставит его при отправке."""
    h = _get(db, code)
    # кто менял — помним и при сбросе: иначе не видно, кто убрал вес
    h.weight, h.weight_set_by = body.weight, user.id
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
    if body.status == "accepted":
        # приняли к проверке — Qwen предложит эксперимент: метод, срез, параметры
        enqueue(db, "experiment", {"hypothesis": h.code}, trigger="hypothesis", user_id=user.id)
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
    experiment_from_hypothesis(db, h, user.id)
    close_open_proposals(db, h, user.id)
    db.commit()
    return _out(db, h)
