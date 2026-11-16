"""Перевод черновиков данных из иностранных статей на русский (п. 6 фидбека).

Переводит Argos Translate — офлайн-модели на процессоре лабораторного ПК (runner/translate/worker.py):
видеокарта и Qwen для перевода не нужны, поэтому перевод идёт и когда модель занята другими задачами.
Задача — в той же очереди (QwenJob, kind="translate"), но обработчик Qwen её не берёт (CPU_KINDS).

Таблица черновика не меняется: перевод — словарь «оригинал → по-русски» в итоге задачи, на экране
переключатель «По-русски / Оригинал». В набор данных уходит оригинал (правило 8: производные данные
со ссылкой на статью). Числа не переводятся. Языки — LANGS; остальные переводчик не берёт.
"""

import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataDraft, QwenJob
from app.services.qwen_queue import enqueue

LANGS = {"en": "английский", "ar": "арабский", "zh": "китайский", "fr": "французский", "de": "немецкий"}
TARGET = "ru"
MAX_TEXTS = 3000  # разных строк в одном черновике
MAX_LEN = 2000  # длиннее — не переводим (это уже не подпись таблицы)

_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_CJK = re.compile(r"[㐀-䶿一-鿿]")
_CYR = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN = re.compile(r"[a-zà-ÿœß]", re.IGNORECASE)
_WORD = re.compile(r"[a-zà-ÿœß']+")
STOP = {
    "en": {"the", "and", "of", "in", "to", "is", "for", "with", "on", "by", "from", "total", "year", "average",
           "number", "firms", "share", "rate", "growth", "value", "per", "or", "as", "at"},
    "fr": {"le", "la", "les", "des", "et", "du", "de", "en", "pour", "une", "un", "est", "au", "aux", "sur",
           "par", "année", "taux", "moyenne", "entreprises", "nombre", "chiffre", "affaires"},
    "de": {"der", "die", "das", "und", "den", "dem", "mit", "für", "von", "im", "ist", "zu", "nach", "jahr",
           "unternehmen", "anteil", "anzahl", "durchschnitt", "umsatz", "summe", "insgesamt", "oder"},
}
_MARKS = {"de": re.compile(r"[äöüß]"), "fr": re.compile(r"[éèêàçœëîôùû]")}


def detect(texts: Iterable[str]) -> str:
    """Язык текстов таблицы: по письменности (арабский, китайский, русский), латиница — по частым
    словам и буквам с диакритикой. Пусто — букв нет (одни числа). Русский — «ru»: переводить нечего."""
    sample = " ".join(texts)[:30000]
    letters = len(re.findall(r"[^\W\d_]", sample))
    if not letters:
        return ""
    if len(_ARABIC.findall(sample)) / letters > 0.3:
        return "ar"
    if len(_CJK.findall(sample)) / letters > 0.2:
        return "zh"
    if len(_CYR.findall(sample)) / letters > 0.5:
        return TARGET
    if len(_LATIN.findall(sample)) / letters < 0.5:
        return ""
    low = sample.lower()
    words = _WORD.findall(low)
    score = {lang: sum(1 for w in words if w in stop) for lang, stop in STOP.items()}
    for lang, mark in _MARKS.items():
        score[lang] += 2 * len(mark.findall(low))
    best = max(score, key=lambda k: score[k])
    return best if score[best] > 0 else "en"  # латиница без подсказок — чаще всего английские заголовки


def _foreign(text: str) -> bool:
    """Строку стоит переводить: в ней есть буквы и она не по-русски."""
    letters = len(re.findall(r"[^\W\d_]", text))
    return letters > 0 and len(_CYR.findall(text)) / letters < 0.5 and len(text) <= MAX_LEN


def source_texts(d: DataDraft) -> list[str]:
    """Что показывается из таблицы статьи: заголовки, подпись, текст ячеек (без чисел)."""
    out = [*(d.columns or []), d.caption or ""]
    out += [c for r in d.rows or [] for c in r if isinstance(c, str)]
    return [t for t in out if t]


