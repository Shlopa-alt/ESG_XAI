"""Реестр запусков. Запуск ставится из формы (шаблон из app/services/run_templates.py) в
очередь исполнителя или регистрируется готовым run.json из runner/. Удачный запуск с чистым
коммитом заполняет воспроизводимость эксперимента (правило 3)."""

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Dataset, DatasetSnapshot, Experiment, Run, User
from app.services import run_queue
from app.services.report import Report, merge_run_report
from app.services.data_files import table_columns, to_container
from app.services.run_templates import TEMPLATES, ParamError, check_params, script_args

router = APIRouter(tags=["runs"])

Researcher = Depends(require_role("researcher"))


class RunDataset(BaseModel):
    code: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: str = ""
    raw_manifest_sha256: str = ""
    row_count: int | None = None


class RunPart(BaseModel):
    args: list[str] = []
    exit_code: int
    seconds: int = 0


class RunImport(BaseModel):
    """Содержимое run.json (runner/*/run_exp*.py) и итоговые метрики."""

    runner_commit: str = Field(min_length=7)
    dataset: RunDataset
    env_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    python: str = ""
    seeds: dict[str, Any] = {}
    parts: dict[str, RunPart]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: dict[str, Any] = {}
    results_path: str = ""
    report: Report | None = None  # графики и цифры, посчитанные самим расчётом


class RunOut(BaseModel):
    id: int
    experiment: str
    status: str
    resource: str
    template: str
    config: dict[str, Any]
    runner_commit: str
    dataset: str
    dataset_sha256: str
    env_lock_sha256: str
    python: str
    seeds: dict[str, Any]
    parts: dict[str, Any]
    summary: dict[str, Any]
    results_path: str
    mlflow_run_id: str
    message: str
    author: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime | None
    reproducible: bool
    note: str


class TemplateOut(BaseModel):
    key: str
    title: str
    description: str
    scope: str  # generic — любой подходящий срез и эксперимент; replication — повтор своего эксперимента
    experiment: str
    dataset: str
    resource: str
    limit_min: int
    params: list[dict[str, Any]]
    snapshots: list[dict[str, Any]]


class LaunchIn(BaseModel):
    template: str
    snapshot_id: int
    params: dict[str, Any] = {}
    experiment: str = ""  # общему методу — обязательно: в реестр какого эксперимента запуск


class ColumnsOut(BaseModel):
    columns: list[str]
    numeric: list[str]


class WorkerReport(BaseModel):
    """Ход и итог запуска от исполнителя: running при старте, затем done/failed/stopped."""

    status: Literal["running", "done", "failed", "stopped"]
    message: str = ""
    mlflow_run_id: str = ""
    started_at: datetime | None = None
    run: RunImport | None = None  # run.json, если расчёт успел его записать


def _out(db: Session, run: Run) -> RunOut:
    exp = db.get(Experiment, run.experiment_id)
    snap = db.get(DatasetSnapshot, run.dataset_snapshot_id) if run.dataset_snapshot_id else None
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    user = db.get(User, run.created_by) if run.created_by else None
    reproducible, note = _reproducible(run)
    return RunOut(
        id=run.id, experiment=exp.code if exp else "", status=run.status, resource=run.resource,
        template=run.template, config=run.config or {}, runner_commit=run.runner_commit,
        dataset=ds.code if ds else "", dataset_sha256=snap.sha256 if snap else "",
        env_lock_sha256=run.env_lock_sha256, python=run.python, seeds=run.seeds or {},
        parts=run.parts or {}, summary=run.summary or {}, results_path=run.results_path,
        mlflow_run_id=run.mlflow_run_id, message=run.message, author=user.login if user else "",
        started_at=run.started_at, finished_at=run.finished_at, created_at=run.created_at,
        reproducible=reproducible, note=note,
    )


def _reproducible(run: Run) -> tuple[bool, str]:
    if run.status != "done":
        return False, "запуск не завершился успешно"
    if run.runner_commit.endswith("-dirty"):
        return False, "код runner был изменён и не закоммичен"
    if not (run.dataset_snapshot_id and run.env_lock_sha256 and run.seeds):
        return False, "не хватает среза данных, окружения или seed"
    return True, ""


