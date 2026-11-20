"""Студия, этап 5: импорт из баз данных и экспорт в них (Loginom: «Импорт/Экспорт — База данных»).

Подключения заводит владелец платформы; пароль хранится на сервере зашифрованным. Исполнитель
получает реквизиты от платформы только на время расчёта и только для подключений этого
сценария, процессу расчёта — через переменную окружения STUDIO_CONNECTIONS (не в файлах
результатов). Импорт — только SELECT/WITH одним запросом, сеанс — «только чтение», где это
позволяет СУБД; экспорт — только в подключения, где владелец разрешил запись.
"""

import json
import os
import re
from typing import Any

import pandas as pd

from studio.base import Component, NodeError, Param

Frame = pd.DataFrame
Params = dict[str, Any]
MAX_ROWS = 1_000_000
TIMEOUT_S = 30
DRIVERS = {"postgresql": "postgresql+psycopg", "mysql": "mysql+pymysql", "mssql": "mssql+pymssql",
           "clickhouse": "clickhousedb", "sqlite": "sqlite"}
NAMES = {"postgresql": "PostgreSQL", "mysql": "MySQL / MariaDB", "mssql": "MS SQL Server", "clickhouse": "ClickHouse",
         "sqlite": "SQLite"}


def connections() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(os.environ.get("STUDIO_CONNECTIONS") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _conn(code: str) -> dict[str, Any]:
    c = connections().get(str(code or "").upper())
    if not c:
        raise NodeError(f"Подключение {code}: реквизиты не получены — его удалили или расчёт запущен не с платформы")
    return c


def engine_for(c: dict[str, Any]) -> Any:
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    kind = c.get("kind")
    if kind not in DRIVERS:
        raise NodeError(f"Неизвестный тип базы «{kind}»")
    if kind == "sqlite":
        return create_engine(f"sqlite:///{c['database']}")
    url = URL.create(DRIVERS[kind], username=c.get("username") or None, password=c.get("password") or None,
                     host=c.get("host") or None, port=int(c["port"]) if c.get("port") else None,
                     database=c.get("database") or None)
    args: dict[str, Any] = {}
    if kind == "postgresql":
        args = {"connect_timeout": TIMEOUT_S}
    elif kind == "mysql":
        args = {"connect_timeout": TIMEOUT_S, "read_timeout": 600}
    elif kind == "mssql":
        args = {"login_timeout": TIMEOUT_S, "timeout": 600}
    return create_engine(url, connect_args=args, pool_pre_ping=False)


_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_STRINGS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def check_query(sql: str) -> str:
    """Запрос на чтение: один, начинается с SELECT или WITH, без команд изменения."""
    bare = _COMMENTS.sub(" ", sql).strip().rstrip(";").strip()
    if not bare:
        raise NodeError("База данных: пустой запрос")
    plain = _STRINGS.sub("''", bare)
    if ";" in plain:
        raise NodeError("База данных: только один запрос (без «;» между запросами)")
    first = plain.split(None, 1)[0].upper()
    if first not in ("SELECT", "WITH"):
        raise NodeError("База данных: импорт — только чтение (SELECT или WITH …)")
    banned = re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE|CALL|"
                       r"COPY|ATTACH|DETACH|OPTIMIZE|SYSTEM|INTO\s+OUTFILE)\b", plain, re.I)
    if banned:
        raise NodeError(f"База данных: в запросе «{banned.group(1)}» — импорт только читает")
    return bare


def _read_only(conn: Any, kind: str) -> None:
    from sqlalchemy import text

    if kind == "postgresql":
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = {600 * 1000}"))
    elif kind == "mysql":
        conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
    elif kind == "clickhouse":
        conn.execute(text("SET readonly = 2"))


