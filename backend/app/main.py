from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api import (
    analysis,
    articles,
    audit,
    auth,
    data_drafts,
    datasets,
    experiments,
    hypotheses,
    kb,
    kb_imports,
    methodology,
    methods,
    proposals,
    qwen,
    reports,
    runs,
    tokens,
    users,
)
from app.audit import AuditMiddleware
from app.config import check_settings, get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    check_settings(get_settings())
    yield


API_DESCRIPTION = """Открытый API платформы ESG Open Research.

**Доступ.** Личный токен — на сайте, «Доступ к API». Передаётся заголовком
`Authorization: Bearer esg_…`; кнопка «Authorize» выше — вставить токен и пробовать запросы здесь.
Токен действует с правами вашей роли; «только чтение» — лишь GET. Данные под NDA — только
с допуском, лимиты и квоты расчётов — те же, что на сайте.

**Адреса.** Постоянные — с версией: `/api/v1/…` (то же, что `/api/…` без версии).
Учётной записью (пароль, почта, токены, пользователи) через API управлять нельзя.
"""

app = FastAPI(
    title="ESG Open Research API",
    version="1",
    description=API_DESCRIPTION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(AuditMiddleware)


class ApiVersion:
    """/api/v1/… — постоянные адреса открытого API: ведут туда же, что /api/…"""

    def __init__(self, inner: ASGIApp) -> None:
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/api/v1/"):
            path = "/api/" + scope["path"][len("/api/v1/"):]
            scope = {**scope, "path": path, "raw_path": path.encode()}
        await self.inner(scope, receive, send)


app.add_middleware(ApiVersion)  # снаружи журнала: в журнал пишется адрес без версии

api = APIRouter(prefix="/api")


@api.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


api.include_router(auth.router)
api.include_router(users.router)
api.include_router(kb.router)
api.include_router(kb_imports.router)
api.include_router(experiments.router)
api.include_router(datasets.router)
api.include_router(methodology.router)
api.include_router(hypotheses.router)
api.include_router(audit.router)
api.include_router(runs.router)
api.include_router(qwen.router)
api.include_router(proposals.router)
api.include_router(reports.router)
api.include_router(data_drafts.router)
api.include_router(analysis.router)
api.include_router(articles.router)
api.include_router(methods.router)
api.include_router(methods.worker_router)
api.include_router(tokens.router)
app.include_router(api)


def openapi() -> dict[str, object]:
    """Схема API с входом по токену: в /api/docs работает кнопка «Authorize»."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description,
                         routes=app.routes)
    schema.setdefault("components", {})["securitySchemes"] = {
        "token": {"type": "http", "scheme": "bearer", "description": "Личный токен esg_…"}}
    schema["security"] = [{"token": []}]
    schema["servers"] = [{"url": "/"}]
    app.openapi_schema = schema
    return schema


app.openapi = openapi  # type: ignore[method-assign]
