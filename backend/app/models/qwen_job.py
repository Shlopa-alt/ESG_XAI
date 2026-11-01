"""Задачи для Qwen: модель поднимается по требованию, когда в очереди есть работа.

Очередь разбирает обработчик на машине с видеокартой (runner/qwen/worker.py): поднимает vLLM,
выполняет задачи по одной и выключает модель, когда очередь пуста, — видеокарта занята, только
пока есть работа. Виды задач — QWEN_KINDS; что делает каждая, описано в обработчике.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

QWEN_KINDS = ("graph", "ping")
QWEN_STATUSES = ("queued", "running", "done", "failed", "cancelled")


class QwenJob(Base):
    __tablename__ = "qwen_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        Enum(*QWEN_STATUSES, name="qwen_job_status", native_enum=False, length=16), default="queued"
    )
    # откуда задача: manual — кнопка, import — импорт статьи, snapshot — новый срез, run — запуск
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    message: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