def _seed(seeds: dict[str, Any]) -> int | None:
    for key in ("split", "seed"):
        value = seeds.get(key)
        if isinstance(value, int):
            return value
    # другие имена (bootstrap, permutation…) — первый целый seed
    return next((v for k, v in seeds.items() if not k.startswith("n_") and isinstance(v, int)), None)


def _get_run(db: Session, run_id: int) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет запуска №{run_id}")
    return run


def _apply(db: Session, run: Run, exp: Experiment, body: RunImport) -> None:
    """run.json → запуск; удачный с чистым коммитом заполняет воспроизводимость эксперимента."""
    ds = db.scalar(select(Dataset).where(Dataset.code == body.dataset.code))
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет датасета {body.dataset.code}")
    snap = db.scalar(select(DatasetSnapshot).where(
        DatasetSnapshot.dataset_id == ds.id, DatasetSnapshot.sha256 == body.dataset.sha256))
    if snap is None:
        version = (body.started_at or datetime.now()).strftime("%Y-%m-%d")
        snap = DatasetSnapshot(dataset_id=ds.id, version=version, sha256=body.dataset.sha256,
                               storage_path=body.dataset.path, row_count=body.dataset.row_count)
        db.add(snap)
        db.flush()
    ok = all(p.exit_code == 0 for p in body.parts.values())
    run.status = "done" if ok else "failed"
    run.runner_commit, run.dataset_snapshot_id = body.runner_commit, snap.id
    run.env_lock_sha256, run.python, run.seeds = body.env_lock_sha256, body.python, body.seeds
    run.parts = {k: v.model_dump() for k, v in body.parts.items()}
    run.summary, run.results_path = body.summary, body.results_path
    run.started_at = run.started_at or body.started_at
    run.finished_at = body.finished_at or datetime.now(UTC)
    db.flush()
    if _reproducible(run)[0]:
        # Воспроизводимость эксперимента — из последнего чистого удачного запуска
        exp.runner_commit = body.runner_commit
        exp.dataset_snapshot_id = snap.id
        exp.env_lock = f"requirements.lock sha256:{body.env_lock_sha256}; python {body.python}"
        exp.seed = _seed(body.seeds)
    if body.report is not None and run.status == "done":
        exp.report = merge_run_report(exp.report or {}, body.report)


@router.post("/experiments/{code}/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def import_run(
    code: str, body: RunImport, db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Researcher],
) -> RunOut:
    return _out(db, register_run(db, code, body, user.id))


def register_run(db: Session, code: str, body: RunImport, user_id: int | None) -> Run:
    """Готовый run.json (расчёт запускали на сервере вручную) — запуск у эксперимента."""
    exp = db.scalar(select(Experiment).where(Experiment.code == code))
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет эксперимента {code}")
    run = Run(experiment_id=exp.id, status="queued", resource="cpu", created_by=user_id)
    db.add(run)
    db.flush()
    _apply(db, run, exp, body)
    db.commit()
    return run


@router.get("/runs", response_model=list[RunOut], dependencies=[Depends(current_user)])
def list_runs(db: Annotated[Session, Depends(get_db)]) -> list[RunOut]:
    return [_out(db, r) for r in db.scalars(select(Run).order_by(Run.id.desc()))]


@router.get("/experiments/{code}/runs", response_model=list[RunOut],
            dependencies=[Depends(current_user)])
def experiment_runs(code: str, db: Annotated[Session, Depends(get_db)]) -> list[RunOut]:
    exp = db.scalar(select(Experiment).where(Experiment.code == code))
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет эксперимента {code}")
    runs = db.scalars(select(Run).where(Run.experiment_id == exp.id).order_by(Run.id.desc()))
    return [_out(db, r) for r in runs]


# --- запуск из формы ---


