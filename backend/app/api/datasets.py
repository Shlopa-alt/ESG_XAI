"""Датасеты и их срезы.

Срез — неизменяемый файл данных с sha256: по нему запуск сверяет, что считает на тех же
данных (правило 3). Файлы лежат в папке данных сервера (ESG_DATA_HOST, в контейнере —
ESG_DATA_DIR) в каталоге кода датасета: <папка данных>/DS-05/… Срез можно загрузить с сайта
(<папка>/<код>/snapshots/<версия>/<файл>) или зарегистрировать файл, который уже лежит в
каталоге датасета на сервере. В платформе путь среза хранится путём хоста — так его находит
исполнитель запусков.

NDA (правило 6): описание и срезы (версия, sha256) видны всем, а файлы и пути к ним — только
роли с допуском (owner).
"""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, require_role
from app.config import Settings, get_settings
from app.db import get_db
from app.models import Dataset, DatasetSnapshot, Experiment, Run, User
from app.services.codes import next_code
from app.services.qwen_queue import enqueue

router = APIRouter(prefix="/datasets", tags=["datasets"])

Researcher = Depends(require_role("researcher"))
TABLES = (".csv", ".tsv", ".txt")


class DatasetIn(BaseModel):
    title: str = Field(min_length=3, max_length=512)
    description: str = ""
    source_url: str = Field(default="", max_length=1024)
    license: str = Field(default="", max_length=256)
    access_level: Literal["public", "nda"] = "public"


class DatasetPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=512)
    description: str | None = None
    source_url: str | None = Field(default=None, max_length=1024)
    license: str | None = Field(default=None, max_length=256)
    access_level: Literal["public", "nda"] | None = None


class SnapshotOut(BaseModel):
    id: int
    version: str
    sha256: str
    row_count: int | None
    storage_path: str  # пусто, если у зрителя нет допуска к файлам NDA
    created_at: datetime
    runs: int


class DatasetDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    title: str
    description: str
    source_url: str
    license: str
    access_level: str
    created_at: datetime
    can_see_files: bool
    snapshots: list[SnapshotOut]
    experiments: list[str]


class RegisterIn(BaseModel):
    path: str = Field(min_length=1, max_length=1024)  # от каталога датасета
    version: str = Field(default="", max_length=64)


class FileOut(BaseModel):
    path: str
    bytes: int
    modified: datetime
    snapshot: str  # версия среза, если файл уже зарегистрирован


def _get(db: Session, code: str) -> Dataset:
    ds = db.scalar(select(Dataset).where(Dataset.code == code))
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Нет датасета {code}")
    return ds


def _can_see_files(ds: Dataset, user: User) -> bool:
    return ds.access_level != "nda" or user.role == "owner"


