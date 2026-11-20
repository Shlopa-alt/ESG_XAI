import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.models import User
from app.services import password_reset as reset
from app.services.auth import authenticate, make_session_token, password_stamp
from app.services.passwords import check_strength, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)


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
    _set_session(response, settings, user)
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
    _set_session(response, settings, user)
    return user


# --- «Забыли пароль?»: ссылка на почту (режим password) ---

FORGOT_SENT = ("Если такой пользователь есть и у него указана почта, письмо со ссылкой уже "
               "отправлено. Ссылка действует {minutes} мин. Письма нет — проверьте «Спам» или "
               "обратитесь к администратору платформы.")
NO_MAIL = "Восстановление по почте не настроено — обратитесь к администратору платформы"
BAD_LINK = "Ссылка недействительна или устарела — запросите сброс пароля ещё раз"


class ForgotIn(BaseModel):
    login: str


class ResetIn(BaseModel):
    token: str
    new_password: str


class EmailIn(BaseModel):
    password: str
    email: str


def _set_session(response: Response, settings: Settings, user: User) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        make_session_token(settings, user),
        max_age=settings.session_ttl_s,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def _send_letter(settings: Settings, user_id: int, login: str, email: str, token: str) -> None:
    user = User(id=user_id, login=login, email=email)
    try:
        reset.send(settings, reset.letter(settings, user, token))
        log.info("письмо сброса пароля отправлено: %s", login)
    except Exception:  # noqa: BLE001 — человеку ответ тот же, причина — в журнале сервера
        log.exception("письмо сброса пароля не отправлено: %s", login)


@router.post("/forgot")
def forgot(
    body: ForgotIn,
    tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Письмо со ссылкой сброса. Ответ один и тот же, есть ли такой человек, — по нему не узнать,
    кто зарегистрирован. Искать можно по логину или по почте."""
    if settings.auth_backend != "password":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Пароль задаётся не платформой — восстановите его там, где он выдан")
    if not reset.mail_ready(settings):
        raise HTTPException(status.HTTP_409_CONFLICT, NO_MAIL)
    key = body.login.strip().lower()
    users: list[User] = []
    if key:
        found = db.scalar(select(User).where(User.login == key))
        users = [found] if found else list(db.scalars(select(User).where(User.email == key)))
    for u in users:
        if u.is_active and u.email and reset.may_send(u.id):
            # письмо уходит после ответа: время ответа не выдаёт, нашёлся ли человек
            token = reset.make_token(settings, u)
            tasks.add_task(_send_letter, settings, u.id, u.login, u.email, token)
    return {"detail": FORGOT_SENT.format(minutes=settings.reset_ttl_s // 60)}


@router.post("/reset", response_model=UserOut)
def reset_by_link(
    body: ResetIn,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """Новый пароль по ссылке из письма; после него вход выполнен, ссылка больше не действует."""
    if settings.auth_backend != "password":
        raise HTTPException(status.HTTP_409_CONFLICT, "Пароль задаётся не платформой")
    got = reset.read_token(settings, body.token.strip())
    user = db.get(User, got[0]) if got else None
    if got is None or user is None or not user.is_active or got[1] != password_stamp(user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, BAD_LINK)
    problem = check_strength(body.new_password)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    _set_session(response, settings, user)
    return user


@router.post("/email", response_model=UserOut)
def set_own_email(
    body: EmailIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Depends(current_user)],
) -> User:
    """Своя почта для восстановления пароля — с подтверждением текущим паролем: иначе чужая
    открытая сессия могла бы увести учётную запись через «Забыли пароль?»."""
    if settings.auth_backend != "password":
        raise HTTPException(status.HTTP_409_CONFLICT, "Пароль задаётся не платформой, а LDAP")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный текущий пароль")
    try:
        user.email = reset.clean_email(body.email)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    db.commit()
    return user
