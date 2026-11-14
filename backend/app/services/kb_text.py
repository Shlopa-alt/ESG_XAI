"""Текст статьи из KBRAG — по фрагментам (/api/article), без копирования в платформу (правило 8).

Нужен, чтобы найти в статье, какой сетью пользовались авторы (app/services/net_catalog.py). Текст
читается на время запроса и не сохраняется; в проверку пишется только короткая цитата-основание.
"""

import json
from urllib.error import URLError
from urllib.parse import urlencode

from app.api.kb import fetch
from app.config import Settings

PAGE = 100
MAX_FRAGMENTS = 600


def article_text(settings: Settings, doc_id: str) -> str:
    """Название и фрагменты статьи одной строкой. Статьи нет или KBRAG недоступен — LookupError."""
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
        data = json.loads(body)
        title = title or str(data.get("title") or "")
        fragments = data.get("fragments") or []
        parts += [str(f.get("text") or "") for f in fragments]
        nxt = data.get("next_offset")
        if not fragments or not isinstance(nxt, int) or nxt <= offset:
            break
        offset = nxt
    return "\n".join([title, *parts])
