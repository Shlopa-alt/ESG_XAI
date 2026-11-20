"""Студия: сценарии SC-NN (граф узлов), их версии, расчёты и предпросмотр узла.

Смотреть сценарии может любой вошедший; создавать, менять и считать — researcher+, менять — автор
или владелец платформы (остальные делают копию). Расчёт ставится в очередь studio исполнителя;
результаты узлов из наборов под NDA видны только тем, кому видны файлы этих наборов (правило 6).
"""

import hashlib
import secrets
import time
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.datasets import _can_see_files
from app.api.deps import current_user, require_role
from app.config import Settings, get_settings
from app.db import get_db
from app.models import (
    Dataset,
    DatasetSnapshot,
    DbConnection,
    Scenario,
    ScenarioVersion,
    StudioRun,
    User,
)
from app.services import run_queue
from app.services import secrets as secrets_
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


class ApproveIn(BaseModel):
    node: str = Field(min_length=1, max_length=64)


class ConnectionIn(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    kind: Literal["postgresql", "mysql", "mssql", "clickhouse"]
    host: str = Field(min_length=1, max_length=256)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str = Field(default="", max_length=256)
    username: str = Field(default="", max_length=256)
    password: str | None = Field(default=None, max_length=1024)  # не прислали — прежний
    allow_write: bool = False


class PublishIn(BaseModel):
    version: int | None = None  # пусто — текущая


class ServiceIn(BaseModel):
    # порт «Входа подмодели» → строки
    inputs: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    wait: int = Field(default=30, ge=0, le=60)  # подождать итог, секунд


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
            "updated_at": s.updated_at, "published_version": s.published_version}


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
                 settings: Annotated[Settings, Depends(get_settings)],
                 user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    s = _get(db, code)
    runs = db.scalars(select(StudioRun).where(StudioRun.scenario_id == s.id, StudioRun.until == "")
                      .order_by(StudioRun.id.desc()).limit(10))
    return {**_brief(db, s), "graph": s.graph,
            "editable": s.author_id == user.id or user.role == "owner",
            "python": svc.python_state(settings, s.graph, s.approved_python or []),
            "runs": [_run_out(r, _hidden(db, r, user)) for r in runs]}


@router.post("/scenarios/{code}/approve-python")
def approve_python(code: str, body: ApproveIn, db: Annotated[Session, Depends(get_db)],
                   settings: Annotated[Settings, Depends(get_settings)],
                   user: Annotated[User, Depends(require_role("owner"))]) -> dict[str, Any]:
    """Владелец прочитал код узла «Python» и разрешает его считать (по sha256: код поменяли —
    одобрять снова)."""
    s = _get(db, code)
    node = next((n for n in s.graph.get("nodes") or [] if n.get("id") == body.node), None)
    if node is None or node.get("type") != svc.PYTHON:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет узла Python {body.node}")
    text = str((node.get("params") or {}).get("code") or "")
    chk = svc.pycheck(settings)
    problems = chk.check(text)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"node": body.node,
                             "message": "Код не прошёл проверку: " + "; ".join(problems[:3])})
    s.approved_python = sorted({*(s.approved_python or []), chk.sha256(text)})
    db.commit()
    return {"python": svc.python_state(settings, s.graph, s.approved_python)}


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
    return {**_brief(db, s), "graph": s.graph, "editable": True,
            "python": svc.python_state(settings, s.graph, s.approved_python or [])}


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
    return _run_out(_start(db, settings, user, s, s.graph, s.version, body.until))


