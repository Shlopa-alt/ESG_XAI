"""Студия: сценарии SC-NN (граф узлов), их версии, расчёты и предпросмотр узла.

Смотреть сценарии может любой вошедший; создавать, менять и считать — researcher+, менять — автор
или владелец платформы (остальные делают копию). Расчёт ставится в очередь studio исполнителя;
результаты узлов из наборов под NDA видны только тем, кому видны файлы этих наборов (правило 6).
"""

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.datasets import _can_see_files
from app.api.deps import current_user, require_role
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Dataset, DatasetSnapshot, Scenario, ScenarioVersion, StudioRun, User
from app.services import run_queue
from app.services import studio as svc
from app.services.codes import next_code
from app.services.data_files import to_container

router = APIRouter(prefix="/studio", tags=["studio"])
Researcher = Depends(require_role("researcher"))
ACTIVE = ("queued", "running")


class ScenarioIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=4000)


class ScenarioSave(BaseModel):
    version: int  # версия, на которой основана правка: изменили без вас — 409
    graph: dict[str, Any]
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)


class RunIn(BaseModel):
    until: str = Field(default="", max_length=64)  # узел для предпросмотра; пусто — весь сценарий


class WorkerStudio(BaseModel):
    status: Literal["running", "done", "failed", "stopped"]
    message: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    views: dict[str, Any] = Field(default_factory=dict)
    files: list[str] = Field(default_factory=list)
    results_path: str = ""
    runner_commit: str = ""
    env_lock_sha256: str = ""
    python: str = ""


def _brief(db: Session, s: Scenario) -> dict[str, Any]:
    author = db.get(User, s.author_id) if s.author_id else None
    return {"code": s.code, "title": s.title, "description": s.description, "version": s.version,
            "author": author.login if author else "", "nodes": len(s.graph.get("nodes") or []),
            "updated_at": s.updated_at}


def _get(db: Session, code: str) -> Scenario:
    s = db.scalar(select(Scenario).where(Scenario.code == code.upper()))
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет сценария {code}")
    return s


def _may_edit(s: Scenario, user: User) -> None:
    if s.author_id != user.id and user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Менять сценарий может его автор или владелец платформы — "
                            "сделайте копию")


def _check(settings: Settings, graph: dict[str, Any]) -> None:
    try:
        svc.check_graph(settings, graph)
    except svc.GraphError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"node": exc.node, "message": str(exc)}) from exc


def _run_out(r: StudioRun, hide: bool = False) -> dict[str, Any]:
    return {"id": r.id, "version": r.version, "until": r.until, "status": r.status,
            "message": r.message, "created_at": r.created_at, "started_at": r.started_at,
            "finished_at": r.finished_at, "summary": r.summary, "files": [] if hide else r.files,
            "inputs": r.inputs, "runner_commit": r.runner_commit,
            "env_lock_sha256": r.env_lock_sha256, "hidden": hide}


def _hidden(db: Session, r: StudioRun, user: User) -> bool:
    """Результаты расчёта по набору под NDA — только тем, кому видны его файлы."""
    for item in (r.inputs or {}).values():
        ds = db.scalar(select(Dataset).where(Dataset.code == item.get("dataset")))
        if ds is not None and not _can_see_files(ds, user):
            return True
    return False


