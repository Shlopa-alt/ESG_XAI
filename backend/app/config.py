from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Role = Literal["reader", "researcher", "reviewer", "owner"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://esg:esg@localhost:5432/esg"

    # Сессия: подписанный токен в httpOnly cookie
    secret_key: str = "change-me"
    session_cookie_name: str = "esg_session"
    session_ttl_s: int = 8 * 3600
    cookie_secure: bool = False

    # password — личные пароли (пользователей заводит owner), ldap — вход через LDAP
    # университета, local — заглушка для разработки (общий пароль)
    auth_backend: Literal["password", "ldap", "local"] = "ldap"
    local_dev_password: str = "dev"
    local_dev_role: Role = "researcher"

    ldap_server: str = "ldap://ldap.example.local"
    ldap_user_dn_template: str = "uid={login},ou=people,dc=example,dc=local"
    ldap_use_ssl: bool = False
    # Логины, которые становятся owner при первом входе (через запятую)
    initial_owner_logins: list[str] = Field(default_factory=list)

    # База знаний KBRAG: веб-сервер (kbrag.py web) и служебный токен платформы
    # (kbrag.py access add platform --kb esg)
    kbrag_url: str = "http://host.docker.internal:8000"
    kbrag_token: str = ""
    kbrag_timeout_s: float = 30.0

    # Импорт статей через сайт: папка приёма PDF (общая с обработчиком на машине KBRAG),
    # предел размера файла и токен обработчика (deploy/windows/kb_import_worker.py)
    kb_inbox_dir: str = "/data/kb_inbox"
    kb_import_max_mb: int = 60
    kb_import_token: str = ""

    # Запуск экспериментов из формы: очередь Celery в Redis, исполнитель runner/ (контейнер
    # runner-cpu) сообщает ход и итог по токену RUNNER_TOKEN
    redis_url: str = "redis://redis:6379/0"
    runner_token: str = ""
    gpu_runs_per_user: int = 1

    # Датасеты: папка данных сервера (в контейнере и на хосте) — срезы хранятся путями хоста
    esg_data_dir: str = "/data/esg"
    esg_data_host: str = ""
    dataset_upload_max_mb: int = 60


WEAK_LOCAL_PASSWORDS = frozenset({"", "dev", "change-me"})


def check_settings(settings: Settings) -> None:
    """Отказ стартовать с настройками, при которых войти может кто угодно из сети."""
    if settings.auth_backend == "local" and settings.local_dev_password in WEAK_LOCAL_PASSWORDS:
        raise RuntimeError(
            "AUTH_BACKEND=local с паролем по умолчанию: войти сможет любой, кто видит порт. "
            "Задайте свой LOCAL_DEV_PASSWORD в deploy/.env или включите AUTH_BACKEND=ldap."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
