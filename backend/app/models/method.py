"""Метод библиотеки из статьи банка: код модели написал Qwen по тексту статьи.

Метод — только модель (make_model с fit/predict); протокол CR-01, деление по группам, плацебо и
run.json — общие (runner/methods/protocol.py), поэтому метод из статьи считается по тем же
правилам, что методы лаборатории. Путь метода:

  ready    — код прошёл проверку платформы (разрешённые библиотеки, без файлов, сети и системных
             вызовов) и пробный запуск без сети на синтетических данных; ждёт администратора;
  failed   — проверку или пробный запуск не прошёл (журнал — в check_log); не запускается;
  enabled  — администратор прочитал код и включил: метод в библиотеке, его можно запускать;
  rejected — администратор отклонил (причина — в decision_note).

Код неизменяем: правка — новый метод с новым кодом M-NN (правило 1). sha256 кода записывается в
каждый расчёт, сам код — рядом с результатами (правило 3).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

METHOD_STATUSES = ("ready", "failed", "enabled", "rejected")


class Method(Base):
    __tablename__ = "methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # M-01
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    net: Mapped[str] = mapped_column(String(32), default="")  # сеть каталога: lstm, cnn, mlp…
    task: Mapped[str] = mapped_column(String(32), default="predict")
    # гиперпараметры метода: [{name, label, default, min, max, hint}] — целые числа
    params: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    script: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="ready")
    check_log: Mapped[str] = mapped_column(Text, default="")
    # пробный запуск: секунд на одно обучение модели и сколько строк было — для цены расчёта
    fit_s: Mapped[float] = mapped_column(Float, default=0.0)
    fit_rows: Mapped[int] = mapped_column(Integer, default=0)
    limit_min: Mapped[int] = mapped_column(Integer, default=120)
    # статья-источник в банке (KBRAG): метод описан в ней, цитата — что именно авторы сделали
    doc_id: Mapped[str] = mapped_column(String(512), default="", index=True)
    article_title: Mapped[str] = mapped_column(String(1024), default="")
    doi: Mapped[str] = mapped_column(String(256), default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    qwen_job_id: Mapped[int | None] = mapped_column(ForeignKey("qwen_jobs.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
