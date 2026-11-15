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
from app.services.net_catalog import NETS, NEURAL, TASKS
from app.services.run_templates import TEMPLATES

# сколько строк без пропусков нужно методу (runner/methods/*.py: MIN_ROWS и проверки в main)
MIN_ROWS = {"lab-mlp": 20, "predictive-check": 30, "rank-agreement": 5, "correlation-scan": 40}
MAX_COMPARE = 8  # столбцов в согласованности по умолчанию: пар — до 28
MAX_SCAN = 40  # столбцов в поиске связей: пар — до 780 (runner/methods/correlation_scan.py)
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
# слова, которые есть почти в каждом пункте методики — по ним столбцы не сравниваются
GENERIC = {"esg", "показатель", "показатели", "компании", "компаний", "данные", "задание"}
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
    net: str = ""  # сеть из каталога (app/services/net_catalog.py)
    as_authors: bool = False  # повтор с сетью из статьи-источника
    evidence: str = ""  # цитата статьи, по которой определена сеть авторов


def _columns(n: int) -> str:
    """«1 числовой столбец», «4 числовых столбца», «5 числовых столбцов»."""
    d, dd = n % 10, n % 100
    if d == 1 and dd != 11:
        return f"{n} числовой столбец"
    if 2 <= d <= 4 and not 12 <= dd <= 14:
        return f"{n} числовых столбца"
    return f"{n} числовых столбцов"


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
    words = _words(text) - GENERIC
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
            scored.append((score, c, why, bool(reasons)))
    # есть совпадения по смыслу результата (ROA, выручка…) — только они: общие слова пункта
    # («инвестиции» в «ESG-инвестиции → ROA») чаще описывают входы, а не результат
    if any(r for *_, r in scored):
        scored = [s for s in scored if s[3]]
    # при равном сходстве — более поздний год: его и предсказываем, ранний идёт как прошлый период
    scored.sort(key=lambda s: (-s[0], -_year(s[1]), t.columns.index(s[1])))
    return [{"column": c, "reason": why} for _, c, why, _ in scored[:5]]


# столбцы-идентификаторы и годы строк — не показатели, во входы не идут
ID_LIKE = re.compile(r"(id|инн|огрн|окпо|код|номер|n|№|year|год|fiscal year|отчётный год)")


def _bare(column: str) -> str:
    return re.sub(r"[\[\]()]", "", column).strip().lower()


# год строки — признак панели (компания × год): тогда строки одной компании не независимы
PANEL_YEAR = re.compile(r"(year|год|fiscal year|отчётный год|период|period)")


def panel_group(t: Table) -> str:
    """Столбец-группа панели для поиска связей: при столбце года — текстовый столбец с наибольшим
    числом разных значений в первых строках (страна, компания). Если это не панель и значения
    в нём не повторяются, усреднение по нему ничего не меняет; пусто — года нет."""
    if not any(PANEL_YEAR.fullmatch(_bare(c)) for c in t.columns):
        return ""
    best, levels = "", 1
    for j, c in enumerate(t.columns):
        if c in t.numeric or PANEL_YEAR.fullmatch(_bare(c)):
            continue
        n = len({str(r[j]).strip() for r in t.sample if j < len(r) and _filled(r[j])})
        if n > levels:
            best, levels = c, n
    return best


def _same_indicator(a: str, b: str) -> bool:
    """«ROA 2022» и «ROA 2021» — один показатель за разные годы."""

    def stem(c: str) -> str:
        return re.sub(r"[\s_\-]+", " ", YEAR.sub("", _bare(c))).strip()

    return bool(stem(a)) and stem(a) == stem(b)


