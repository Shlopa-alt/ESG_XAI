"""Анализ данных: рекомендация метода по показателю и набору данных и расчёт в один шаг.

Рекомендацию смотрит любой вошедший (столбцы версии данных под NDA — только с допуском, как и
выгрузка файлов: правило 6). Запуск — researcher+: создаёт проверку EXP-NNN с пунктом методики,
данными, методом и причиной выбора и ставит расчёт метода библиотеки (app/api/runs.py: start_run —
там же проверки параметров, среза и лимитов). Воспроизводимость расчёт фиксирует сам (правило 3).
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
from app.models import Dataset, DatasetSnapshot, Experiment, MethodologySection, User
from app.services import analysis
from app.services.codes import next_code
from app.services.run_templates import TEMPLATES

router = APIRouter(prefix="/analysis", tags=["analysis"])

Researcher = Depends(require_role("researcher"))


class RecommendIn(BaseModel):
    snapshot_id: int
    sheet: str = ""
    target: str = ""  # целевой показатель; пусто — сравнить показатели между собой
    node: str = ""  # пункт методики (номер), к которому относится анализ


class Choice(BaseModel):
    """Что выбрал человек и почему — пишется в проверку (config.analysis) и видно на её странице."""

    key: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=512)
    why: list[str] = Field(default_factory=list, max_length=20)
    primary: bool = False  # выбрана рекомендация платформы, а не альтернатива
    net: str = Field(default="", max_length=64)


class LaunchIn(BaseModel):
    snapshot_id: int
    template: str
    params: dict[str, Any] = Field(default_factory=dict)
    node: str = ""
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


@router.post("/recommend")
def recommend(
    body: RecommendIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    snap, ds = _snapshot(db, body.snapshot_id)
    table = snapshot_table(db, settings, snap, user, body.sheet)  # NDA — только с допуском
    try:
        out = analysis.recommend(table, snap.row_count, body.target, _node(db, body.node))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {
        "snapshot": {"id": snap.id, "dataset": ds.code, "title": ds.title, "version": snap.version},
        **out,
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
    try:
        exp = Experiment(
            code=next_code(db, Experiment.code, "EXP", 3),
            title=body.title.strip() or f"{body.choice.title or t.title} · {ds.code}",
            hypothesis=analysis.question(t.key, body.params),
            status="running",
            author_id=user.id,
            method=t.title,
            data_summary=f"{ds.code} · версия {snap.version}"[:512],
            dataset_snapshot_id=snap.id,
            methodology_node_id=node.id if node else None,
            setup=[*body.choice.why[:10]],
            results=[],
            limitations=[],
            reproducibility=[],
            config={
                "analysis": {
                    "template": t.key,
                    "snapshot_id": snap.id,
                    "node": body.node,
                    **body.choice.model_dump(),
                }
            },
        )
        db.add(exp)
        db.flush()
        run = start_run(db, settings, user, t.key, snap.id, body.params, exp.code)
    except HTTPException:
        db.rollback()  # проверка без расчёта в реестре не нужна
        raise
    db.commit()
    return LaunchOut(experiment=exp.code, run_id=run.id)
