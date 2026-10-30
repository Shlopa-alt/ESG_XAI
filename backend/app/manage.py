"""Служебные команды на сервере (внутри контейнера backend).

    python -m app.manage set-password <login> [--role owner]
    python -m app.manage import-run <EXP-код> <run.json>

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


def import_run(code: str, path: str) -> int:
    """Регистрирует run.json так же, как POST /api/experiments/{code}/runs."""
    import json
    from pathlib import Path

    from app.api.runs import RunImport, _reproducible, register_run

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data.setdefault("results_path", str(Path(path).parent))
    body = RunImport.model_validate(data)
    with SessionLocal() as db:
        run = register_run(db, code, body, None)
        ok, note = _reproducible(run)
        print(f"{code}: запуск #{run.id}, {run.status}; воспроизводим: {'да' if ok else 'нет — ' + note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("set-password", help="временный пароль пользователю")
    sp.add_argument("login")
    sp.add_argument("--role", choices=["reader", "researcher", "reviewer", "owner"])
    ir = sub.add_parser("import-run", help="зарегистрировать run.json у эксперимента")
    ir.add_argument("code")
    ir.add_argument("path")
    args = ap.parse_args(argv)
    if args.cmd == "set-password":
        return set_password(args.login, args.role)
    if args.cmd == "import-run":
        return import_run(args.code, args.path)
    return 1


if __name__ == "__main__":
    sys.exit(main())
