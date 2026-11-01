"""Импорт статей в базу знаний через сайт: PDF-файлом или по DOI (открытый PDF).

Загружает researcher и выше; список видят все вошедшие. Платформа кладёт PDF и метаданные
(JSON — он же YAML, который читает KBRAG) в папку приёма и ставит статью в очередь.
Разбирает её обработчик на машине KBRAG: он забирает очередь и сообщает итог по служебному
токену (X-Import-Token), без сессии пользователя.
"""

import hashlib
import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.api.kb import fetch
from app.config import Settings, get_settings
from app.db import get_db
from app.models import KbImport, User
from app.services.article_fetch import (
    FetchError,
    doc_id_for_doi,
    download_pdf,
    normalize_doi,
    openalex_work,
)
from app.services.qwen_queue import enqueue

router = APIRouter(prefix="/kb-imports", tags=["kb-imports"])

Researcher = Depends(require_role("researcher"))
KB_PATH = re.compile(r"esg(\.[a-z0-9_]+)*")


class ImportOut(BaseModel):
    id: int
    kb_path: str
    source: str
    filename: str
    doi: str
    title: str
    year: int | None
    authors: list[str]
    bytes_len: int
    status: str
    doc_id: str
    message: str
    author: str
    created_at: datetime
    finished_at: datetime | None


class DoiIn(BaseModel):
    doi: str = Field(min_length=7, max_length=256)
    kb_path: str


class Job(BaseModel):
    id: int
    kb_path: str
    path: str  # от корня папки приёма
    filename: str


class ResultIn(BaseModel):
    status: Literal["done", "duplicate", "failed"]
    doc_id: str = ""
    message: str = ""


def _out(db: Session, imp: KbImport) -> ImportOut:
    user = db.get(User, imp.created_by) if imp.created_by else None
    return ImportOut(
        id=imp.id, kb_path=imp.kb_path, source=imp.source, filename=imp.filename, doi=imp.doi,
        title=imp.title, year=imp.year, authors=list(imp.authors or []), bytes_len=imp.bytes_len,
        status=imp.status, doc_id=imp.doc_id, message=imp.message,
        author=user.login if user else "", created_at=imp.created_at,
        finished_at=imp.finished_at,
    )


def _kb_path(value: str) -> str:
    value = value.strip()
    if not KB_PATH.fullmatch(value):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Ветка базы знаний — esg или её подветка (esg.finance…)")
    return value


def _doi(value: str) -> str:
    try:
        return normalize_doi(value)
    except FetchError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


def _not_twice(db: Session, sha: str = "", doi: str = "") -> None:
    """Тот же файл или DOI уже в очереди или загружен — второй раз не ставим."""
    q = select(KbImport).where(KbImport.status != "failed")
    q = q.where(KbImport.sha256 == sha) if sha else q.where(KbImport.doi == doi)
    same = db.scalars(q).first()
    if same is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Эта статья уже загружена через сайт: импорт №{same.id} ({same.status})")


def _in_kb(settings: Settings, doi: str) -> bool:
    """Есть ли статья с этим DOI в KBRAG (идентификатор — из DOI)."""
    url = f"{settings.kbrag_url.rstrip('/')}/api/document?doc_id={doc_id_for_doi(doi)}"
    try:
        code, _body, _kind = fetch(url, settings.kbrag_token, settings.kbrag_timeout_s)
    except OSError:
        return False  # KBRAG недоступен — повтор отсечёт сам импорт
    return code == 200


def _store(db: Session, settings: Settings, imp: KbImport, data: bytes, meta: dict[str, object]) -> None:
    """PDF и метаданные — в папку приёма: <год-месяц>/<номер>/<имя>.pdf и .yaml рядом.
    Имя файла — исходное: если названия нет ни в метаданных, ни в PDF, KBRAG берёт его."""
    db.add(imp)
    db.flush()
    stem = re.sub(r"[^\w.-]+", "_", Path(imp.filename).stem).strip("_.")[:120] or "article"
    rel = Path(datetime.now(UTC).strftime("%Y-%m")) / f"{imp.id:05d}" / f"{stem}.pdf"
    target = Path(settings.kb_inbox_dir) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    clean = {k: v for k, v in meta.items() if v not in (None, "", [])}
    if clean:
        target.with_suffix(".yaml").write_text(json.dumps(clean, ensure_ascii=False, indent=2),
                                               encoding="utf-8")
    imp.storage_path = rel.as_posix()
    db.commit()


