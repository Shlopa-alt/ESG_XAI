from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.audit import AuditLog
from app.db import get_db

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    login: str
    method: str
    path: str
    status: int
    client: str


@router.get("", response_model=list[AuditOut], dependencies=[Depends(require_role("owner"))])
def list_audit(
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    login: str | None = None,
) -> list[AuditLog]:
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if login:
        q = q.where(AuditLog.login == login.lower())
    return list(db.scalars(q))
