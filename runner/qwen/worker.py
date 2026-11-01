"""Обработчик очереди задач Qwen: модель на видеокарте — только пока есть работа.

    py -3.12 runner/qwen/worker.py              работать постоянно (так его запускает start_all.ps1)
    py -3.12 runner/qwen/worker.py --once       разобрать очередь и выйти
    ... --idle-min 10                           сколько минут простоя до выключения модели

Цикл: раз в 15 с — есть ли задачи в очереди платформы (/api/qwen/worker/peek). Есть — поднять
vLLM (`docker compose --profile llm up -d llm` в KBRAG) и дождаться готовности, затем брать
задачи по одной и выполнять. Очередь пуста дольше --idle-min — остановить модель, если её
поднимал этот обработчик (модель, запущенную вручную, он не трогает). Раз в 30 с — отметка
платформе: состояние модели и память видеокарты (её видно на странице «Задачи Qwen»).

Задачи (kind):
  ping  — проверка: модель отвечает
  graph — достроить граф фактов KBRAG по новым фрагментам (`kbrag.py graph --kb <ветка>`)

Только стандартная библиотека. Настройки — deploy/.env (QWEN_TOKEN, HTTP_PORT), KBRAG_HOME,
KBRAG_DSN.
"""

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"
DOCKER = os.environ.get("DOCKER", r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
LLM_URL = os.environ.get("KBRAG_LLM", "http://127.0.0.1:8100").rstrip("/")
LLM_CONTAINER = "kbrag-llm"
POLL_S = 15
BEAT_S = 30


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


class Platform:
    def __init__(self, url: str, token: str, ca: Path) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.ctx = ssl.create_default_context(cafile=str(ca)) if ca.is_file() else None

    def post(self, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        req = Request(f"{self.url}/api/qwen/worker/{path}", data=json.dumps(body or {}).encode(),
                      headers={"X-Qwen-Token": self.token, "Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=60, context=self.ctx) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except HTTPError as exc:
            raise RuntimeError(f"платформа ответила {exc.code}: {exc.read()[:300]!r}") from exc


class Model:
    """vLLM в контейнере KBRAG: поднять, дождаться, остановить; состояние для отметки."""

    def __init__(self, kbrag: Path) -> None:
        self.kbrag = kbrag
        self.state = "on" if self.up() else "off"
        self.started_by_me = False
        self.detail = ""

    @staticmethod
    def up() -> bool:
        try:
            with urlopen(f"{LLM_URL}/v1/models", timeout=3) as r:
                return r.status == 200
        except (URLError, TimeoutError, OSError):
            return False

    def start(self, wait_s: int = 900) -> bool:
        if self.up():
            self.state = "on"
            return True
        self.state, self.detail = "starting", "поднимаю модель"
        log("поднимаю vLLM")
        r = subprocess.run([DOCKER, "compose", "--profile", "llm", "up", "-d", "llm"], cwd=self.kbrag,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            self.state, self.detail = "off", f"не поднялась: {r.stderr.strip()[-300:]}"
            log(self.detail)
            return False
        self.started_by_me = True
        t0 = time.time()
        while time.time() - t0 < wait_s:
            if self.up():
                self.state, self.detail = "on", ""
                log(f"модель готова за {time.time() - t0:.0f} с")
                return True
            time.sleep(5)
        self.state, self.detail = "off", f"не ответила за {wait_s // 60} мин — журнал: docker logs {LLM_CONTAINER}"
        log(self.detail)
        return False

    def stop(self) -> None:
        if not self.started_by_me:
            return
        self.state = "stopping"
        log("очередь пуста — останавливаю модель, видеокарта свободна")
        subprocess.run([DOCKER, "stop", LLM_CONTAINER], capture_output=True)
        self.state, self.started_by_me = "off", False


def gpu() -> tuple[int | None, int | None]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        used, total = (int(x) for x in out.split(","))
        return used, total
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, None


def chat(prompt: str, max_tokens: int = 200) -> str:
    body = {"model": "qwen3-14b", "max_tokens": max_tokens, "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt + " /no_think"}]}
    req = Request(f"{LLM_URL}/v1/chat/completions", data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=300) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"]
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


# --- задачи ---


def job_ping(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    answer = chat("Ответь одним словом по-русски: готова ли ты к работе?", 20)
    return {"answer": answer, "seconds": round(time.time() - t0, 1)}


def job_graph(job: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Граф фактов по новым фрагментам ветки: готовое не пересчитывается."""
    kb = str(job["payload"].get("kb") or "esg")
    if not re.fullmatch(r"esg(\.[a-z0-9_]+)*", kb):
        raise ValueError(f"ветка не из дерева esg: {kb}")
    kbrag: Path = ctx["kbrag"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.setdefault("KBRAG_DSN", "postgresql://kbrag:kbrag@127.0.0.1:5434/kbrag")
    log_path = ctx["logs"] / f"qwen-graph-{job['id']}.log"
    with log_path.open("w", encoding="utf-8") as out:
        code = subprocess.run([str(kbrag / ".venv" / "Scripts" / "python.exe"), "kbrag.py", "graph", "--kb", kb],
                              cwd=kbrag, env=env, stdout=out, stderr=subprocess.STDOUT).returncode
    text = log_path.read_text(encoding="utf-8", errors="replace")
    result: dict[str, Any] = {"kb": kb, "log": str(log_path)}
    m = re.search(r"Пройдено фрагментов: (\d+) из (\d+)", text)
    if m:
        result["fragments"] = int(m.group(1))
    m = re.search(r"Фактов принято: (\d+); отброшено проверкой: (\d+)", text)
    if m:
        result["facts_accepted"], result["facts_rejected"] = int(m.group(1)), int(m.group(2))
    if code != 0:
        raise RuntimeError(f"kbrag.py graph завершился с кодом {code}; журнал: {log_path}")
    if "fragments" not in result and re.search(r"нов\w* фрагмент\w* нет|нечего", text, re.I):
        result["fragments"] = 0
    return result


HANDLERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]] = {
    "ping": job_ping,
    "graph": job_graph,
}


def describe(kind: str, result: dict[str, Any]) -> str:
    if kind == "graph":
        if "facts_accepted" in result:
            return (f"Пройдено фрагментов: {result.get('fragments', '?')}; фактов принято "
                    f"{result['facts_accepted']}, отброшено проверкой {result['facts_rejected']}")
        return "Новых фрагментов нет — граф уже полный"
    if kind == "ping":
        return f"Модель ответила за {result.get('seconds')} с: {result.get('answer')}"
    return ""


def main() -> int:
    env = read_env(DEPLOY / ".env")
    ap = argparse.ArgumentParser(description="Обработчик очереди задач Qwen")
    ap.add_argument("--platform", default=f"https://127.0.0.1:{env.get('HTTP_PORT', '8080')}")
    ap.add_argument("--ca", type=Path, default=DEPLOY / "certs" / "lab-root-ca.crt")
    ap.add_argument("--kbrag", type=Path, default=Path(os.environ.get("KBRAG_HOME", r"C:\Users\Grisha\KBRAG")))
    ap.add_argument("--idle-min", type=float, default=10)
    ap.add_argument("--once", action="store_true", help="разобрать очередь, выключить модель и выйти")
    args = ap.parse_args()
    token = os.environ.get("QWEN_TOKEN") or env.get("QWEN_TOKEN", "")
    if not token:
        log("нет QWEN_TOKEN в deploy/.env — выхожу")
        return 1
    platform = Platform(args.platform, token, args.ca)
    model = Model(args.kbrag)
    logs = DEPLOY / "windows" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    ctx = {"kbrag": args.kbrag, "logs": logs}
    current: dict[str, Any] = {}

    def beat() -> None:
        used, total = gpu()
        detail = model.detail or (f"задача №{current['id']} ({current['kind']})" if current else "")
        try:
            platform.post("heartbeat", {"model": model.state, "detail": detail,
                                        "gpu_used_mb": used, "gpu_total_mb": total})
        except (RuntimeError, URLError, OSError) as exc:
            log(f"отметка не прошла: {exc}")

    def beat_forever() -> None:
        while True:
            beat()
            time.sleep(BEAT_S)

    threading.Thread(target=beat_forever, daemon=True).start()
    log(f"обработчик Qwen: {args.platform}, KBRAG {args.kbrag}, выключение после {args.idle_min} мин простоя")
    try:
        log(f"вернул в очередь недоделанные: {platform.post('requeue')[1]['requeued']}")
    except (RuntimeError, URLError, OSError) as exc:
        log(f"платформа недоступна: {exc}")
    idle_since = time.time()
    while True:
        try:
            queued = platform.post("peek")[1]["queued"]
        except (RuntimeError, URLError, OSError, TypeError) as exc:
            log(f"платформа недоступна: {exc}")
            queued = 0
        if queued and model.start():
            while True:
                try:
                    code, job = platform.post("next")
                except (RuntimeError, URLError, OSError) as exc:
                    log(f"платформа недоступна: {exc}")
                    break
                if code != 200 or not job:
                    break
                current.update(job)
                log(f"задача №{job['id']}: {job['kind']} {job['payload']}")
                handler = HANDLERS.get(job["kind"])
                try:
                    if handler is None:
                        raise ValueError(f"обработчик не умеет задачи «{job['kind']}»")
                    result = handler(job, ctx)
                    body = {"status": "done", "result": result, "message": describe(job["kind"], result)}
                except Exception as exc:  # noqa: BLE001 — сбой одной задачи не останавливает очередь
                    body = {"status": "failed", "message": f"{type(exc).__name__}: {exc}"[:2000]}
                log(f"задача №{job['id']}: {body['status']} {body.get('message', '')}")
                try:
                    platform.post(f"{job['id']}/result", body)
                except (RuntimeError, URLError, OSError) as exc:
                    log(f"итог не отправлен ({exc}); при перезапуске задача вернётся в очередь")
                current.clear()
            idle_since = time.time()
        elif queued:
            log("модель не поднялась — задачи ждут; повтор через минуту")
            time.sleep(60)
            continue
        if args.once:
            model.stop()
            beat()  # страница сразу видит, что модель выключена
            return 0
        if model.started_by_me and time.time() - idle_since > args.idle_min * 60:
            model.stop()
            beat()
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
