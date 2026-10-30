from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import UserOut
from app.api.deps import require_role
from app.db import get_db
from app.models import User
from app.services.passwords import hash_password, temporary_password

router = APIRouter(prefix="/users", tags=["users"])

OwnerOnly = Depends(require_role("owner"))
Role = Literal["reader", "researcher", "reviewer", "owner"]


class UserPatch(BaseModel):
    role: Role | None = None
    nda_access: bool | None = None
    is_active: bool | None = None
    full_name: str | None = None


class UserCreate(BaseModel):
    login: str = Field(min_length=2, max_length=128, pattern=r"^[A-Za-z0-9._@-]+$")
    full_name: str = ""
    email: str = ""
    role: Role = "reader"
    nda_access: bool = False


class UserWithPassword(UserOut):
    temporary_password: str


def _get(db: Session, login: str) -> User:
    user = db.scalar(select(User).where(User.login == login.lower()))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    return user


def _keep_one_owner(db: Session, user: User) -> None:
    """Без владельца некому раздавать роли — последнего не понизить и не заблокировать."""
    if user.role != "owner":
        return
    owners = db.scalar(
        select(func.count()).select_from(User).where(User.role == "owner", User.is_active)
    )
    if (owners or 0) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя снять роль с последнего владельца")


@router.get("", response_model=list[UserOut], dependencies=[OwnerOnly])
def list_users(db: Annotated[Session, Depends(get_db)]) -> list[User]:
    return list(db.scalars(select(User).order_by(User.login)))


@router.post("", response_model=UserWithPassword, status_code=status.HTTP_201_CREATED,
             dependencies=[OwnerOnly])
def create_user(body: UserCreate, db: Annotated[Session, Depends(get_db)]) -> UserWithPassword:
    """Новый пользователь с временным паролем: показывается один раз, при входе его меняют."""
    login = body.login.lower()
    if db.scalar(select(User).where(User.login == login)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Логин {login} уже занят")
    password = temporary_password()
    user = User(login=login, full_name=body.full_name, email=body.email, role=body.role,
                nda_access=body.nda_access, password_hash=hash_password(password),
                must_change_password=True, is_active=True)
    db.add(user)
    db.commit()
    return UserWithPassword(**UserOut.model_validate(user).model_dump(),
                            temporary_password=password)


@router.post("/{login}/reset-password", response_model=UserWithPassword,
             dependencies=[OwnerOnly])
def reset_password(login: str, db: Annotated[Session, Depends(get_db)]) -> UserWithPassword:
    """Новый временный пароль; все сессии пользователя перестают действовать."""
    user = _get(db, login)
    password = temporary_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    db.commit()
    return UserWithPassword(**UserOut.model_validate(user).model_dump(),
                            temporary_password=password)


@router.patch("/{login}", response_model=UserOut, dependencies=[OwnerOnly])
def patch_user(login: str, body: UserPatch, db: Annotated[Session, Depends(get_db)]) -> User:
    user = _get(db, login)
    if (body.role is not None and body.role != "owner") or body.is_active is False:
        _keep_one_owner(db, user)
    if body.role is not None:
        user.role = body.role
    if body.nda_access is not None:
        user.nda_access = body.nda_access
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.full_name is not None:
        user.full_name = body.full_name
    db.commit()
    return user
