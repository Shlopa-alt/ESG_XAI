"""Реестр запусков. Результат расчёта (run.json из runner/) регистрируется у эксперимента;
удачный запуск с чистым коммитом заполняет воспроизводимость эксперимента (правило 3)."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.db import get_db
from app.models import Dataset, DatasetSnapshot, Experiment, Run, User

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
    """Содержимое run.json (runner/hsu2025/run_exp007.py) и итоговые метрики."""

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


class RunOut(BaseModel):
    id: int
    experiment: str
    status: str
    runner_commit: str
    dataset: str
    dataset_sha256: str
    env_lock_sha256: str
    python: str
    seeds: dict[str, Any]
    parts: dict[str, Any]
    summary: dict[str, Any]
    results_path: str
    started_at: datetime | None
    finished_at: datetime | None
    reproducible: bool
    note: str


def _out(db: Session, run: Run) -> RunOut:
    exp = db.get(Experiment, run.experiment_id)
    snap = db.get(DatasetSnapshot, run.dataset_snapshot_id) if run.dataset_snapshot_id else None
    ds = db.get(Dataset, snap.dataset_id) if snap else None
    reproducible, note = _reproducible(run)
    return RunOut(
        id=run.id, experiment=exp.code if exp else "", status=run.status,
        runner_commit=run.runner_commit, dataset=ds.code if ds else "",
        dataset_sha256=snap.sha256 if snap else "", env_lock_sha256=run.env_lock_sha256,
        python=run.python, seeds=run.seeds, parts=run.parts, summary=run.summary,
        results_path=run.results_path, started_at=run.started_at, finished_at=run.finished_at,
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
    return None


@router.post("/experiments/{code}/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
def import_run(
    code: str, body: RunImport, db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Researcher],
) -> RunOut:
    exp = db.scalar(select(Experiment).where(Experiment.code == code))
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет эксперимента {code}")
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
    run = Run(
        experiment_id=exp.id, status="done" if ok else "failed", resource="cpu",
        runner_commit=body.runner_commit, dataset_snapshot_id=snap.id,
        env_lock_sha256=body.env_lock_sha256, python=body.python, seeds=body.seeds,
        parts={k: v.model_dump() for k, v in body.parts.items()}, summary=body.summary,
        results_path=body.results_path, started_at=body.started_at,
        finished_at=body.finished_at, created_by=user.id,
    )
    db.add(run)
    db.flush()
    if _reproducible(run)[0]:
        # Воспроизводимость эксперимента — из последнего чистого удачного запуска
        exp.runner_commit = body.runner_commit
        exp.dataset_snapshot_id = snap.id
        exp.env_lock = f"requirements.lock sha256:{body.env_lock_sha256}; python {body.python}"
        exp.seed = _seed(body.seeds)
    db.commit()
    return _out(db, run)


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