def _worker(settings: Annotated[Settings, Depends(get_settings)],
            x_import_token: Annotated[str, Header()] = "") -> None:
    if not settings.kb_import_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "KB_IMPORT_TOKEN не задан")
    if not secrets.compare_digest(x_import_token, settings.kb_import_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный токен обработчика")


Worker = Depends(_worker)


@router.get("", response_model=list[ImportOut], dependencies=[Depends(current_user)])
def list_imports(db: Annotated[Session, Depends(get_db)]) -> list[ImportOut]:
    return [_out(db, i) for i in db.scalars(select(KbImport).order_by(KbImport.id.desc()).limit(200))]


@router.post("", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
def upload(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Researcher],
    file: Annotated[UploadFile, File()],
    kb_path: Annotated[str, Form()],
    doi: Annotated[str, Form()] = "",
    title: Annotated[str, Form()] = "",
    year: Annotated[str, Form()] = "",
    authors: Annotated[str, Form()] = "",
) -> ImportOut:
    """PDF-файл; DOI, название, год и авторы — если указаны, важнее того, что в самом PDF.
    Указан DOI, а остального нет — недостающее берётся из OpenAlex."""
    path = _kb_path(kb_path)
    limit = settings.kb_import_max_mb * 2**20
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Файл больше {settings.kb_import_max_mb} МБ")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Это не PDF")
    norm_doi = _doi(doi) if doi.strip() else ""
    if year.strip() and not re.fullmatch(r"(19|20)\d\d", year.strip()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Год — четыре цифры, например 2024")
    sha = hashlib.sha256(data).hexdigest()
    _not_twice(db, sha=sha)
    names = [a.strip() for a in re.split(r"[;\n]", authors) if a.strip()]
    meta: dict[str, Any] = {"title": title.strip(), "year": int(year) if year.strip() else None,
                            "authors": names, "journal": ""}
    if norm_doi and not all(meta[k] for k in ("title", "year", "authors")):
        # Свойства PDF часто врут (автор — тот, кто сохранял файл): по DOI — из OpenAlex
        try:
            work = openalex_work(norm_doi, 15.0)
            meta.update({k: meta[k] or work[k] for k in ("title", "year", "authors", "journal")})
        except (FetchError, ValueError):
            pass
    imp = KbImport(kb_path=path, source="file", filename=Path(file.filename or "article.pdf").name[:512],
                   sha256=sha, bytes_len=len(data), doi=norm_doi, title=str(meta["title"])[:1024],
                   year=meta["year"], authors=meta["authors"], status="queued", created_by=user.id)
    _store(db, settings, imp, data, {
        **meta, "doi": norm_doi, "url": f"https://doi.org/{norm_doi}" if norm_doi else "",
    })
    return _out(db, imp)


@router.post("/doi", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
def by_doi(
    body: DoiIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Researcher],
) -> ImportOut:
    """Статья по DOI: метаданные из OpenAlex, открытый PDF скачивается сразу."""
    path, doi = _kb_path(body.kb_path), _doi(body.doi)
    _not_twice(db, doi=doi)
    if _in_kb(settings, doi):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Статья {doi} уже есть в базе знаний")
    try:
        work = openalex_work(doi)
        data, url = download_pdf(work["pdf_urls"], settings.kb_import_max_mb * 2**20)
    except FetchError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    sha = hashlib.sha256(data).hexdigest()
    _not_twice(db, sha=sha)
    imp = KbImport(kb_path=path, source="doi", filename=f"{doc_id_for_doi(doi)}.pdf", sha256=sha,
                   bytes_len=len(data), doi=doi, title=work["title"][:1024], year=work["year"],
                   authors=work["authors"], status="queued", created_by=user.id,
                   message=f"PDF: {url}")
    _store(db, settings, imp, data, {
        "title": work["title"], "year": work["year"], "doi": doi, "authors": work["authors"],
        "journal": work["journal"], "url": f"https://doi.org/{doi}",
    })
    return _out(db, imp)


@router.post("/{import_id}/retry", response_model=ImportOut)
def retry(import_id: int, db: Annotated[Session, Depends(get_db)],
          _user: Annotated[User, Researcher]) -> ImportOut:
    imp = db.get(KbImport, import_id)
    if imp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет импорта №{import_id}")
    if imp.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Повторить можно только неудавшийся импорт")
    imp.status, imp.message, imp.started_at, imp.finished_at = "queued", "", None, None
    db.commit()
    return _out(db, imp)


# --- обработчик на машине KBRAG ---


@router.post("/worker/requeue", dependencies=[Worker])
def requeue_stale(db: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    """При старте обработчика: то, что он разбирал до остановки, — снова в очередь."""
    n = db.execute(update(KbImport).where(KbImport.status == "processing")
                   .values(status="queued", started_at=None)).rowcount
    db.commit()
    return {"requeued": n}


@router.post("/worker/next", response_model=Job, dependencies=[Worker],
             responses={204: {"description": "очередь пуста"}})
def next_job(db: Annotated[Session, Depends(get_db)]) -> Job | Response:
    imp = db.scalars(select(KbImport).where(KbImport.status == "queued")
                     .order_by(KbImport.id).limit(1).with_for_update(skip_locked=True)).first()
    if imp is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    imp.status, imp.started_at = "processing", datetime.now(UTC)
    db.commit()
    return Job(id=imp.id, kb_path=imp.kb_path, path=imp.storage_path, filename=imp.filename)


@router.post("/worker/{import_id}/result", response_model=ImportOut, dependencies=[Worker])
def job_result(import_id: int, body: ResultIn,
               db: Annotated[Session, Depends(get_db)]) -> ImportOut:
    imp = db.get(KbImport, import_id)
    if imp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет импорта №{import_id}")
    imp.status, imp.doc_id, imp.message = body.status, body.doc_id, body.message[:4000]
    imp.finished_at = datetime.now(UTC)
    if body.status == "done":
        # новая статья в базе — Qwen достроит граф и предложит гипотезы (одна задача на все импорты подряд)
        enqueue(db, "graph", {"kb": "esg"}, trigger="import")
        enqueue(db, "hypotheses", {}, trigger="import")  # после графа: очередь идёт по порядку
    db.commit()
    return _out(db, imp)
