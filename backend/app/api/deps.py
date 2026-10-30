from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User
from app.services.auth import read_session_token


def current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    # Имя cookie — из настроек, то же, под которым её выдаёт /auth/login
    token = request.cookies.get(settings.session_cookie_name)
    uid = read_session_token(settings, token) if token else None
    user = db.get(User, uid) if uid is not None else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    """Допускает пользователей с одной из ролей; owner допускается всегда."""

    allowed = {*roles, "owner"}

    def checker(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return checker
