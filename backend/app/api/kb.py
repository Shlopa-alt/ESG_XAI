"""Прокси к базе знаний KBRAG: статьи, поиск, граф фактов.

Платформа не хранит статей и графа (docs/SPEC.md, раздел 1): запросы вошедшего
пользователя уходят в веб-сервер KBRAG со служебным токеном платформы.
"""

import json
from collections.abc import Iterator
from typing import Annotated, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Request as ApiRequest
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import current_user
from app.config import Settings, get_settings
from app.models import User

router = APIRouter(prefix="/kb", tags=["kb"])

# Только чтение: адреса KBRAG, которые отдаёт платформа (имя в /api/kb/{name} → /api/{name}).
ALLOWED = frozenset(
    {
        "stats",
        "kbs",
        "search",
        "documents",
        "document",
        "article",
        "fragment",
        "network",
        "facts",
        "datasets",
        "dataset",
    }
)


def fetch(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
    """GET к KBRAG: (код, тело, тип содержимого). Ошибку KBRAG возвращает как есть."""
    headers = {"X-KBRAG-Token": token} if token else {}
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout_s) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "application/json")
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "application/json")


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    kb: str = Field(default="esg", pattern=r"^esg(\.[a-z0-9_]+)*$")
    history: list[Turn] = Field(default_factory=list, max_length=20)
    conflicts: bool | None = None  # сверять ли расхождения между статьями (по умолчанию — как в KBRAG)


@router.post("/chat")
def chat(
    body: ChatIn,
    _user: Annotated[User, Depends(current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    """Чат-бот KBRAG потоком: строка JSON на событие (status, sources, token, revised, done,
    error). Отвечает модель по фрагментам статей ветки со ссылками [n]; очередь к модели —
    общая с Телеграм-ботом KBRAG. Ушёл со страницы — поток закрывается, модель перестаёт писать."""
    payload = body.model_dump(exclude_none=True)
    payload["history"] = payload["history"][-10:]
    req = Request(
        f"{settings.kbrag_url.rstrip('/')}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8",
                 **({"X-KBRAG-Token": settings.kbrag_token} if settings.kbrag_token else {})},
        method="POST",
    )
    try:
        upstream = urlopen(req, timeout=180)  # между событиями — не дольше (в очереди — раз в 2 с)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"База знаний: {exc.code} {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"База знаний недоступна: {exc}") from exc

    def lines() -> Iterator[bytes]:
        try:
            for line in upstream:
                yield line
        except (TimeoutError, OSError) as exc:
            yield (json.dumps({"type": "error", "error": f"База знаний не ответила: {exc}"},
                              ensure_ascii=False) + "\n").encode("utf-8")
        finally:
            upstream.close()

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{name}")
def proxy(
    name: str,
    request: ApiRequest,
    _user: Annotated[User, Depends(current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    if name not in ALLOWED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нет такого адреса базы знаний")
    query = urlencode(list(request.query_params.multi_items()))
    url = f"{settings.kbrag_url.rstrip('/')}/api/{name}" + (f"?{query}" if query else "")
    try:
        code, body, kind = fetch(url, settings.kbrag_token, settings.kbrag_timeout_s)
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"База знаний недоступна: {exc}"
        ) from exc
    return Response(content=body, status_code=code, media_type=kind)
