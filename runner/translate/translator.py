"""Переводчик черновиков данных на русский: Argos Translate на процессоре (п. 6 фидбека).

    runner\\translate\\.venv\\Scripts\\python.exe runner\\translate\\translator.py            работать постоянно
    ... --once                                                                          разобрать очередь и выйти
    ... --install                                                                       скачать языки и выйти

Берёт из очереди платформы только задачи «translate» (/api/qwen/worker/* с kinds) — обработчик Qwen
их не видит, видеокарта и модель для перевода не нужны. Языки: английский, арабский, китайский,
французский, немецкий → русский. Прямых моделей «→ русский» у Argos есть не для всех, поэтому
перевод идёт через английский (ar → en → ru): так же делает сам Argos, когда прямой пары нет.

Задача: {"draft", "source", "target": "ru", "texts": [...]}; итог — {"pairs": {оригинал: перевод},
"engine"}. Таблицу черновика платформа не меняет: перевод показывается рядом с оригиналом.

Процессор делится с расчётами: потоков перевода — ARGOS_INTRA_THREADS (по умолчанию 2).
Настройки — deploy/.env (QWEN_TOKEN, HTTP_PORT или PLATFORM_URL), как у обработчика Qwen.
"""

import argparse
import importlib.util
import os
import sys
import threading
import time
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any
from urllib.error import URLError

os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")
os.environ.setdefault("ARGOS_INTRA_THREADS", "2")  # не отбирать процессор у расчётов

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("qwen_worker", REPO / "runner" / "qwen" / "worker.py")
qw = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(qw)  # type: ignore[union-attr]  # клиент платформы — общий с обработчиком Qwen

KINDS = {"kinds": ["translate"]}
TARGET = "ru"
PIVOT = "en"
SOURCES = ("en", "ar", "zh", "fr", "de")
# какие модели нужны: всё → английский, английский → русский
NEEDED = [(PIVOT, TARGET), *[(s, PIVOT) for s in SOURCES if s != PIVOT]]
POLL_S = 20
BEAT_S = 30


def install() -> list[str]:
    """Скачать недостающие модели Argos (один раз; дальше перевод работает без интернета)."""
    import argostranslate.package as pkg

    have = {(p.from_code, p.to_code) for p in pkg.get_installed_packages()}
    missing = [pair for pair in NEEDED if pair not in have]
    if not missing:
        return []
    pkg.update_package_index()
    available = pkg.get_available_packages()
    done = []
    for f, t in missing:
        found = next((p for p in available if p.from_code == f and p.to_code == t), None)
        if found is None:
            qw.log(f"в каталоге Argos нет модели {f} → {t}")
            continue
        qw.log(f"скачиваю модель {f} → {t}")
        pkg.install_from_path(found.download())
        done.append(f"{f}→{t}")
    return done


@cache
def _direct(f: str, t: str) -> Callable[[str], str] | None:
    import argostranslate.translate as tr

    langs = {lang.code: lang for lang in tr.get_installed_languages()}
    if f not in langs or t not in langs:
        return None
    translation = langs[f].get_translation(langs[t])
    return translation.translate if translation is not None else None


def translator(source: str, target: str = TARGET) -> Callable[[str], str]:
    """Перевод source → target: прямой, если есть, иначе через английский."""
    direct = _direct(source, target)
    if direct is not None:
        return direct
    first, second = _direct(source, PIVOT), _direct(PIVOT, target)
    if first is None or second is None:
        raise RuntimeError(f"нет модели Argos {source} → {target} (запустите с --install)")
    return lambda text: second(first(text))


def engine() -> str:
    try:
        from importlib.metadata import version

        return f"Argos Translate {version('argostranslate')}"
    except Exception:  # noqa: BLE001
        return "Argos Translate"


