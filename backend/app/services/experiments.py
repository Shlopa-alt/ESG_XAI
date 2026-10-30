"""Правила домена для экспериментов (CLAUDE.md, правило 3)."""

from datetime import UTC, datetime

from app.models import Experiment

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
