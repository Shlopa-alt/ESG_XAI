"""Очередь задач Qwen: модель работает по требованию (app/models/qwen_job.py).

Очередь, состояние модели и видеокарты видит и ведёт только owner: это служебная кухня, а результат
(гипотезы, отчёты) остальные видят на своих страницах.
Обработчик на машине с видеокартой (runner/qwen/worker.py) забирает задачи и сообщает итог и
своё состояние (модель выключена / запускается / работает) по токену X-Qwen-Token.
"""

import json
import secrets
import time
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import redis
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.config import Settings, get_settings
from app.db import get_db
from app.models import ExperimentReport, QwenJob, User
from app.models.qwen_job import QWEN_KINDS
from app.services import qwen_experiments, qwen_hypotheses, qwen_reports
from app.services.qwen_queue import enqueue

router = APIRouter(prefix="/qwen", tags=["qwen"])

Owner = Depends(require_role())  # только owner
HEARTBEAT = "qwen:heartbeat"
HEARTBEAT_TTL_S = 120  # обработчик отмечается раз в 30 с; дольше молчит — считается остановленным
MANUAL_KINDS = ("graph", "ping", "hypotheses")  # что owner может поставить кнопкой


class JobOut(BaseModel):
    id: int
    kind: str
    status: str
    trigger: str
    payload: dict[str, Any]
    result: dict[str, Any]
    message: str
    author: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class StatusOut(BaseModel):
    worker: bool  # обработчик отмечался недавно
    model: str  # off | starting | on | stopping
    detail: str
    gpu_used_mb: int | None
    gpu_total_mb: int | None
    seen_at: float | None
    queued: int
    running: int


class JobIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


class Heartbeat(BaseModel):
    model: Literal["off", "starting", "on", "stopping"]
    detail: str = ""
    gpu_used_mb: int | None = None
    gpu_total_mb: int | None = None


class JobResult(BaseModel):
    status: Literal["done", "failed"]
    result: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


def _out(db: Session, j: QwenJob) -> JobOut:
    user = db.get(User, j.created_by) if j.created_by else None
    return JobOut(id=j.id, kind=j.kind, status=j.status, trigger=j.trigger, payload=j.payload or {},
                  result=j.result or {}, message=j.message, author=user.login if user else "",
                  created_at=j.created_at, started_at=j.started_at, finished_at=j.finished_at)


def _redis(settings: Settings) -> "redis.Redis[bytes]":
    return redis.Redis.from_url(settings.redis_url, socket_timeout=3)