def _start(db: Session, settings: Settings, user: User, s: Scenario, base: dict[str, Any],
           version: int, until: str, inject: dict[str, Any] | None = None) -> StudioRun:
    """Поставить расчёт: вложить подмодели, проверить код Python, входные наборы и подключения к
    базам, записать всё для повтора и отдать исполнителю. inject — данные вызова веб-сервиса."""
    _check(settings, base)

    def resolve(sub_code: str, version: int | None) -> tuple[dict[str, Any], int]:
        sub = db.scalar(select(Scenario).where(Scenario.code == sub_code))
        if sub is None:
            raise svc.GraphError("", f"Нет сценария {sub_code}")
        g, v = sub.graph, sub.version
        if version is not None:
            row = db.scalar(select(ScenarioVersion).where(ScenarioVersion.scenario_id == sub.id,
                                                          ScenarioVersion.version == version))
            if row is None:
                raise svc.GraphError("", f"У {sub_code} нет версии {version}")
            g, v = row.graph, version
        svc.check_graph(settings, g)
        return g, v

    try:
        graph, all_nodes = svc.expand(base, resolve)
    except svc.GraphError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"node": exc.node, "message": str(exc)}) from exc
    ids = {n["id"] for n in graph.get("nodes") or []}
    if not ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "В сценарии нет узлов")
    if until and until not in ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Нет узла {until}")
    top = svc.needed(graph, until, settings) if until else None
    # вложенные узлы нужны, если нужен их узел-подмодель верхнего уровня
    used = [e for e in all_nodes if top is None or e["id"].split("/", 1)[0] in top]
    busy = db.scalar(select(StudioRun).where(StudioRun.created_by == user.id,
                                             StudioRun.status.in_(ACTIVE), StudioRun.until == "")
                     .limit(1))
    if busy is not None and not until and inject is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Уже идёт ваш расчёт сценария (№ {busy.id}) — "
                            "дождитесь его или остановите")
    inputs: dict[str, Any] = {}
    job_inputs: dict[str, Any] = {}
    comps = svc.components(settings)
    chk = svc.pycheck(settings)
    approved: dict[str, list[str]] = {}
    for e in used:
        node = e["node"]
        if node.get("type") == svc.PYTHON:
            text = str((node.get("params") or {}).get("code") or "")
            problems = chk.check(text)
            if problems:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    {"node": e["id"],
                                     "message": "Python: " + "; ".join(problems[:3])})
            owner_code = e["chain"][-1] if e["chain"] else s.code
            if owner_code not in approved:
                holder = s if owner_code == s.code else db.scalar(
                    select(Scenario).where(Scenario.code == owner_code))
                approved[owner_code] = (holder.approved_python if holder else None) or []
            if chk.sha256(text) not in approved[owner_code] and user.role != "owner":
                raise HTTPException(status.HTTP_403_FORBIDDEN,
                                    {"node": e["id"],
                                     "message": f"Код узла Python в {owner_code} не одобрен "
                                                "владельцем платформы — попросите его одобрить"})
        if node.get("type") in svc.NESTED:
            p = node.get("params") or {}
            inputs[f"{e['id']}#подмодель"] = {"scenario": str(p.get("scenario") or "").upper(),
                                              "version": p.get("__version__")}
    connections: set[str] = set()
    for e in used:  # базы данных: подключение есть; запись — только если владелец разрешил
        node = e["node"]
        if node.get("type") not in svc.DB_NODES:
            continue
        p = node.get("params") or {}
        conn_code = str(p.get("connection") or "").upper()
        conn = (db.scalar(select(DbConnection).where(DbConnection.code == conn_code))
                if conn_code else None)
        if conn is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                {"node": e["id"], "message": "База данных: не выбрано подключение"})
        if node["type"] == "export.database" and not conn.allow_write:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                {"node": e["id"],
                                 "message": f"В {conn.code} запись не разрешена владельцем"})
        connections.add(conn.code)
        if node["type"] == "import.database":
            q = str(p.get("query") or "")
            inputs[e["id"]] = {"connection": conn.code,
                               "query_sha256": hashlib.sha256(q.encode()).hexdigest()}
    for e in [x for x in used if comps.get(x["node"].get("type"), {}).get("loads")
              and x["node"].get("type") == "import.dataset"]:
        node = {**e["node"], "id": e["id"]}
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
    if connections:
        inputs["__connections__"] = {"codes": sorted(connections)}
    if inject is not None:
        inputs["__service__"] = {"version": version}
    run = StudioRun(scenario_id=s.id, version=version, until=until, status="queued",
                    created_by=user.id, inputs=inputs, summary={}, views={}, files=[])
    db.add(run)
    db.flush()
    job = {"studio_run_id": run.id, "scenario": s.code, "version": version, "graph": graph,
           "inputs": job_inputs, "until": until, "limit_min": svc.LIMIT_MIN,
           "rows": svc.PREVIEW_ROWS if until else svc.RUN_ROWS,
           "connections": sorted(connections)}
    if inject is not None:
        job.update(inject=inject, output=True)
    try:
        run_queue.enqueue_studio(settings.redis_url, run.id, job)
    except Exception as exc:  # noqa: BLE001 — очередь недоступна: расчёта нет
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"Очередь расчётов недоступна: {type(exc).__name__}") from exc
    db.commit()
    return run


