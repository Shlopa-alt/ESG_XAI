"""Личные пароли платформы (режим AUTH_BACKEND=password): хеш scrypt из стандартной библиотеки."""

import hashlib
import hmac
import secrets

# Параметры scrypt: ~16 МБ памяти и десятки миллисекунд на проверку
_N, _R, _P = 2**14, 8, 1
MIN_LENGTH = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if kind != "scrypt":
        return False
    got = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
        dklen=len(digest) // 2,
    )
    return hmac.compare_digest(got.hex(), digest)


def temporary_password() -> str:
    """Временный пароль: показывается owner один раз, при первом входе его меняют."""
    return secrets.token_urlsafe(9)


def check_strength(password: str) -> str | None:
    """Текст ошибки, если пароль слабый; None — годится."""
    if len(password) < MIN_LENGTH:
        return f"Пароль должен быть не короче {MIN_LENGTH} символов"
    if password.isdigit() or password.isalpha():
        return "Пароль должен содержать и буквы, и цифры или знаки"
    return None
