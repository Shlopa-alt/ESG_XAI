"""Запуски экспериментов: что, на каких данных и в каком окружении посчитано (правило 3)."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RUN_STATUSES = ("queued", "running", "done", "failed", "stopped")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    status: Mapped[str] = mapped_column(
        Enum(*RUN_STATUSES, name="run_status", native_enum=False, length=16), default="queued"
    )
    resource: Mapped[str] = mapped_column(String(8), default="cpu")
    runner_commit: Mapped[str] = mapped_column(String(64), default="")
    dataset_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_snapshots.id"), nullable=True
    )
    env_lock_sha256: Mapped[str] = mapped_column(String(64), default="")
    python: Mapped[str] = mapped_column(String(32), default="")
    seeds: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    parts: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)  # имя → аргументы, код, время
    summary: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)  # итоговые метрики
    results_path: Mapped[str] = mapped_column(String(1024), default="")
    mlflow_run_id: Mapped[str] = mapped_column(String(64), default="")
    # Запуск из формы: шаблон (app/services/run_templates.py), его параметры, задача в очереди
    template: Mapped[str] = mapped_column(String(64), default="")
    config: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    task_id: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text, default="")  # почему остановлен или упал
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