def job_translate(job: dict[str, Any], translate: Callable[[str, str], Callable[[str], str]] = translator) -> dict[str, Any]:
    """Строки черновика → словарь переводов. Сбой одной строки — без неё, остальные переводятся."""
    p = job.get("payload") or {}
    source = str(p.get("source") or "")
    if source not in SOURCES:
        raise ValueError(f"язык «{source}» переводчик не знает: {', '.join(SOURCES)}")
    fn = translate(source, TARGET)
    pairs, failed = {}, 0
    for text in p.get("texts") or []:
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            out = fn(text).strip()
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        if out:
            # заголовок с заглавной — и перевод с заглавной («Industry» → «Промышленность»); у письма без
            # заглавных (китайский, арабский) — тоже: по-русски подпись начинается с заглавной
            first = text.lstrip()[:1]
            if (first.isupper() or first.upper() == first.lower() and first.isalpha()) and out[:1].islower():
                out = out[:1].upper() + out[1:]
            pairs[text] = out
    return {"pairs": pairs, "engine": engine(), "failed": failed}


def main() -> int:
    env = qw.read_env(qw.DEPLOY / ".env")
    ap = argparse.ArgumentParser(description="Переводчик черновиков данных (Argos Translate, процессор)")
    ap.add_argument("--platform", default=env.get("PLATFORM_URL") or f"https://127.0.0.1:{env.get('HTTP_PORT', '8080')}")
    ap.add_argument("--ca", type=Path, default=qw.DEPLOY / "certs" / "lab-root-ca.crt")
    ap.add_argument("--once", action="store_true", help="разобрать очередь и выйти")
    ap.add_argument("--install", action="store_true", help="скачать модели языков и выйти")
    args = ap.parse_args()
    if args.install:
        qw.log(f"модели: {', '.join(install()) or 'все уже скачаны'}")
        return 0
    token = os.environ.get("QWEN_TOKEN") or env.get("QWEN_TOKEN", "")
    if not token:
        qw.log("нет QWEN_TOKEN в deploy/.env — выхожу")
        return 1
    platform = qw.Platform(args.platform, token, args.ca)
    try:
        got = install()
        if got:
            qw.log(f"скачаны модели: {', '.join(got)}")
    except Exception as exc:  # noqa: BLE001 — без интернета работаем с тем, что уже скачано
        qw.log(f"модели не скачались ({exc}); перевожу тем, что есть")

    def beat_forever() -> None:
        while True:
            try:
                platform.post("translator-heartbeat")
            except (RuntimeError, URLError, OSError) as exc:
                qw.log(f"отметка не прошла: {exc}")
            time.sleep(BEAT_S)

    threading.Thread(target=beat_forever, daemon=True).start()
    qw.log(f"переводчик: {args.platform}, {engine()}, потоков {os.environ['ARGOS_INTRA_THREADS']}")
    try:
        qw.log(f"вернул в очередь недоделанные: {platform.post('requeue', KINDS)[1]['requeued']}")
    except (RuntimeError, URLError, OSError) as exc:
        qw.log(f"платформа недоступна: {exc}")
    while True:
        while True:
            try:
                code, job = platform.post("next", KINDS)
            except (RuntimeError, URLError, OSError) as exc:
                qw.log(f"платформа недоступна: {exc}")
                break
            if code != 200 or not job:
                break
            qw.log(f"задача №{job['id']}: перевод черновика №{job['payload'].get('draft')} "
                   f"({job['payload'].get('source')}, строк {len(job['payload'].get('texts') or [])})")
            try:
                result = job_translate(job)
                body = {"status": "done", "result": result,
                        "message": f"Переведено строк: {len(result['pairs'])}"}
            except Exception as exc:  # noqa: BLE001 — сбой одной задачи не останавливает очередь
                body = {"status": "failed", "message": f"{type(exc).__name__}: {exc}"[:2000]}
            qw.log(f"задача №{job['id']}: {body['status']} {body.get('message', '')}")
            try:
                qw.post_retry(platform, f"{job['id']}/result", body)
            except Exception as exc:  # noqa: BLE001
                qw.log(f"итог не отправлен ({exc}); при перезапуске задача вернётся в очередь")
        if args.once:
            return 0
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