def _worker(settings: Annotated[Settings, Depends(get_settings)],
            x_qwen_token: Annotated[str, Header()] = "") -> None:
    if not settings.qwen_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "QWEN_TOKEN не задан")
    if not secrets.compare_digest(x_qwen_token, settings.qwen_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный токен обработчика Qwen")


Worker = Depends(_worker)


@router.get("/status", response_model=StatusOut, dependencies=[Owner])
def qwen_status(db: Annotated[Session, Depends(get_db)],
                settings: Annotated[Settings, Depends(get_settings)]) -> StatusOut:
    try:
        raw = _redis(settings).get(HEARTBEAT)
    except redis.RedisError:
        raw = None
    beat = json.loads(raw) if raw else {}
    count = lambda s: len(list(db.scalars(select(QwenJob.id).where(QwenJob.status == s))))  # noqa: E731
    return StatusOut(worker=bool(beat), model=beat.get("model", "off"), detail=beat.get("detail", ""),
                     gpu_used_mb=beat.get("gpu_used_mb"), gpu_total_mb=beat.get("gpu_total_mb"),
                     seen_at=beat.get("at"), queued=count("queued"), running=count("running"))


@router.get("/jobs", response_model=list[JobOut], dependencies=[Owner])
def list_jobs(db: Annotated[Session, Depends(get_db)]) -> list[JobOut]:
    return [_out(db, j) for j in db.scalars(select(QwenJob).order_by(QwenJob.id.desc()).limit(100))]


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def add_job(body: JobIn, db: Annotated[Session, Depends(get_db)],
            user: Annotated[User, Owner]) -> JobOut:
    if body.kind not in MANUAL_KINDS or body.kind not in QWEN_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Задачу «{body.kind}» кнопкой не ставят")
    job = enqueue(db, body.kind, body.payload, trigger="manual", user_id=user.id)
    db.commit()
    return _out(db, job)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, db: Annotated[Session, Depends(get_db)],
               _user: Annotated[User, Owner]) -> JobOut:
    job = db.get(QwenJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет задачи №{job_id}")
    if job.status != "queued":
        raise HTTPException(status.HTTP_409_CONFLICT, "Снять можно только задачу в очереди")
    job.status, job.finished_at, job.message = "cancelled", datetime.now(UTC), "снята с очереди"
    db.commit()
    return _out(db, job)


# --- обработчик на машине с видеокартой ---


@router.post("/worker/heartbeat", dependencies=[Worker])
def heartbeat(body: Heartbeat, settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, bool]:
    _redis(settings).set(HEARTBEAT, json.dumps({**body.model_dump(), "at": time.time()}), ex=HEARTBEAT_TTL_S)
    return {"ok": True}


@router.post("/worker/requeue", dependencies=[Worker])
def requeue(db: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    """При старте обработчика: то, что он делал до остановки, — снова в очередь."""
    n = db.execute(update(QwenJob).where(QwenJob.status == "running")
                   .values(status="queued", started_at=None)).rowcount
    db.commit()
    return {"requeued": n}


@router.post("/worker/peek", dependencies=[Worker])
def peek(db: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    """Есть ли работа — чтобы поднять модель до того, как брать задачу."""
    return {"queued": len(list(db.scalars(select(QwenJob.id).where(QwenJob.status == "queued"))))}


@router.post("/worker/context", dependencies=[Worker])
def worker_context(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Что нужно Qwen для гипотез: задания методики с разделами, датасеты, методы, прежние гипотезы."""
    return qwen_hypotheses.context(db)


class ExperimentContextIn(BaseModel):
    hypothesis: str


@router.post("/worker/experiment-context", dependencies=[Worker])
def worker_experiment_context(body: ExperimentContextIn, db: Annotated[Session, Depends(get_db)],
                              settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    """Что нужно Qwen для предложения эксперимента: гипотеза, задание, методы, срезы со столбцами."""
    try:
        return qwen_experiments.context(db, settings, body.hypothesis)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


class ReportContextIn(BaseModel):
    report: int


@router.post("/worker/report-context", dependencies=[Worker])
def worker_report_context(body: ReportContextIn, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Что нужно Qwen для отчёта: факты расчёта, задание методики с разделами, опоры гипотезы."""
    r = db.get(ExperimentReport, body.report)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет отчёта №{body.report}")
    return qwen_reports.context(db, r)


@router.post("/worker/next", response_model=JobOut, dependencies=[Worker],
             responses={204: {"description": "очередь пуста"}})
def next_job(db: Annotated[Session, Depends(get_db)]) -> JobOut | Response:
    job = db.scalars(select(QwenJob).where(QwenJob.status == "queued").order_by(QwenJob.id)
                     .limit(1).with_for_update(skip_locked=True)).first()
    if job is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    job.status, job.started_at = "running", datetime.now(UTC)
    db.commit()
    return _out(db, job)


@router.post("/worker/{job_id}/result", response_model=JobOut, dependencies=[Worker])
def job_result(job_id: int, body: JobResult, db: Annotated[Session, Depends(get_db)],
               settings: Annotated[Settings, Depends(get_settings)]) -> JobOut:
    job = db.get(QwenJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет задачи №{job_id}")
    if job.status != "running":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Задача №{job_id} уже {job.status}")
    job.status, job.result, job.message = body.status, body.result, body.message[:4000]
    job.finished_at = datetime.now(UTC)
    if job.kind == "hypotheses" and body.status == "done":
        # предложения модели проверяются здесь: опоры, повторы, предел нерассмотренных на задание
        created = qwen_hypotheses.create_from_result(db, job, body.result)
        job.result = {**{k: v for k, v in body.result.items() if k != "hypotheses"},
                      "proposed": len(body.result.get("hypotheses") or []), "created": created}
        job.message = (f"Предложено гипотез: {len(created)} — {', '.join(created)}" if created
                       else "Новых гипотез нет: опор не нашлось или по заданиям уже ждут рецензии")
    if job.kind == "report" and body.status == "done":
        r = qwen_reports.apply_result(db, job, body.result)
        job.message = (f"Отчёт v{r.version} написан" + (f" — {r.problems}" if r.problems else "") if r is not None
                       else "Отчёт уже рассмотрен — текст не нужен")
    if job.kind == "experiment" and body.status == "done":
        p = qwen_experiments.create_from_result(db, settings, job, body.result)
        job.message = (f"Предложен эксперимент для {job.payload.get('hypothesis')}: «{p.title}»"
                       + (f" — поправить: {p.problems}" if p.problems else "") if p is not None
                       else "Гипотезу уже проверяют или отклонили — предложение не нужно")
    db.commit()
    return _out(db, job)