def snapshot_table(db: Session, settings: Settings, snap: DatasetSnapshot,
                   user: User | None) -> tuple[list[str], set[str]]:
    """Столбцы среза из его файла (NDA — только тем, кому видны файлы)."""
    ds = db.get(Dataset, snap.dataset_id)
    if ds is not None and ds.access_level == "nda" and (user is None or user.role != "owner"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Файлы датасета под NDA — только для допущенных")
    path = to_container(settings, snap.storage_path) if snap.storage_path else None
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Файл среза на сервере не найден")
    try:
        return table_columns(path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/run-templates", response_model=list[TemplateOut], dependencies=[Depends(current_user)])
def list_templates(db: Annotated[Session, Depends(get_db)]) -> list[TemplateOut]:
    """Библиотека методов: общие — со всеми срезами в CSV, повторы — со срезами своего датасета."""
    rows = db.execute(select(DatasetSnapshot, Dataset.code).join(Dataset)
                      .order_by(Dataset.code, DatasetSnapshot.id.desc())).all()
    out = []
    for t in TEMPLATES.values():
        snaps = [(s, code) for s, code in rows
                 if (code == t.dataset if t.scope == "replication"
                     else s.storage_path.lower().endswith((".csv", ".tsv", ".txt")))]
        out.append(TemplateOut(
            key=t.key, title=t.title, description=t.description, scope=t.scope, experiment=t.experiment,
            dataset=t.dataset, resource=t.resource, limit_min=t.limit_min,
            params=[{"name": p.name, "label": p.label, "default": p.default, "min": p.min, "max": p.max,
                     "kind": p.kind, "numeric": p.numeric, "required": p.required, "hint": p.hint}
                    for p in t.params],
            snapshots=[{"id": s.id, "dataset": code, "version": s.version, "sha256": s.sha256,
                        "row_count": s.row_count} for s, code in snaps],
        ))
    return out


@router.get("/snapshots/{snapshot_id}/columns", response_model=ColumnsOut)
def snapshot_columns(snapshot_id: int, db: Annotated[Session, Depends(get_db)],
                     settings: Annotated[Settings, Depends(get_settings)],
                     user: Annotated[User, Depends(current_user)]) -> ColumnsOut:
    snap = db.get(DatasetSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет среза №{snapshot_id}")
    columns, numeric = snapshot_table(db, settings, snap, user)
    return ColumnsOut(columns=columns, numeric=[c for c in columns if c in numeric])


def start_run(db: Session, settings: Settings, user: User, template: str, snapshot_id: int,
              params: dict[str, Any], experiment: str = "") -> Run:
    """Запуск метода библиотеки: метод, срез, эксперимент и параметры проверены — задача в очередь
    исполнителя. Общий метод — на любом срезе CSV и в указанном эксперименте; повтор — на срезе
    своего датасета и в своём эксперименте."""
    t = TEMPLATES.get(template)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет метода {template}")
    snap = db.get(DatasetSnapshot, snapshot_id)
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    if snap is None or ds is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Нет среза №{snapshot_id}")
    if t.scope == "replication" and ds.code != t.dataset:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Срез №{snapshot_id} — не срез датасета {t.dataset}")
    if not snap.storage_path:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "У среза не записан путь к файлу — запустить нельзя")
    code = t.experiment if t.scope == "replication" else experiment
    if not code:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Укажите эксперимент, в реестр которого идёт запуск")
    exp = db.scalar(select(Experiment).where(Experiment.code == code))
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет эксперимента {code}")
    columns: list[str] | None = None
    numeric: set[str] | None = None
    if any(p.kind != "int" for p in t.params):
        columns, numeric = snapshot_table(db, settings, snap, user)
    try:
        checked = check_params(t, params, columns, numeric)
    except ParamError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if t.resource == "gpu":
        busy = db.scalar(select(func.count()).select_from(Run).where(
            Run.created_by == user.id, Run.resource == "gpu", Run.status.in_(("queued", "running"))))
        if (busy or 0) >= settings.gpu_runs_per_user:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "На видеокарте уже идёт ваш запуск — дождитесь его или остановите")
    run = Run(experiment_id=exp.id, status="queued", resource=t.resource, template=t.key,
              config={"params": checked, "limit_min": t.limit_min}, seeds={},
              dataset_snapshot_id=snap.id, created_by=user.id)
    db.add(run)
    db.flush()
    job = {
        "run_id": run.id, "experiment": exp.code, "dataset": ds.code,
        "workdir": t.workdir, "script": t.script, "args": script_args(t, checked, exp.code, ds.code),
        "params": checked, "snapshot_path": snap.storage_path, "snapshot_sha256": snap.sha256,
        "dataset_dir_up": t.dataset_dir_up, "limit_min": t.limit_min, "template": t.key,
    }
    try:
        run.task_id = run_queue.enqueue(settings.redis_url, run.id, job, t.resource)
    except Exception as exc:  # noqa: BLE001 — брокер недоступен: запуска нет
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"Очередь запусков недоступна: {exc}") from exc
    return run


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def launch(
    body: LaunchIn,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Researcher],
) -> RunOut:
    """Запуск из формы: метод библиотеки, срез, параметры (у общего метода — и эксперимент)."""
    run = start_run(db, settings, user, body.template, body.snapshot_id, body.params, body.experiment)
    db.commit()
    return _out(db, run)


