"""Очередь запусков и их живой поток.

Платформа ставит задачу `runner.execute` в Celery (брокер — Redis, очередь cpu или gpu); её
выполняет контейнер-исполнитель из runner/worker. Исполнитель публикует события запуска
(строки лога, ход, метрики, статус) в канал Redis `run:{id}` и копит их в списке `run:{id}:log`:
поток /api/runs/{id}/stream отдаёт сначала накопленное, затем новое — у каждого события номер
seq, повторы отбрасываются. Остановка — флаг `run:{id}:stop`, исполнитель проверяет его раз в
секунду и останавливает расчёт сам: так частичные результаты остаются на диске.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

import redis
import redis.asyncio as aredis
from celery import Celery

TASK = "runner.execute"
FINAL = frozenset({"done", "failed", "stopped"})


@lru_cache
def _celery(broker: str) -> Celery:
    app = Celery("platform", broker=broker)
    # Redis недоступен — ошибка сразу, а не ожидание минутами
    app.conf.broker_connection_timeout = 3
    app.conf.task_publish_retry_policy = {"max_retries": 1, "interval_start": 0, "interval_step": 1}
    return app


def enqueue(broker: str, run_id: int, job: dict[str, Any], queue: str) -> str:
    task_id = f"run-{run_id}"
    _celery(broker).send_task(TASK, kwargs={"job": job}, queue=queue, task_id=task_id)
    return task_id


def revoke(broker: str, task_id: str) -> None:
    """Задача ещё в очереди — исполнитель её не возьмёт."""
    _celery(broker).control.revoke(task_id)


def request_stop(url: str, run_id: int) -> None:
    redis.Redis.from_url(url).set(f"run:{run_id}:stop", 1, ex=7 * 86400)


def sse(event: dict[str, Any]) -> str:
    head = f"id: {event['seq']}\n" if "seq" in event else ""
    return f"{head}data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def events(url: str, run_id: int, status: str, alive: Any) -> AsyncIterator[str]:
    """SSE-поток запуска: накопленное, затем новое, пока запуск не закончится или зритель не уйдёт.
    status — состояние в базе: у давно законченного запуска лог в Redis мог истечь."""
    client = aredis.Redis.from_url(url)
    pubsub = client.pubsub()
    await pubsub.subscribe(f"run:{run_id}")  # сначала подписка, потом журнал: ничего не теряется
    try:
        last = 0
        finished = False
        for raw in await client.lrange(f"run:{run_id}:log", 0, -1):
            ev = json.loads(raw)
            last = max(last, ev.get("seq", 0))
            finished = finished or (ev.get("type") == "status" and ev.get("status") in FINAL)
            yield sse(ev)
        if status in FINAL and not finished:
            yield sse({"type": "status", "status": status})
            return
        while not finished and await alive():
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
            if msg is None:
                yield ": ping\n\n"  # nginx и браузер не закрывают молчащее соединение
                continue
            ev = json.loads(msg["data"])
            if ev.get("seq", 0) <= last:
                continue
            last = ev["seq"]
            finished = ev.get("type") == "status" and ev.get("status") in FINAL
            yield sse(ev)
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await client.aclose()


async def still_open(request: Any) -> bool:
    await asyncio.sleep(0)
    return not await request.is_disconnected()
