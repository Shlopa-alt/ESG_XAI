"""Отчёты по экспериментам: Qwen пишет текст по фактам расчёта, человек правит, рецензент одобряет —
и отчёт в PDF уходит в базу знаний (ветка esg.experiments) через очередь импорта статей.

Смотреть и выгружать (Word, PDF) может любой вошедший; заказать отчёт, править и отправить на
рецензию — researcher+; одобрить и отклонить — reviewer+. Отрицательный результат публикуется
наравне с положительным (правило 4).
"""

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.api.kb_imports import _store
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Experiment, ExperimentReport, KbImport, QwenJob, Run, User
from app.services import qwen_cr, qwen_reports, report_render
from app.services.qwen_queue import enqueue

router = APIRouter(tags=["reports"])

Researcher = Depends(require_role("researcher"))
ReviewerRole = Depends(require_role("reviewer"))
KB_BRANCH = "esg.experiments"


class ReportOut(BaseModel):
    id: int
    experiment: str
    run_id: int | None
    version: int
    status: str
    facts: dict[str, Any]
    sections: dict[str, Any]
    problems: str
    note: str
    reviewer: str
    writing: bool  # Qwen ещё пишет текст
    kb_status: str  # статус импорта в базу знаний
    kb_doc_id: str
    cr: str  # код CR, который Qwen предложил по отчёту
    cr_writing: bool  # Qwen готовит CR
    cr_note: str  # почему CR нет (Qwen решил не менять методику, черновик отброшен)
    created_at: datetime


class SectionsIn(BaseModel):
    sections: dict[str, Any]


class RejectIn(BaseModel):
    note: str = Field(min_length=3)


def _out(db: Session, r: ExperimentReport) -> ReportOut:
    exp = db.get(Experiment, r.experiment_id)
    user = db.get(User, r.reviewed_by) if r.reviewed_by else None
    imp = db.get(KbImport, r.kb_import_id) if r.kb_import_id else None
    job = db.scalar(select(QwenJob).where(QwenJob.kind == "report", QwenJob.status.in_(("queued", "running")))
                    .where(QwenJob.payload["report"].as_integer() == r.id)) if not r.sections else None
    cr = qwen_cr.for_report(db, r.id) if r.status == "approved" else None
    cr_job = qwen_cr.last_job(db, r.id) if r.status == "approved" and cr is None else None
    return ReportOut(id=r.id, experiment=exp.code if exp else "", run_id=r.run_id, version=r.version,
                     status=r.status, facts=r.facts or {}, sections=r.sections or {}, problems=r.problems,
                     note=r.note, reviewer=user.login if user else "", writing=job is not None,
                     kb_status=imp.status if imp else "", kb_doc_id=imp.doc_id if imp else "",
                     cr=cr.code if cr else "",
                     cr_writing=cr_job is not None and cr_job.status in ("queued", "running"),
                     cr_note=cr_job.message if cr_job is not None and cr_job.status in ("done", "failed") else "",
                     created_at=r.created_at)


def _get(db: Session, rid: int) -> ExperimentReport:
    r = db.get(ExperimentReport, rid)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет отчёта №{rid}")
    return r


def request_report(db: Session, exp: Experiment, run: Run | None, user_id: int | None, trigger: str) -> ExperimentReport:
    """Черновик с фактами и задача Qwen написать текст."""
    r = qwen_reports.new_report(db, exp, run)
    enqueue(db, "report", {"report": r.id}, trigger=trigger, user_id=user_id, dedupe=False)
    return r


def _render(db: Session, r: ExperimentReport) -> dict[str, Any]:
    user = db.get(User, r.reviewed_by) if r.reviewed_by else None
    return {"facts": r.facts or {}, "sections": r.sections or {}, "version": r.version, "status": r.status,
            "reviewer": user.login if user else ""}


@router.get("/experiments/{code}/reports", response_model=list[ReportOut], dependencies=[Depends(current_user)])
def list_reports(code: str, db: Annotated[Session, Depends(get_db)]) -> list[ReportOut]:
    exp = db.scalar(select(Experiment).where(Experiment.code == code))
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет эксперимента {code}")
    rows = db.scalars(select(ExperimentReport).where(ExperimentReport.experiment_id == exp.id)
                      .order_by(ExperimentReport.version.desc()))
    return [_out(db, r) for r in rows]


@router.post("/experiments/{code}/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def make_report(code: str, db: Annotated[Session, Depends(get_db)],
                user: Annotated[User, Researcher]) -> ReportOut:
    """Отчёт по последнему удачному запуску (или по тексту эксперимента, если запусков нет)."""
    exp = db.scalar(select(Experiment).where(Experiment.code == code))
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет эксперимента {code}")
    pending = db.scalar(select(ExperimentReport).where(ExperimentReport.experiment_id == exp.id,
                                                       ExperimentReport.status == "draft"))
    if pending is not None and not pending.sections:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Qwen ещё пишет отчёт v{pending.version}")
    run = db.scalars(select(Run).where(Run.experiment_id == exp.id, Run.status == "done")
                     .order_by(Run.id.desc()).limit(1)).first()
    r = request_report(db, exp, run, user.id, "manual")
    db.commit()
    return _out(db, r)


