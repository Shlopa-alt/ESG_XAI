"""Шифрование паролей подключений к базам данных (Студия): Fernet (AES + HMAC).

Ключ выводится из SECRET_KEY сервера (HKDF), в базе платформы — только шифротекст. Сменили
SECRET_KEY — сохранённые пароли не расшифровать, их вводят заново (сказано в docs/STUDIO.md).
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Settings


class SecretError(ValueError):
    pass


def _fernet(settings: Settings) -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"esg-open-research",
               info=b"studio-db-connections").derive(settings.secret_key.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(settings: Settings, value: str) -> str:
    return _fernet(settings).encrypt(value.encode("utf-8")).decode("ascii") if value else ""


def decrypt(settings: Settings, token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet(settings).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretError("Пароль подключения не расшифровать (сменился SECRET_KEY?) — "
                          "введите его заново") from exc
