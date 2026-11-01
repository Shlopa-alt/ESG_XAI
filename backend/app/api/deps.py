from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User
from app.services.auth import password_stamp, read_session_token

# С временным паролем доступны только эти адреса: узнать себя, сменить пароль, выйти
WHILE_MUST_CHANGE = frozenset({"/api/auth/me", "/api/auth/change-password", "/api/auth/logout"})


def current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    # Имя cookie — из настроек, то же, под которым её выдаёт /auth/login
    token = request.cookies.get(settings.session_cookie_name)
    session = read_session_token(settings, token) if token else None
    user = db.get(User, session[0]) if session is not None else None
    # Сессия недействительна, если пользователя заблокировали или сменили ему пароль
    if user is None or session is None or not user.is_active or session[1] != password_stamp(user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
    # В режиме личных паролей сессия без пароля (открытая до перехода) не действует
    if settings.auth_backend == "password" and not user.password_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
    if user.must_change_password and request.url.path not in WHILE_MUST_CHANGE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Смените временный пароль")
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    """Допускает пользователей с одной из ролей; owner допускается всегда."""

    allowed = {*roles, "owner"}

    def checker(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return checker
