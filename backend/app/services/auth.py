import hashlib
from dataclasses import dataclass

from itsdangerous import BadSignature, URLSafeTimedSerializer
from ldap3 import Connection, Server
from ldap3.core.exceptions import LDAPException
from ldap3.utils.dn import escape_rdn
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User
from app.services.passwords import hash_password, verify_password


@dataclass
class Identity:
    login: str
    full_name: str = ""
    email: str = ""


def _ldap_authenticate(settings: Settings, login: str, password: str) -> Identity | None:
    # Логин подставляется в DN экранированным: «,» «=» «+» и т.п. не меняют запрос к LDAP
    dn = settings.ldap_user_dn_template.format(login=escape_rdn(login))
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
    # Логин без учёта регистра: «Ivanov» и «ivanov» — один пользователь
    login = login.strip().lower()
    if not login or not password:
        return None
    if settings.auth_backend == "password":
        # Личные пароли: пользователя заводит owner, сам при входе он не создаётся
        found = db.scalar(select(User).where(User.login == login))
        if found is None or not found.is_active or not found.password_hash:
            verify_password(password, _DUMMY_HASH)  # время ответа то же, что у настоящего
            return None
        return found if verify_password(password, found.password_hash) else None
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
        elif identity.login in {x.strip().lower() for x in settings.initial_owner_logins}:
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
        if not user.is_active:
            return None
        user.full_name = identity.full_name or user.full_name
        user.email = identity.email or user.email
    db.commit()
    return user


_DUMMY_HASH = hash_password("dummy-password-for-timing")


def password_stamp(user: User) -> str:
    """Отпечаток пароля в сессии: сменили или сбросили пароль — старые сессии не действуют."""
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:12] if user.password_hash else ""


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="esg-session")


def make_session_token(settings: Settings, user: User) -> str:
    return _serializer(settings).dumps({"uid": user.id, "pv": password_stamp(user)})


def read_session_token(settings: Settings, token: str) -> tuple[int, str] | None:
    """(id пользователя, отпечаток пароля на момент входа) или None."""
    try:
        data = _serializer(settings).loads(token, max_age=settings.session_ttl_s)
    except BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    uid, stamp = data.get("uid"), data.get("pv", "")
    return (uid, stamp if isinstance(stamp, str) else "") if isinstance(uid, int) else None
