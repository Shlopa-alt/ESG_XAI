"""Исполнитель запусков платформы: задача `runner.execute` из очереди Celery (брокер Redis).

    celery -A worker.tasks worker -Q cpu -c 2

Задачу ставит платформа (POST /api/runs, шаблоны — backend/app/services/run_templates.py).
Исполнитель:
1. сверяет sha256 файла среза с записанным в платформе — изменившиеся данные не считаются
   (правило 3);
2. запускает скрипт runner/<каталог>/<скрипт> <каталог датасета> <каталог результатов>
   --data <файл среза> <параметры> интерпретатором с зафиксированным окружением (requirements.lock);
3. строки вывода и события `@event {...}` (ход, метрики) публикует в Redis: канал run:{id}
   и журнал run:{id}:log — их отдаёт платформа потоком /api/runs/{id}/stream;
   метрики и итог пишет в MLflow;
4. раз в секунду проверяет флаг остановки run:{id}:stop и лимит времени шаблона;
5. итог и run.json, который записал скрипт, отправляет платформе (X-Runner-Token).

Пути: срезы в платформе записаны путями хоста (ESG_DATA_HOST), в контейнере та же папка
смонтирована в ESG_DATA_DIR; в run.json возвращаются пути хоста.
"""

import hashlib
import json
import os
import queue
import re
import signal
import subprocess
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import redis
from celery import Celery
from celery.signals import worker_ready

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
PLATFORM_URL = os.environ.get("PLATFORM_URL", "http://backend:8000").rstrip("/")
RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN", "")
MLFLOW_URI = os.environ.get("MLFLOW_TRACKING_URI", "")
RUN_PYTHON = os.environ.get("RUN_PYTHON", "/opt/run/bin/python")
REPO = Path(os.environ.get("REPO_DIR", "/repo"))
DATA_DIR = os.environ.get("ESG_DATA_DIR", "/data/esg").rstrip("/")
DATA_HOST = os.environ.get("ESG_DATA_HOST", "").replace("\\", "/").rstrip("/")
QUEUE = os.environ.get("RUNNER_QUEUE", "cpu")
LOG_KEEP = 5000  # строк лога в Redis на запуск
KEEP_S = 7 * 86400

app = Celery("runner", broker=REDIS_URL)
app.conf.update(task_default_queue=QUEUE, worker_prefetch_multiplier=1, task_acks_late=False,
                broker_connection_retry_on_startup=True, worker_hijack_root_logger=False)


class Failure(Exception):
    """Запуск не состоялся по понятной причине — она уходит в платформу как сообщение."""


def to_container(host_path: str) -> Path:
    p = host_path.replace("\\", "/")
    if DATA_HOST and p.lower().startswith(DATA_HOST.lower() + "/"):
        return Path(DATA_DIR) / p[len(DATA_HOST) + 1:]
    if p.startswith(DATA_DIR + "/"):
        return Path(p)
    raise Failure(f"Срез лежит вне папки данных ({DATA_HOST or DATA_DIR}): {host_path}")


def to_host(path: str) -> str:
    if DATA_HOST and path.startswith(DATA_DIR + "/"):
        rest = path[len(DATA_DIR) + 1:]
        sep = "\\" if re.match(r"^[A-Za-z]:", DATA_HOST) else "/"
        return DATA_HOST.replace("/", sep) + sep + rest.replace("/", sep)
    return path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


class Events:
    """События запуска: журнал в Redis и канал для живого потока."""

    def __init__(self, run_id: int) -> None:
        self.r = redis.Redis.from_url(REDIS_URL)
        self.key = f"run:{run_id}"
        self.tail: deque[str] = deque(maxlen=15)  # последние строки лога — в сообщение о сбое

    def emit(self, kind: str, **data: Any) -> None:
        if kind == "log":
            self.tail.append(str(data.get("line", "")))
        seq = self.r.incr(f"{self.key}:seq")
        ev = json.dumps({"seq": seq, "type": kind, "t": round(time.time(), 3), **data},
                        ensure_ascii=False)
        pipe = self.r.pipeline()
        pipe.rpush(f"{self.key}:log", ev)
        pipe.ltrim(f"{self.key}:log", -LOG_KEEP, -1)
        pipe.expire(f"{self.key}:log", KEEP_S)
        pipe.expire(f"{self.key}:seq", KEEP_S)
        pipe.publish(self.key, ev)
        pipe.execute()

    def stop_requested(self) -> bool:
        return bool(self.r.exists(f"{self.key}:stop"))


