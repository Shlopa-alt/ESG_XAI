"""Учёт ресурсов: цена расчёта до запуска, выбор способа расчёта и лимиты на сервере.

Оценка — по формуле метода: сколько раз обучается модель (разбиения × испытания подбора × фолды,
плацебо) × сколько стоит одно обучение (строки, входы, сеть). Это порядок величины, поэтому
показывается с разбросом ×0,5…×2. Когда у метода накопилось хотя бы CALIBRATE завершённых расчётов
с записанной оценкой, формула поправляется по их фактическому времени (медиана отношения).

Лимиты (deploy/.env) проверяет start_run — не только интерфейс:
* расчёт, который по оценке не уложится в лимит времени метода, не ставится — с советом, как
  уложиться (меньше испытаний подбора; разбиения по CR-01 — не меньше 30);
* у человека не больше RUN_ACTIVE_PER_USER проверок, расчёты которых в очереди или идут (набор
  сетей одной проверки — одна проверка);
* за сутки — не больше RUN_CPU_MINUTES_PER_DAY оценённых минут (администратора квота не держит);
* видеокарта — как раньше, GPU_RUNS_PER_USER; выбирается, только если её исполнитель включён.
"""

import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import DatasetSnapshot, Experiment, Run, User
from app.services.data_files import EXCEL, to_container
from app.services.run_templates import Template

CALIBRATE = 3  # завершённых расчётов метода, после которых формула поправляется по факту
UNKNOWN_ROWS = 200  # число строк версии данных не записано — считаем так и предупреждаем
EXECUTOR_SLOTS = 2  # исполнитель считает два расчёта сразу (celery -c 2)
GPU_SPEEDUP = 4.0
MIN_SPLITS = 30  # протокол CR-01
# цена одного шага обучения (батч ~30 строк) на двух потоках процессора, секунды; трансформер — дороже
STEP_S = {"mlp": 0.00025, "transformer": 0.0025}


