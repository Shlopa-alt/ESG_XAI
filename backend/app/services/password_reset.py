"""Сброс пароля по почте (режим AUTH_BACKEND=password).

Ссылка в письме несёт подписанный токен: id пользователя и отпечаток его пароля. Срок — RESET_TTL_S.
После смены пароля отпечаток другой, поэтому ссылка срабатывает один раз; базы для токенов не нужно.
"""

import re
import smtplib
import threading
import time
from email.message import EmailMessage

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import Settings
from app.models import User
from app.services.auth import password_stamp

# письмо одному человеку — не чаще раза в 5 минут (чтобы «Забыли пароль?» не засыпало ящик)
RESEND_S = 300
_sent: dict[int, float] = {}
_lock = threading.Lock()


EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_email(value: str) -> str:
    """Почта для восстановления: пусто — убрать; иначе адрес вида имя@домен."""
    email = value.strip().lower()
    if email and (len(email) > 256 or not EMAIL.match(email)):
        raise ValueError(f"Не похоже на адрес почты: {value.strip()[:80]}")
    return email


def mail_ready(settings: Settings) -> bool:
    return bool(settings.smtp_host and settings.public_url)


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="esg-password-reset")


def make_token(settings: Settings, user: User) -> str:
    return _serializer(settings).dumps({"uid": user.id, "pv": password_stamp(user)})


def read_token(settings: Settings, token: str) -> tuple[int, str] | None:
    """(id пользователя, отпечаток пароля на момент запроса) или None — подделан или устарел."""
    try:
        data = _serializer(settings).loads(token, max_age=settings.reset_ttl_s)
    except BadSignature:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("uid"), int):
        return None
    pv = data.get("pv", "")
    return data["uid"], pv if isinstance(pv, str) else ""


def may_send(user_id: int, now: float | None = None) -> bool:
    """Отметить отправку; False — письмо этому человеку уже уходило недавно."""
    now = time.monotonic() if now is None else now
    with _lock:
        last = _sent.get(user_id)
        if last is not None and now - last < RESEND_S:
            return False
        _sent[user_id] = now
        return True


def reset_link(settings: Settings, token: str) -> str:
    # токен — после «#»: не попадает в журналы веб-сервера и в Referer
    return f"{settings.public_url.rstrip('/')}/reset-password#{token}"


def letter(settings: Settings, user: User, token: str) -> EmailMessage:
    minutes = settings.reset_ttl_s // 60
    msg = EmailMessage()
    msg["Subject"] = "ESG Open Research: сброс пароля"
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = user.email
    msg.set_content(
        "Здравствуйте!\n\n"
        f"Для входа «{user.login}» на платформе ESG Open Research запрошен сброс пароля.\n"
        f"Задать новый пароль: {reset_link(settings, token)}\n\n"
        f"Ссылка действует {minutes} мин и срабатывает один раз. Если вы не запрашивали сброс, "
        "ничего не делайте — пароль останется прежним.\n"
    )
    return msg


def send(settings: Settings, msg: EmailMessage) -> None:
    """Отправка через SMTP; ошибка — в журнал сервера, человеку ответ тот же."""
    if settings.smtp_security == "ssl":
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
