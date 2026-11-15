"""Библиотека методов: встроенные методы и методы из статей банка (app/services/method_library.py).

Путь метода из статьи: исследователь нажимает «Сделать метод по статье» → задача Qwen `method`
(runner/qwen/worker.py): Qwen читает, каким методом пользовались авторы, и пишет код модели;
обработчик проверяет код здесь (/qwen/worker/method-check) и пробует его без сети на синтетических
данных → метод «готов» → администратор читает код и включает его → метод в библиотеке: его видят
«Нейросети», рекомендация «как у авторов» и запуск расчётов. Людей, пишущих код метода, нет.
"""

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.api.qwen import Worker
from app.db import get_db
from app.models import Method, QwenJob, User
from app.services import method_library as lib
from app.services import net_catalog
from app.services.codes import next_code
from app.services.qwen_queue import enqueue
from app.services.run_templates import TEMPLATES

router = APIRouter(prefix="/methods", tags=["methods"])
# обработчик Qwen ходит по /qwen/worker/… (runner/qwen/worker.py: Platform.post)
worker_router = APIRouter(prefix="/qwen/worker", tags=["qwen"])
Researcher = Depends(require_role("researcher"))
Owner = Depends(require_role("owner"))


class MethodOut(BaseModel):
    code: str
    key: str  # ключ метода в библиотеке расчётов: method:M-01
    title: str
    description: str
    net: str
    net_title: str
    task: str
    params: list[dict[str, Any]]
    status: str
    check_log: str
    sha256: str
    doc_id: str
    article_title: str
    doi: str
    evidence: str
    author: str
    decided_by: str
    decision_note: str
    created_at: datetime
    script: str = ""  # только в карточке метода


class BuiltinOut(BaseModel):
    key: str
    title: str
    description: str


class LibraryOut(BaseModel):
    builtin: list[BuiltinOut]
    methods: list[MethodOut]
    pending: list[dict[str, Any]]  # задачи Qwen «метод по статье», которые ещё идут


class FromArticleIn(BaseModel):
    doc_id: str = Field(min_length=1, max_length=512)


class DecisionIn(BaseModel):
    note: str = Field(default="", max_length=2000)


def _login(db: Session, uid: int | None) -> str:
    u = db.get(User, uid) if uid else None
    return u.login if u else ""


def _out(db: Session, m: Method, script: bool = False) -> MethodOut:
    net = net_catalog.NETS.get(m.net)
    return MethodOut(
        code=m.code, key=f"{lib.PREFIX}{m.code}", title=m.title, description=m.description, net=m.net,
        net_title=net.title if net else m.net, task=m.task, params=lib.hyper_params(m.params), status=m.status,
        check_log=m.check_log, sha256=m.sha256, doc_id=m.doc_id, article_title=m.article_title, doi=m.doi,
        evidence=m.evidence, author=_login(db, m.created_by), decided_by=_login(db, m.decided_by),
        decision_note=m.decision_note, created_at=m.created_at, script=m.script if script else "",
    )


def _get(db: Session, code: str) -> Method:
    m = db.scalar(select(Method).where(Method.code == code))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет метода {code}")
    return m


@router.get("", response_model=LibraryOut, dependencies=[Depends(current_user)])
def library(db: Annotated[Session, Depends(get_db)]) -> LibraryOut:
    pending = [{"job": j.id, "doc_id": (j.payload or {}).get("doc_id", ""), "status": j.status}
               for j in db.scalars(select(QwenJob).where(QwenJob.kind == "method",
                                                         QwenJob.status.in_(("queued", "running")))
                                   .order_by(QwenJob.id))]
    return LibraryOut(
        builtin=[BuiltinOut(key=t.key, title=t.title, description=t.description)
                 for t in TEMPLATES.values() if t.scope == "generic"],
        methods=[_out(db, m) for m in db.scalars(select(Method).order_by(Method.id.desc()))],
        pending=pending,
    )


@router.get("/{code}", response_model=MethodOut, dependencies=[Depends(current_user)])
def method(code: str, db: Annotated[Session, Depends(get_db)]) -> MethodOut:
    return _out(db, _get(db, code), script=True)


