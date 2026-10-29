from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ROLES = ("reader", "researcher", "reviewer", "owner")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(256), default="")
    email: Mapped[str] = mapped_column(String(256), default="")
    role: Mapped[str] = mapped_column(
        Enum(*ROLES, name="user_role", native_enum=False, length=16), default="reader"
    )
    nda_access: Mapped[bool] = mapped_column(Boolean, default=False)
