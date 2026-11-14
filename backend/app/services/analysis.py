"""Анализ данных: показатель (или пункт методики) + набор данных → рекомендованный метод → расчёт.

Рекомендация — правила по самим данным, без модели: сколько строк, какие столбцы числовые, какие
текстовые с немногими значениями (отрасль, регион — параметры Z), есть ли целевой показатель.
Каждое решение сопровождается причиной на русском — её видит человек и она пишется в проверку.
Методы — только из библиотеки (app/services/run_templates.py): новых расчётов здесь не появляется.
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.models import MethodologySection
from app.services.data_files import MISSING, Table
from app.services.run_templates import TEMPLATES

# сколько строк без пропусков нужно методу (runner/methods/*.py: MIN_ROWS и проверки в main)
MIN_ROWS = {"lab-mlp": 20, "predictive-check": 30, "rank-agreement": 5}
MAX_COMPARE = 8  # столбцов в согласованности по умолчанию: пар — до 28
MAX_LEVELS = 30  # текстовый столбец с большим числом значений — не категория (имя компании)
SMALL = 100  # строк меньше — оценки качества шумные

# понятия результата: если пункт методики и столбец называют одно и то же — столбец наверх
OUTCOMES: dict[str, tuple[str, ...]] = {
    "рентабельность активов": ("roa", "рентабельность активов", "return on assets"),
    "рентабельность капитала": ("roe", "рентабельность капитала", "return on equity"),
    "выручка": ("выручк", "revenue", "sales", "оборот"),
    "прибыль": ("прибыл", "profit", "net income", "ebit"),
    "налоги": ("налог", "tax"),
    "стоимость компании": ("капитализац", "market cap", "tobin", "стоимост", "value"),
    "рейтинг": ("рейтинг", "rating", "score", "оценк"),
    "выбросы": ("выброс", "emission", "co2", "ghg"),
    "доходность": ("доходност", "return", "yield"),
}
LAG_WORDS = ("прош", "lag", "prev", "t-1", "предыдущ")
YEAR = re.compile(r"(19|20)\d{2}")


@dataclass
class Recommendation:
    key: str  # уникально в ответе: шаблон + вариант
    template: str
    title: str  # что предлагается, по-человечески
    method_title: str  # название метода в библиотеке
    params: dict[str, Any]
    why: list[str]
    warnings: list[str] = field(default_factory=list)
    primary: bool = False
    runnable: bool = True
    net: str = ""  # сеть из каталога (задача 9); пусто — метод без выбора сети


def _filled(v: Any) -> bool:
    return v not in (None, "") and str(v).strip().lower() not in MISSING


def categories(t: Table) -> list[str]:
    """Текстовые столбцы с немногими значениями — кандидаты в параметры Z (отрасль, регион)."""
    out = []
    for j, c in enumerate(t.columns):
        if c in t.numeric:
            continue
        vals = [str(r[j]).strip() for r in t.sample if j < len(r) and _filled(r[j])]
        levels = len(set(vals))
        if vals and 2 <= levels <= MAX_LEVELS and levels <= max(2, len(vals) // 3):
            out.append(c)
    return out


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zа-яё0-9]+", text.lower()) if len(w) >= 3}


def target_candidates(node: MethodologySection | None, t: Table) -> list[dict[str, str]]:
    """Числовые столбцы, похожие на результат пункта методики, — по убыванию сходства, с причиной."""
    if node is None:
        return []
    text = f"{node.title} {node.content}".lower()
    words = _words(text)
    scored = []
    for c in t.numeric:
        name = c.lower()
        reasons = [
            label
            for label, terms in OUTCOMES.items()
            if any(term in name for term in terms) and any(term in text for term in terms)
        ]
        common = sorted(w for w in _words(name) & words if not w.isdigit())
        score = 2 * len(reasons) + len(common)
        if score:
            why = (
                f"в пункте {node.number} речь о: {', '.join(reasons)}"
                if reasons
                else f"в пункте {node.number} есть слова «{', '.join(common)}»"
            )
            scored.append((score, c, why))
    scored.sort(key=lambda s: (-s[0], t.columns.index(s[1])))
    return [{"column": c, "reason": why} for _, c, why in scored[:5]]


def guess_lag(target: str, numeric: list[str]) -> str:
    """Столбец «тот же показатель в прошлом периоде»: ROA_2022 → ROA_2021, «ROA прошлый год»."""
    m = YEAR.search(target)
    if m:
        prev = target[: m.start()] + str(int(m.group(0)) - 1) + target[m.end() :]
        if prev in numeric:
            return prev
    stem = YEAR.sub("", target).strip(" _-").lower()
    for c in numeric:
        low = c.lower()
        if c != target and stem and stem in low and any(w in low for w in LAG_WORDS):
            return c
    return ""


def _rows_note(rows: int | None, need: int) -> tuple[bool, str]:
    if rows is None:
        return True, ""
    if rows < need:
        return False, f"в версии данных {rows} строк, методу нужно хотя бы {need} без пропусков"
    return True, ""


def recommend(
    t: Table, rows: int | None, target: str, node: MethodologySection | None
) -> dict[str, Any]:
    """Тип задачи и рекомендации по данным. target — выбранный показатель (пусто — не выбран)."""
    numeric = [c for c in t.columns if c in t.numeric]
    cats = categories(t)
    recs: list[Recommendation] = []
    if target:
        if target not in numeric:
            raise ValueError(f"Показатель «{target}» — не числовой столбец этой версии данных")
        lag = guess_lag(target, numeric)
        features = [c for c in numeric if c not in (target, lag)]
        if not features:
            raise ValueError(
                "Кроме показателя, в данных нет числовых столбцов — предсказывать не по чему"
            )
        task = {
            "key": "predict",
            "title": "Прогноз числового показателя",
            "text": f"Предсказать «{target}» по остальным показателям: постановка лаборатории R = f(X, Z).",
        }
        base = {"target": target, "features": features, "sheet": t.sheet}
        small = rows is not None and rows < SMALL
        ok, why_not = _rows_note(rows, MIN_ROWS["lab-mlp"])
        mlp_why = [
            "Задача — предсказать числовой результат R по входам X: это постановка лаборатории, п. 3.1 методики.",
            f"Входы X — {len(features)} числовых столбцов"
            + (
                f"; параметры Z — {', '.join(cats)} (категории, учитываются отдельно)"
                if cats
                else ""
            )
            + ".",
            "Протокол CR-01 встроен: 30 разбиений, плацебо, сравнение с линейной моделью — "
            "видно, нужна ли нейросеть вообще.",
        ]
        if lag:
            mlp_why.append(
                f"«{lag}» похож на прошлый период показателя — добавлен прогноз «как в прошлом году»."
            )
        recs.append(
            Recommendation(
                key="lab-mlp",
                template="lab-mlp",
                title="Нейросеть лаборатории (перцептрон) с вкладом факторов",
                method_title=TEMPLATES["lab-mlp"].title,
                params={**base, "context": cats, "lag": lag},
                why=mlp_why,
                warnings=(
                    [
                        f"Строк {rows} — меньше {SMALL}: оценка R² будет шумной, нейросеть может не обогнать "
                        "линейную модель."
                    ]
                    if small and ok
                    else []
                )
                + ([why_not] if not ok else []),
                primary=ok,
                runnable=ok,
            )
        )
        ok2, why_not2 = _rows_note(rows, MIN_ROWS["predictive-check"])
        recs.append(
            Recommendation(
                key="predictive-check",
                template="predictive-check",
                title="Быстрая проверка без нейросети: линейная модель и бустинг",
                method_title=TEMPLATES["predictive-check"].title,
                params=dict(base),
                why=[
                    "Отвечает на тот же вопрос — предсказывают ли входы показатель — за минуты, а не часы.",
                    "Если она не хуже нейросети, нелинейная модель для этих данных не нужна.",
                ]
                + (["Текстовые параметры Z этот метод не учитывает."] if cats else []),
                warnings=[why_not2] if not ok2 else [],
                primary=not ok and ok2,
                runnable=ok2,
            )
        )
    else:
        compare = numeric[:MAX_COMPARE]
        if len(compare) < 2:
            raise ValueError(
                "В данных меньше двух числовых столбцов — сравнивать нечего; выберите показатель"
            )
        task = {
            "key": "agreement",
            "title": "Согласованность показателей",
            "text": "Показатель не выбран: сравним числовые столбцы между собой — "
            "сходятся ли они в оценке одних и тех же компаний.",
        }
        ok, why_not = _rows_note(rows, MIN_ROWS["rank-agreement"])
        recs.append(
            Recommendation(
                key="rank-agreement",
                template="rank-agreement",
                title="Ранговая корреляция показателей",
                method_title=TEMPLATES["rank-agreement"].title,
                params={"columns": compare, "invert": [], "sheet": t.sheet},
                why=[
                    "Без целевого показателя задача — сравнить показатели между собой: нейросеть здесь не нужна.",
                    f"Сравниваются {len(compare)} числовых столбцов"
                    + (
                        f" (первые {MAX_COMPARE} — остальные можно добавить)"
                        if len(numeric) > MAX_COMPARE
                        else ""
                    )
                    + ": ρ Спирмена, бутстреп-интервал, перестановочный тест.",
                    "У шкал «больше — хуже» (риск) отметьте обращение — иначе знак связи перевернётся.",
                ],
                warnings=[why_not] if not ok else [],
                primary=ok,
                runnable=ok,
            )
        )
    return {
        "columns": t.columns,
        "numeric": numeric,
        "categories": cats,
        "sheet": t.sheet,
        "sheets": t.sheets,
        "rows": rows,
        "target_candidates": target_candidates(node, t),
        "task": task,
        "recommendations": [asdict(r) for r in recs],
    }


def question(template: str, params: dict[str, Any]) -> str:
    """Вопрос проверки словами — в поле «гипотеза» карточки, когда идеи для проверки нет."""
    if template == "rank-agreement":
        cols = params.get("columns") or []
        return f"Согласуются ли показатели {', '.join(map(str, cols))} между собой?"
    feats = params.get("features") or []
    shown = ", ".join(map(str, feats[:6])) + (f" и ещё {len(feats) - 6}" if len(feats) > 6 else "")
    return f"Предсказывают ли {shown} показатель «{params.get('target', '')}» лучше среднего и плацебо?"