def texts(d: DataDraft) -> list[str]:
    """Разные строки черновика, которые нужно перевести, — по порядку появления."""
    seen: dict[str, None] = {}
    for t in [d.title or "", d.description or "", *source_texts(d)]:
        t = t.strip()
        if t and _foreign(t):
            seen.setdefault(t, None)
    return list(seen)[:MAX_TEXTS]


def language(d: DataDraft) -> str:
    return detect(source_texts(d) or [d.title or "", d.description or ""])


def _jobs(db: Session, d: DataDraft) -> list[QwenJob]:
    return [j for j in db.scalars(select(QwenJob).where(QwenJob.kind == "translate").order_by(QwenJob.id.desc())
                                  .limit(500)) if (j.payload or {}).get("draft") == d.id]


def request(db: Session, d: DataDraft, lang: str = "", trigger: str = "manual",
            user_id: int | None = None) -> QwenJob | None:
    """Поставить перевод черновика. lang — язык оригинала (пусто — определить). None — переводить
    нечего: русский, одни числа или язык, которого переводчик не знает."""
    lang = lang or language(d)
    if lang not in LANGS:
        return None
    items = texts(d)
    if not items:
        return None
    return enqueue(db, "translate", {"draft": d.id, "source": lang, "target": TARGET, "texts": items},
                   trigger=trigger, user_id=user_id)


def auto(db: Session, ids: list[int]) -> int:
    """Новые черновики из иностранных статей — сразу в перевод. Сколько поставлено."""
    n = 0
    for did in ids:
        d = db.get(DataDraft, did)
        if d is not None and request(db, d, trigger="draft") is not None:
            n += 1
    return n


def clean_result(job: QwenJob, result: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Итог переводчика → только переводы строк, которые просили; сообщение задачи."""
    raw = (job.payload or {}).get("texts")
    asked = {t for t in raw if isinstance(t, str)} if isinstance(raw, list) else set()
    pairs = result.get("pairs")
    clean = {k: v.strip()[:MAX_LEN * 2] for k, v in (pairs.items() if isinstance(pairs, dict) else [])
             if k in asked and isinstance(v, str) and v.strip()}
    engine = str(result.get("engine") or "")[:200]
    out = {"pairs": clean, "engine": engine, "source": (job.payload or {}).get("source"), "target": TARGET,
           "missing": len(asked) - len(clean)}
    msg = f"Переведено строк: {len(clean)} из {len(asked)}" + (f" ({engine})" if engine else "")
    return out, msg


def state(db: Session, d: DataDraft) -> dict[str, Any]:
    """Перевод для экрана черновика: последний готовый (словарь) и идёт ли новый."""
    jobs = _jobs(db, d)
    done = next((j for j in jobs if j.status == "done"), None)
    pending = next((j for j in jobs if j.status in ("queued", "running")), None)
    failed = jobs[0] if jobs and jobs[0].status == "failed" else None
    lang = language(d)
    res = done.result if done is not None and isinstance(done.result, dict) else {}
    return {
        "lang": lang,
        "lang_title": LANGS.get(lang, ""),
        "can_translate": lang in LANGS and bool(texts(d)),
        "pairs": res.get("pairs") or {},
        "source": res.get("source") or "",
        "engine": res.get("engine") or "",
        "done_at": done.finished_at if done is not None else None,
        "pending": pending.status if pending is not None else "",
        "failed": failed.message if failed is not None else "",
    }


def titles(db: Session) -> dict[int, dict[str, str]]:
    """Последний готовый перевод каждого черновика — для списка (название по-русски)."""
    out: dict[int, dict[str, str]] = {}
    for j in db.scalars(select(QwenJob).where(QwenJob.kind == "translate", QwenJob.status == "done")
                        .order_by(QwenJob.id.desc()).limit(2000)):
        did = (j.payload or {}).get("draft")
        pairs = (j.result or {}).get("pairs") if isinstance(j.result, dict) else None
        if isinstance(did, int) and did not in out and isinstance(pairs, dict):
            out[did] = pairs
    return out