def report(run_id: int, body: dict[str, Any], path: str | None = None) -> int:
    """Платформе: ход и итог запуска. Код ответа (409 — запуск уже снят)."""
    url = f"{PLATFORM_URL}/api/runs/worker/{path or run_id}"
    req = Request(url, data=json.dumps(body, ensure_ascii=False, default=str).encode(),
                  headers={"X-Runner-Token": RUNNER_TOKEN, "Content-Type": "application/json"},
                  method="POST")
    try:
        with urlopen(req, timeout=60) as r:
            return int(r.status)
    except HTTPError as exc:
        print(f"платформа ответила {exc.code} на {url}: {exc.read()[:500]!r}", flush=True)
        return exc.code
    except URLError as exc:
        print(f"платформа недоступна ({url}): {exc}", flush=True)
        return 0


class Tracker:
    """MLflow: параметры, метрики по ходу и итог; сбой MLflow запуск не останавливает."""

    def __init__(self, ev: Events) -> None:
        self.ev = ev
        self.ml: Any = None
        self.run_id = ""

    def start(self, job: dict[str, Any]) -> None:
        if not MLFLOW_URI:
            return
        try:
            import mlflow

            mlflow.set_tracking_uri(MLFLOW_URI)
            mlflow.set_experiment(job["experiment"])
            run = mlflow.start_run(run_name=f"run-{job['run_id']}",
                                   tags={"platform_run": str(job["run_id"]), "template": job["template"]})
            mlflow.log_params({**job["params"], "dataset": job["dataset"],
                               "snapshot_sha256": job["snapshot_sha256"]})
            self.ml, self.run_id = mlflow, run.info.run_id
        except Exception as exc:  # noqa: BLE001
            self.ev.emit("log", line=f"[исполнитель] MLflow недоступен: {exc}")

    def metric(self, name: str, value: float, step: int | None) -> None:
        if self.ml is not None:
            try:
                self.ml.log_metric(re.sub(r"[^\w\-. /]", "_", name)[:250], value, step=step)
            except Exception:  # noqa: BLE001
                pass

    def finish(self, status: str, results: Path | None, summary: dict[str, Any]) -> None:
        if self.ml is None:
            return
        try:
            for key, value in flatten(summary).items():
                self.metric(key, value, None)
            if results is not None and results.is_dir():
                for f in sorted(results.rglob("*")):
                    if f.is_file() and f.stat().st_size < 50 * 2**20:
                        sub = f.parent.relative_to(results).as_posix()
                        self.ml.log_artifact(str(f), None if sub == "." else sub)
            self.ml.end_run({"done": "FINISHED", "stopped": "KILLED"}.get(status, "FAILED"))
        except Exception as exc:  # noqa: BLE001
            self.ev.emit("log", line=f"[исполнитель] MLflow: {exc}")