def _files_guard(ds: Dataset, user: User) -> None:
    if not _can_see_files(ds, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Файлы датасета под NDA — только для допущенных")


def _root(settings: Settings, ds: Dataset) -> Path:
    return Path(settings.esg_data_dir) / ds.code


def _host_path(settings: Settings, path: Path) -> str:
    """Путь в контейнере → путь хоста (так его хранят срезы и ищет исполнитель)."""
    rel = path.relative_to(settings.esg_data_dir).as_posix()
    host = settings.esg_data_host.replace("\\", "/").rstrip("/")
    if not host:
        return path.as_posix()
    if re.match(r"^[A-Za-z]:", host):
        return (host + "/" + rel).replace("/", "\\")
    return host + "/" + rel


def _sha_and_rows(path: Path) -> tuple[str, int | None]:
    h = hashlib.sha256()
    lines = 0
    last = b"\n"
    with path.open("rb") as f:
        for block in iter(lambda: f.read(2**20), b""):
            h.update(block)
            lines += block.count(b"\n")
            last = block[-1:]
    if path.suffix.lower() not in TABLES:
        return h.hexdigest(), None
    lines += 0 if last == b"\n" else 1  # последняя строка без перевода
    return h.hexdigest(), max(lines - 1, 0)  # без заголовка


def _version(db: Session, ds: Dataset, wanted: str) -> str:
    base = wanted.strip() or datetime.now(UTC).strftime("%Y-%m-%d")
    if not re.fullmatch(r"[\w.-]{1,64}", base):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Версия — буквы, цифры, точка, дефис, например 2026-10-30")
    taken = set(db.scalars(select(DatasetSnapshot.version).where(DatasetSnapshot.dataset_id == ds.id)))
    version, n = base, 2
    while version in taken:
        version, n = f"{base}-{n}", n + 1
    return version


def _add_snapshot(db: Session, settings: Settings, ds: Dataset, path: Path, version: str) -> DatasetSnapshot:
    sha, rows = _sha_and_rows(path)
    same = db.scalar(select(DatasetSnapshot).where(DatasetSnapshot.dataset_id == ds.id,
                                                   DatasetSnapshot.sha256 == sha))
    if same is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Такой срез уже есть: версия {same.version} (sha256 совпадает)")
    snap = DatasetSnapshot(dataset_id=ds.id, version=version, sha256=sha,
                           storage_path=_host_path(settings, path), row_count=rows)
    db.add(snap)
    # новые данные — Qwen посмотрит, какие гипотезы теперь можно проверить
    enqueue(db, "hypotheses", {}, trigger="snapshot")
    db.commit()
    return snap


def _detail(db: Session, ds: Dataset, user: User) -> DatasetDetail:
    see = _can_see_files(ds, user)
    snaps = list(db.scalars(select(DatasetSnapshot).where(DatasetSnapshot.dataset_id == ds.id)
                            .order_by(DatasetSnapshot.id.desc())))
    out = []
    for s in snaps:
        runs = len(list(db.scalars(select(Run.id).where(Run.dataset_snapshot_id == s.id))))
        out.append(SnapshotOut(id=s.id, version=s.version, sha256=s.sha256, row_count=s.row_count,
                               storage_path=s.storage_path if see else "", created_at=s.created_at,
                               runs=runs))
    ids = [s.id for s in snaps]
    exps = sorted(set(db.scalars(select(Experiment.code).where(
        Experiment.dataset_snapshot_id.in_(ids))))) if ids else []
    return DatasetDetail(code=ds.code, title=ds.title, description=ds.description,
                         source_url=ds.source_url, license=ds.license, access_level=ds.access_level,
                         created_at=ds.created_at, can_see_files=see, snapshots=out, experiments=exps)


@router.get("/{code}", response_model=DatasetDetail)
def get_dataset(code: str, db: Annotated[Session, Depends(get_db)],
                user: Annotated[User, Depends(current_user)]) -> DatasetDetail:
    return _detail(db, _get(db, code), user)


@router.post("", response_model=DatasetDetail, status_code=status.HTTP_201_CREATED)
def create_dataset(body: DatasetIn, db: Annotated[Session, Depends(get_db)],
                   user: Annotated[User, Researcher]) -> DatasetDetail:
    """Код — следующий DS-NN, неизменяем (правило 1)."""
    ds = Dataset(code=next_code(db, Dataset.code, "DS", 2), **body.model_dump())
    db.add(ds)
    db.commit()
    return _detail(db, ds, user)


@router.patch("/{code}", response_model=DatasetDetail)
def patch_dataset(code: str, body: DatasetPatch, db: Annotated[Session, Depends(get_db)],
                  user: Annotated[User, Researcher]) -> DatasetDetail:
    ds = _get(db, code)
    data = body.model_dump(exclude_unset=True)
    if "access_level" in data and data["access_level"] != ds.access_level and user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Уровень доступа меняет owner")
    for key, value in data.items():
        setattr(ds, key, value)
    db.commit()
    return _detail(db, ds, user)


@router.get("/{code}/files", response_model=list[FileOut])
def list_files(code: str, db: Annotated[Session, Depends(get_db)],
               settings: Annotated[Settings, Depends(get_settings)],
               user: Annotated[User, Researcher]) -> list[FileOut]:
    """Файлы в каталоге датасета на сервере — что можно зарегистрировать срезом."""
    ds = _get(db, code)
    _files_guard(ds, user)
    root = _root(settings, ds)
    if not root.is_dir():
        return []
    known = {s.storage_path: s.version for s in db.scalars(
        select(DatasetSnapshot).where(DatasetSnapshot.dataset_id == ds.id))}
    out = []
    for f in sorted(root.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            st = f.stat()
            out.append(FileOut(path=f.relative_to(root).as_posix(), bytes=st.st_size,
                               modified=datetime.fromtimestamp(st.st_mtime, UTC),
                               snapshot=known.get(_host_path(settings, f), "")))
        if len(out) >= 500:
            break
    return out


@router.post("/{code}/snapshots/register", response_model=DatasetDetail,
             status_code=status.HTTP_201_CREATED)
def register_snapshot(code: str, body: RegisterIn, db: Annotated[Session, Depends(get_db)],
                      settings: Annotated[Settings, Depends(get_settings)],
                      user: Annotated[User, Researcher]) -> DatasetDetail:
    """Файл, уже лежащий в каталоге датасета на сервере, — срезом (sha256 считает сервер)."""
    ds = _get(db, code)
    _files_guard(ds, user)
    root = _root(settings, ds).resolve()
    path = (root / body.path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Нет такого файла в каталоге {ds.code}: {body.path}")
    _add_snapshot(db, settings, ds, path, _version(db, ds, body.version))
    return _detail(db, ds, user)


@router.post("/{code}/snapshots", response_model=DatasetDetail, status_code=status.HTTP_201_CREATED)
def upload_snapshot(
    code: str,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User, Researcher],
    file: Annotated[UploadFile, File()],
    version: Annotated[str, Form()] = "",
) -> DatasetDetail:
    """Файл с сайта — в <папка данных>/<код>/snapshots/<версия>/ и срезом."""
    ds = _get(db, code)
    _files_guard(ds, user)
    limit = settings.dataset_upload_max_mb * 2**20
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Файл больше {settings.dataset_upload_max_mb} МБ — положите его в каталог "
                            f"{ds.code} на сервере и зарегистрируйте")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Пустой файл")
    sha = hashlib.sha256(data).hexdigest()
    same = db.scalar(select(DatasetSnapshot).where(DatasetSnapshot.dataset_id == ds.id,
                                                   DatasetSnapshot.sha256 == sha))
    if same is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Такой срез уже есть: версия {same.version} (sha256 совпадает)")
    ver = _version(db, ds, version)
    name = re.sub(r"[^\w.-]+", "_", Path(file.filename or "data").name).strip("_.") or "data"
    target = _root(settings, ds) / "snapshots" / ver / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    _add_snapshot(db, settings, ds, target, ver)
    return _detail(db, ds, user)
