"""Анализ данных: рекомендация метода по показателю и набору данных и расчёт в один шаг.

Рекомендацию смотрит любой вошедший (столбцы версии данных под NDA — только с допуском, как и
выгрузка файлов: правило 6). Запуск — researcher+: создаёт проверку EXP-NNN с пунктом методики,
данными, методом и причиной выбора и ставит расчёт метода библиотеки (app/api/runs.py: start_run —
там же проверки параметров, среза и лимитов). Воспроизводимость расчёт фиксирует сам (правило 3).

С идеей для проверки (hypothesis): платформа ищет в статье-источнике, какой сетью пользовались
авторы, и ставит первой карточку «как у авторов» (app/services/net_catalog.py). Проверка по идее
создаётся только из принятой идеи, источники переносятся как основания (SPEC, раздел 3).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.api.runs import snapshot_table, start_run
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    Dataset,
    DatasetSnapshot,
    Experiment,
    Hypothesis,
    HypothesisRef,
    KbRef,
    MethodologySection,
    User,
)
from app.services import analysis, kb_text, net_catalog
from app.services.codes import next_code
from app.services.qwen_experiments import experiment_from_hypothesis
from app.services.run_templates import TEMPLATES

router = APIRouter(prefix="/analysis", tags=["analysis"])

Researcher = Depends(require_role("researcher"))
MAX_ARTICLES = 3  # статей-источников, в которых ищем сеть авторов


class RecommendIn(BaseModel):
    snapshot_id: int
    sheet: str = ""
    target: str = ""  # целевой показатель; пусто — сравнить показатели между собой
    node: str = ""  # пункт методики (номер), к которому относится анализ
    hypothesis: str = ""  # идея для проверки (H-NNN): «как у авторов» по её статье


class Choice(BaseModel):
    """Что выбрал человек и почему — пишется в проверку (config.analysis) и видно на её странице."""

    key: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=512)
    why: list[str] = Field(default_factory=list, max_length=20)
    primary: bool = False  # выбрана рекомендация платформы, а не альтернатива
    net: str = Field(default="", max_length=64)
    as_authors: bool = False  # повтор с сетью авторов статьи
    evidence: str = Field(default="", max_length=2000)  # цитата статьи о сети авторов
    article: str = Field(default="", max_length=1024)
    task: str = Field(default="", max_length=64)


class LaunchIn(BaseModel):
    snapshot_id: int
    template: str
    params: dict[str, Any] = Field(default_factory=dict)
    node: str = ""
    hypothesis: str = ""
    title: str = Field(default="", max_length=512)
    choice: Choice = Field(default_factory=Choice)


class LaunchOut(BaseModel):
    experiment: str
    run_id: int


def _node(db: Session, number: str) -> MethodologySection | None:
    if not number:
        return None
    node = db.scalar(select(MethodologySection).where(MethodologySection.number == number))
    if node is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Нет пункта методики {number}")
    return node


def _snapshot(db: Session, sid: int) -> tuple[DatasetSnapshot, Dataset]:
    snap = db.get(DatasetSnapshot, sid)
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    if snap is None or ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет версии данных №{sid}")
    return snap, ds


def _hypothesis(db: Session, code: str) -> Hypothesis | None:
    if not code:
        return None
    h = db.scalar(select(Hypothesis).where(Hypothesis.code == code))
    if h is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет идеи для проверки {code}")
    return h


def _refs(db: Session, h: Hypothesis) -> list[KbRef]:
    return list(
        db.scalars(
            select(KbRef)
            .join(HypothesisRef, HypothesisRef.kb_ref_id == KbRef.id)
            .where(HypothesisRef.hypothesis_id == h.id)
        )
    )


def authors(settings: Settings, refs: list[KbRef]) -> tuple[dict[str, Any] | None, str]:
    """Сеть авторов по статьям-источникам идеи: текст статьи из банка (не хранится), иначе — то,
    что записано в источнике (название и цитата). Возвращает (сеть с цитатой, пояснение)."""
    articles = [r for r in refs if r.kind == "article"][:MAX_ARTICLES]
    if not articles:
        return None, "У идеи нет статьи-источника — сеть авторов не определить."
    unavailable = []
    for ref in articles:
        try:
            text = kb_text.article_text(settings, ref.kbrag_id)
        except LookupError as exc:
            unavailable.append(str(exc))
            text = f"{ref.title}\n{ref.quote}"
        found = net_catalog.authors_net(text)
        if found is not None:
            return {**found, "article_title": ref.title, "doc_id": ref.kbrag_id}, ""
    if unavailable:
        return None, f"Текст статьи недоступен ({unavailable[0]}); в источнике сеть не названа."
    return None, "В статье-источнике не названа сеть или метод — рекомендация по данным."


@router.get("/catalog", dependencies=[Depends(current_user)])
def catalog() -> dict[str, Any]:
    """Классификация «тип задачи → рекомендуемые сети» и что из них считается в платформе."""
    return net_catalog.catalog()


@router.post("/recommend")
def recommend(
    body: RecommendIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    snap, ds = _snapshot(db, body.snapshot_id)
    table = snapshot_table(db, settings, snap, user, body.sheet)  # NDA — только с допуском
    h = _hypothesis(db, body.hypothesis)
    found, note = authors(settings, _refs(db, h)) if h is not None else (None, "")
    node = _node(db, body.node)
    if node is None and h is not None and h.methodology_node_id:
        node = db.get(MethodologySection, h.methodology_node_id)
    try:
        out = analysis.recommend(table, snap.row_count, body.target, node, found)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {
        "snapshot": {"id": snap.id, "dataset": ds.code, "title": ds.title, "version": snap.version},
        **out,
        "authors_note": out["authors_note"] or note,
        "hypothesis": (
            {
                "code": h.code,
                "title": h.title,
                "statement": h.statement,
                "status": h.status,
                "node": node.number if node else "",
            }
            if h is not None
            else None
        ),
    }


@router.post("/launch", response_model=LaunchOut, status_code=status.HTTP_201_CREATED)
def launch(
    body: LaunchIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Researcher],
) -> LaunchOut:
    """Проверка EXP-NNN и расчёт — одним действием. Не встал расчёт — нет и проверки."""
    t = TEMPLATES.get(body.template)
    if t is None or t.scope != "generic":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Анализ данных запускает только общие методы библиотеки",
        )
    snap, ds = _snapshot(db, body.snapshot_id)
    node = _node(db, body.node)
    h = _hypothesis(db, body.hypothesis)
    if h is not None and h.status != "accepted":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{h.code} не принята к проверке — проверку создают только из принятой идеи",
        )
    title = body.title.strip() or f"{body.choice.title or t.title} · {ds.code}"
    summary = f"{ds.code} · версия {snap.version}"[:512]
    choice = {
        "template": t.key,
        "snapshot_id": snap.id,
        "node": body.node,
        **body.choice.model_dump(),
    }
    try:
        if h is not None:
            # идея и её источники переносятся в проверку, идея — «проверяется»
            exp = experiment_from_hypothesis(
                db,
                h,
                user.id,
                title=title,
                method=t.title,
                data_summary=summary,
                setup=[*body.choice.why[:10]],
            )
            if node is not None:
                exp.methodology_node_id = node.id
        else:
            exp = Experiment(
                code=next_code(db, Experiment.code, "EXP", 3),
                title=title,
                hypothesis=analysis.question(t.key, body.params),
                author_id=user.id,
                method=t.title,
                data_summary=summary,
                methodology_node_id=node.id if node else None,
                setup=[*body.choice.why[:10]],
                results=[],
                limitations=[],
                reproducibility=[],
            )
            db.add(exp)
        exp.status, exp.dataset_snapshot_id = "running", snap.id
        exp.config = {**(exp.config or {}), "analysis": choice}
        db.flush()
        run = start_run(db, settings, user, t.key, snap.id, body.params, exp.code)
    except HTTPException:
        db.rollback()  # проверка без расчёта в реестре не нужна
        raise
    db.commit()
    return LaunchOut(experiment=exp.code, run_id=run.id)
