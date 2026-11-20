"""Личные токены открытого API: выпуск, проверка, отметка использования.

Запрос с токеном: заголовок «Authorization: Bearer esg_…». Токен действует от имени владельца и с
его ролью; «только чтение» пропускает лишь GET. Учётной записью (токены, пароль, почта,
пользователи) через токен управлять нельзя — только со входом на сайте: утёкший токен не даёт
выпустить себе новый или сменить пароль.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.models import ApiToken

PREFIX = "esg_"
MAX_DAYS = 365
MAX_ACTIVE = 10
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# управление учётной записью — только со входом на сайте
ACCOUNT_PATHS = ("/api/tokens", "/api/auth/", "/api/users")
TOUCH_EVERY = timedelta(minutes=1)


def bearer(request: Request) -> str | None:
    """Токен из заголовка Authorization; None — заголовка нет или он не про наш токен."""
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token.startswith(PREFIX):
        return None
    return token


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue() -> tuple[str, str, str]:
    """(токен, его sha256, начало для списка)."""
    token = PREFIX + secrets.token_urlsafe(32)
    return token, digest(token), token[:12]


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def active(tok: ApiToken, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return tok.revoked_at is None and _aware(tok.expires_at) > now


def find(db: Session, token: str) -> ApiToken | None:
    tok = db.scalar(select(ApiToken).where(ApiToken.token_hash == digest(token)))
    return tok if tok is not None and active(tok) else None


def touch(db: Session, tok: ApiToken) -> None:
    """Когда токеном пользовались последний раз — не чаще раза в минуту: не на каждый запрос."""
    now = datetime.now(UTC)
    if tok.last_used_at is None or now - _aware(tok.last_used_at) > TOUCH_EVERY:
        tok.last_used_at = now
        db.commit()


def denied(tok: ApiToken, method: str, path: str) -> str | None:
    """Почему запрос с этим токеном нельзя выполнить; None — можно."""
    if path.startswith(ACCOUNT_PATHS) and path != "/api/auth/me":
        return "Учётной записью и токенами через API управлять нельзя — только со входом на сайте"
    if tok.scope != "write" and method.upper() not in READ_METHODS:
        return "Токен только для чтения: изменять и запускать можно токеном «чтение и запуск»"
    return None
