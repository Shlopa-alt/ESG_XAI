from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.models import User
from app.services.auth import authenticate, make_session_token
from app.services.passwords import check_strength, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    login: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    full_name: str
    email: str
    role: str
    nda_access: bool
    must_change_password: bool = False
    is_active: bool = True


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/login", response_model=UserOut)
def login(
    body: LoginIn,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    user = authenticate(db, settings, body.login.strip(), body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    response.set_cookie(
        settings.session_cookie_name,
        make_session_token(settings, user),
        max_age=settings.session_ttl_s,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    response.delete_cookie(settings.session_cookie_name)


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user


@router.post("/change-password", response_model=UserOut)
def change_password(
    body: ChangePasswordIn,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(current_user)],
) -> User:
    """Смена своего пароля (режим password); старые сессии после неё не действуют."""
    if settings.auth_backend != "password":
        raise HTTPException(status.HTTP_409_CONFLICT, "Пароль задаётся не платформой, а LDAP")
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный текущий пароль")
    problem = check_strength(body.new_password)
    if problem is None and body.new_password == body.old_password:
        problem = "Новый пароль совпадает с текущим"
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    response.set_cookie(
        settings.session_cookie_name,
        make_session_token(settings, user),
        max_age=settings.session_ttl_s,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return user
