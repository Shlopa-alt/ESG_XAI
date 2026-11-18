"""Правила домена для экспериментов (CLAUDE.md, правило 3)."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models import Experiment

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Без этого запуск не попадает в реестр: код, срез данных, окружение, seed.
REPRODUCIBILITY_FIELDS = ("runner_commit", "dataset_snapshot_id", "env_lock", "seed")


class DomainError(ValueError):
    """Нарушение правила домена — ответ 422 с понятным текстом."""


def missing_for_done(exp: Experiment) -> list[str]:
    missing = []
    for name in REPRODUCIBILITY_FIELDS:
        value = getattr(exp, name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(name)
    return missing


def set_status(exp: Experiment, status: str) -> None:
    """Смена статуса; в «done» — только при полной воспроизводимости."""
    if status == "done":
        missing = missing_for_done(exp)
        if missing:
            raise DomainError(
                "Эксперимент не может быть завершён без воспроизводимости: не заполнено "
                + ", ".join(missing)
            )
        exp.finished_at = exp.finished_at or datetime.now(UTC)
    exp.status = status


# --- статус проверки по её расчётам (п. 12 фидбека) ---

ACTIVE_RUNS = ("queued", "running")
SCAN = "correlation-scan"


def refresh_after_runs(db: "Session", exp: Experiment) -> None:
    """Расчёты проверки закончились — проверка не остаётся «в работе» навсегда:
    хоть один удачный — «на проверке» (можно рецензировать), все упали или остановлены — «сбой».
    Только поиск связей — сразу «завершён»: на рецензию он не идёт.
    Пока идёт хоть один расчёт, статус не трогается; «на проверке» и «завершён» не откатываются."""
    from sqlalchemy import select

    from app.models import Run

    if exp.status not in ("planned", "running"):
        return
    statuses = list(db.scalars(select(Run.status).where(Run.experiment_id == exp.id)))
    if not statuses or any(s in ACTIVE_RUNS for s in statuses):
        return
    if "done" not in statuses:
        exp.status = "failed"
        return
    # поиск связей — разведка, а не проверка идеи: рецензировать нечего, он сразу «завершён»
    templates = set(db.scalars(select(Run.template).where(Run.experiment_id == exp.id)))
    if templates == {SCAN} and not missing_for_done(exp):
        set_status(exp, "done")
    else:
        exp.status = "review"


def progress(db: "Session", exp: Experiment) -> dict[str, object] | None:
    """Ход проверки для списка и карточки (п. 13): сколько расчётов готово, что идёт сейчас,
    сколько прошло и сколько примерно осталось по оценке расчёта. Нет расчётов — None."""
    from sqlalchemy import select

    from app.models import Run
    from app.services.run_templates import TEMPLATES

    runs = list(db.scalars(select(Run).where(Run.experiment_id == exp.id).order_by(Run.id)))
    if not runs:
        return None
    now = datetime.now(UTC)
    active = []
    left = 0.0
    for r in runs:
        if r.status not in ACTIVE_RUNS:
            continue
        est = (r.config or {}).get("estimate") if isinstance(r.config, dict) else None
        minutes = float(est.get("minutes") or 0) if isinstance(est, dict) else 0.0
        started = r.started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        elapsed = (now - started).total_seconds() / 60 if (r.status == "running" and started) else 0.0
        left += max(0.0, minutes - elapsed)
        t = TEMPLATES.get(r.template)
        active.append({"run_id": r.id, "status": r.status, "title": t.title if t else r.template or "расчёт",
                       "elapsed_min": round(elapsed, 1), "estimate_min": minutes})
    return {
        "total": len(runs),
        "done": sum(r.status == "done" for r in runs),
        "failed": sum(r.status in ("failed", "stopped") for r in runs),
        "active": active,
        "left_min": round(left, 1),
    }
