"""Таблицы статей → наблюдения (CSV): из разметки docling, которую хранит KBRAG (<doc_id>.docling.json).

Только код, без модели: структуру и числа разбирают правила, и каждое преобразование записывается в
`notes` — исследователь видит, что сделано с таблицей статьи, прежде чем подтвердить срез.

- шапка — строки, которые docling пометил заголовком, и следующие за ними строки без чисел
  («1 год» под названиями индексов); имя столбца — части шапки через « · »;
- числа: «31,7», «17 053,0», «5,838,951.7», «1.234,5», «−2,7», «18 %»; «-», «—», «н/д» — пропуск;
  ничья рангов «73-74» — середина (73,5); ячейка, где слиплись два числа («115403 1,8»), — пропуск;
- группы рядом (у каждого показателя подстолбцы DC | DEC) — складываются строками со столбцом группы;
- показатели строками и годы столбцами — таблица поворачивается: строка — год;
- итоговые строки («Всего», «Total», «2018-2022» среди отдельных лет) в данные не берутся.

Решить, наблюдения это или результаты (коэффициенты, описательная статистика), помогает
`looks_like_data`; окончательно — Qwen по подписи и человек при подтверждении.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

MISSING = {"", "-", "–", "—", "−", "н/д", "нд", "n/a", "na", "nan", "…", "...", "x", "х"}
YEAR = re.compile(r"(?:19|20)\d{2}")
GROUPED_SPACE = re.compile(r"[-+]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?")
# запятая между разрядами — только если групп две и больше или есть точка дроби: «0,217» — дробь
GROUPED_COMMA = re.compile(r"[-+]?\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?|[-+]?\d{1,3}(?:,\d{3})+\.\d+")
GROUPED_DOT = re.compile(r"[-+]?\d{1,3}(?:\.\d{3})+,\d+|[-+]?\d{1,3}(?:\.\d{3}){2,}")
PLAIN = re.compile(r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)")
TIE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")
TOTAL = re.compile(r"(всего|итого|в среднем|среднее|total|sum|average|mean)\b", re.IGNORECASE)
PERIOD = re.compile(r"(?:19|20)\d{2}\s*[-–—]\s*(?:19|20)\d{2}")
STARS = re.compile(r"\*|^\(\s*-?\d+[.,]\d+\s*\)$")
RESULTS = re.compile(r"regress|coef|estimat|robust|correlat|descriptive|summary stat|variable definit|"
                     r"hypothes|результат\w* (?:регресс|оценк)|регресс|корреляц|описательн|определени\w* перемен|"
                     r"гипотез", re.IGNORECASE)


def number(text: str) -> float | None:
    """Число из ячейки или None (пусто, пометка «нет значения», текст, слипшиеся числа)."""
    s = text.strip().replace("−", "-").replace("–", "-").rstrip("%").strip()
    if s.lower() in MISSING:
        return None
    if GROUPED_SPACE.fullmatch(s):
        return float(re.sub(r"[   ]", "", s).replace(",", "."))
    if GROUPED_COMMA.fullmatch(s):
        return float(s.replace(",", ""))
    if GROUPED_DOT.fullmatch(s):
        return float(s.replace(".", "").replace(",", "."))
    if PLAIN.fullmatch(s):
        return float(s.replace(",", "."))
    return None


def tie(text: str) -> float | None:
    """Ничья рангов «73-74» → 73,5 (разница не больше 5); иначе None."""
    m = TIE.fullmatch(text.strip())
    if m and 0 < int(m[2]) - int(m[1]) <= 5 and int(m[2]) < 1000:  # «2018-2022» — период, не ничья
        return (int(m[1]) + int(m[2])) / 2
    return None


@dataclass
class Table:
    columns: list[str]
    rows: list[list[Any]]  # числа — float, текст — str, пропуск — None
    notes: list[str] = field(default_factory=list)

    def numeric_columns(self) -> list[str]:
        out = []
        for j, c in enumerate(self.columns):
            vals = [r[j] for r in self.rows if r[j] is not None]
            if vals and all(isinstance(v, float) for v in vals):
                out.append(c)
        return out

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(self.columns)
        for r in self.rows:
            w.writerow([_fmt(v) for v in r])
        return buf.getvalue()


def _fmt(v: Any) -> str:
    """Число без потери знаков: 5838951.7, а не 5.83895e+06."""
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    return str(v)


def grid(table: dict[str, Any]) -> tuple[list[list[str]], set[int]]:
    """Сетка текста ячеек и строки, которые docling пометил заголовком."""
    g = [[" ".join(str(c.get("text") or "").split()) for c in row] for row in table["data"].get("grid") or []]
    header = {c["start_row_offset_idx"] for c in table["data"].get("table_cells") or [] if c.get("column_header")}
    return g, header


def _is_num(text: str) -> bool:
    return number(text) is not None or tie(text) is not None


def _value(text: str, notes: set[str]) -> float | str | None:
    v = number(text)
    if v is not None:
        return v
    t = tie(text)
    if t is not None:
        notes.add("ничья рангов вида «73-74» — середина интервала")
        return t
    s = text.strip()
    if s.lower() in MISSING:
        return None
    if re.fullmatch(r"[-+\d\s.,%]+", s):  # цифры, но не число: слиплись соседние ячейки
        notes.add("ячейки, где слиплись числа (например, «115403 1,8»), — пропуск")
        return None
    return s


def _header(g: list[list[str]], flagged: set[int]) -> int:
    """Сколько первых строк — шапка."""
    n = 0
    while n < len(g) and n < 4 and (n in flagged or (n == 0 and not any(_is_num(c) for c in g[0][1:]))):
        n += 1
    n = max(n, 1)
    while n < len(g) - 1 and n < 4 and not any(_is_num(c) for c in g[n] if c):  # «1 год» под шапкой
        n += 1
    return n


def _section(row: list[str]) -> str:
    """Строка — заголовок раздела («2 года» во всех ячейках или только в первой)? Тогда его текст."""
    filled = [c for c in row if c.strip()]
    if not filled or any(_is_num(c) for c in filled):
        return ""
    if len(set(filled)) == 1 and (len(filled) == len(row) or (len(filled) == 1 and row[0].strip())):
        return filled[0] if len(row) > 2 else ""
    return ""


def _names(g: list[list[str]], n: int) -> tuple[list[list[str]], str]:
    """Части шапки по столбцам (повтор растянутой ячейки — один раз). Строка шапки, одинаковая у всех
    столбцов («1 год» под каждым индексом), в имена не идёт: это первый раздел таблицы."""
    same, first = set(), ""
    for i in range(1, n):
        if _section(g[i]):
            same.add(i)
            first = first or _section(g[i])
    out = []
    for j in range(len(g[0])):
        parts: list[str] = []
        for i in (i for i in range(n) if i not in same):
            t = g[i][j] if j < len(g[i]) else ""
            if t and t not in parts:
                parts.append(t)
        out.append(parts)
    return out, first


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in names:
        k = seen.get(name, 0)
        seen[name] = k + 1
        out.append(name if k == 0 else f"{name} ({k + 1})")
    return out


def _groups(parts: list[list[str]], start: int) -> list[str] | None:
    """Подстолбцы-группы: нижняя часть шапки повторяется циклом (DC, DEC, DC, DEC…) под одной верхней."""
    low = [p[-1] if len(p) >= 2 else "" for p in parts[start:]]
    up = [p[-2] if len(p) >= 2 else "" for p in parts[start:]]
    if not low or "" in low:
        return None
    k = len(dict.fromkeys(low))
    if k < 2 or len(low) % k or len(low) // k < 2:
        return None
    cycle = low[:k]
    for i in range(0, len(low), k):
        if low[i:i + k] != cycle or len(set(up[i:i + k])) != 1:
            return None
    return cycle


def parse(table: dict[str, Any]) -> Table | None:
    g, flagged = grid(table)
    if len(g) < 3 or not g[0]:
        return None
    width = max(len(r) for r in g)
    g = [r + [""] * (width - len(r)) for r in g]
    n = _header(g, flagged)
    notes: set[str] = set()
    parts, section = _names(g, n)
    body, sections = [], []
    for r in g[n:]:
        if not any(c.strip() for c in r):
            continue
        if _section(r):
            section = _section(r)
            continue
        body.append(r)
        sections.append(section)
    if len(set(sections)) < 2:
        sections = []  # один раздел на всю таблицу — не столбец
    elif any(sections):
        notes.add(f"таблица из разделов ({', '.join(dict.fromkeys(s for s in sections if s))}) — "
                  "столбец «раздел»")
    text_first = sum(1 for r in body if r[0] and not _is_num(r[0])) >= len(body) * 0.6
    periods = sum(1 for r in body if YEAR.fullmatch(r[0].strip()) or PERIOD.fullmatch(r[0].strip()))
    label_col = 1 if text_first or (body and periods >= len(body) * 0.6) else 0
    groups = _groups(parts, label_col) if n >= 2 else None
    if groups:  # группы рядом → строками со столбцом группы
        k = len(groups)
        heads = [" · ".join(parts[label_col + i][:-1]) for i in range(0, width - label_col, k)]
        columns = ([" · ".join(parts[0]) or "строка"] if label_col else []) + ["группа"] + _unique(heads)
        rows = []
        for ri, r in enumerate(body):
            for gi, gname in enumerate(groups):
                vals = [_value(r[label_col + i + gi], notes) for i in range(0, width - label_col, k)]
                if all(v is None for v in vals):
                    continue
                rows.append(([r[0]] if label_col else []) + [gname] + vals + ([sections[ri]] if sections else []))
        notes.add(f"группы рядом ({', '.join(groups)}) сложены строками, столбец «группа»")
    else:
        columns = _unique([" · ".join(p) or ("строка" if j == 0 else f"столбец {j + 1}")
                           for j, p in enumerate(parts)])
        rows = [[r[0] if label_col else _value(r[0], notes)] + [_value(c, notes) for c in r[1:]]
                + ([sections[ri]] if sections else []) for ri, r in enumerate(body)]
    if sections:
        columns = [*columns, "раздел"]
    t = Table(columns, rows, sorted(notes))
    t = _drop_totals(t, label_col == 1, periods_are_rows=bool(sections))
    labels = [str(r[0]).strip() for r in t.rows]
    if label_col == 1 and labels and all(YEAR.fullmatch(s) for s in labels):
        t.rows = [[float(s), *r[1:]] for s, r in zip(labels, t.rows, strict=True)]
        if t.columns[0] in ("строка", "") or YEAR.fullmatch(t.columns[0]):
            t.columns[0] = "год"
    elif label_col == 1 and labels and all(YEAR.fullmatch(s) or PERIOD.fullmatch(s) for s in labels):
        if t.columns[0] in ("строка", ""):
            t.columns[0] = "период"
    if label_col == 1 and not groups and not sections:
        t = _transpose_years(t)
    t.rows = [r for r in t.rows if any(v is not None for v in r[1 if label_col else 0:])]
    keep = [j for j in range(len(t.columns)) if any(r[j] is not None for r in t.rows)]
    if len(keep) < len(t.columns):
        t.notes.append("пустые столбцы убраны")
        t.columns = [t.columns[j] for j in keep]
        t.rows = [[r[j] for j in keep] for r in t.rows]
    return t


def _drop_totals(t: Table, labelled: bool, periods_are_rows: bool = False) -> Table:
    """Итоговые строки: «Всего», «Total»; «2018-2022» среди отдельных лет — тоже, если только таблица не
    из разделов по горизонту («1 год», «2 года»…), где периоды — сами наблюдения."""
    if not labelled:
        return t
    labels = [str(r[0]) for r in t.rows]
    years = sum(1 for s in labels if YEAR.fullmatch(s.strip()))
    keep, dropped = [], []
    for r, s in zip(t.rows, labels, strict=True):
        if TOTAL.match(s.strip()) or (years >= 3 and not periods_are_rows and PERIOD.fullmatch(s.strip())):
            dropped.append(s)
        else:
            keep.append(r)
    if dropped:
        t.notes.append("итоговые строки не взяты: " + ", ".join(f"«{s}»" for s in dropped[:5])
                       + (" …" if len(dropped) > 5 else ""))
    return Table(t.columns, keep, t.notes)


def _transpose_years(t: Table) -> Table:
    """Показатели строками, годы столбцами → строка — год."""
    years = [c for c in t.columns[1:] if YEAR.fullmatch(c.split(" · ")[-1].strip())]
    if len(years) < 3 or len(years) < (len(t.columns) - 1) * 0.6:
        return t
    idx = [t.columns.index(c) for c in years]
    labels = _unique([str(r[0]) for r in t.rows])
    rows = [[float(YEAR.search(t.columns[j].split(" · ")[-1]).group(0))]  # type: ignore[union-attr]
            + [r[j] for r in t.rows] for j in idx]
    notes = [*t.notes, "показатели были строками, годы — столбцами: таблица повёрнута, строка — год"]
    return Table(["год", *labels], rows, notes)


def caption(doc: dict[str, Any], table: dict[str, Any]) -> str:
    out = []
    for ref in table.get("captions") or []:
        idx = int(str(ref.get("$ref", "")).split("/")[-1] or -1)
        if 0 <= idx < len(doc.get("texts") or []):
            out.append(str(doc["texts"][idx].get("text") or ""))
    return " ".join(" ".join(out).split())


def page(table: dict[str, Any]) -> int | None:
    prov = table.get("prov") or [{}]
    p = prov[0].get("page_no")
    return p if isinstance(p, int) else None


def looks_like_data(t: Table, cap: str) -> tuple[bool, str]:
    """Похоже на наблюдения (а не результаты расчёта)? И почему нет."""
    cells = [v for r in t.rows for v in r if isinstance(v, str)]
    if RESULTS.search(cap):
        return False, "по подписи — результаты или статистика"
    if any(STARS.search(c) for c in cells):
        return False, "звёздочки значимости или t-статистики"
    if len(t.rows) < 10:
        return False, f"строк {len(t.rows)} — меньше 10"
    if len(t.numeric_columns()) < 2:
        return False, "числовых столбцов меньше двух"
    labels = {str(r[0]) for r in t.rows}
    if len(labels & set(t.columns)) >= 3:
        return False, "матрица (строки и столбцы — одни и те же показатели)"
    return True, ""


def tables(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Все таблицы статьи: номер, страница, подпись, разбор, похожа ли на данные."""
    out = []
    for i, raw in enumerate(doc.get("tables") or [], start=1):
        t = parse(raw)
        if t is None or not t.rows:
            continue
        cap = caption(doc, raw)
        ok, why = looks_like_data(t, cap)
        out.append({"number": i, "page": page(raw), "caption": cap, "table": t, "data": ok, "why_not": why})
    return out
