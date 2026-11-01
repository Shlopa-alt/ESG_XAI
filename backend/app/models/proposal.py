"""Предложение эксперимента от Qwen по принятой гипотезе.

Qwen предлагает метод из библиотеки (app/services/run_templates.py), срез и параметры, протокол и
что подтвердит или опровергнет гипотезу. Человек (researcher+) правит и одобряет — тогда
создаётся эксперимент и сразу ставится запуск — или отклоняет с объяснением.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

PROPOSAL_STATUSES = ("proposed", "approved", "rejected")


class ExperimentProposal(Base):
    __tablename__ = "experiment_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id"))
    qwen_job_id: Mapped[int | None] = mapped_column(ForeignKey("qwen_jobs.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(*PROPOSAL_STATUSES, name="proposal_status", native_enum=False, length=16), default="proposed"
    )
    title: Mapped[str] = mapped_column(String(512), default="")
    method: Mapped[str] = mapped_column(String(64), default="")  # ключ метода библиотеки; пусто — нет подходящего
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_snapshots.id"), nullable=True)
    params: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    setup: Mapped[list[str]] = mapped_column(JSON, default=list)  # протокол: шаги проверки
    expected: Mapped[str] = mapped_column(Text, default="")  # что подтвердит или опровергнет гипотезу
    rationale: Mapped[str] = mapped_column(Text, default="")  # почему такой метод и данные
    problems: Mapped[str] = mapped_column(Text, default="")  # что не так с предложением (проверка платформы)
    note: Mapped[str] = mapped_column(Text, default="")  # решение человека
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
