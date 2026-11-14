"""Текст статьи из KBRAG — по фрагментам (/api/article), без копирования в платформу (правило 8).

Нужен, чтобы найти в статье, какой сетью пользовались авторы (app/services/net_catalog.py). Текст
держится в памяти процесса недолго (CACHE_S) — рекомендация пересчитывается при каждой смене
показателя, а статья за это время не меняется; в базу платформы он не пишется, в проверку идёт
только короткая цитата-основание.
"""

import json
import threading
import time
from urllib.error import URLError
from urllib.parse import urlencode

from app.api.kb import fetch
from app.config import Settings

PAGE = 100
MAX_FRAGMENTS = 600
CACHE_S = 600.0
CACHE_MAX = 64  # статей в памяти
_cache: dict[tuple[str, str], tuple[float, str]] = {}
_lock = threading.Lock()


def article_text(settings: Settings, doc_id: str) -> str:
    """Название и фрагменты статьи одной строкой. Статьи нет или KBRAG недоступен — LookupError."""
    key = (settings.kbrag_url, doc_id)
    with _lock:
        hit = _cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < CACHE_S:
            return hit[1]
    text = _load(settings, doc_id)
    with _lock:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[key] = (time.monotonic(), text)
    return text


def _load(settings: Settings, doc_id: str) -> str:
    base = f"{settings.kbrag_url.rstrip('/')}/api/article"
    parts: list[str] = []
    title = ""
    offset = 0
    while offset < MAX_FRAGMENTS:
        query = urlencode({"doc_id": doc_id, "text": "1", "offset": offset, "limit": PAGE})
        try:
            code, body, _ = fetch(f"{base}?{query}", settings.kbrag_token, settings.kbrag_timeout_s)
        except (URLError, OSError) as exc:
            raise LookupError(f"Банк статей недоступен: {exc}") from exc
        if code != 200:
            raise LookupError(f"Банк статей не отдал статью {doc_id} (код {code})")
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise LookupError(f"Банк статей ответил не JSON по статье {doc_id}") from exc
        if not isinstance(data, dict):
            raise LookupError(f"Банк статей ответил непонятно по статье {doc_id}")
        title = title or str(data.get("title") or "")
        fragments = data.get("fragments") or []
        parts += [str(f.get("text") or "") for f in fragments if isinstance(f, dict)]
        nxt = data.get("next_offset")
        if not fragments or not isinstance(nxt, int) or nxt <= offset:
            break
        offset = nxt
    return "\n".join([title, *parts])
