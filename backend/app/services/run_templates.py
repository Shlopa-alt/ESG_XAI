"""Шаблоны запуска: какие расчёты из runner/ можно запустить из формы и с какими параметрами.

Шаблон привязан к эксперименту и датасету: запуск берёт выбранный срез датасета (его
sha256 исполнитель сверяет перед стартом — правило 3), передаёт скрипту каталог датасета,
каталог результатов и параметры ключами командной строки (seed → --seed, n_boot → --n-boot).
Скрипт пишет run.json — исполнитель возвращает его платформе.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    default: int
    min: int
    max: int


@dataclass(frozen=True)
class Template:
    key: str
    title: str
    description: str
    experiment: str
    dataset: str
    workdir: str  # каталог в runner/
    script: str
    resource: Literal["cpu", "gpu"]
    limit_min: int  # дольше — исполнитель останавливает расчёт
    params: tuple[Param, ...] = field(default_factory=tuple)
    # срез — файл; каталог датасета, который ждёт скрипт, — на столько уровней выше файла
    dataset_dir_up: int = 2


SEED = Param("seed", "Seed", 42, 0, 2**31 - 1)

TEMPLATES: dict[str, Template] = {
    t.key: t
    for t in (
        Template(
            key="exp001-dow30",
            title="EXP-001 · согласованность ESG-рейтингов Dow30",
            description="ρ Спирмена по парам провайдеров, бутстреп-интервал и перестановочный тест. "
                        "Около минуты.",
            experiment="EXP-001", dataset="DS-01", workdir="dow30", script="run_exp001.py",
            resource="cpu", limit_min=30,
            params=(SEED,
                    Param("n_boot", "Повторных выборок (бутстреп)", 10_000, 100, 100_000),
                    Param("n_perm", "Перестановок", 10_000, 100, 100_000)),
        ),
        Template(
            key="exp007-hsu",
            title="EXP-007 · повтор Hsu et al. (2025)",
            description="Протоколы «как в статье» и честный, 30 разбиений, плацебо, MLP с SHAP. "
                        "При 100 испытаниях Optuna — около 75 минут на 16 ядрах.",
            experiment="EXP-007", dataset="DS-04", workdir="hsu2025", script="run_exp007.py",
            resource="cpu", limit_min=240,
            params=(SEED, Param("trials", "Испытаний Optuna", 100, 5, 500)),
        ),
    )
}


class ParamError(ValueError):
    pass


def check_params(t: Template, given: dict[str, Any]) -> dict[str, int]:
    """Параметры запуска: значения по умолчанию, поверх — заданные; целые в границах шаблона."""
    unknown = set(given) - {p.name for p in t.params}
    if unknown:
        raise ParamError(f"У шаблона нет параметров: {', '.join(sorted(unknown))}")
    out: dict[str, int] = {}
    for p in t.params:
        value = given.get(p.name, p.default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ParamError(f"«{p.label}» — целое число")
        if not p.min <= value <= p.max:
            raise ParamError(f"«{p.label}»: от {p.min} до {p.max}")
        out[p.name] = value
    return out


def script_args(params: dict[str, int]) -> list[str]:
    return [a for k, v in params.items() for a in (f"--{k.replace('_', '-')}", str(v))]
