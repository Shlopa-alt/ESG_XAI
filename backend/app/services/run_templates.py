"""Библиотека методов: какие расчёты из runner/ можно запустить из формы и с какими параметрами.

Два вида:
- общий метод (scope="generic") — считается на любом подходящем срезе (CSV) и в любом
  эксперименте: параметры — столбцы среза (их платформа сверяет с заголовком файла) и числа;
- повтор (scope="replication") — расчёт конкретного эксперимента на своём датасете (EXP-001,
  EXP-007): тот же код, что дал опубликованный результат.

Запуск берёт выбранный срез (его sha256 исполнитель сверяет перед стартом — правило 3) и передаёт
скрипту каталог датасета, каталог результатов, файл среза (--data); числа — ключами командной
строки (seed → --seed, n_boot → --n-boot), общим методам — ещё --params <JSON> со всеми
параметрами, --experiment и --dataset. Скрипт пишет run.json — исполнитель возвращает его
платформе. Новые методы пишут люди: скрипт в runner/methods/ и запись здесь.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Literal

ParamKind = Literal["int", "column", "columns"]


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    default: Any = None
    min: int = 0
    max: int = 0
    kind: ParamKind = "int"
    numeric: bool = True  # столбцы: только числовые (буквенная шкала рейтингов AAA…CCC — числовая)
    required: bool = True
    hint: str = ""


@dataclass(frozen=True)
class Template:
    key: str
    title: str
    description: str
    workdir: str  # каталог в runner/
    script: str
    resource: Literal["cpu", "gpu"]
    limit_min: int  # дольше — исполнитель останавливает расчёт
    params: tuple[Param, ...] = field(default_factory=tuple)
    scope: Literal["generic", "replication"] = "generic"
    experiment: str = ""  # повтор: чей результат воспроизводит
    dataset: str = ""  # повтор: на каком датасете
    # срез — файл; каталог датасета, который ждёт скрипт, — на столько уровней выше файла
    dataset_dir_up: int = 2


SEED = Param("seed", "Seed", 42, 0, 2**31 - 1)

TEMPLATES: dict[str, Template] = {
    t.key: t
    for t in (
        Template(
            key="rank-agreement",
            title="Согласованность показателей (ранговая корреляция)",
            description="ρ Спирмена для каждой пары выбранных столбцов, 95 % бутстреп-интервал и "
                        "перестановочный тест. Подходит для сравнения рейтингов провайдеров, оценок, "
                        "показателей. У столбцов «больше — хуже» (шкала риска) знак обращается.",
            workdir="methods", script="rank_agreement.py", resource="cpu", limit_min=30,
            params=(Param("columns", "Столбцы для сравнения", [], kind="columns", hint="не меньше двух"),
                    Param("invert", "Столбцы, где больше — хуже", [], kind="columns", required=False),
                    SEED,
                    Param("n_boot", "Повторных выборок (бутстреп)", 10_000, 100, 100_000),
                    Param("n_perm", "Перестановок", 10_000, 100, 100_000)),
        ),
        Template(
            key="predictive-check",
            title="Предсказательная проверка (протокол CR-01)",
            description="Предсказывают ли признаки целевой показатель лучше среднего: линейная модель и "
                        "градиентный бустинг без подбора по тесту, 30 случайных разбиений 80/20, плацебо на "
                        "перемешанной цели. Итог — R² на отложенной выборке со средним и разбросом.",
            workdir="methods", script="predictive_check.py", resource="cpu", limit_min=60,
            params=(Param("target", "Целевой показатель", "", kind="column"),
                    Param("features", "Признаки", [], kind="columns", hint="ESG-признаки и контрольные"),
                    SEED,
                    Param("splits", "Случайных разбиений", 30, 5, 200)),
        ),
        Template(
            key="exp001-dow30",
            title="Повтор EXP-001 · согласованность ESG-рейтингов Dow30",
            description="Расчёт EXP-001 как есть: ρ Спирмена по парам провайдеров, бутстреп-интервал и "
                        "перестановочный тест. Около минуты.",
            workdir="dow30", script="run_exp001.py", resource="cpu", limit_min=30, scope="replication",
            experiment="EXP-001", dataset="DS-01",
            params=(SEED,
                    Param("n_boot", "Повторных выборок (бутстреп)", 10_000, 100, 100_000),
                    Param("n_perm", "Перестановок", 10_000, 100, 100_000)),
        ),
        Template(
            key="exp007-hsu",
            title="Повтор EXP-007 · Hsu et al. (2025)",
            description="Расчёт EXP-007 как есть: протоколы «как в статье» и честный, 30 разбиений, плацебо, "
                        "MLP с SHAP. При 100 испытаниях Optuna — около 75 минут на 16 ядрах.",
            workdir="hsu2025", script="run_exp007.py", resource="cpu", limit_min=240, scope="replication",
            experiment="EXP-007", dataset="DS-04",
            params=(SEED, Param("trials", "Испытаний Optuna", 100, 5, 500)),
        ),
    )
}


class ParamError(ValueError):
    pass


def check_params(t: Template, given: dict[str, Any], columns: list[str] | None = None,
                 numeric: set[str] | None = None) -> dict[str, Any]:
    """Параметры запуска: значения по умолчанию, поверх — заданные. Числа — целые в границах,
    столбцы — из заголовка среза (columns), для числовых параметров — числовые (numeric)."""
    unknown = set(given) - {p.name for p in t.params}
    if unknown:
        raise ParamError(f"У метода нет параметров: {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for p in t.params:
        value = given.get(p.name, p.default)
        if p.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ParamError(f"«{p.label}» — целое число")
            if not p.min <= value <= p.max:
                raise ParamError(f"«{p.label}»: от {p.min} до {p.max}")
        else:
            names = [value] if p.kind == "column" else value
            if not isinstance(names, list) or not all(isinstance(v, str) for v in names):
                raise ParamError(f"«{p.label}» — {'столбец' if p.kind == 'column' else 'список столбцов'}")
            names = [v for v in names if v]
            if p.required and not names:
                raise ParamError(f"«{p.label}»: выберите столбец")
            if columns is not None:
                missing = [v for v in names if v not in columns]
                if missing:
                    raise ParamError(f"«{p.label}»: в срезе нет столбцов {', '.join(missing)}")
            if p.numeric and numeric is not None:
                text = [v for v in names if v not in numeric]
                if text:
                    raise ParamError(f"«{p.label}»: не числовые столбцы {', '.join(text)}")
            if len(set(names)) != len(names):
                raise ParamError(f"«{p.label}»: столбец указан дважды")
            value = names[0] if p.kind == "column" and names else ("" if p.kind == "column" else names)
        out[p.name] = value
    if t.key == "rank-agreement" and len(out["columns"]) < 2:
        raise ParamError("Для согласованности нужны хотя бы два столбца")
    if t.key == "rank-agreement" and not set(out["invert"]) <= set(out["columns"]):
        raise ParamError("Обращать можно только сравниваемые столбцы")
    if t.key == "predictive-check" and out["target"] in out["features"]:
        raise ParamError("Целевой показатель не может быть признаком")
    return out


def script_args(t: Template, params: dict[str, Any], experiment: str, dataset: str) -> list[str]:
    if t.scope == "replication":
        return [a for k, v in params.items() for a in (f"--{k.replace('_', '-')}", str(v))]
    return ["--params", json.dumps(params, ensure_ascii=False), "--experiment", experiment, "--dataset", dataset]
