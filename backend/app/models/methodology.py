"""Методология: разделы, версии, предложения изменений (CR) и их основания (docs/SPEC.md, раздел 3)."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

STABILITIES = ("stable", "draft", "contested")
CR_STATUSES = ("proposed", "review", "accepted", "rejected")
BASIS_TYPES = ("experiment", "kb_fact", "kb_article")


class MethodologySection(Base):
    __tablename__ = "methodology_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(16), unique=True)
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text, default="")
    stability: Mapped[str] = mapped_column(
        Enum(*STABILITIES, name="stability", native_enum=False, length=16), default="draft"
    )


class MethodologyVersion(Base):
    __tablename__ = "methodology_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(16), unique=True)
    # {номер раздела: {"title", "content", "stability"}} — снимок всех разделов
    sections_content: Mapped[dict[str, dict[str, str]]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChangeRequest(Base):
    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("methodology_sections.id"))
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    proposed_content: Mapped[str] = mapped_column(Text, default="")  # новый текст раздела
    status: Mapped[str] = mapped_column(
        Enum(*CR_STATUSES, name="cr_status", native_enum=False, length=16), default="proposed"
    )
    target_version: Mapped[str] = mapped_column(String(16), default="")
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CrBasis(Base):
    __tablename__ = "cr_bases"

    id: Mapped[int] = mapped_column(primary_key=True)
    cr_id: Mapped[int] = mapped_column(ForeignKey("change_requests.id"))
    basis_type: Mapped[str] = mapped_column(
        Enum(*BASIS_TYPES, name="basis_type", native_enum=False, length=16)
    )
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), nullable=True)
    kb_ref_id: Mapped[int | None] = mapped_column(ForeignKey("kb_refs.id"), nullable=True)
