from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api import (
    audit,
    auth,
    datasets,
    experiments,
    hypotheses,
    kb,
    kb_imports,
    methodology,
    proposals,
    qwen,
    runs,
    users,
)
from app.audit import AuditMiddleware
from app.config import check_settings, get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    check_settings(get_settings())
    yield


app = FastAPI(
    title="ESG Open Research",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(AuditMiddleware)

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
app.include_router(api)
