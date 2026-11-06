"""Черновик датасета из таблицы статьи KBRAG.

Обработчик Qwen (задача `tables`) разбирает таблицы статьи кодом (runner/qwen/tables.py), Qwen
отбирает таблицы-наблюдения и описывает их. Человек (researcher+) смотрит черновик, правит его
руками или командами Qwen (задача `table_edit`) — и создаёт датасет со срезом или отклоняет
черновик.
Правки — операции из фиксированного набора (app/services/data_drafts.py), каждая — в журнале.
Статья не копируется (правило 8): в черновике — только таблица и ссылка на статью.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

DRAFT_STATUSES = ("proposed", "approved", "rejected")


class DataDraft(Base):
    __tablename__ = "data_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # откуда таблица: статья KBRAG, номер таблицы в статье, страница, подпись
    doc_id: Mapped[str] = mapped_column(String(512), index=True)
    kb_path: Mapped[str] = mapped_column(String(256), default="esg")
    article_title: Mapped[str] = mapped_column(String(1024), default="")
    doi: Mapped[str] = mapped_column(String(256), default="")
    table_number: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str] = mapped_column(Text, default="")
    # что предлагается: название и описание будущего датасета, таблица наблюдений
    title: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    columns: Mapped[list[str]] = mapped_column(JSON, default=list)
    rows: Mapped[list[list[Any]]] = mapped_column(JSON, default=list)
    # что сделано с таблицей статьи: разбор кодом, затем правки людей и Qwen —
    # [{"at", "who", "kind": parse|manual|qwen, "text", "ops"}]
    history: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(
        Enum(*DRAFT_STATUSES, name="data_draft_status", native_enum=False, length=16),
        default="proposed",
    )
    note: Mapped[str] = mapped_column(Text, default="")  # решение человека
    qwen_job_id: Mapped[int | None] = mapped_column(ForeignKey("qwen_jobs.id"), nullable=True)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id"), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
