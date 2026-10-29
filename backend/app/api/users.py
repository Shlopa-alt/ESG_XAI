from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import UserOut
from app.api.deps import require_role
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])

OwnerOnly = Depends(require_role("owner"))


class UserPatch(BaseModel):
    role: Literal["reader", "researcher", "reviewer", "owner"] | None = None
    nda_access: bool | None = None


@router.get("", response_model=list[UserOut], dependencies=[OwnerOnly])
def list_users(db: Annotated[Session, Depends(get_db)]) -> list[User]:
    return list(db.scalars(select(User).order_by(User.login)))


@router.patch("/{login}", response_model=UserOut, dependencies=[OwnerOnly])
def patch_user(login: str, body: UserPatch, db: Annotated[Session, Depends(get_db)]) -> User:
    user = db.scalar(select(User).where(User.login == login))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if body.role is not None:
        user.role = body.role
    if body.nda_access is not None:
        user.nda_access = body.nda_access
    db.commit()
    return user