@router.get("/components")
def get_components(settings: Annotated[Settings, Depends(get_settings)],
                   _: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    return svc.catalog(settings)


@router.get("/scenarios")
def list_scenarios(db: Annotated[Session, Depends(get_db)],
                   _: Annotated[User, Depends(current_user)]) -> list[dict[str, Any]]:
    rows = db.scalars(select(Scenario).order_by(Scenario.updated_at.desc()))
    return [_brief(db, s) for s in rows]


@router.post("/scenarios", status_code=status.HTTP_201_CREATED, dependencies=[Researcher])
def create_scenario(body: ScenarioIn, db: Annotated[Session, Depends(get_db)],
                    user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    s = Scenario(code=next_code(db, Scenario.code, "SC", 2), title=body.title.strip(),
                 description=body.description.strip(), graph=svc.empty_graph(), version=1,
                 author_id=user.id, updated_at=datetime.now(UTC))
    db.add(s)
    db.flush()
    db.add(ScenarioVersion(scenario_id=s.id, version=1, graph=s.graph, saved_by=user.id))
    db.commit()
    return _brief(db, s)


@router.get("/scenarios/{code}")
def get_scenario(code: str, db: Annotated[Session, Depends(get_db)],
                 user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    s = _get(db, code)
    runs = db.scalars(select(StudioRun).where(StudioRun.scenario_id == s.id, StudioRun.until == "")
                      .order_by(StudioRun.id.desc()).limit(10))
    return {**_brief(db, s), "graph": s.graph,
            "editable": s.author_id == user.id or user.role == "owner",
            "runs": [_run_out(r, _hidden(db, r, user)) for r in runs]}


@router.put("/scenarios/{code}", dependencies=[Researcher])
def save_scenario(code: str, body: ScenarioSave, db: Annotated[Session, Depends(get_db)],
                  settings: Annotated[Settings, Depends(get_settings)],
                  user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    s = _get(db, code)
    _may_edit(s, user)
    if body.version != s.version:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Сценарий уже сохранили без вас (версия {s.version}) — "
                            "обновите страницу")
    _check(settings, body.graph)
    if body.graph != s.graph:
        s.version += 1
        s.graph = body.graph
        db.add(ScenarioVersion(scenario_id=s.id, version=s.version, graph=body.graph,
                               saved_by=user.id))
    if body.title is not None:
        s.title = body.title.strip()
    if body.description is not None:
        s.description = body.description.strip()
    s.updated_at = datetime.now(UTC)
    db.commit()
    return {**_brief(db, s), "graph": s.graph, "editable": True}


@router.post("/scenarios/{code}/copy", status_code=status.HTTP_201_CREATED,
             dependencies=[Researcher])
def copy_scenario(code: str, db: Annotated[Session, Depends(get_db)],
                  user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    src = _get(db, code)
    s = Scenario(code=next_code(db, Scenario.code, "SC", 2), title=f"{src.title} (копия)"[:256],
                 description=f"Копия {src.code}, версия {src.version}. {src.description}"[:4000],
                 graph=src.graph, version=1, author_id=user.id, updated_at=datetime.now(UTC))
    db.add(s)
    db.flush()
    db.add(ScenarioVersion(scenario_id=s.id, version=1, graph=s.graph, saved_by=user.id))
    db.commit()
    return _brief(db, s)


@router.get("/scenarios/{code}/versions")
def versions(code: str, db: Annotated[Session, Depends(get_db)],
             _: Annotated[User, Depends(current_user)]) -> list[dict[str, Any]]:
    s = _get(db, code)
    rows = db.scalars(select(ScenarioVersion).where(ScenarioVersion.scenario_id == s.id)
                      .order_by(ScenarioVersion.version.desc()))
    out = []
    for v in rows:
        who = db.get(User, v.saved_by) if v.saved_by else None
        out.append({"version": v.version, "saved_at": v.saved_at,
                    "saved_by": who.login if who else "", "nodes": len(v.graph.get("nodes") or [])})
    return out


@router.post("/scenarios/{code}/run", status_code=status.HTTP_201_CREATED,
             dependencies=[Researcher])
def run_scenario(code: str, body: RunIn, db: Annotated[Session, Depends(get_db)],
                 settings: Annotated[Settings, Depends(get_settings)],
                 user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    """Расчёт сохранённой версии: весь сценарий или (until) только узел и то, от чего он зависит."""
    s = _get(db, code)
    graph = s.graph
    _check(settings, graph)
    ids = {n["id"] for n in graph.get("nodes") or []}
    if not ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "В сценарии нет узлов")
    if body.until and body.until not in ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Нет узла {body.until}")
    only = svc.needed(graph, body.until) if body.until else None
    busy = db.scalar(select(StudioRun).where(StudioRun.created_by == user.id,
                                             StudioRun.status.in_(ACTIVE), StudioRun.until == "")
                     .limit(1))
    if busy is not None and not body.until:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Уже идёт ваш расчёт сценария (№ {busy.id}) — "
                            "дождитесь его или остановите")
    inputs: dict[str, Any] = {}
    job_inputs: dict[str, Any] = {}
    for node in svc.import_nodes(settings, graph, only):
        params = node.get("params") or {}
        sid = params.get("snapshot_id")
        snap = db.get(DatasetSnapshot, int(str(sid))) if str(sid or "").isdigit() else None
        ds = db.get(Dataset, snap.dataset_id) if snap else None
        if snap is None or ds is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                {"node": node["id"],
                                 "message": "Набор данных: не выбрана версия набора"})
        if not _can_see_files(ds, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                {"node": node["id"],
                                 "message": f"{ds.code} под NDA — только для допущенных"})
        if not snap.storage_path:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                {"node": node["id"], "message": f"У версии {ds.code} нет файла"})
        sheet = str(params.get("sheet") or "")
        inputs[node["id"]] = {"dataset": ds.code, "snapshot_id": snap.id, "version": snap.version,
                              "sha256": snap.sha256, "sheet": sheet}
        job_inputs[node["id"]] = {"path": snap.storage_path, "sha256": snap.sha256, "sheet": sheet}
    run = StudioRun(scenario_id=s.id, version=s.version, until=body.until, status="queued",
                    created_by=user.id, inputs=inputs, summary={}, views={}, files=[])
    db.add(run)
    db.flush()
    job = {"studio_run_id": run.id, "scenario": s.code, "version": s.version, "graph": graph,
           "inputs": job_inputs, "until": body.until, "limit_min": svc.LIMIT_MIN,
           "rows": svc.PREVIEW_ROWS if body.until else svc.RUN_ROWS}
    try:
        run_queue.enqueue_studio(settings.redis_url, run.id, job)
    except Exception as exc:  # noqa: BLE001 — очередь недоступна: расчёта нет
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"Очередь расчётов недоступна: {type(exc).__name__}") from exc
    db.commit()
    return _run_out(run)


