"""Статьи, загруженные через сайт: очередь импорта в базу знаний KBRAG.

Разбирает и загружает статью обработчик на машине с KBRAG (deploy/windows/kb_import_worker.py),
теми же средствами, что `kbrag.py import`. Платформа кладёт PDF в папку приёма (KB_INBOX_DIR) и
хранит только статус: статья живёт в KBRAG, а он ссылается на этот PDF (pdf_path), поэтому
файл из папки приёма не удаляется.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

IMPORT_STATUSES = ("queued", "processing", "done", "duplicate", "failed")


class KbImport(Base):
    __tablename__ = "kb_imports"

    id: Mapped[int] = mapped_column(primary_key=True)
    kb_path: Mapped[str] = mapped_column(String(256))  # ветка KBRAG, куда кладётся статья
    source: Mapped[str] = mapped_column(String(8), default="file")  # file — загружен, doi — скачан
    filename: Mapped[str] = mapped_column(String(512), default="")  # имя, под которым загрузили
    storage_path: Mapped[str] = mapped_column(String(1024), default="")  # от корня папки приёма
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    bytes_len: Mapped[int] = mapped_column(Integer, default=0)
    doi: Mapped[str] = mapped_column(String(256), default="")
    title: Mapped[str] = mapped_column(String(1024), default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(
        Enum(*IMPORT_STATUSES, name="kb_import_status", native_enum=False, length=16),
        default="queued",
    )
    doc_id: Mapped[str] = mapped_column(String(512), default="")  # идентификатор статьи в KBRAG
    message: Mapped[str] = mapped_column(Text, default="")  # что сказал разбор
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
