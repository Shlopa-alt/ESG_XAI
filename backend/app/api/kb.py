"""Прокси к базе знаний KBRAG: статьи, поиск, граф фактов.

Платформа не хранит статей и графа (docs/SPEC.md, раздел 1): запросы вошедшего
пользователя уходят в веб-сервер KBRAG со служебным токеном платформы.
"""

import json
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Request as ApiRequest
from fastapi.responses import Response

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


def slim_network(body: bytes) -> bytes:
    """Граф для экрана: без цитат у рёбер и написаний у узлов. Цитаты страница берёт по
    щелчку (/kb/dataset), а с ними ответ по всей ветке esg весит ~4 МБ вместо ~2."""
    data = json.loads(body)
    for edge in data.get("edges", []):
        edge.pop("quotes", None)
    for node in data.get("nodes", []):
        node.pop("spellings", None)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def fetch(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
    """GET к KBRAG: (код, тело, тип содержимого). Ошибку KBRAG возвращает как есть."""
    headers = {"X-KBRAG-Token": token} if token else {}
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout_s) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "application/json")
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "application/json")


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
    if name == "network" and code == 200:
        body = slim_network(body)
    return Response(content=body, status_code=code, media_type=kind)