# --- подключения к базам данных ---

def _conn_out(c: DbConnection) -> dict[str, Any]:
    return {"code": c.code, "title": c.title, "kind": c.kind, "host": c.host, "port": c.port,
            "database": c.database, "username": c.username, "has_password": bool(c.password_enc),
            "allow_write": c.allow_write}


@router.get("/connections")
def list_connections(db: Annotated[Session, Depends(get_db)],
                     _: Annotated[User, Depends(current_user)]) -> list[dict[str, Any]]:
    """Подключения — без паролей: их видит только исполнитель во время расчёта."""
    return [_conn_out(c) for c in db.scalars(select(DbConnection).order_by(DbConnection.code))]


@router.post("/connections", status_code=status.HTTP_201_CREATED)
def create_connection(body: ConnectionIn, db: Annotated[Session, Depends(get_db)],
                      settings: Annotated[Settings, Depends(get_settings)],
                      user: Annotated[User, Depends(require_role("owner"))]) -> dict[str, Any]:
    c = DbConnection(code=next_code(db, DbConnection.code, "DB", 2), title=body.title.strip(),
                     kind=body.kind, host=body.host.strip(), port=body.port,
                     database=body.database.strip(), username=body.username.strip(),
                     password_enc=secrets_.encrypt(settings, body.password or ""),
                     allow_write=body.allow_write, created_by=user.id, updated_at=datetime.now(UTC))
    db.add(c)
    db.commit()
    return _conn_out(c)


def _get_conn(db: Session, code: str) -> DbConnection:
    c = db.scalar(select(DbConnection).where(DbConnection.code == code.upper()))
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет подключения {code}")
    return c


@router.put("/connections/{code}")
def update_connection(code: str, body: ConnectionIn, db: Annotated[Session, Depends(get_db)],
                      settings: Annotated[Settings, Depends(get_settings)],
                      _: Annotated[User, Depends(require_role("owner"))]) -> dict[str, Any]:
    c = _get_conn(db, code)
    c.title, c.kind, c.host, c.port = body.title.strip(), body.kind, body.host.strip(), body.port
    c.database, c.username = body.database.strip(), body.username.strip()
    c.allow_write = body.allow_write
    if body.password is not None:
        c.password_enc = secrets_.encrypt(settings, body.password)
    c.updated_at = datetime.now(UTC)
    db.commit()
    return _conn_out(c)


@router.delete("/connections/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(code: str, db: Annotated[Session, Depends(get_db)],
                      _: Annotated[User, Depends(require_role("owner"))]) -> Response:
    db.delete(_get_conn(db, code))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- публикация сценария как веб-сервиса ---

@router.post("/scenarios/{code}/publish", dependencies=[Researcher])
def publish(code: str, body: PublishIn, db: Annotated[Session, Depends(get_db)],
            settings: Annotated[Settings, Depends(get_settings)],
            user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    """Версия сценария — веб-сервис: данные вызова идут во «Входы подмодели», ответ — «Выход»."""
    s = _get(db, code)
    _may_edit(s, user)
    version = body.version or s.version
    graph = _version_graph(db, s, version)
    _check(settings, graph)
    outs = [n for n in graph.get("nodes") or [] if n.get("type") == "control.output"]
    if len(outs) != 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Для веб-сервиса нужен ровно один узел «Выход подмодели» — "
                            "его таблица и будет ответом")
    s.published_version, s.published_at, s.published_by = version, datetime.now(UTC), user.id
    db.commit()
    return _brief(db, s)


