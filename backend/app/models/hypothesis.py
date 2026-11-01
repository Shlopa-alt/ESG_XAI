"""Гипотезы: предлагает любой пользователь, разбирают рецензенты, проверяют экспериментом."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

H_STATUSES = ("proposed", "accepted", "rejected", "testing", "tested")


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    statement: Mapped[str] = mapped_column(Text)  # проверяемое утверждение
    rationale: Mapped[str] = mapped_column(Text, default="")  # почему так думаем, откуда
    direction: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(
        Enum(*H_STATUSES, name="h_status", native_enum=False, length=16), default="proposed"
    )
    decision_note: Mapped[str] = mapped_column(Text, default="")  # почему приняли или отклонили
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), nullable=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(8), default="human")  # human | qwen — кто предложил
    # что Qwen предлагает для проверки: {"dataset": "DS-04", "method": "…"} — исходные данные шага «эксперимент»
    suggested: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    qwen_job_id: Mapped[int | None] = mapped_column(ForeignKey("qwen_jobs.id"), nullable=True)
    # узел методики (задание, вариант или направление), к которому относится
    methodology_node_id: Mapped[int | None] = mapped_column(ForeignKey("methodology_sections.id"),
                                                            nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HypothesisRef(Base):
    """Опора гипотезы в базе знаний: статья или факт KBRAG."""

    __tablename__ = "hypothesis_refs"

    id: Mapped[int] = mapped_column(primary_key=True)
    hypothesis_id: Mapped[int] = mapped_column(ForeignKey("hypotheses.id"))
    kb_ref_id: Mapped[int] = mapped_column(ForeignKey("kb_refs.id"))
