"""Идею уже проверяли: что пробовали и какой вариант взять другим.

Подсказка автору новой идеи (правка «Экономика — правки и идеи по сайту»): если похожая идея уже
проверена, видно итог той проверки, на каких данных и каким методом её считали, и какие наборы
данных и методы библиотеки ещё не пробовали. Ничего не создаёт и не меняет. Названия наборов
данных видны всем вошедшим (описание датасета под NDA открыто, закрыты только файлы — правило 6).
"""

from dataclasses import dataclass, field

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.models import Dataset, DatasetSnapshot, Experiment, Run
from app.services.run_templates import TEMPLATES

ALTERNATIVES_MAX = 3  # сколько других наборов данных и методов предложить


@dataclass
class Named:
    code: str
    title: str


@dataclass
class Tried:
    experiment: str
    status: str
    outcome: str | None
    datasets: list[Named] = field(default_factory=list)
    methods: list[Named] = field(default_factory=list)
    other_datasets: list[Named] = field(default_factory=list)
    other_methods: list[Named] = field(default_factory=list)


def _dataset_of(db: Session, snapshot_id: int | None) -> Dataset | None:
    snap = db.get(DatasetSnapshot, snapshot_id) if snapshot_id else None
    return db.get(Dataset, snap.dataset_id) if snap else None


def tried(db: Session, experiment_id: int) -> Tried | None:
    """Что пробовали в проверке и чего ещё не пробовали; None — проверки нет."""
    exp = db.get(Experiment, experiment_id)
    if exp is None:
        return None
    # «пробовали» — только законченные расчёты: упавший или стоящий в очереди работой не считается
    runs = list(db.scalars(select(Run).where(Run.experiment_id == exp.id, Run.status == "done")
                           .order_by(Run.id)))
    used_ds: dict[int, Dataset] = {}
    for sid in [exp.dataset_snapshot_id, *(r.dataset_snapshot_id for r in runs)]:
        ds = _dataset_of(db, sid)
        if ds is not None:
            used_ds.setdefault(ds.id, ds)
    used_keys = list(dict.fromkeys(r.template for r in runs if r.template in TEMPLATES))
    methods = [Named(k, TEMPLATES[k].title) for k in used_keys]
    if not methods and exp.method:  # метод записан текстом, без расчёта библиотеки
        methods = [Named("", exp.method)]
    fresh = Dataset.id.not_in(list(used_ds)) if used_ds else true()
    # предлагаем только наборы с версией данных: на остальных расчёт не запустить
    has_version = (select(DatasetSnapshot.id)
                   .where(DatasetSnapshot.dataset_id == Dataset.id).exists())
    others = db.scalars(select(Dataset).where(fresh, has_version).order_by(Dataset.code)
                        .limit(ALTERNATIVES_MAX))
    other_methods = [Named(t.key, t.title) for t in TEMPLATES.values()
                     if t.scope == "generic" and t.key not in used_keys][:ALTERNATIVES_MAX]
    return Tried(
        experiment=exp.code, status=exp.status, outcome=exp.outcome,
        datasets=[Named(d.code, d.title) for d in used_ds.values()], methods=methods,
        other_datasets=[Named(d.code, d.title) for d in others], other_methods=other_methods,
    )
