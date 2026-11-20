"""Личный токен открытого API: программы и скрипты обращаются к платформе от имени человека.

Токен показывается один раз при создании; в базе — только его sha256 и первые символы, чтобы
человек узнал свой токен в списке. Права — роль владельца токена, сузить можно до «только чтение».
Срок обязателен; отозванный или истёкший токен не действует, заблокированный человек — тоже.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TOKEN_SCOPES = ("read", "write")


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(8), default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