class LimitError(Exception):
    """Расчёт не ставится: причина и что сделать — для человека. status — код ответа API."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Estimate:
    template: str
    resource: str  # cpu | gpu — где посчитается
    minutes: float
    low: float
    high: float
    limit_min: int
    within_limit: bool
    basis: str  # откуда оценка: формула или формула, поправленная по прошлым расчётам
    resource_why: str
    fits: int = 0  # сколько раз обучается модель
    warnings: list[str] = field(default_factory=list)
    suggestion: dict[str, Any] | None = (
        None  # {"params", "minutes", "text"} — как уложиться в лимит
    )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def _inputs(params: dict[str, Any]) -> int:
    feats = _list(params.get("features"))
    ctx = _list(params.get("context"))
    # текстовые параметры Z раскрываются в несколько столбцов — в среднем три значения
    return max(1, len(feats) + 3 * len(ctx))


def _int(params: dict[str, Any], key: str, default: int) -> int:
    v = params.get(key, default)
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def _lab_seconds(params: dict[str, Any], rows: int) -> tuple[float, int]:
    arch = str(params.get("architecture") or "mlp")
    splits, trials = _int(params, "splits", 30), _int(params, "trials", 10)
    inputs = _inputs(params)
    train = rows * 0.8
    folds = 3 if train < 60 else 5
    fit_rows = train * (folds - 1) / folds
    steps = 115 * max(1, math.ceil(fit_rows / 30))  # эпох в среднем × батчей
    per_fit = (
        steps
        * STEP_S.get(arch, STEP_S["mlp"])
        * (1 + inputs / (10 if arch == "transformer" else 100))
    )
    # на каждом разбиении: подбор (испытания × фолды) и итоговое обучение — для данных и для плацебо
    fits = splits * 2 * (trials * folds + 1) + trials * folds + 1
    shap = 20 + min(rows, 300) * inputs * 0.02
    return fits * per_fit + shap, fits


def formula_minutes(t: Template, params: dict[str, Any], rows: int) -> tuple[float, int]:
    """Оценка по формуле метода, минуты, и сколько раз обучается модель."""
    if t.key == "lab-mlp":
        sec, fits = _lab_seconds(params, rows)
    elif t.key == "predictive-check":
        splits, inputs = _int(params, "splits", 30), _inputs(params)
        fits = splits * 2 * 2  # линейная и бустинг, данные и плацебо
        sec = 5 + fits * (0.05 + rows * inputs * 2e-5)
    elif t.key == "rank-agreement":
        k = len(_list(params.get("columns"))) or 2
        resamples = _int(params, "n_boot", 10_000) + _int(params, "n_perm", 10_000)
        fits = k * (k - 1) // 2 * resamples
        sec = 3 + fits * (rows * 2e-6 + 1e-4)
    elif t.key == "exp007-hsu":
        fits = _int(params, "trials", 100)
        sec = 45 * fits  # 100 испытаний — около 75 минут (runner/hsu2025)
    elif t.method:  # метод из статьи: время одного обучения — по пробному запуску (протокол: данные и плацебо)
        fits = _int(params, "splits", 30) * 2
        per_fit = t.fit_s * max(1.0, rows * 0.8 / t.fit_rows) if t.fit_s and t.fit_rows else 2.0
        sec = 15 + fits * per_fit
    else:  # повтор EXP-001 и прочие короткие расчёты
        fits, sec = 1, 60
    return sec / 60, fits


def _arch(params: Any) -> str:
    return str((params or {}).get("architecture") or "mlp") if isinstance(params, dict) else "mlp"


def calibration(db: Session, template: str, arch: str = "mlp") -> tuple[float, int]:
    """Поправка формулы по фактическому времени прошлых расчётов метода с той же сетью
    (перцептрон и трансформер считаются по-разному): (множитель, сколько расчётов)."""
    ratios = []
    runs = db.scalars(
        select(Run)
        .where(Run.template == template, Run.status == "done")
        .order_by(Run.id.desc())
        .limit(20)
    )
    for r in runs:
        if template == "lab-mlp" and _arch((r.config or {}).get("params")) != arch:
            continue
        est = (r.config or {}).get("estimate") or {}
        minutes = est.get("minutes") if isinstance(est, dict) else None
        if (
            not isinstance(minutes, int | float)
            or minutes <= 0
            or not r.started_at
            or not r.finished_at
        ):
            continue
        actual = (r.finished_at - r.started_at).total_seconds() / 60
        if actual > 0:
            ratios.append(actual / float(minutes))
    if len(ratios) < CALIBRATE:
        return 1.0, len(ratios)
    return median(ratios), len(ratios)


def _resource(
    t: Template, params: dict[str, Any], cpu_minutes: float, settings: Settings
) -> tuple[str, float, str]:
    if t.resource == "gpu":
        return "gpu", cpu_minutes, "метод считается только на видеокарте"
    if params.get("architecture") == "transformer":
        if settings.gpu_executor and cpu_minutes > 30:
            return (
                "gpu",
                cpu_minutes / GPU_SPEEDUP,
                "трансформер на видеокарте считается в несколько раз быстрее",
            )
        if cpu_minutes > 30:
            return (
                "cpu",
                cpu_minutes,
                "на видеокарте было бы быстрее, но её исполнитель пока не подключён",
            )
    return "cpu", cpu_minutes, "небольшой расчёт — процессора достаточно"


def _round(m: float) -> float:
    return round(m, 1) if m < 10 else float(round(m))


def estimate(
    db: Session, settings: Settings, t: Template, params: dict[str, Any], rows: int | None
) -> Estimate:
    warnings = []
    if rows is None:
        warnings.append(f"Число строк версии данных не записано — оценка для {UNKNOWN_ROWS} строк.")
    n = rows or UNKNOWN_ROWS
    base, fits = formula_minutes(t, params, n)
    k, past = calibration(db, t.key, _arch(params))
    resource, minutes, why = _resource(t, params, base * k, settings)
    basis = (
        f"по формуле метода, поправленной по {past} прошлым расчётам (×{k:.2f})"
        if past >= CALIBRATE
        else "по формуле метода"
        + (f"; прошлых расчётов {past} — поправка с {CALIBRATE}" if past else "")
    )
    est = Estimate(
        template=t.key,
        resource=resource,
        minutes=_round(minutes),
        low=_round(minutes * 0.5),
        high=_round(minutes * 2),
        limit_min=t.limit_min,
        within_limit=minutes <= t.limit_min,
        basis=basis,
        resource_why=why,
        fits=fits,
        warnings=warnings,
    )
    if not est.within_limit:
        est.suggestion = _fit_limit(db, settings, t, params, n, k)
    return est


def _fit_limit(
    db: Session, settings: Settings, t: Template, params: dict[str, Any], rows: int, k: float
) -> dict[str, Any] | None:
    """Оптимальный способ уложиться в лимит: меньше испытаний подбора, бутстрепа — не протокола."""
    knob = {
        "lab-mlp": ("trials", 3),
        "exp007-hsu": ("trials", 5),
        "rank-agreement": ("n_boot", 100),
    }.get(t.key)
    if knob is None:
        return {
            "params": None,
            "minutes": None,
            "text": "Сократите число входов или строк — параметры протокола CR-01 уменьшать нельзя.",
        }
    name, lowest = knob
    value = _int(params, name, 0)
    while value > lowest:
        value = max(lowest, value * 2 // 3)
        trial = {**params, name: value}
        if name == "n_boot":
            trial["n_perm"] = value
        m = formula_minutes(t, trial, rows)[0] * k
        if (
            t.key == "lab-mlp"
            and params.get("architecture") == "transformer"
            and settings.gpu_executor
        ):
            m /= GPU_SPEEDUP
        if m <= 0.8 * t.limit_min:
            label = {"trials": "испытаний подбора", "n_boot": "повторных выборок и перестановок"}[
                name
            ]
            return {
                "params": trial,
                "minutes": _round(m),
                "text": f"Уменьшите число {label} до {value} — около {_round(m)} мин.",
            }
    if t.key == "lab-mlp":
        return {
            "params": None,
            "minutes": None,
            "text": "Даже при 3 испытаниях подбора не укладывается: уберите часть входов или выберите "
            "перцептрон вместо трансформера (разбиения по CR-01 — не меньше 30).",
        }
    return None


def _today(db: Session, user: User) -> float:
    since = datetime.now(UTC) - timedelta(days=1)
    total = 0.0
    recent = select(Run).where(Run.created_by == user.id).order_by(Run.id.desc()).limit(500)
    for r in db.scalars(recent):
        created = r.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        est = (r.config or {}).get("estimate") or {}
        minutes = est.get("minutes") if isinstance(est, dict) else None
        if created is not None and created >= since and isinstance(minutes, int | float):
            total += float(minutes)
    return total


def usage(
    db: Session, settings: Settings, user: User, experiment_id: int | None = None
) -> dict[str, Any]:
    """Сколько проверок человека сейчас считается. Лимит — на проверки, а не на расчёты: набор
    сетей в одной проверке — это одна проверка; расчёт в ту же проверку лимит не тратит."""
    rows = db.execute(
        select(Experiment.id, Experiment.code)
        .join(Run, Run.experiment_id == Experiment.id)
        .where(Run.created_by == user.id, Run.status.in_(("queued", "running")))
        .distinct()
    ).all()
    checks = sorted(code for eid, code in rows if eid != experiment_id)
    return {
        "active": len(checks),
        "active_checks": checks,
        "active_limit": settings.run_active_per_user,
        "minutes_today": _round(_today(db, user)),
        "minutes_limit": settings.run_cpu_minutes_per_day,
        "unlimited": user.role == "owner",
    }


def rows_of(settings: Settings, snap: DatasetSnapshot, sheet: str = "") -> int | None:
    """Строк в версии данных. У CSV число записано при загрузке; у книги Excel — нет, поэтому
    считаем по листу (иначе оценка шла бы по 200 строкам и большой расчёт проходил бы лимиты)."""
    if snap.row_count is not None:
        return snap.row_count
    path = to_container(settings, snap.storage_path) if snap.storage_path else None
    if path is None or not path.is_file() or path.suffix.lower() not in EXCEL:
        return None
    try:
        from openpyxl import load_workbook  # type: ignore[import-untyped]

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.worksheets[0]
            return max(0, (ws.max_row or 1) - 1)  # без строки заголовка
        finally:
            wb.close()
    except Exception:  # noqa: BLE001 — не прочитали книгу: оценка по умолчанию с предупреждением
        return None


def _run_minutes(r: Run) -> float:
    est = (r.config or {}).get("estimate")
    value = est.get("minutes") if isinstance(est, dict) else None
    return float(value) if isinstance(value, int | float) else 0.0


def queue(db: Session, resource: str) -> dict[str, Any]:
    """Сколько расчётов впереди в очереди того же ресурса и примерно сколько ждать."""
    ahead = list(
        db.scalars(
            select(Run).where(Run.resource == resource, Run.status.in_(("queued", "running")))
        )
    )
    minutes = sum(_run_minutes(r) for r in ahead)
    return {"ahead": len(ahead), "wait_minutes": _round(minutes / EXECUTOR_SLOTS)}


def check_limits(
    db: Session, settings: Settings, user: User, est: Estimate, experiment_id: int | None = None
) -> None:
    """Лимиты на сервере. Нарушен — LimitError с причиной и советом."""
    if not est.within_limit:
        tip = f" {est.suggestion['text']}" if est.suggestion else ""
        raise LimitError(
            f"По оценке расчёт займёт около {est.minutes:g} мин — больше лимита метода "
            f"{est.limit_min} мин.{tip}",
            status=422,
        )
    u = usage(db, settings, user, experiment_id)
    if u["active"] >= settings.run_active_per_user:
        raise LimitError(
            f"У вас уже считаются проверки {', '.join(u['active_checks'])} (одновременно можно "
            f"{settings.run_active_per_user}) — дождитесь, пока одна закончится, или остановите её "
            "расчёты: расчёты проверки — внизу её страницы, кнопка «Остановить» — на странице расчёта."
        )
    if not u["unlimited"] and u["minutes_today"] + est.minutes > settings.run_cpu_minutes_per_day:
        left = max(0.0, settings.run_cpu_minutes_per_day - u["minutes_today"])
        raise LimitError(
            f"Дневная квота — {settings.run_cpu_minutes_per_day} мин расчётов, осталось "
            f"{_round(left):g}, а этот расчёт — около {est.minutes:g}. Уменьшите расчёт или "
            "попросите администратора."
        )