@router.delete("/scenarios/{code}/publish", dependencies=[Researcher])
def unpublish(code: str, db: Annotated[Session, Depends(get_db)],
              user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    s = _get(db, code)
    _may_edit(s, user)
    s.published_version = s.published_at = s.published_by = None
    db.commit()
    return _brief(db, s)


def _version_graph(db: Session, s: Scenario, version: int) -> dict[str, Any]:
    if version == s.version:
        return s.graph
    row = db.scalar(select(ScenarioVersion).where(ScenarioVersion.scenario_id == s.id,
                                                  ScenarioVersion.version == version))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"У {s.code} нет версии {version}")
    return row.graph


def _service_out(db: Session, r: StudioRun, user: User) -> dict[str, Any]:
    hide = _hidden(db, r, user)
    out = {"run_id": r.id, "status": r.status, "message": r.message, "version": r.version,
           "output": None if hide else (r.views or {}).get("__output__")}
    if r.status == "done" and not hide and out["output"] is None:
        out["message"] = out["message"] or ("Узел «Выход подмодели» не посчитан — ошибки узлов: "
                                            f"GET /api/v1/studio/runs/{r.id}")
    return out


SERVICE_ACTIVE = 3
SERVICE_INPUT_MB = 5


@router.post("/services/{code}/run", status_code=status.HTTP_200_OK, dependencies=[Researcher])
def call_service(code: str, body: ServiceIn, request: Request,
                 db: Annotated[Session, Depends(get_db)],
                 settings: Annotated[Settings, Depends(get_settings)],
                 user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    """Вызов опубликованного сценария: строки — во «Входы подмодели» по портам, ответ — таблица
    «Выхода подмодели». Ждёт итог до wait секунд, иначе отдаёт run_id: GET /services/runs/{id}."""
    s = _get(db, code)
    if s.published_version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{s.code} не опубликован как веб-сервис")
    size = int(request.headers.get("content-length") or 0)
    if size > SERVICE_INPUT_MB * 2**20:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Данных больше {SERVICE_INPUT_MB} МБ")
    if set(body.inputs) - {"in", "in2"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Входы веб-сервиса — in и in2")
    active = [r for r in db.scalars(select(StudioRun).where(StudioRun.created_by == user.id,
                                                            StudioRun.status.in_(ACTIVE)))
              if "__service__" in (r.inputs or {})]
    if len(active) >= SERVICE_ACTIVE:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Уже идут ваши вызовы веб-сервисов: {len(active)} — дождитесь их")
    graph = _version_graph(db, s, s.published_version)
    run = _start(db, settings, user, s, graph, s.published_version, "", inject=body.inputs)
    deadline = time.monotonic() + body.wait
    while time.monotonic() < deadline:
        db.expire(run)
        if run.status not in ACTIVE:
            break
        time.sleep(0.5)
    return _service_out(db, run, user)


@router.get("/services/runs/{run_id}")
def service_run(run_id: int, db: Annotated[Session, Depends(get_db)],
                user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    r = _get_run(db, run_id)
    if "__service__" not in (r.inputs or {}):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"№ {run_id} — не вызов веб-сервиса")
    if r.created_by != user.id and user.role != "owner":
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет вызова № {run_id}")
    return _service_out(db, r, user)


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


@router.get("/worker/{run_id}/connections", dependencies=[Depends(_runner)])
def worker_connections(run_id: int, db: Annotated[Session, Depends(get_db)],
                       settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    """Реквизиты подключений — исполнителю, только пока этот расчёт идёт, только его подключения."""
    r = _get_run(db, run_id)
    if r.status not in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Расчёт № {run_id} уже {r.status}")
    out: dict[str, Any] = {}
    for code in (r.inputs or {}).get("__connections__", {}).get("codes", []):
        c = db.scalar(select(DbConnection).where(DbConnection.code == code))
        if c is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Подключение {code} удалено")
        try:
            password = secrets_.decrypt(settings, c.password_enc)
        except secrets_.SecretError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{code}: {exc}") from exc
        out[code] = {"kind": c.kind, "host": c.host, "port": c.port, "database": c.database,
                     "username": c.username, "password": password, "allow_write": c.allow_write}
    return out


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
