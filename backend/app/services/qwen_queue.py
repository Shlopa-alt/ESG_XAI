"""Постановка задач Qwen в очередь (см. app/models/qwen_job.py)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import QwenJob


def enqueue(db: Session, kind: str, payload: dict[str, Any] | None = None, trigger: str = "manual",
            user_id: int | None = None, dedupe: bool = True) -> QwenJob:
    """Задача в очередь. dedupe — такая же (вид и данные) уже ждёт: вторая не нужна —
    например, после пяти импортов подряд граф достраивается один раз."""
    payload = payload or {}
    if dedupe:
        for job in db.scalars(select(QwenJob).where(QwenJob.kind == kind, QwenJob.status == "queued")):
            if job.payload == payload:
                return job
    job = QwenJob(kind=kind, payload=payload, trigger=trigger, created_by=user_id, status="queued")
    db.add(job)
    db.flush()
    return job
