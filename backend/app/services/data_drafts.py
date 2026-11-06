"""Черновики датасетов из таблиц статей: операции правки, предложения Qwen, CSV.

Правка черновика — только операции из OPS: так правят и люди (кнопки на странице), и Qwen (команда
словами → список операций, задача `table_edit`). Код Qwen не пишет и не исполняет: модель выбирает
операции, применяет их платформа, и каждая правка с её операциями пишется в журнал черновика.
"""

import csv
import io
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DataDraft, QwenJob

MAX_ROWS = 5000
MAX_COLS = 60
CELL = 300  # знаков в текстовой ячейке
MISSING = {"", "-", "–", "—", "−", "н/д", "нд", "n/a", "na", "nan", "…", "..."}
GROUPED_SPACE = re.compile(r"[-+]?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?")
GROUPED_COMMA = re.compile(r"[-+]?\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?|[-+]?\d{1,3}(?:,\d{3})+\.\d+")
GROUPED_DOT = re.compile(r"[-+]?\d{1,3}(?:\.\d{3})+,\d+|[-+]?\d{1,3}(?:\.\d{3}){2,}")
PLAIN = re.compile(r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)")
TESTS = ("empty", "equals", "contains", "less", "greater")

Cell = float | str | None


class OpError(ValueError):
    """Понятная человеку причина, по которой операцию не применить."""


def number(text: object) -> float | None:
    """Число из ячейки (те же правила, что у разбора таблиц runner/qwen/tables.py)."""
    if isinstance(text, bool):
        return None
    if isinstance(text, int | float):
        return float(text)
    s = str(text or "").strip().replace("−", "-").replace("–", "-").rstrip("%").strip()
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


def clean_cell(v: object) -> Cell:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    s = " ".join(str(v).split())[:CELL]
    return s or None


def clean_table(columns: object, rows: object) -> tuple[list[str], list[list[Cell]]]:
    """Таблица из чужих рук (обработчик, форма): размеры, пустые и повторные имена столбцов."""
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise OpError("Таблица — список столбцов и список строк")
    cols = [" ".join(str(c or "").split())[:120] for c in columns][:MAX_COLS]
    if not cols:
        raise OpError("В таблице нет столбцов")
    seen: dict[str, int] = {}
    for j, c in enumerate(cols):
        c = c or f"столбец {j + 1}"
        k = seen.get(c, 0)
        seen[c] = k + 1
        cols[j] = c if k == 0 else f"{c} ({k + 1})"
    out = []
    for r in rows[:MAX_ROWS]:
        vals = list(r) if isinstance(r, list) else []
        vals = (vals + [None] * len(cols))[: len(cols)]
        out.append([clean_cell(v) for v in vals])
    return cols, out


def _col(columns: list[str], name: object) -> int:
    if not isinstance(name, str) or name not in columns:
        raise OpError(f"Нет столбца «{name}»")
    return columns.index(name)


def _match(v: Cell, test: str, value: object) -> bool:
    if test == "empty":
        return v is None
    if v is None:
        return False
    if test == "equals":
        num = number(value)
        return v == num if isinstance(v, float) and num is not None else str(v) == str(value)
    if test == "contains":
        return str(value).lower() in str(v).lower()
    a, b = (v if isinstance(v, float) else number(v)), number(value)
    if a is None or b is None:
        return False
    return a < b if test == "less" else a > b


