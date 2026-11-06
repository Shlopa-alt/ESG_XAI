"""Черновики датасетов из таблиц статей: смотреть может любой вошедший, править, давать команды
Qwen, создавать датасет и отклонять — researcher+.

Правка — операции из app/services/data_drafts.py (руками — с этой страницы, словами — задачей Qwen
`table_edit`, её операции применяет платформа). «Создать датасет» — DS-NN со ссылкой на статью и
срез CSV из таблицы черновика; в описание датасета пишется, откуда таблица и что с ней сделано.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.datasets import _add_snapshot, _root, _version
from app.api.deps import current_user, require_role
from app.config import Settings, get_settings
from app.db import get_db
from app.models import DataDraft, Dataset, QwenJob, User
from app.services import data_drafts as svc
from app.services.codes import next_code
from app.services.qwen_queue import enqueue

router = APIRouter(prefix="/data-drafts", tags=["data-drafts"])

Researcher = Depends(require_role("researcher"))


class DraftItem(BaseModel):
    id: int
    status: str
    title: str
    article_title: str
    doi: str
    doc_id: str
    table_number: int
    page: int | None
    n_rows: int
    n_cols: int
    dataset: str
    created_at: datetime


class JobState(BaseModel):
    id: int
    status: str
    command: str
    message: str


class DraftOut(DraftItem):
    kb_path: str
    caption: str
    description: str
    columns: list[str]
    rows: list[list[Any]]
    numeric: list[str]
    history: list[dict[str, Any]]
    note: str
    decided_by: str
    decided_at: datetime | None
    jobs: list[JobState]  # последние команды Qwen по этому черновику


class DraftEdit(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    description: str | None = Field(default=None, max_length=4000)
    ops: list[dict[str, Any]] | None = None


class CommandIn(BaseModel):
    text: str = Field(min_length=3, max_length=1000)


class ApproveIn(BaseModel):
    title: str = Field(min_length=3, max_length=512)
    description: str = Field(default="", max_length=4000)
    access_level: Literal["public", "nda"] = "public"


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


class ScanIn(BaseModel):
    doc_id: str = Field(default="", max_length=512)


def _get(db: Session, did: int) -> DataDraft:
    d = db.get(DataDraft, did)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет черновика №{did}")
    return d


def _open(d: DataDraft) -> None:
    if d.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Черновик уже рассмотрен")


def _item(db: Session, d: DataDraft) -> dict[str, Any]:
    ds = db.get(Dataset, d.dataset_id) if d.dataset_id else None
    return {
        "id": d.id,
        "status": d.status,
        "title": d.title,
        "article_title": d.article_title,
        "doi": d.doi,
        "doc_id": d.doc_id,
        "table_number": d.table_number,
        "page": d.page,
        "n_rows": len(d.rows or []),
        "n_cols": len(d.columns or []),
        "dataset": ds.code if ds else "",
        "created_at": d.created_at,
    }


def _jobs(db: Session, d: DataDraft) -> list[JobState]:
    jobs = db.scalars(
        select(QwenJob).where(QwenJob.kind == "table_edit").order_by(QwenJob.id.desc()).limit(200)
    )
    out = []
    for j in jobs:
        if (j.payload or {}).get("draft") == d.id:
            out.append(
                JobState(
                    id=j.id,
                    status=j.status,
                    command=str(j.payload.get("command") or ""),
                    message=j.message,
                )
            )
        if len(out) >= 5:
            break
    return out


def _out(db: Session, d: DataDraft) -> DraftOut:
    user = db.get(User, d.decided_by) if d.decided_by else None
    numeric = [
        c
        for j, c in enumerate(d.columns or [])
        if any(r[j] is not None for r in d.rows or [])
        and all(isinstance(r[j], int | float) for r in d.rows or [] if r[j] is not None)
    ]
    return DraftOut(
        **_item(db, d),
        kb_path=d.kb_path,
        caption=d.caption,
        description=d.description,
        columns=d.columns or [],
        rows=d.rows or [],
        numeric=numeric,
        history=d.history or [],
        note=d.note,
        decided_by=user.login if user else "",
        decided_at=d.decided_at,
        jobs=_jobs(db, d),
    )


@router.get("", response_model=list[DraftItem])
def list_drafts(
    db: Annotated[Session, Depends(get_db)],
    _user: Annotated[User, Depends(current_user)],
    status_: Annotated[str, Query(alias="status")] = "proposed",
) -> list[DraftItem]:
    q = select(DataDraft).order_by(DataDraft.id.desc())
    if status_ != "all":
        q = q.where(DataDraft.status == status_)
    return [DraftItem(**_item(db, d)) for d in db.scalars(q.limit(300))]


@router.get("/{did}", response_model=DraftOut)
def get_draft(
    did: int, db: Annotated[Session, Depends(get_db)], _user: Annotated[User, Depends(current_user)]
) -> DraftOut:
    return _out(db, _get(db, did))


@router.patch("/{did}", response_model=DraftOut)
def edit_draft(
    did: int,
    body: DraftEdit,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Researcher],
) -> DraftOut:
    """Правка руками: название, описание и операции над таблицей (в журнал — кто и что)."""
    d = _get(db, did)
    _open(d)
    if body.title is not None:
        d.title = body.title.strip()
    if body.description is not None:
        d.description = body.description.strip()
    if body.ops:
        try:
            svc.edit(d, body.ops, "manual", user.login)
        except svc.OpError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    db.commit()
    return _out(db, d)


@router.post("/{did}/command", response_model=DraftOut, status_code=status.HTTP_202_ACCEPTED)
def command(
    did: int,
    body: CommandIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Researcher],
) -> DraftOut:
    """Команда словами — Qwen («убери строки с итогами», «переведи тыс. руб. в руб.»). Модель
    отвечает операциями, применяет их платформа, когда задача вернётся."""
    d = _get(db, did)
    _open(d)
    enqueue(
        db,
        "table_edit",
        {"draft": d.id, "command": " ".join(body.text.split())},
        trigger="manual",
        user_id=user.id,
        dedupe=False,
    )
    svc.note(d, "command", user.login, f"Команда Qwen: «{' '.join(body.text.split())}»")
    db.commit()
    return _out(db, d)


@router.post("/{did}/approve", response_model=DraftOut)
def approve(
    did: int,
    body: ApproveIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Researcher],
) -> DraftOut:
    """Черновик → датасет DS-NN (ссылка на статью, откуда таблица, что с ней сделано), срез CSV."""
    d = _get(db, did)
    _open(d)
    if len(d.rows or []) < 3 or not d.columns:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "В таблице меньше трёх строк")
    description = "\n\n".join(
        x for x in (body.description.strip() or d.description, svc.provenance(d)) if x
    )
    ds = Dataset(
        code=next_code(db, Dataset.code, "DS", 2),
        title=body.title.strip(),
        description=description[:20000],
        source_url=f"https://doi.org/{d.doi}" if d.doi else "",
        license="",
        access_level=body.access_level,
    )
    db.add(ds)
    db.flush()
    version = _version(db, ds, "")
    stem = re.sub(r"[^\w.-]+", "_", f"{d.doc_id}_t{d.table_number}").strip("_.")[:120] or "table"
    target = _root(settings, ds) / "snapshots" / version / f"{stem}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(svc.to_csv(d), encoding="utf-8")
    d.status, d.dataset_id, d.decided_by, d.decided_at = (
        "approved",
        ds.id,
        user.id,
        datetime.now(UTC),
    )
    d.title = body.title.strip()
    svc.note(d, "approve", user.login, f"создан датасет {ds.code}, срез {version}")
    _add_snapshot(db, settings, ds, target, version)  # коммитит
    return _out(db, d)


@router.post("/{did}/reject", response_model=DraftOut)
def reject(
    did: int,
    body: RejectIn,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Researcher],
) -> DraftOut:
    d = _get(db, did)
    _open(d)
    d.status, d.note, d.decided_by, d.decided_at = (
        "rejected",
        body.note.strip(),
        user.id,
        datetime.now(UTC),
    )
    svc.note(d, "reject", user.login, f"отклонён: {d.note}")
    db.commit()
    return _out(db, d)


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
def scan(
    body: ScanIn, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Researcher]
) -> dict[str, int]:
    """Поискать таблицы-наблюдения: в одной статье (doc_id) или во всех статьях ветки esg."""
    job = enqueue(
        db,
        "tables",
        {"doc_id": body.doc_id} if body.doc_id else {},
        trigger="manual",
        user_id=user.id,
    )
    db.commit()
    return {"job": job.id}
