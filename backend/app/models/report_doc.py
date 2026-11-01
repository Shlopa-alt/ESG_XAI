"""Отчёт по эксперименту: факты расчёта и текст Qwen, рецензия, выгрузка, база знаний.

facts — заморожены при создании отчёта из эксперимента и запуска: постановка, данные, метод,
параметры, воспроизводимость, ключевые цифры и графики (числа берутся из run.json, не у модели).
sections — текст Qwen: резюме, вердикт по гипотезе, интерпретация, ограничения, что это значит
для задания методики, что дальше. Человек правит текст, рецензент одобряет — тогда PDF отчёта
уходит в базу знаний (ветка esg.experiments) через очередь импорта статей.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

REPORT_STATUSES = ("draft", "review", "approved", "rejected")


class ExperimentReport(Base):
    __tablename__ = "experiment_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # номер отчёта у эксперимента
    status: Mapped[str] = mapped_column(
        Enum(*REPORT_STATUSES, name="report_status", native_enum=False, length=16), default="draft"
    )
    facts: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    sections: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    problems: Mapped[str] = mapped_column(Text, default="")  # числа в тексте, которых нет в расчёте
    note: Mapped[str] = mapped_column(Text, default="")  # решение рецензента
    qwen_job_id: Mapped[int | None] = mapped_column(ForeignKey("qwen_jobs.id"), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    kb_import_id: Mapped[int | None] = mapped_column(ForeignKey("kb_imports.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
