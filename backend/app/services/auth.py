from dataclasses import dataclass

from itsdangerous import BadSignature, URLSafeTimedSerializer
from ldap3 import Connection, Server
from ldap3.core.exceptions import LDAPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User


@dataclass
class Identity:
    login: str
    full_name: str = ""
    email: str = ""


def _ldap_authenticate(settings: Settings, login: str, password: str) -> Identity | None:
    dn = settings.ldap_user_dn_template.format(login=login)
    server = Server(settings.ldap_server, use_ssl=settings.ldap_use_ssl)
    try:
        with Connection(server, user=dn, password=password) as conn:
            if not conn.bind():
                return None
            conn.search(dn, "(objectClass=*)", attributes=["cn", "mail"])
            entry = conn.entries[0] if conn.entries else None
            return Identity(
                login=login,
                full_name=str(entry.cn) if entry is not None and "cn" in entry else "",
                email=str(entry.mail) if entry is not None and "mail" in entry else "",
            )
    except LDAPException:
        return None


def _local_authenticate(settings: Settings, login: str, password: str) -> Identity | None:
    if password != settings.local_dev_password:
        return None
    return Identity(login=login, full_name=login)


def authenticate(db: Session, settings: Settings, login: str, password: str) -> User | None:
    """Проверяет пароль и возвращает пользователя из БД, создавая его при первом входе."""
    if not login or not password:
        return None
    if settings.auth_backend == "local":
        identity = _local_authenticate(settings, login, password)
    else:
        identity = _ldap_authenticate(settings, login, password)
    if identity is None:
        return None

    user = db.scalar(select(User).where(User.login == identity.login))
    if user is None:
        if settings.auth_backend == "local":
            role = settings.local_dev_role
        elif identity.login in settings.initial_owner_logins:
            role = "owner"
        else:
            role = "reader"
        user = User(
            login=identity.login,
            full_name=identity.full_name,
            email=identity.email,
            role=role,
        )
        db.add(user)
    else:
        user.full_name = identity.full_name or user.full_name
        user.email = identity.email or user.email
    db.commit()
    return user


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="esg-session")


def make_session_token(settings: Settings, user: User) -> str:
    return _serializer(settings).dumps({"uid": user.id})


def read_session_token(settings: Settings, token: str) -> int | None:
    try:
        data = _serializer(settings).loads(token, max_age=settings.session_ttl_s)
    except BadSignature:
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None
