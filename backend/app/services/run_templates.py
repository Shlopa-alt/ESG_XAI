"""Библиотека методов: какие расчёты из runner/ можно запустить из формы и с какими параметрами.

Два вида:
- общий метод (scope="generic") — считается на любом подходящем срезе (CSV или лист книги Excel)
  и в любом эксперименте: параметры — лист книги, столбцы (их платформа сверяет с заголовком) и числа;
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

ParamKind = Literal["int", "column", "columns", "sheet", "choice"]


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
    options: tuple[tuple[str, str], ...] = ()  # choice: (значение, подпись на экране)


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
    # метод из библиотеки (статья банка, код — Qwen): код идёт в задании исполнителю, sha256 — в расчёт
    method_code: str = ""
    method_sha256: str = ""
    method: str = ""  # код метода M-NN
    fit_s: float = 0.0  # пробный запуск: секунд на одно обучение модели …
    fit_rows: int = 0  # … на стольких строках — для цены расчёта


SEED = Param("seed", "Seed", 42, 0, 2**31 - 1)
# сеть метода лаборатории: «как у авторов» статьи или замена при том же протоколе (net_catalog.py)
ARCHITECTURE = Param("architecture", "Нейросеть", "mlp", kind="choice", required=False,
                     options=(("mlp", "перцептрон лаборатории (MLP)"),
                              ("transformer", "трансформер для таблиц (FT-Transformer)")),
                     hint="перцептрон — как в постановке лаборатории; трансформер — замена")
# способ поиска связей (runner/methods/correlation_scan.py: METHODS); объяснения — на вкладке «Нейросети»
LINK_METHOD = Param("method", "Способ поиска связей", "rank", kind="choice", required=False,
                    options=(("rank", "любые связи: монотонные (ρ Спирмена) и U-образные (ξ Чаттерджи)"),
                             ("linear", "только прямолинейные (r Пирсона)"),
                             ("partial", "без влияния остальных показателей (частная ρ)")),
                    hint="деление на поиск и подтверждение, поправка и плацебо — у всех способов одни")
# у книги Excel — какой лист считать (пусто — первый лист-таблица); у CSV параметра не видно
SHEET = Param("sheet", "Лист книги", "", kind="sheet", required=False, hint="для срезов Excel")

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
            params=(SHEET,
                    Param("columns", "Столбцы для сравнения", [], kind="columns", hint="не меньше двух"),
                    Param("invert", "Столбцы, где больше — хуже", [], kind="columns", required=False),
                    SEED,
                    Param("n_boot", "Повторных выборок (бутстреп)", 10_000, 100, 100_000),
                    Param("n_perm", "Перестановок", 10_000, 100, 100_000)),
        ),
        Template(
            key="correlation-scan",
            title="Поиск связей (все пары столбцов, с подтверждением)",
            description="Ищет связи между всеми парами столбцов: монотонные (ρ Спирмена) и "
                        "немонотонные (ξ Чаттерджи). Строки делятся на поиск и подтверждение; "
                        "поправка на множественное сравнение (Бенджамини — Хохберг), каждая "
                        "находка перепроверяется на отложенной части, поиск повторяется на "
                        "перемешанных данных. Итог — кандидаты в идеи, не выводы.",
            workdir="methods", script="correlation_scan.py", resource="cpu", limit_min=60,
            params=(SHEET,
                    Param("columns", "Столбцы", [], kind="columns", required=False,
                          hint="пусто — все числовые, не больше 40"),
                    Param("group", "Столбец-группа", "", kind="column", required=False,
                          numeric=False,
                          hint="у панели компания × год — компания: строки усредняются по ней"),
                    LINK_METHOD,
                    Param("holdout", "Отложенная часть (на подтверждение), %", 50, 20, 70),
                    Param("fdr", "Допустимая доля ложных находок, %", 10, 1, 25),
                    Param("placebo", "Повторов на перемешанных данных", 5, 0, 20),
                    SEED),
        ),
        Template(
            key="predictive-check",
            title="Предсказательная проверка (протокол CR-01)",
            description="Предсказывают ли признаки целевой показатель лучше среднего: линейная модель и "
                        "градиентный бустинг без подбора по тесту, 30 случайных разбиений 80/20, плацебо на "
                        "перемешанной цели. Итог — R² на отложенной выборке со средним и разбросом.",
            workdir="methods", script="predictive_check.py", resource="cpu", limit_min=60,
            params=(SHEET,
                    Param("target", "Целевой показатель", "", kind="column"),
                    Param("features", "Признаки", [], kind="columns", hint="ESG-признаки и контрольные"),
                    Param("group", "Столбец-группа (панель)", "", kind="column", required=False,
                          numeric=False,
                          hint="у панели компания × год — компания: проверка на компаниях вне обучения"),
                    SEED,
                    Param("splits", "Случайных разбиений", 30, 5, 200)),
        ),
        Template(
            key="lab-mlp",
            title="Метод лаборатории: нейросеть R = f(X, Z) с SHAP (протокол CR-01)",
            description="Модель из постановки задачи лаборатории: однослойная нейросеть (MLP, "
                        "ReLU или tanh, MSE, Adam/RMSProp) предсказывает результат R по ESG-входам "
                        "X и параметрам Z (размер, отрасль). Гиперпараметры (Optuna) — только по "
                        "обучающей части; 30 случайных разбиений 80/20, плацебо на перемешанной "
                        "цели, сравнение со средним, линейной моделью и прогнозом «как в прошлом "
                        "году». Вклад факторов — SHAP. Минуты–часы: зависит от строк и испытаний.",
            workdir="methods", script="lab_mlp.py", resource="cpu", limit_min=240,
            params=(SHEET,
                    Param("target", "Результат R (целевой показатель)", "", kind="column"),
                    Param("features", "Входы X (ESG-показатели, инвестиции по статьям)", [],
                          kind="columns"),
                    Param("context", "Параметры Z (размер, отрасль, регион)", [], kind="columns",
                          numeric=False, required=False, hint="текстовые — по категориям"),
                    Param("lag", "R прошлого периода", "", kind="column", required=False,
                          hint="для прогноза «как в прошлом году»"),
                    Param("group", "Столбец-группа (панель)", "", kind="column", required=False,
                          numeric=False,
                          hint="у панели компания × год — компания: проверка на компаниях вне обучения"),
                    ARCHITECTURE,
                    SEED,
                    Param("splits", "Случайных разбиений", 30, 5, 200),
                    Param("trials", "Испытаний Optuna на разбиение", 10, 3, 100)),
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
                 numeric: set[str] | None = None, sheets: list[str] | None = None,
                 sheet: str = "") -> dict[str, Any]:
    """Параметры запуска: значения по умолчанию, поверх — заданные. Числа — целые в границах,
    столбцы — из заголовка среза (columns), для числовых параметров — числовые (numeric).
    Лист — из листов-таблиц книги (sheets; у CSV — пусто); sheet — какой прочитан для columns."""
    unknown = set(given) - {p.name for p in t.params}
    if unknown:
        raise ParamError(f"У метода нет параметров: {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for p in t.params:
        value = given.get(p.name, p.default)
        if p.kind == "sheet":
            if not isinstance(value, str):
                raise ParamError(f"«{p.label}» — имя листа")
            if sheets is not None:
                if not sheets and value:
                    raise ParamError("Лист выбирают только у книги Excel, а срез — CSV")
                if sheets and (value or sheet) not in sheets:
                    raise ParamError(f"В книге нет листа-таблицы «{value}»; есть: {', '.join(sheets)}")
                value = value or sheet  # пусто — лист, который прочитан (первый лист-таблица)
            out[p.name] = value
            continue
        if p.kind == "choice":
            allowed = [v for v, _ in p.options]
            if value not in allowed:
                raise ParamError(f"«{p.label}»: одно из {', '.join(allowed)}")
            out[p.name] = value
            continue
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
    if t.key == "correlation-scan" and len(out["columns"]) == 1:
        raise ParamError("Для поиска связей нужны хотя бы два столбца "
                         "(или пусто — все числовые)")
    if t.key == "correlation-scan" and out["group"] and out["group"] in out["columns"]:
        raise ParamError("По столбцу-группе усредняются строки, в связях он не ищется — "
                         "уберите его из столбцов")
    if t.key in ("predictive-check", "lab-mlp") and out["group"]:
        used = [out["target"], *out["features"], *out.get("context", []), out.get("lag", "")]
        if out["group"] in used:
            raise ParamError("Столбец-группа делит строки на обучение и проверку — "
                             "он не может быть целью, входом или параметром Z")
    if t.key == "correlation-scan" and len(out["columns"]) > 40:
        raise ParamError("Не больше 40 столбцов: иначе пар больше 780 "
                         "и поправка съедает все находки")
    if t.key == "predictive-check" and out["target"] in out["features"]:
        raise ParamError("Целевой показатель не может быть признаком")
    if t.key == "lab-mlp":
        inputs = [*out["features"], *out["context"]]
        if out["target"] in inputs or (out["lag"] and out["lag"] in inputs):
            raise ParamError("Результат R и его прошлый период не могут быть входами X или Z")
        if out["lag"] == out["target"]:
            raise ParamError("Прошлый период — другой столбец, не сам результат R")
        if set(out["features"]) & set(out["context"]):
            raise ParamError("Столбец не может быть и во входах X, и в параметрах Z")
    return out


def script_args(t: Template, params: dict[str, Any], experiment: str, dataset: str) -> list[str]:
    if t.scope == "replication":
        return [a for k, v in params.items() for a in (f"--{k.replace('_', '-')}", str(v))]
    return ["--params", json.dumps(params, ensure_ascii=False), "--experiment", experiment, "--dataset", dataset]