def flatten(data: Any, prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        out[prefix] = float(data)
    return out


def run_script(argv: list[str], cwd: Path, ev: Events, tracker: Tracker, limit_s: int,
               log_file: Path) -> tuple[int, str]:
    """Скрипт до конца, остановки или лимита: (код выхода, причина остановки или "")."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1,
                            start_new_session=True)  # своя группа процессов: остановка — всем частям
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line.rstrip("\n"))
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    t0, reason, done = time.time(), "", False
    with log_file.open("a", encoding="utf-8") as log:
        while not done:
            try:
                line = lines.get(timeout=1)
            except queue.Empty:
                line = ""
            if line is None:
                done = True
            elif line:
                log.write(line + "\n")
                handle_line(line, ev, tracker)
            if not reason and proc.poll() is None:
                if ev.stop_requested():
                    reason = "stopped"
                elif time.time() - t0 > limit_s:
                    reason = "limit"
                if reason:
                    ev.emit("log", line="[исполнитель] останавливаю расчёт…")
                    stop_group(proc)
    return proc.wait(), reason


def handle_line(line: str, ev: Events, tracker: Tracker) -> None:
    if line.startswith("@event "):
        try:
            data = json.loads(line[7:])
            kind = str(data.pop("type"))
        except (ValueError, KeyError):
            ev.emit("log", line=line)
            return
        if kind == "metric" and isinstance(data.get("value"), (int, float)):
            tracker.metric(str(data.get("name", "metric")), float(data["value"]), data.get("step"))
        ev.emit(kind, **data)
    else:
        ev.emit("log", line=line)


def stop_group(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def newest_run_json(root: Path) -> Path | None:
    found = sorted(root.glob("*/run.json"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


@app.task(name="runner.execute")
def execute(job: dict[str, Any]) -> str:
    run_id = int(job["run_id"])
    ev = Events(run_id)
    if ev.stop_requested():  # сняли, пока ждал в очереди
        report(run_id, {"status": "stopped", "message": "Снят с очереди до начала расчёта"})
        ev.emit("status", status="stopped")
        return "stopped"
    if report(run_id, {"status": "running", "started_at": datetime.now(UTC).isoformat()}) == 409:
        return "skipped"
    ev.emit("status", status="running")
    tracker = Tracker(ev)
    results: Path | None = None
    try:
        snap = to_container(job["snapshot_path"])
        if not snap.is_file():
            raise Failure(f"Нет файла среза: {job['snapshot_path']}")
        ev.emit("log", line=f"[исполнитель] сверяю срез {job['dataset']}: {snap.name}")
        actual = sha256(snap)
        if actual != job["snapshot_sha256"]:
            raise Failure(f"Срез данных изменился: sha256 файла {actual[:12]}… ≠ записанного "
                          f"{job['snapshot_sha256'][:12]}… — нужен новый срез")
        ds_dir = snap.parents[int(job["dataset_dir_up"]) - 1]
        results = Path(DATA_DIR) / job["experiment"] / f"run-{run_id:05d}"
        results.mkdir(parents=True, exist_ok=True)
        workdir = REPO / "runner" / job["workdir"]
        # скрипт считает именно сверенный файл среза, а не то, что лежит в каталоге датасета
        argv = [RUN_PYTHON, "-u", "-B", job["script"], str(ds_dir), str(results), "--data", str(snap),
                *job["args"]]
        ev.emit("log", line="$ " + " ".join(argv[3:]))
        tracker.start(job)
        code, reason = run_script(argv, workdir, ev, tracker, int(job["limit_min"]) * 60,
                                  results / "worker.log")
        run_json = newest_run_json(results)
        host_results = to_host(str(results))
        if reason == "stopped":
            raise Failure(f"Остановлен по запросу; что успело посчитаться — {host_results}", "stopped")
        if reason == "limit":
            raise Failure(f"Превышен лимит {job['limit_min']} мин — расчёт остановлен; "
                          f"частичные результаты — {host_results}")
        if run_json is None:
            raise Failure(f"Скрипт завершился с кодом {code} и не записал run.json:\n" + "\n".join(ev.tail))
        data = json.loads(run_json.read_text(encoding="utf-8"))
        data["results_path"] = to_host(str(run_json.parent))
        if isinstance(data.get("dataset"), dict) and data["dataset"].get("path"):
            data["dataset"]["path"] = to_host(str(data["dataset"]["path"]))
        tracker.finish("done" if code == 0 else "failed", run_json.parent, data.get("summary") or {})
        report(run_id, {"status": "done", "run": data, "mlflow_run_id": tracker.run_id,
                        "message": "" if code == 0 else f"Скрипт завершился с кодом {code}"})
        ev.emit("status", status="done" if code == 0 else "failed")
        return "done"
    except Failure as exc:
        status = exc.args[1] if len(exc.args) > 1 else "failed"
        message = str(exc.args[0])
    except Exception as exc:  # noqa: BLE001 — сбой исполнителя: запуск отмечается упавшим
        status, message = "failed", f"Сбой исполнителя: {type(exc).__name__}: {exc}"
    tracker.finish(status, results, {})
    report(run_id, {"status": status, "message": message, "mlflow_run_id": tracker.run_id})
    ev.emit("log", line=f"[исполнитель] {message}")
    ev.emit("status", status=status, message=message)
    return status


@worker_ready.connect
def _orphans(**_: Any) -> None:
    """Исполнитель только что запустился: его «идущие» запуски прервались вместе с ним."""
    report(0, {}, path=f"orphans?queue={QUEUE}")