@router.post("/from-article", status_code=status.HTTP_202_ACCEPTED)
def from_article(body: FromArticleIn, db: Annotated[Session, Depends(get_db)],
                 user: Annotated[User, Researcher]) -> dict[str, Any]:
    """Метод по статье банка: Qwen прочтёт, каким методом пользовались авторы, и напишет его код."""
    doc = body.doc_id.strip()
    busy = [j for j in db.scalars(select(QwenJob).where(QwenJob.kind == "method",
                                                        QwenJob.status.in_(("queued", "running"))))
            if (j.payload or {}).get("doc_id") == doc]
    if busy:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Метод по этой статье уже пишется: задача №{busy[0].id}")
    have = db.scalar(select(Method).where(Method.doc_id == doc, Method.status.in_(("ready", "enabled"))))
    if have is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"По этой статье метод уже есть: {have.code}")
    job = enqueue(db, "method", {"doc_id": doc}, trigger="manual", user_id=user.id)
    db.commit()
    return {"job": job.id}


@router.post("/{code}/enable", response_model=MethodOut)
def enable(code: str, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Owner]) -> MethodOut:
    """Администратор прочитал код и включает метод: с этого момента его можно запускать."""
    m = _get(db, code)
    if m.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Включить можно только метод, прошедший проверку (сейчас: {m.status})")
    problems = lib.check_code(m.script)  # правила проверки могли ужесточиться после пробы
    if problems or hashlib.sha256(m.script.encode("utf-8")).hexdigest() != m.sha256:
        raise HTTPException(status.HTTP_409_CONFLICT, "Код не проходит проверку: " + "; ".join(problems or ["sha256"]))
    m.status, m.decided_by, m.decided_at = "enabled", user.id, datetime.now(UTC)
    db.commit()
    return _out(db, m)


@router.post("/{code}/reject", response_model=MethodOut)
def reject(code: str, body: DecisionIn, db: Annotated[Session, Depends(get_db)],
           user: Annotated[User, Owner]) -> MethodOut:
    m = _get(db, code)
    if m.status not in ("ready", "enabled"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Метод {code} уже {m.status}")
    if not body.note.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Напишите, почему метод отклонён")
    m.status, m.decision_note = "rejected", body.note.strip()
    m.decided_by, m.decided_at = user.id, datetime.now(UTC)
    db.commit()
    return _out(db, m)


# --- обработчик Qwen (X-Qwen-Token) ---


class CheckIn(BaseModel):
    script: str


class MethodIn(BaseModel):
    """Метод, который Qwen написал по статье, с итогом пробного запуска у обработчика."""

    job: int
    doc_id: str
    article_title: str = ""
    doi: str = ""
    title: str = Field(min_length=3, max_length=300)
    description: str = ""
    net: str = ""
    evidence: str = ""
    params: list[dict[str, Any]] = []
    script: str
    smoke_ok: bool
    smoke_log: str = ""
    fit_s: float = 0.0
    fit_rows: int = 0


@worker_router.post("/method-check", dependencies=[Worker])
def worker_check(body: CheckIn) -> dict[str, list[str]]:
    """Замечания к коду метода — обработчик просит Qwen исправить код, пока замечания есть."""
    return {"problems": lib.check_code(body.script)}


@worker_router.post("/method", dependencies=[Worker], status_code=status.HTTP_201_CREATED)
def worker_result(body: MethodIn, db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
    """Метод из статьи: платформа проверяет код сама (не доверяет отметке обработчика) и
    записывает метод — «готов» к решению администратора или «не прошёл» с журналом."""
    job = db.get(QwenJob, body.job)
    if job is None or job.kind != "method":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет задачи «метод по статье» №{body.job}")
    problems = lib.check_code(body.script)
    ok = body.smoke_ok and not problems
    log = "\n".join([*(f"Проверка кода: {p}" for p in problems), body.smoke_log.strip()]).strip()
    m = Method(
        code=next_code(db, Method.code, "M", 2), title=body.title.strip()[:300],
        description=body.description.strip()[:4000],
        net=body.net if body.net in net_catalog.NETS else "", task="predict",
        params=lib.hyper_params(body.params), script=body.script, sha256=lib.sha256(body.script),
        status="ready" if ok else "failed", check_log=log[:20_000], fit_s=max(0.0, body.fit_s),
        fit_rows=max(0, body.fit_rows), doc_id=body.doc_id, article_title=body.article_title[:1024],
        doi=body.doi[:256], evidence=body.evidence[:4000], qwen_job_id=job.id, created_by=job.created_by,
    )
    db.add(m)
    db.commit()
    return {"code": m.code, "status": m.status}