@router.patch("/reports/{rid}", response_model=ReportOut)
def edit_report(rid: int, body: SectionsIn, db: Annotated[Session, Depends(get_db)],
                _user: Annotated[User, Researcher]) -> ReportOut:
    r = _get(db, rid)
    if r.status not in ("draft", "review"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Отчёт уже рассмотрен — закажите новую версию")
    r.sections = qwen_reports.clean_sections({**(r.sections or {}), **body.sections})
    r.problems = qwen_reports.check_numbers(r.facts, r.sections)
    db.commit()
    return _out(db, r)


@router.post("/reports/{rid}/submit", response_model=ReportOut)
def submit(rid: int, db: Annotated[Session, Depends(get_db)], _user: Annotated[User, Researcher]) -> ReportOut:
    r = _get(db, rid)
    if r.status != "draft" or not r.sections:
        raise HTTPException(status.HTTP_409_CONFLICT, "На рецензию — черновик с текстом")
    r.status = "review"
    db.commit()
    return _out(db, r)


@router.post("/reports/{rid}/approve", response_model=ReportOut)
def approve(rid: int, db: Annotated[Session, Depends(get_db)], settings: Annotated[Settings, Depends(get_settings)],
            user: Annotated[User, ReviewerRole]) -> ReportOut:
    """Одобрить: PDF отчёта — в папку приёма и в очередь импорта, ветка esg.experiments."""
    r = _get(db, rid)
    if r.status != "review":
        raise HTTPException(status.HTTP_409_CONFLICT, "Одобрить можно отчёт на рецензии")
    r.status, r.reviewed_by, r.reviewed_at = "approved", user.id, datetime.now(UTC)
    pdf = report_render.pdf_bytes(_render(db, r))
    e = (r.facts or {}).get("experiment", {})
    imp = KbImport(kb_path=KB_BRANCH, source="report", filename=f"{e.get('code', 'EXP')}-report-v{r.version}.pdf",
                   sha256=hashlib.sha256(pdf).hexdigest(), bytes_len=len(pdf),
                   title=f"Отчёт об эксперименте {e.get('code', '')}: {e.get('title', '')}"[:1024],
                   year=datetime.now(UTC).year, authors=["Лаборатория ИИ в ESG-управлении (НИЦ ИИ, Университет «Дубна»)"],
                   status="queued", created_by=user.id)
    _store(db, settings, imp, pdf, {"title": imp.title, "year": imp.year, "authors": imp.authors,
                                    "journal": "Отчёты экспериментов ESG Open Research"})
    r.kb_import_id = imp.id
    if str((r.sections or {}).get("methodology") or "").strip():
        # в отчёте есть предложение для методики — Qwen готовит черновик CR
        enqueue(db, "cr", {"report": r.id}, trigger="report", user_id=user.id)
    db.commit()
    return _out(db, r)


@router.post("/reports/{rid}/cr", response_model=ReportOut)
def request_cr(rid: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Researcher]) -> ReportOut:
    """Попросить Qwen предложить CR по одобренному отчёту (если сам не предложил или решил не менять)."""
    r = _get(db, rid)
    if r.status != "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "CR предлагается по одобренному отчёту")
    if (cr := qwen_cr.for_report(db, r.id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"По отчёту уже есть {cr.code}")
    if qwen_cr.pending_job(db, r.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Qwen уже готовит CR")
    enqueue(db, "cr", {"report": r.id}, trigger="manual", user_id=user.id, dedupe=False)
    db.commit()
    return _out(db, r)


@router.post("/reports/{rid}/reject", response_model=ReportOut)
def reject(rid: int, body: RejectIn, db: Annotated[Session, Depends(get_db)],
           user: Annotated[User, ReviewerRole]) -> ReportOut:
    r = _get(db, rid)
    if r.status != "review":
        raise HTTPException(status.HTTP_409_CONFLICT, "Отклонить можно отчёт на рецензии")
    r.status, r.note, r.reviewed_by, r.reviewed_at = "rejected", body.note.strip(), user.id, datetime.now(UTC)
    db.commit()
    return _out(db, r)


@router.get("/reports/{rid}/export.{fmt}", dependencies=[Depends(current_user)])
def export(rid: int, fmt: str, db: Annotated[Session, Depends(get_db)]) -> Response:
    r = _get(db, rid)
    if not r.sections:
        raise HTTPException(status.HTTP_409_CONFLICT, "Qwen ещё пишет текст отчёта")
    code = (r.facts or {}).get("experiment", {}).get("code", "EXP")
    if fmt == "docx":
        data, media = report_render.docx_bytes(_render(db, r)), \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif fmt == "pdf":
        data, media = report_render.pdf_bytes(_render(db, r)), "application/pdf"
    else:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Выгрузка — docx или pdf")
    return Response(data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{code}-report-v{r.version}.{fmt}"'})
