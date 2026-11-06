"""Учётные записи стенда по одной на роль. Только для deploy/review: в миграции и сиды не попадают."""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User

with SessionLocal() as db:
    for role in ("reader", "researcher", "reviewer", "owner"):
        login = f"review-{role}"
        if db.scalar(select(User).where(User.login == login)) is None:
            db.add(User(login=login, full_name=login, email="", role=role))
    db.commit()
