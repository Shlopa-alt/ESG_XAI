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
# языки, которые платформа узнаёт, но переводчик (модели Argos на лабораторном ПК) не знает:
# их таблицы не переводятся сами — лучше без перевода, чем испанский «по-французски»
# (транслитерация вместо смысла)
OTHER = {"es": "испанский", "pt": "португальский", "it": "итальянский", "tr": "турецкий",
         "vi": "вьетнамский", "fa": "персидский", "uk": "украинский"}
NAMES = {**LANGS, **OTHER}
TARGET = "ru"
MAX_TEXTS = 3000  # разных строк в одном черновике
MAX_LEN = 2000  # длиннее — не переводим (это уже не подпись таблицы)

# арабское письмо — и обычные буквы, и «формы представления» (U+FB50–FDFF, U+FE70–FEFF):
# так его часто отдаёт PDF (docling), и без них арабская или персидская таблица была «без языка»
_ARABIC = re.compile("[\\u0600-\\u06ff\\u0750-\\u077f\\ufb50-\\ufdff\\ufe70-\\ufefc]")
# буквы, которых нет в арабском, но есть в персидском: پ چ ژ گ ک ی — и их формы представления
_PERSIAN = re.compile("[\\u067e\\u0686\\u0698\\u06af\\u06a9\\u06cc\\ufb56-\\ufb59\\ufb7a-\\ufb7d"
                      "\\ufb8a\\ufb8b\\ufb8e-\\ufb95\\ufbfc-\\ufbff]")
_CJK = re.compile("[\\u3400-\\u4dbf\\u4e00-\\u9fff]")
_CYR = re.compile(r"[а-яёіїєґ]", re.IGNORECASE)
_UKR = re.compile(r"[іїєґ]", re.IGNORECASE)
_LATIN = re.compile(r"[a-zà-ÿœßğışăđơưạ-ỹ]", re.IGNORECASE)
_WORD = re.compile(r"[a-zà-ÿœßğışãõ']+")
# вьетнамский: буквы с тоном (U+1EA0–1EF9) и ă đ ơ ư — их нет в европейских языках
_VI = re.compile(r"[ăđơưạ-ỹ]", re.IGNORECASE)
# у европейских языков таких букв единицы процентов, у «кракозябр» (Òàáëèöà) — большинство
_MOJIBAKE = re.compile(r"[À-ÿ]")
_TR = re.compile(r"[ğışĞİŞ]")  # без IGNORECASE: «ı» без учёта регистра совпадает с латинской i
STOP = {
    "en": {"the", "and", "of", "in", "to", "is", "for", "with", "on", "by", "from", "total", "year", "average",
           "number", "firms", "share", "rate", "growth", "value", "per", "or", "as", "at"},
    "fr": {"le", "la", "les", "des", "et", "du", "de", "en", "pour", "une", "un", "est", "au", "aux", "sur",
           "par", "année", "taux", "moyenne", "entreprises", "nombre", "chiffre", "affaires",
           "tableau"},
    "de": {"der", "die", "das", "und", "den", "dem", "mit", "für", "von", "im", "ist", "zu", "nach", "jahr",
           "unternehmen", "anteil", "anzahl", "durchschnitt", "umsatz", "summe", "insgesamt", "oder"},
    # общие с французским «de», «la», «en» — в обоих списках: решают слова и буквы, которых
    # у соседа нет
    "es": {"el", "los", "las", "del", "de", "la", "en", "y", "para", "por", "con", "una", "que",
           "tabla", "año", "años", "empresas", "media", "número", "tasa", "valor", "estadísticos",
           "diferencias"},
    "pt": {"o", "os", "as", "do", "da", "dos", "das", "de", "em", "e", "para", "com", "uma", "não",
           "tabela", "ano", "anos", "empresas", "média", "número", "taxa", "valor"},
    "it": {"il", "lo", "gli", "della", "delle", "dei", "degli", "di", "e", "per", "con", "una",
           "che", "tabella", "anno", "anni", "imprese", "media", "numero", "tasso", "valore"},
}
_MARKS = {"de": re.compile(r"[äöüß]"), "fr": re.compile(r"[éèêàçœëîôùû]"),
          "es": re.compile(r"[ñáíóú¿¡]"), "pt": re.compile(r"[ãõ]"), "it": re.compile(r"[ìò]")}


def detect(texts: Iterable[str]) -> str:
    """Язык текстов таблицы: по письменности (арабский или персидский, китайский, русский или
    украинский), латиница — по особым буквам (вьетнамский, турецкий), частым словам и диакритике.
    Пусто — букв нет (одни числа). Русский — «ru»: переводить нечего."""
    sample = " ".join(texts)[:30000]
    letters = len(re.findall(r"[^\W\d_]", sample))
    if not letters:
        return ""
    arabic = len(_ARABIC.findall(sample))
    if arabic / letters > 0.3:
        return "fa" if len(_PERSIAN.findall(sample)) / arabic > 0.02 else "ar"
    if len(_CJK.findall(sample)) / letters > 0.2:
        return "zh"
    cyr = len(_CYR.findall(sample))
    if cyr / letters > 0.5:
        return "uk" if len(_UKR.findall(sample)) / cyr > 0.02 else TARGET
    latin = len(_LATIN.findall(sample))
    if latin / letters < 0.5:
        return ""
    if len(_MOJIBAKE.findall(sample)) / latin > 0.3:
        return ""  # «Òàáëèöà» — русский текст в чужой кодировке: это не язык, переводить нечего
    if len(_VI.findall(sample)) / latin > 0.03:
        return "vi"
    if len(_TR.findall(sample)) / latin > 0.01:
        return "tr"
    low = sample.lower()
    words = _WORD.findall(low)
    score = {lang: sum(1 for w in words if w in stop) for lang, stop in STOP.items()}
    for lang, mark in _MARKS.items():
        score[lang] += 2 * len(mark.findall(low))
    best = max(score, key=lambda k: score[k])
    return best if score[best] > 0 else "en"  # латиница без подсказок — чаще всего английские заголовки


# код, а не слова: «H2», «H1a», «HRM -> HQXH», «PROC-INDEP», «ROA», «CA» — переводчик делал из них
# кириллицу («Н2», «ГОК»), и в таблице по-русски это выглядело как данные
_TOKEN = re.compile(r"[^\W_]+")


def _code_like(text: str) -> bool:
    """Строка — одни коды: в каждом слове цифра (H1a, 2021), или это заглавная аббревиатура
    до пяти букв (HRM, HQXH, INDEP), или одна-две буквы (p, t, CA). «TOTAL ASSETS» — уже слова."""
    words = _TOKEN.findall(text)
    return bool(words) and all(
        any(ch.isdigit() for ch in w) or (w.isupper() and len(w) <= 5) or len(w) <= 2 for w in words
    )


def _foreign(text: str) -> bool:
    """Строку стоит переводить: в ней есть буквы и иностранного в ней больше, чем русского
    (иероглиф — за две буквы: он короче слова)."""
    letters = len(re.findall(r"[^\W\d_]", text))
    cyr = len(_CYR.findall(text))
    other = letters - cyr + len(_CJK.findall(text))
    return letters > 0 and other > cyr and len(text) <= MAX_LEN and not _code_like(text)


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
        "lang_title": NAMES.get(lang, ""),
        "supported": lang in LANGS,  # язык знает переводчик: переводится сам, без выбора языка
        "can_translate": lang in LANGS and bool(texts(d)),
        # есть что переводить (иностранные строки), даже если язык не определился или переводчик его
        # не знает: тогда язык выбирают вручную
        "has_texts": bool(texts(d)),
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