@router.get("/runs/{run_id}", response_model=RunOut, dependencies=[Depends(current_user)])
def get_run(run_id: int, db: Annotated[Session, Depends(get_db)]) -> RunOut:
    return _out(db, _get_run(db, run_id))


@router.get("/runs/{run_id}/stream", dependencies=[Depends(current_user)])
def stream(
    run_id: int, request: Request, db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    """Живой поток запуска (SSE): строки лога, ход частей, метрики, смена статуса."""
    run = _get_run(db, run_id)
    gen = run_queue.events(settings.redis_url, run.id, run.status,
                           lambda: run_queue.still_open(request))
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/runs/{run_id}/stop", response_model=RunOut)
def stop(
    run_id: int, db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)], user: Annotated[User, Researcher],
) -> RunOut:
    """Остановить может автор запуска или owner. В очереди — снимается сразу, идущий —
    останавливает исполнитель; что расчёт успел записать, остаётся в каталоге результатов."""
    run = _get_run(db, run_id)
    if run.created_by != user.id and user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Остановить может автор запуска или owner")
    if run.status not in ("queued", "running"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Запуск уже закончился")
    try:
        run_queue.request_stop(settings.redis_url, run.id)
        if run.status == "queued" and run.task_id:
            run_queue.revoke(settings.redis_url, run.task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"Очередь запусков недоступна: {exc}") from exc
    if run.status == "queued":
        run.status, run.finished_at = "stopped", datetime.now(UTC)
        run.message = f"Снят с очереди: {user.login}"
    else:
        run.message = f"Остановка запрошена: {user.login}"
    db.commit()
    return _out(db, run)


# --- исполнитель (runner/worker) ---


def _runner(settings: Annotated[Settings, Depends(get_settings)],
            x_runner_token: Annotated[str, Header()] = "") -> None:
    if not settings.runner_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "RUNNER_TOKEN не задан")
    if not secrets.compare_digest(x_runner_token, settings.runner_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Неверный токен исполнителя")


@router.post("/runs/worker/orphans", dependencies=[Depends(_runner)])
def orphans(queue: Literal["cpu", "gpu"], db: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    """При старте исполнителя: его прежние «идущие» запуски прервались вместе с ним."""
    runs = list(db.scalars(select(Run).where(Run.status == "running", Run.resource == queue)))
    for run in runs:
        run.status, run.finished_at = "failed", datetime.now(UTC)
        run.message = "Исполнитель перезапустился во время расчёта — запустите заново"
    db.commit()
    return {"failed": len(runs)}


@router.post("/runs/worker/{run_id}", response_model=RunOut, dependencies=[Depends(_runner)])
def worker_report(run_id: int, body: WorkerReport,
                  db: Annotated[Session, Depends(get_db)]) -> RunOut:
    run = _get_run(db, run_id)
    exp = db.get(Experiment, run.experiment_id)
    if run.status in run_queue.FINAL:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Запуск №{run_id} уже {run.status}")
    if body.mlflow_run_id:
        run.mlflow_run_id = body.mlflow_run_id
    if body.status == "running":
        run.status, run.started_at = "running", body.started_at or datetime.now(UTC)
    elif body.status == "done" and body.run is not None and exp is not None:
        _apply(db, run, exp, body.run)  # статус — по кодам выхода частей
        run.message = body.message
    else:
        # остановлен или упал: воспроизводимость эксперимента такой запуск не трогает
        run.status = "failed" if body.status == "done" else body.status
        run.finished_at = datetime.now(UTC)
        run.message = body.message or ("Расчёт не записал run.json" if body.status == "done" else "")
    db.commit()
    return _out(db, run)
