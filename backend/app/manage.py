"""Служебные команды на сервере (внутри контейнера backend).

    python -m app.manage set-password <login> [--role owner]

Задаёт пользователю временный пароль (создаёт пользователя, если его нет) и печатает его.
Нужно, чтобы завести первого владельца при переходе на AUTH_BACKEND=password.
"""

import argparse
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from app.services.passwords import hash_password, temporary_password


def set_password(login: str, role: str | None) -> int:
    login = login.strip().lower()
    password = temporary_password()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.login == login))
        if user is None:
            user = User(login=login, full_name=login, email="", role=role or "reader")
            db.add(user)
        elif role:
            user.role = role
        user.password_hash = hash_password(password)
        user.must_change_password = True
        user.is_active = True
        db.commit()
        print(f"{login} ({user.role}): временный пароль {password} — сменить при первом входе")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("set-password", help="временный пароль пользователю")
    sp.add_argument("login")
    sp.add_argument("--role", choices=["reader", "researcher", "reviewer", "owner"])
    args = ap.parse_args(argv)
    if args.cmd == "set-password":
        return set_password(args.login, args.role)
    return 1


if __name__ == "__main__":
    sys.exit(main())
