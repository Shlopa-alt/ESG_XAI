from fastapi import APIRouter, FastAPI

from app.api import auth, kb, users

app = FastAPI(title="ESG Open Research", docs_url="/api/docs", openapi_url="/api/openapi.json")

api = APIRouter(prefix="/api")


@api.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


api.include_router(auth.router)
api.include_router(users.router)
api.include_router(kb.router)
app.include_router(api)