def apply(
    columns: list[str], rows: list[list[Cell]], ops: list[dict[str, Any]]
) -> tuple[list[str], list[list[Cell]], list[str]]:
    """Операции по порядку; возвращает новую таблицу и что сделано (по-русски). Ошибка — OpError,
    таблица тогда не меняется (работа идёт на копии)."""
    cols, data = list(columns), [list(r) for r in rows]
    done: list[str] = []
    if not isinstance(ops, list) or not ops:
        raise OpError("Нет операций")
    for op in ops[:50]:
        if not isinstance(op, dict):
            raise OpError("Операция — объект с полем op")
        kind = op.get("op")
        if kind == "rename":
            j = _col(cols, op.get("column"))
            to = " ".join(str(op.get("to") or "").split())[:120]
            if not to or (to in cols and to != cols[j]):
                raise OpError(f"Новое имя столбца пустое или уже есть: «{to}»")
            done.append(f"столбец «{cols[j]}» → «{to}»")
            cols[j] = to
        elif kind in ("drop_columns", "keep_columns"):
            names = op.get("columns")
            if not isinstance(names, list) or not names:
                raise OpError("Не указаны столбцы")
            idx = [_col(cols, n) for n in names]
            keep = [j for j in range(len(cols)) if j not in idx] if kind == "drop_columns" else idx
            if not keep:
                raise OpError("Нельзя убрать все столбцы")
            done.append(
                ("убраны столбцы: " if kind == "drop_columns" else "оставлены столбцы: ")
                + ", ".join(f"«{n}»" for n in names)
            )
            cols, data = [cols[j] for j in keep], [[r[j] for j in keep] for r in data]
        elif kind == "drop_rows":
            nums = op.get("rows")
            if not isinstance(nums, list) or not nums or not all(isinstance(i, int) for i in nums):
                raise OpError("Строки — список номеров")
            bad = [i for i in nums if not 0 <= i < len(data)]
            if bad:
                raise OpError(f"Нет строк с номерами {', '.join(str(i + 1) for i in bad)}")
            data = [r for i, r in enumerate(data) if i not in set(nums)]
            done.append(f"убраны строки: {', '.join(str(i + 1) for i in sorted(nums))}")
        elif kind in ("drop_rows_where", "keep_rows_where"):
            j = _col(cols, op.get("column"))
            test = op.get("test")
            if test not in TESTS:
                raise OpError(f"Условие — одно из: {', '.join(TESTS)}")
            hit = [_match(r[j], str(test), op.get("value")) for r in data]
            before = len(data)
            data = [r for r, h in zip(data, hit, strict=True) if h == (kind == "keep_rows_where")]
            word = {
                "empty": "пусто",
                "equals": "=",
                "contains": "содержит",
                "less": "<",
                "greater": ">",
            }[str(test)]
            cond = f"«{cols[j]}» {word}" + ("" if test == "empty" else f" {op.get('value')}")
            done.append(
                f"{'оставлены' if kind == 'keep_rows_where' else 'убраны'} строки, где {cond}: "
                f"было {before}, стало {len(data)}"
            )
        elif kind == "set_cell":
            i, j = op.get("row"), _col(cols, op.get("column"))
            if not isinstance(i, int) or not 0 <= i < len(data):
                raise OpError(f"Нет строки {i}")
            raw = op.get("value")
            num = number(raw)
            data[i][j] = num if num is not None else clean_cell(raw)
            shown = data[i][j] if data[i][j] is not None else "пусто"
            done.append(f"ячейка: строка {i + 1}, «{cols[j]}» = {shown}")
        elif kind == "to_number":
            j = _col(cols, op.get("column"))
            lost = 0
            for r in data:
                v = r[j]
                n = v if isinstance(v, float) else number(v)
                lost += v is not None and n is None
                r[j] = n
            done.append(
                f"«{cols[j]}» — числа" + (f" (не числа стали пропуском: {lost})" if lost else "")
            )
        elif kind == "scale":
            j = _col(cols, op.get("column"))
            f = number(op.get("factor"))
            if f is None or f == 0:
                raise OpError("Множитель — число, не ноль")
            for r in data:
                if isinstance(r[j], float):
                    r[j] = r[j] * f  # type: ignore[operator]
            done.append(f"«{cols[j]}» × {f:g}")
        elif kind == "add_column":
            name = " ".join(str(op.get("name") or "").split())[:120]
            if not name or name in cols:
                raise OpError(f"Имя нового столбца пустое или уже есть: «{name}»")
            raw = op.get("value")
            val = number(raw) if number(raw) is not None else clean_cell(raw)
            cols.append(name)
            for r in data:
                r.append(val)
            done.append(f"добавлен столбец «{name}» = {val}")
        elif kind == "sort":
            j = _col(cols, op.get("column"))
            desc = bool(op.get("descending"))
            data.sort(
                key=lambda r: (r[j] is None, r[j] if isinstance(r[j], float) else str(r[j] or "")),
                reverse=False,
            )
            if desc:
                filled = [r for r in data if r[j] is not None][::-1]
                data = filled + [r for r in data if r[j] is None]
            done.append(f"сортировка по «{cols[j]}»" + (" по убыванию" if desc else ""))
        elif kind == "transpose":
            labels = [
                str(r[0]) if r[0] is not None else f"строка {i + 1}" for i, r in enumerate(data)
            ]
            if len(labels) > MAX_COLS:
                raise OpError(f"После поворота столбцов было бы {len(labels)} — больше {MAX_COLS}")
            new_cols = [cols[0], *labels]
            data = [[cols[j], *[r[j] for r in data]] for j in range(1, len(cols))]
            cols, data = clean_table(new_cols, data)
            done.append("таблица повёрнута: строки стали столбцами")
        else:
            raise OpError(f"Неизвестная операция «{kind}»")
    return cols, data, done


def note(
    draft: DataDraft, kind: str, who: str, text: str, ops: list[dict[str, Any]] | None = None
) -> None:
    draft.history = [
        *(draft.history or []),
        {
            "at": datetime.now(UTC).isoformat(),
            "who": who,
            "kind": kind,
            "text": text[:2000],
            "ops": ops or [],
        },
    ]


def edit(
    draft: DataDraft, ops: list[dict[str, Any]], kind: str, who: str, text: str = ""
) -> list[str]:
    current = [[clean_cell(v) for v in r] for r in draft.rows or []]
    cols, rows, done = apply(list(draft.columns or []), current, ops)
    draft.columns, draft.rows = cols, rows
    note(draft, kind, who, (text + ": " if text else "") + "; ".join(done), ops)
    return done


