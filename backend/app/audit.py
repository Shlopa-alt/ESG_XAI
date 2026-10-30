"""Журнал аудита (docs/SPEC.md, раздел 7): каждое изменяющее действие — кто, что, результат.

Пишется прослойкой для POST/PATCH/PUT/DELETE под /api. Тело запроса не сохраняется
(в нём бывают пароли) — только метод, адрес, код ответа, пользователь и адрес клиента.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings
from app.db import Base, SessionLocal
from app.services.auth import read_session_token

WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    login: Mapped[str] = mapped_column(String(128), default="")
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(512))
    status: Mapped[int] = mapped_column(Integer)
    client: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _client(request: Request) -> str:
    # За nginx настоящий адрес — в X-Real-IP
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "")


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.method in WRITE_METHODS and request.url.path.startswith("/api/"):
            try:
                record(request, response.status_code)
            except Exception:  # noqa: BLE001 — сбой журнала не должен ронять запрос
                pass
        return response


def record(request: Request, status_code: int) -> None:
    from app.models import User  # здесь — чтобы не было циклического импорта

    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    session = read_session_token(settings, token) if token else None
    with SessionLocal() as db:
        user = db.get(User, session[0]) if session else None
        login = user.login if user else ""
        if request.url.path == "/api/auth/login" and not login:
            login = "(вход)"
        db.add(AuditLog(user_id=user.id if user else None, login=login, method=request.method,
                        path=request.url.path[:512], status=status_code, client=_client(request)))
        db.commit()