def read(code: str, sql: str, max_rows: int = MAX_ROWS) -> Frame:
    from sqlalchemy import text

    c = _conn(code)
    query = check_query(sql)
    eng = engine_for(c)
    try:
        with eng.connect() as conn:
            _read_only(conn, c["kind"])
            res = conn.execute(text(query))
            cols = list(res.keys())
            rows = res.fetchmany(max_rows + 1)
    except NodeError:
        raise
    except Exception as exc:  # noqa: BLE001 — ошибка СУБД или сети: человеку — её текст
        raise NodeError(f"База данных {code}: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}") from exc
    finally:
        eng.dispose()
    df = _typed(pd.DataFrame([tuple(r) for r in rows[:max_rows]], columns=cols))
    if len(rows) > max_rows:
        df.attrs["report"] = {"kind": "database", "title": f"Импорт из {code}",
                              "notes": [f"Строк больше {max_rows} — взяты первые {max_rows}; уточните запрос."]}
    return df


def _typed(df: Frame) -> Frame:
    """Типы СУБД — в обычные: numeric/decimal (Decimal) — в числа, UUID и прочее — в текст."""
    from decimal import Decimal

    for c in df.columns:
        s = df[c]
        if s.dtype != object:
            continue
        vals = s.dropna()
        if len(vals) and all(isinstance(v, Decimal) for v in vals):
            df[c] = pd.to_numeric(s.map(lambda v: None if v is None else float(v)), errors="coerce")
        elif len(vals) and not all(isinstance(v, (str, bytes, int, float, bool)) or hasattr(v, "isoformat")
                                   for v in vals):
            df[c] = s.map(lambda v: None if v is None else str(v))
    return df


def import_db(inp: dict[str, Frame], p: Params) -> Frame:
    """Узел импорта: таблицу движок получает через load() — run_scenario вызывает read()."""
    if "data" not in inp:
        raise NodeError("База данных: данные не загружены")
    return inp["data"]


SAFE_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def export_db(inp: dict[str, Frame], p: Params) -> Frame:
    """Экспорт в базу: дописать строки в таблицу или заменить её (создаётся, если нет)."""
    df = inp["in"]
    if os.environ.get("STUDIO_PREVIEW"):  # «Посчитать узел» не пишет в чужую базу
        out = df.copy()
        out.attrs["report"] = {"kind": "database", "title": "Предпросмотр: в базу не записано",
                               "notes": [f"При расчёте сценария строк будет записано: {len(df)}."]}
        return out
    c = _conn(p["connection"])
    if not c.get("allow_write"):
        raise NodeError(f"Подключение {p['connection']}: запись не разрешена владельцем платформы")
    table = str(p["table"]).strip()
    if not SAFE_TABLE.match(table):
        raise NodeError("Экспорт в базу: имя таблицы — латиница, цифры и «_», можно со схемой: схема.таблица")
    schema, _, name = table.rpartition(".")
    mode = p.get("mode", "append")
    if mode not in ("append", "replace"):
        raise NodeError(f"Экспорт в базу: нет способа «{mode}»")
    eng = engine_for(c)
    try:
        df.to_sql(name, eng, schema=schema or None, if_exists=mode, index=False, chunksize=5000, method="multi")
    except Exception as exc:  # noqa: BLE001
        raise NodeError(f"Экспорт в {p['connection']}.{table}: {type(exc).__name__}: {str(exc).splitlines()[0][:300]}") from exc
    finally:
        eng.dispose()
    df = df.copy()
    df.attrs["report"] = {"kind": "database", "title": f"Записано в {p['connection']}: {table}",
                          "summary": [["строк", len(df)], ["способ", "дописать" if mode == "append" else "заменить"]]}
    return df


COMPONENTS = [
    Component("import.database", "База данных", "Импорт",
              "Таблица из внешней базы (PostgreSQL, MySQL, MS SQL, ClickHouse) по запросу SELECT",
              (), (Param("connection", "Подключение", "connection"),
                   Param("query", "Запрос (SELECT … или WITH …)", "sql", default="SELECT * FROM таблица LIMIT 1000"),
                   Param("max_rows", "Строк не больше", "number", required=False, default=MAX_ROWS)),
              import_db, loads=True),
    Component("export.database", "База данных", "Экспорт",
              "Записать таблицу во внешнюю базу: дописать или заменить (если владелец разрешил запись)",
              ("in",), (Param("connection", "Подключение", "connection"),
                        Param("table", "Таблица (схема.таблица)", "text"),
                        Param("mode", "Как записать", "select", default="append",
                              options=(("append", "дописать строки"), ("replace", "заменить таблицу")))),
              export_db),
]