def fmt(v: Cell) -> str:
    """Число в CSV без потери знаков: 5838951.7, а не 5.83895e+06."""
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    return v


def to_csv(draft: DataDraft) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(draft.columns)
    for r in draft.rows:
        w.writerow([fmt(clean_cell(v)) for v in r])
    return buf.getvalue()


def provenance(draft: DataDraft) -> str:
    """Откуда данные и что с ними сделано — в описание датасета."""
    src = f"Таблица {draft.table_number}" + (f" (с. {draft.page})" if draft.page else "")
    src += f" статьи «{draft.article_title}»" if draft.article_title else f" статьи {draft.doc_id}"
    src += f", DOI {draft.doi}" if draft.doi else ""
    lines = [f"Источник: {src}; KBRAG {draft.kb_path}/{draft.doc_id}."]
    if not draft.doi:
        lines.append("DOI нет — требует источника: найдите ссылку на статью, прежде чем опираться на эти данные.")
    # таблица из статьи — производные данные (правило 8): условия задаёт сама статья
    lines.append("Условия использования определяет статья: при публикации результатов ссылайтесь на неё и проверьте её лицензию.")
    if draft.caption:
        lines.append(f"Подпись в статье: {draft.caption[:500]}")
    steps = [
        str(h.get("text"))
        for h in draft.history or []
        if h.get("kind") in ("parse", "manual", "qwen")
    ]
    if steps:
        lines.append("Обработка: " + "; ".join(steps)[:3000])
    return "\n".join(lines)


def known(db: Session) -> list[list[Any]]:
    """Какие таблицы статей уже разобраны (любой статус): обработчик их снова не предлагает."""
    return [[d, n] for d, n in db.execute(select(DataDraft.doc_id, DataDraft.table_number))]


def create_from_result(db: Session, job: QwenJob, result: dict[str, Any]) -> list[int]:
    """Таблицы-наблюдения от обработчика → черновики (повтор той же таблицы статьи — нет)."""
    have = {(d, n) for d, n in known(db)}
    created = []
    for item in result.get("drafts") or []:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("doc_id") or "")[:512]
        num = item.get("table_number")
        if not doc_id or not isinstance(num, int) or (doc_id, num) in have:
            continue
        try:
            cols, rows = clean_table(item.get("columns"), item.get("rows"))
        except OpError:
            continue
        if len(rows) < 3:
            continue
        page = item.get("page")
        d = DataDraft(
            doc_id=doc_id,
            kb_path=str(item.get("kb_path") or "esg")[:256],
            article_title=str(item.get("article_title") or "")[:1024],
            doi=str(item.get("doi") or "")[:256],
            table_number=num,
            page=page if isinstance(page, int) else None,
            caption=str(item.get("caption") or "")[:4000],
            title=str(item.get("title") or "")[:512],
            description=str(item.get("description") or "")[:4000],
            columns=cols,
            rows=rows,
            qwen_job_id=job.id,
            history=[],
        )
        for n in item.get("notes") or []:
            note(d, "parse", "разбор таблицы", str(n))
        db.add(d)
        db.flush()
        have.add((doc_id, num))
        created.append(d.id)
    return created


def apply_edit_result(db: Session, job: QwenJob, result: dict[str, Any]) -> str:
    """Команда словами → операции Qwen → правка черновика. Возвращает сообщение задачи."""
    draft = db.get(DataDraft, int(str(job.payload.get("draft") or 0)))
    if draft is None or draft.status != "proposed":
        return "Черновик уже рассмотрен — правка не нужна"
    command = str(job.payload.get("command") or "")
    ops = result.get("ops") or []
    explanation = str(result.get("explanation") or "")[:1000]
    if not ops:
        note(
            draft,
            "qwen",
            "Qwen",
            f"Команда «{command}»: правок нет — {explanation or 'модель не нашла операций'}",
        )
        return f"Правок нет: {explanation}"
    try:
        done = edit(
            draft,
            ops,
            "qwen",
            "Qwen",
            f"Команда «{command}»" + (f" ({explanation})" if explanation else ""),
        )
    except OpError as exc:
        note(draft, "qwen", "Qwen", f"Команда «{command}» не выполнена: {exc}", ops)
        return f"Не выполнено: {exc}"
    return "Сделано: " + "; ".join(done)


def context(draft: DataDraft, command: str) -> dict[str, Any]:
    """Что видит Qwen для команды: шапка, начало таблицы, подпись, журнал."""
    return {
        "draft": draft.id,
        "command": command,
        "title": draft.title,
        "description": draft.description,
        "caption": draft.caption,
        "article_title": draft.article_title,
        "columns": draft.columns,
        "rows": draft.rows[:40],
        "row_count": len(draft.rows),
        "history": [str(h.get("text")) for h in (draft.history or [])[-10:]],
    }
