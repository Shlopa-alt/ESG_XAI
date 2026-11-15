"""«Что говорят статьи» по пункту методики (app/services/articles_summary.py).

Смотрит любой вошедший — как граф и статьи банка: данные приходят из KBRAG со служебным токеном
платформы через тот же прокси (app/api/kb.py), платформа их не хранит (правило 8). Рядом —
свои итоги платформы по пункту: проверки с итогом, в том числе отрицательным (правило 4), и идеи
с типом связи. Ничего не создаёт и не меняет.
"""

import json
from typing import Annotated, Any
from urllib.error import URLError
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import kb as kb_api
from app.api.deps import current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Experiment, Hypothesis, MethodologySection
from app.services import articles_summary as svc

router = APIRouter(prefix="/methodology/sections", tags=["methodology"])

ROOT_KB = "esg"


def _node(db: Session, number: str) -> MethodologySection:
    node = db.scalar(select(MethodologySection).where(MethodologySection.number == number))
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет пункта методики {number}")
    return node


def _kbrag(settings: Settings, name: str, params: dict[str, str]) -> tuple[int, Any]:
    url = f"{settings.kbrag_url.rstrip('/')}/api/{name}?{urlencode(params)}"
    try:
        code, body, _ = kb_api.fetch(url, settings.kbrag_token, settings.kbrag_timeout_s)
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Банк статей недоступен: {exc}") from exc
    try:
        return code, json.loads(body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Банк статей ответил не JSON") from exc


def _dataset(settings: Settings, name: str) -> dict[str, Any]:
    code, data = _kbrag(settings, "dataset", {"name": name, "kb": ROOT_KB})
    if code == 400:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Понятия «{name}» в статьях банка нет")
    if code != 200:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Банк статей ответил {code}")
    return dict(data)


@router.get("/{number}/articles", dependencies=[Depends(current_user)])
def articles(
    number: str, db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    factor: Annotated[str, Query(min_length=1, max_length=200)],
    outcome: Annotated[str, Query(min_length=1, max_length=200)],
) -> dict[str, Any]:
    """Что статьи банка говорят о связи «фактор → результат» и что по пункту уже есть у нас."""
    node = _node(db, number)
    summary = svc.summarize(_dataset(settings, factor), _dataset(settings, outcome))
    exps = db.scalars(select(Experiment).where(Experiment.methodology_node_id == node.id)
                      .order_by(Experiment.code))
    hyps = db.scalars(select(Hypothesis).where(Hypothesis.methodology_node_id == node.id)
                      .order_by(Hypothesis.code))
    summary["experiments"] = [{"code": e.code, "title": e.title, "status": e.status,
                               "outcome": e.outcome} for e in exps]
    summary["hypotheses"] = [_idea(db, h) for h in hyps]
    summary["findings"] = svc.findings(summary, summary["hypotheses"])
    return summary


def _idea(db: Session, h: Hypothesis) -> dict[str, Any]:
    exp = db.get(Experiment, h.experiment_id) if h.experiment_id else None
    return {"code": h.code, "title": h.title, "status": h.status, "effect": h.effect,
            "target_kind": h.target_kind, "weight": h.weight,
            "experiment": exp.code if exp else "", "outcome": exp.outcome if exp else None}