def _get_run(db: Session, run_id: int) -> StudioRun:
    r = db.get(StudioRun, run_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет расчёта сценария № {run_id}")
    return r


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Annotated[Session, Depends(get_db)],
            user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    r = _get_run(db, run_id)
    hide = _hidden(db, r, user)
    out = _run_out(r, hide)
    out["views"] = {} if hide else r.views
    return out


@router.post("/runs/{run_id}/stop", dependencies=[Researcher])
def stop_run(run_id: int, db: Annotated[Session, Depends(get_db)],
             settings: Annotated[Settings, Depends(get_settings)],
             user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    r = _get_run(db, run_id)
    if r.created_by != user.id and user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Остановить может тот, кто запустил")
    if r.status not in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Расчёт уже {r.status}")
    key = f"studio-{r.id}"
    try:
        run_queue.request_stop(settings.redis_url, r.id, prefix="studio")
        if r.status == "queued":
            run_queue.revoke(settings.redis_url, key)
    except Exception:  # noqa: BLE001 — нет Redis: расчёт всё равно снимается
        pass
    if r.status == "queued" or not run_queue.is_alive(settings.redis_url, r.id, prefix="studio"):
        r.status, r.finished_at = "stopped", datetime.now(UTC)
        r.message = f"Остановлен: {user.login}"
    db.commit()
    return _run_out(r)


@router.get("/runs/{run_id}/files/{name}")
def run_file(run_id: int, name: str, db: Annotated[Session, Depends(get_db)],
             settings: Annotated[Settings, Depends(get_settings)],
             user: Annotated[User, Depends(current_user)]) -> FileResponse:
    r = _get_run(db, run_id)
    if _hidden(db, r, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Результаты по набору под NDA — только для допущенных")
    if name not in (r.files or []) or not r.results_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет файла {name}")
    folder = to_container(settings, r.results_path)
    path = folder / "files" / name if folder else None
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Файл ещё не доехал с компьютера лаборатории — попробуйте через минуту")
    return FileResponse(path, filename=name)


# --- исполнитель ---

def _runner(settings: Annotated[Settings, Depends(get_settings)],
            x_runner_token: Annotated[str, Header()] = "") -> None:
    if not settings.runner_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "RUNNER_TOKEN не задан")
    if not secrets.compare_digest(x_runner_token, settings.runner_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный токен исполнителя")


@router.post("/worker/orphans", dependencies=[Depends(_runner)])
def orphans(db: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    """Исполнитель Студии перезапустился: его идущие расчёты прервались."""
    runs = list(db.scalars(select(StudioRun).where(StudioRun.status == "running")))
    for r in runs:
        r.status, r.finished_at = "failed", datetime.now(UTC)
        r.message = "Исполнитель перезапустился во время расчёта — запустите заново"
    db.commit()
    return {"failed": len(runs)}


@router.post("/worker/{run_id}", dependencies=[Depends(_runner)])
def worker_report(run_id: int, body: WorkerStudio,
                  db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    r = _get_run(db, run_id)
    if r.status not in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Расчёт № {run_id} уже {r.status}")
    now = datetime.now(UTC)
    if body.status == "running":
        r.status, r.started_at = "running", now
    else:
        r.status, r.finished_at, r.message = body.status, now, body.message[:4000]
        r.summary, r.views, r.files = body.summary, body.views, body.files
        r.results_path = body.results_path[:1024]
        r.runner_commit, r.env_lock_sha256 = body.runner_commit[:64], body.env_lock_sha256[:64]
        r.python = body.python[:32]
    db.commit()
    return {"id": r.id, "status": r.status}
