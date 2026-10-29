from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.main import app
from app.models import User


@pytest.fixture
def settings() -> Settings:
    return Settings(auth_backend="local", secret_key="test", local_dev_password="dev")


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def client(db_session: Session, settings: Settings) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_client(db_session: Session, settings: Settings):  # type: ignore[no-untyped-def]
    """Возвращает клиента, вошедшего под пользователем с заданной ролью."""

    def factory(login: str, role: str) -> TestClient:
        db_session.add(User(login=login, role=role))
        db_session.commit()
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"login": login, "password": "dev"})
        assert r.status_code == 200
        return c

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_settings] = lambda: settings
    yield factory
    app.dependency_overrides.clear()
