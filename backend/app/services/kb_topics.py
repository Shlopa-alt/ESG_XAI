"""Общий граф банка статей (п. 1 фидбека): в какой теме о каждом понятии пишут больше всего.

Корневая ветка KBRAG (esg) уже содержит все связи всех тем — это и есть общий граф. Чтобы на нём
было видно, откуда понятие, платформа раз в час проходит графы тем (ветки первого уровня) и
запоминает только «понятие → сколько утверждений о нём в теме». Графы тем большие (до десятков МБ
по туннелю с компьютера лаборатории), поэтому собирается это в фоне: первый запрос получает
ready=False, экран показывает граф без раскраски и спрашивает снова.

Граф фактов по-прежнему редактируется только в KBRAG (правило 8): здесь только чтение и подсчёт.
"""

import json
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode

from app.config import Settings

FRESH_S = 3600.0
Fetch = Callable[[str, str, float], tuple[int, bytes, str]]

_lock = threading.Lock()
_state: dict[str, Any] = {"stamp": 0.0, "topics": [], "counts": {}, "building": False, "error": ""}


def build(settings: Settings, fetch: Fetch, root: str = "esg") -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """Темы первого уровня и в каждой — сколько утверждений о каждом понятии."""
    base = settings.kbrag_url.rstrip("/")
    code, body, _ = fetch(f"{base}/api/kbs?{urlencode({'kb': root})}", settings.kbrag_token, settings.kbrag_timeout_s)
    if code != 200:
        raise RuntimeError(f"KBRAG не отдал темы: {code}")
    nodes = json.loads(body).get("nodes") or []
    topics: list[dict[str, Any]] = []
    counts: dict[str, dict[str, int]] = {}
    for n in nodes:
        if n.get("depth") != 1 or not n.get("in_db") or not n.get("subtree"):
            continue
        path = str(n.get("path") or "")
        code, body, _ = fetch(f"{base}/api/network?{urlencode({'kb': path})}", settings.kbrag_token,
                              max(settings.kbrag_timeout_s, 120.0))
        if code != 200:
            continue
        data = json.loads(body)
        c = {str(x["id"]): int(x.get("facts") or 0) for x in data.get("nodes") or []
             if x.get("kind") == "сущность" and x.get("facts")}
        counts[path] = c
        topics.append({"path": path, "title": str(n.get("title") or path), "articles": int(n.get("subtree") or 0),
                       "concepts": len(c)})
    topics.sort(key=lambda t: -t["articles"])
    return topics, counts


def _run(settings: Settings, fetch: Fetch) -> None:
    try:
        topics, counts = build(settings, fetch)
        with _lock:
            _state.update(stamp=time.monotonic(), topics=topics, counts=counts, error="")
    except (URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        with _lock:
            _state["error"] = str(exc)[:300]
    finally:
        with _lock:
            _state["building"] = False


def ensure(settings: Settings, fetch: Fetch, start: Callable[[Callable[[], None]], None] | None = None) -> None:
    """Устарело или не собрано — собрать в фоне (одна сборка за раз)."""
    with _lock:
        stale = not _state["topics"] or time.monotonic() - _state["stamp"] > FRESH_S
        if not stale or _state["building"]:
            return
        _state["building"] = True
    job = lambda: _run(settings, fetch)  # noqa: E731
    if start is None:
        threading.Thread(target=job, daemon=True).start()
    else:
        start(job)


def lookup(ids: list[str]) -> dict[str, Any]:
    """Главная тема каждого понятия: где о нём больше утверждений (при равенстве — более крупная тема)."""
    with _lock:
        topics, counts = list(_state["topics"]), dict(_state["counts"])
        building, error = bool(_state["building"]), str(_state["error"])
    order = [t["path"] for t in topics]  # уже по убыванию статей
    main = {}
    for cid in ids:
        best, n = "", 0
        for path in order:
            k = counts.get(path, {}).get(cid, 0)
            if k > n:
                best, n = path, k
        if best:
            main[cid] = best
    return {"ready": bool(topics), "building": building, "error": error, "topics": topics, "main": main}


def reset() -> None:
    """Для тестов: забыть собранное."""
    with _lock:
        _state.update(stamp=0.0, topics=[], counts={}, building=False, error="")
