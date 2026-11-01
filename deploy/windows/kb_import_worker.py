"""Обработчик очереди импорта статей: то, что загрузили через сайт, — в базу знаний KBRAG.

Запускается Python из окружения KBRAG (нужен пакет kbrag и docling):

    C:\\Users\\Grisha\\KBRAG\\.venv\\Scripts\\python.exe deploy\\windows\\kb_import_worker.py
    ... --once              разобрать очередь и выйти
    ... --device cuda       разбор и векторы на видеокарте (только когда модель графа не запущена)

Берёт статью из очереди платформы (POST /api/kb-imports/worker/next), разбирает её как
`kbrag.py import <pdf> --kb <ветка>` — PDF и метаданные (.yaml рядом) лежат в папке приёма
KB_INBOX_DIR — загружает в базу, кладёт в ветку и сообщает итог платформе. Факты графа для
новой статьи выпишет следующий проход `kbrag.py graph`.

Настройки — из deploy/.env (KB_IMPORT_TOKEN, KB_INBOX_DIR, HTTP_PORT) и переменных
KBRAG_HOME, KBRAG_DSN. По умолчанию всё на процессоре: видеокарта остаётся модели графа.
"""

import argparse
import json
import os
import ssl
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEPLOY = Path(__file__).resolve().parents[1]
POLL_S = 30


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


class Platform:
    """Служебные адреса платформы для обработчика (токен в X-Import-Token)."""

    def __init__(self, url: str, token: str, ca: Path) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.ctx = ssl.create_default_context(cafile=str(ca)) if ca.is_file() else None

    def post(self, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        req = Request(
            f"{self.url}/api/kb-imports/worker/{path}",
            data=json.dumps(body or {}).encode(),
            headers={"X-Import-Token": self.token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=60, context=self.ctx) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except HTTPError as exc:
            raise RuntimeError(f"платформа ответила {exc.code}: {exc.read()[:300]!r}") from exc


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def process(job: dict[str, Any], inbox: Path, device: str, dsn: str | None) -> dict[str, str]:
    """Одна статья: разбор → база → ветка. Итог — для платформы."""
    from kbrag.common import kb_from_args
    from kbrag.library import cli, importer
    from kbrag.paths import ARTICLES

    pdf = inbox / job["path"]
    if not pdf.is_file():
        return {"status": "failed", "message": f"Нет файла в папке приёма: {pdf}"}
    base = kb_from_args(job["kb_path"])
    if base is None:
        return {"status": "failed", "message": f"В KBRAG нет ветки {job['kb_path']}"}
    args = SimpleNamespace(device=device, no_images=False, ocr=False, dsn=dsn, articles=ARTICLES,
                           no_summaries=True)
    items = importer.import_pdfs([pdf], cli._settings(args), ARTICLES, kb=base, log=log)
    if not items:
        return {"status": "failed", "message": "Импорт не нашёл PDF"}
    item = items[0]
    if item.status == importer.SCANNED:
        return {"status": "failed", "doc_id": item.doc_id,
                "message": "Скан без текстового слоя: нужен разбор с OCR (kbrag.py import --ocr)"}
    if not item.indexed:
        return {"status": "failed", "doc_id": item.doc_id,
                "message": f"{item.status}: {item.note}".strip(": ")}
    if cli._load(args, items, base.path, force=False) != 0:
        return {"status": "failed", "doc_id": item.doc_id,
                "message": "Разобрана, но загрузка в базу знаний с ошибками — см. журнал обработчика"}
    if item.status == importer.SAME:
        return {"status": "duplicate", "doc_id": item.doc_id,
                "message": (item.note or "Статья уже была в базе знаний") + f"; ветка {base.path}"}
    return {"status": "done", "doc_id": item.doc_id,
            "message": f"Разобрана (рисунков {item.figures}), загружена в ветку {base.path}. "
                       "Факты графа — при следующем проходе kbrag.py graph"}


def main() -> int:
    env = read_env(DEPLOY / ".env")
    p = argparse.ArgumentParser(description="Очередь импорта статей с сайта → KBRAG")
    p.add_argument("--platform", default=f"https://127.0.0.1:{env.get('HTTP_PORT', '8080')}")
    p.add_argument("--inbox", type=Path, default=Path(env.get("KB_INBOX_DIR", DEPLOY.parent / ".local" / "kb_inbox")))
    p.add_argument("--ca", type=Path, default=DEPLOY / "certs" / "lab-root-ca.crt")
    p.add_argument("--kbrag", type=Path, default=Path(os.environ.get("KBRAG_HOME", r"C:\Users\Grisha\KBRAG")))
    p.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    p.add_argument("--once", action="store_true", help="разобрать очередь и выйти")
    args = p.parse_args()

    token = os.environ.get("KB_IMPORT_TOKEN") or env.get("KB_IMPORT_TOKEN", "")
    if not token:
        log("нет KB_IMPORT_TOKEN в deploy/.env — выхожу")
        return 1
    sys.path.insert(0, str(args.kbrag))
    os.chdir(args.kbrag)
    dsn = os.environ.get("KBRAG_DSN")
    platform = Platform(args.platform, token, args.ca)
    log(f"обработчик импорта: {args.platform}, папка приёма {args.inbox}, устройство {args.device}")
    try:
        log(f"вернул в очередь недоделанные: {platform.post('requeue')[1]['requeued']}")
    except (RuntimeError, URLError, OSError) as exc:
        log(f"платформа недоступна: {exc}")
        if args.once:
            return 1
    while True:
        try:
            code, job = platform.post("next")
        except (RuntimeError, URLError, OSError) as exc:
            log(f"платформа недоступна: {exc}")
            code, job = 0, None
        if code != 200 or not job:
            if args.once:
                return 0
            time.sleep(POLL_S)
            continue
        log(f"импорт №{job['id']}: {job['filename']} → {job['kb_path']}")
        try:
            result = process(job, args.inbox, args.device, dsn)
        except Exception as exc:  # noqa: BLE001 — сбой одной статьи не должен останавливать очередь
            traceback.print_exc()
            result = {"status": "failed", "message": f"{type(exc).__name__}: {exc}"[:2000]}
        log(f"импорт №{job['id']}: {result['status']} {result.get('doc_id', '')} {result.get('message', '')}")
        try:
            platform.post(f"{job['id']}/result", result)
        except (RuntimeError, URLError, OSError) as exc:
            log(f"итог не отправлен ({exc}); при перезапуске статья вернётся в очередь")


if __name__ == "__main__":
    raise SystemExit(main())