def _year(column: str) -> int:
    years = [int(m.group(0)) for m in YEAR.finditer(column)]
    return max(years, default=0)


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
    t: Table,
    rows: int | None,
    target: str,
    node: MethodologySection | None,
    authors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Тип задачи и рекомендации по данным. target — выбранный показатель (пусто — не выбран);
    authors — сеть из статьи-источника идеи (net_catalog.authors_net + article_title)."""
    numeric = [c for c in t.columns if c in t.numeric]
    cats = categories(t)
    recs: list[Recommendation] = []
    if target:
        if target not in numeric:
            raise ValueError(f"Показатель «{target}» — не числовой столбец этой версии данных")
        lag = guess_lag(target, numeric)
        # во входы не берём: будущие годы того же показателя (утечка ответа) и номера/годы строк
        future = [
            c
            for c in numeric
            if c != target and _same_indicator(c, target) and _year(c) > _year(target)
        ]
        ids = [c for c in numeric if ID_LIKE.fullmatch(_bare(c))]
        features = [c for c in numeric if c not in (target, lag, *future, *ids)]
        if not features:
            raise ValueError(
                "Кроме показателя, в данных нет числовых столбцов — предсказывать не по чему"
            )
        task = {
            "key": "predict",
            "title": "Прогноз числового показателя",
            "text": f"Предсказать «{target}» по остальным показателям: постановка лаборатории R = f(X, Z).",
        }
        # панель (компания × год): проверка — на компаниях, которых не было в обучении; компания — не Z
        group = panel_group(t)
        cats = [c for c in cats if c != group]
        base = {"target": target, "features": features, "group": group, "sheet": t.sheet}
        small = rows is not None and rows < SMALL
        ok, why_not = _rows_note(rows, MIN_ROWS["lab-mlp"])
        mlp_why = [
            "Задача — предсказать числовой результат R по входам X: это постановка лаборатории, п. 3.1 методики.",
            f"Входы X — {_columns(len(features))}"
            + (
                f"; параметры Z — {', '.join(cats)} (категории, учитываются отдельно)"
                if cats
                else ""
            )
            + ".",
            "Протокол CR-01 встроен: 30 разбиений, плацебо, сравнение с линейной моделью — "
            "видно, нужна ли нейросеть вообще.",
        ]
        if group:
            mlp_why.append(
                f"Строки повторяются по годам — проверка на «{group}», которых не было в обучении: "
                "иначе модель узнаёт объект по его прошлым годам, и R² завышен."
            )
        if lag:
            mlp_why.append(
                f"«{lag}» похож на прошлый период показателя — добавлен прогноз «как в прошлом году»."
            )
        if future:
            mlp_why.append(
                f"Не во входах: {', '.join(future)} — более поздние значения того же показателя, "
                "по ним прогноз «подсмотрел» бы ответ."
            )
        recs.append(
            Recommendation(
                key="lab-mlp:mlp",
                template="lab-mlp",
                title="Нейросеть лаборатории (перцептрон) с вкладом факторов",
                method_title=TEMPLATES["lab-mlp"].title,
                params={**base, "context": cats, "lag": lag, "architecture": "mlp"},
                why=mlp_why,
                net="mlp",
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
        recs.append(
            Recommendation(
                key="lab-mlp:transformer",
                template="lab-mlp",
                title="Замена сети: трансформер для таблиц",
                method_title=TEMPLATES["lab-mlp"].title,
                params={**base, "context": cats, "lag": lag, "architecture": "transformer"},
                why=[
                    "Та же задача и тот же протокол CR-01, другая сеть: каждый показатель — отдельный "
                    "токен, сеть сама ищет, какие показатели важны вместе (самовнимание).",
                    "Сравните с перцептроном: если трансформер не лучше, сложная сеть не нужна.",
                ],
                warnings=["Считается в несколько раз дольше перцептрона."]
                + ([why_not] if not ok else []),
                runnable=ok,
                net="transformer",
            )
        )
        ok2, why_not2 = _rows_note(rows, MIN_ROWS["predictive-check"])
        recs.append(
            Recommendation(
                key="predictive-check",
                net="gbm",
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
        # год и номер строки — не показатели: сравнивать их с рейтингами бессмысленно
        indicators = [c for c in numeric if not ID_LIKE.fullmatch(_bare(c))]
        compare = indicators[:MAX_COMPARE]
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
                    f"Сравниваются {_columns(len(compare))}"
                    + (
                        f" (первые {MAX_COMPARE} — остальные можно добавить)"
                        if len(indicators) > MAX_COMPARE
                        else ""
                    )
                    + ": ρ Спирмена, бутстреп-интервал, перестановочный тест.",
                    "У шкал «больше — хуже» (риск) отметьте обращение — иначе знак связи перевернётся.",
                ],
                warnings=[why_not] if not ok else [],
                primary=ok,
                runnable=ok,
                net="rank",
            )
        )
        ok_scan, why_not_scan = _rows_note(rows, MIN_ROWS["correlation-scan"])
        scan_cols = [c for c in numeric if not ID_LIKE.fullmatch(_bare(c))][:MAX_SCAN]
        group = panel_group(t)
        panel = (
            [
                f"Строки повторяются по годам — данные усредняются по «{group}»: один объект — "
                "одно наблюдение. Иначе годы одного объекта считались бы независимыми, и связи "
                "«подтверждались» бы даже на шуме. Ищутся связи между объектами по средним "
                "за период; нужно не меньше 40 объектов."
            ]
            if group
            else []
        )
        recs.append(
            Recommendation(
                key="correlation-scan",
                template="correlation-scan",
                title="Поиск неочевидных связей по всем столбцам",
                method_title=TEMPLATES["correlation-scan"].title,
                params={"columns": scan_cols, "group": group, "sheet": t.sheet},
                why=[
                    "Не знаете, что с чем связано, — платформа переберёт все пары столбцов: "
                    "и прямые связи, и немонотонные (U-образные, пороговые), которые обычная "
                    "корреляция не видит.",
                    f"Пар — {len(scan_cols) * (len(scan_cols) - 1) // 2}. Чтобы не принять "
                    "случайность за находку: поиск на половине строк, подтверждение на другой, "
                    "поправка на множественное сравнение и повтор на перемешанных данных.",
                    *panel,
                    "Подтверждённая связь — кандидат в идею для проверки, а не вывод.",
                ],
                warnings=[why_not_scan] if not ok_scan else [],
                runnable=ok_scan and len(scan_cols) >= 2,
            )
        )
    note = ""
    if authors is not None:
        recs, note = _as_authors(recs, authors, task["key"])
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
        "authors": authors,
        "authors_note": note,
    }


def _as_authors(
    recs: list[Recommendation], authors: dict[str, Any], task: str
) -> tuple[list[Recommendation], str]:
    """Сначала — «как у авторов» (та же сеть, что в статье), потом альтернативы того же типа задачи.
    Сети авторов нет в библиотеке — карточка без запуска и ближайшая доступная замена."""
    net = NETS[authors["net"]]
    article = authors.get("article_title") or "статья-источник"
    evidence = f"В статье «{article}» авторы пишут: «{authors['quote']}»"
    if task not in ("predict",) or net.key == "rank":
        if net.key in NEURAL:
            return recs, (
                f"У авторов — {net.title}. Чтобы повторить их расчёт, выберите целевой показатель: "
                "сеть предсказывает показатель, а не сравнивает показатели между собой."
            )
        return recs, ""
    # тот же метод библиотеки с теми же параметрами сети (линейная регрессия — внутри быстрой проверки)
    same = next(
        (
            r
            for r in recs
            if net.template
            and r.runnable
            and r.template == net.template
            and all(r.params.get(k) == v for k, v in net.params.items())
        ),
        None,
    )
    if same is not None:
        for r in recs:
            r.primary = False
        lead = Recommendation(
            **{
                **asdict(same),
                "key": f"authors:{net.key}",
                "title": f"Как у авторов: {net.title}",
                "why": [
                    evidence,
                    "Сначала повторяем выбор авторов на наших данных — так видно, переносится ли их "
                    "результат; затем сравниваем с заменой сети ниже.",
                    *same.why[1:],
                ],
                "primary": True,
                "as_authors": True,
                "evidence": authors["quote"],
                "net": net.key,  # линейная регрессия авторов считается в быстрой проверке, но сеть — их
            }
        )
        rest = [r for r in recs if r is not same]
        for r in rest:
            if r.net in TASKS["predict"].nets and r.net != net.key:
                r.why = [f"Замена сети авторов ({net.title}) на «{NETS[r.net].title}».", *r.why]
        return [lead, *rest], ""
    nearest = net.nearest
    # сеть в библиотеке есть, но метод на этих данных не считается (мало строк) — так и пишем
    blocked = bool(net.template) and any(r.template == net.template for r in recs)
    reason = (
        next((w for r in recs if r.template == net.template for w in r.warnings), "")
        if blocked
        else ""
    )
    absent = Recommendation(
        key=f"authors:{net.key}",
        template="",
        title=f"Как у авторов: {net.title} — "
        + ("на этих данных не посчитать" if blocked else "в библиотеке пока нет"),
        method_title="",
        params={},
        why=[evidence]
        + ([f"Причина: {reason}."] if reason else [])
        + ([f"Ближайшая доступная замена — «{NETS[nearest].title}»."] if nearest else []),
        runnable=False,
        net=net.key,
        as_authors=True,
        evidence=authors["quote"],
    )
    for r in recs:
        if nearest and r.net == nearest and r.runnable:
            r.why = [f"Ближайшая замена сети авторов ({net.title}).", *r.why]
    return [absent, *recs], ""


def question(template: str, params: dict[str, Any]) -> str:
    """Вопрос проверки словами — в поле «гипотеза» карточки, когда идеи для проверки нет."""
    if template == "correlation-scan":
        cols = params.get("columns") or []
        what = f"{len(cols)} столбцами" if cols else "всеми числовыми столбцами"
        return (f"Какие связи между {what} подтверждаются на отложенной части данных, "
                "а не только на той, где их нашли?")
    if template == "rank-agreement":
        cols = params.get("columns") or []
        return f"Согласуются ли показатели {', '.join(map(str, cols))} между собой?"
    feats = params.get("features") or []
    shown = ", ".join(map(str, feats[:6])) + (f" и ещё {len(feats) - 6}" if len(feats) > 6 else "")
    return f"Предсказывают ли {shown} показатель «{params.get('target', '')}» лучше среднего и плацебо?"
