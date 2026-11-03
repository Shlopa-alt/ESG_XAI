"""Прокси к базе знаний KBRAG: статьи, поиск, граф фактов.

Платформа не хранит статей и графа (docs/SPEC.md, раздел 1): запросы вошедшего
пользователя уходят в веб-сервер KBRAG со служебным токеном платформы.
"""

import gzip
import json
import threading
import time
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
    """Граф для экрана: без цитат у рёбер — страница берёт их по щелчку (/kb/dataset), а
    цитаты — больше половины ответа. Написания узлов остаются: по ним ищет поиск на графе."""
    data = json.loads(body)
    for edge in data.get("edges", []):
        edge.pop("quotes", None)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def unpack(body: bytes, encoding: str | None) -> bytes:
    """Тело ответа KBRAG без сжатия: большие ответы он отдаёт в gzip."""
    return gzip.decompress(body) if (encoding or "").lower() == "gzip" else body


def fetch(url: str, token: str, timeout_s: float) -> tuple[int, bytes, str]:
    """GET к KBRAG: (код, тело, тип содержимого). Ошибку KBRAG возвращает как есть."""
    headers = {"Accept-Encoding": "gzip"}
    if token:
        headers["X-KBRAG-Token"] = token
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout_s) as r:
            body = unpack(r.read(), r.headers.get("Content-Encoding"))
            return r.status, body, r.headers.get("Content-Type", "application/json")
    except HTTPError as exc:
        body = unpack(exc.read(), exc.headers.get("Content-Encoding"))
        return exc.code, body, exc.headers.get("Content-Type", "application/json")


# Граф ветки целиком — десятки МБ с компьютера лаборатории по туннелю (до минуты), а меняется
# он только после прохода модели. Поэтому граф держим в памяти: свежий отдаём сразу,
# устаревший — тоже сразу, обновляя его в фоне; ждёт только самый первый запрос.
NETWORK_FRESH_S = 600.0
NETWORK_CACHE: dict[str, tuple[float, bytes, str]] = {}
_network_lock = threading.Lock()
_network_busy: dict[str, threading.Lock] = {}


def _load_network(url: str, settings: Settings) -> tuple[int, bytes, str]:
    """Забрать граф из KBRAG и положить в кэш; ответ с ошибкой KBRAG не кэшируется."""
    code, body, kind = fetch(url, settings.kbrag_token, settings.kbrag_timeout_s)
    if code == 200:
        body = slim_network(body)
        NETWORK_CACHE[url] = (time.monotonic(), body, kind)
    return code, body, kind


def _refresh_network(url: str, settings: Settings) -> None:
    busy = _network_busy[url]
    try:
        _load_network(url, settings)
    except (URLError, TimeoutError, OSError, ValueError):
        pass  # остаётся прежний граф; следующий запрос попробует снова
    finally:
        busy.release()


def network(url: str, settings: Settings) -> tuple[int, bytes, str]:
    with _network_lock:
        busy = _network_busy.setdefault(url, threading.Lock())
    cached = NETWORK_CACHE.get(url)
    if cached is not None:
        stamp, body, kind = cached
        if time.monotonic() - stamp > NETWORK_FRESH_S and busy.acquire(blocking=False):
            threading.Thread(target=_refresh_network, args=(url, settings), daemon=True).start()
        return 200, body, kind
    with busy:  # первый запрос: остальные ждут его, а не тянут граф параллельно
        cached = NETWORK_CACHE.get(url)
        if cached is not None:
            return 200, cached[1], cached[2]
        return _load_network(url, settings)


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
        if name == "network":
            code, body, kind = network(url, settings)
        else:
            code, body, kind = fetch(url, settings.kbrag_token, settings.kbrag_timeout_s)
    except (URLError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"База знаний недоступна: {exc}"
        ) from exc
    return Response(content=body, status_code=code, media_type=kind)
