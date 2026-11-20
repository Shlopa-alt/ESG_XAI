"""Студия: сценарии анализа данных из узлов (замена Loginom) и их расчёты.

Сценарий SC-NN — граф узлов (формат runner/studio/engine.py). Код неизменяем (правило 1); каждое
сохранение — новая версия, старые хранятся: расчёт ссылается на версию, по которой считал.

Расчёт сценария считает исполнитель на ПК лаборатории (очередь studio). Предпросмотр — расчёт с
until: только узел и то, от чего он зависит. В расчёте записано всё для повтора (правило 3):
версия сценария, sha256 каждого входного файла, коммит runner и хеш окружения.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

STUDIO_RUN_STATUSES = ("queued", "running", "done", "failed", "stopped")


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    graph: Mapped[dict[str, Any]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # sha256 кода узлов «Python», которые одобрил владелец платформы (код поменяли — снова одобрять)
    approved_python: Mapped[list[str]] = mapped_column(JSON, default=list)


class ScenarioVersion(Base):
    __tablename__ = "scenario_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict[str, Any]] = mapped_column(JSON)
    saved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StudioRun(Base):
    __tablename__ = "studio_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    until: Mapped[str] = mapped_column(String(64), default="")  # предпросмотр узла; пусто — весь
    status: Mapped[str] = mapped_column(String(16), default="queued")
    message: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # узел → версия набора и sha256; узел → посчитан ли, ошибка, строк; «Таблица» и «Статистика»
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    views: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    files: Mapped[list[str]] = mapped_column(JSON, default=list)
    results_path: Mapped[str] = mapped_column(String(1024), default="")
    runner_commit: Mapped[str] = mapped_column(String(64), default="")
    env_lock_sha256: Mapped[str] = mapped_column(String(64), default="")
    python: Mapped[str] = mapped_column(String(32), default="")
