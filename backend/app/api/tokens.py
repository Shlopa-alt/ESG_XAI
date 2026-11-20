"""Личные токены открытого API: свои — создать, посмотреть, отозвать; владелец платформы видит и
отзывает все. Только со входом на сайте: через сам токен этих адресов нет
(services/api_tokens.py)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db import get_db
from app.models import ApiToken, User
from app.services import api_tokens

router = APIRouter(prefix="/tokens", tags=["tokens"])


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    scope: Literal["read", "write"] = "read"
    days: int = Field(default=90, ge=1, le=api_tokens.MAX_DAYS)


class TokenOut(BaseModel):
    id: int
    login: str
    name: str
    prefix: str
    scope: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    active: bool


class NewToken(TokenOut):
    token: str  # показывается один раз


def _out(tok: ApiToken, login: str) -> TokenOut:
    return TokenOut(id=tok.id, login=login, name=tok.name, prefix=tok.prefix, scope=tok.scope,
                    created_at=tok.created_at, expires_at=tok.expires_at,
                    last_used_at=tok.last_used_at, revoked_at=tok.revoked_at,
                    active=api_tokens.active(tok))


@router.get("", response_model=list[TokenOut])
def list_tokens(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    all: bool = False,  # noqa: A002 — так короче в адресе: ?all=true
) -> list[TokenOut]:
    """Свои токены; владелец платформы с ?all=true — токены всех."""
    q = select(ApiToken, User.login).join(User, User.id == ApiToken.user_id)
    if not (all and user.role == "owner"):
        q = q.where(ApiToken.user_id == user.id)
    rows = db.execute(q.order_by(ApiToken.id.desc())).all()
    return [_out(tok, login) for tok, login in rows]


@router.post("", response_model=NewToken, status_code=status.HTTP_201_CREATED)
def create_token(
    body: TokenIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> NewToken:
    alive = [t for t in db.scalars(select(ApiToken).where(ApiToken.user_id == user.id))
             if api_tokens.active(t)]
    if len(alive) >= api_tokens.MAX_ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Действующих токенов уже {len(alive)} — отзовите ненужные")
    token, digest, prefix = api_tokens.issue()
    tok = ApiToken(user_id=user.id, name=body.name.strip(), token_hash=digest, prefix=prefix,
                   scope=body.scope, created_at=datetime.now(UTC),
                   expires_at=datetime.now(UTC) + timedelta(days=body.days))
    db.add(tok)
    db.commit()
    return NewToken(**_out(tok, user.login).model_dump(), token=token)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> Response:
    tok = db.get(ApiToken, token_id)
    if tok is None or (tok.user_id != user.id and user.role != "owner"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет токена №{token_id}")
    if tok.revoked_at is None:
        tok.revoked_at = datetime.now(UTC)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def revoke_all(db: Session, user_id: int) -> None:
    """Отозвать все токены человека (пароль сброшен владельцем — учётную запись могли увести)."""
    now = datetime.now(UTC)
    for tok in db.scalars(select(ApiToken).where(ApiToken.user_id == user_id,
                                                 ApiToken.revoked_at.is_(None))):
        tok.revoked_at = now
