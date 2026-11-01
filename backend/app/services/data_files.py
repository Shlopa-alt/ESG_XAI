"""Файлы срезов на сервере: путь хоста ↔ путь в контейнере, столбцы таблицы.

Срезы записаны в платформе путями хоста (ESG_DATA_HOST), в контейнере та же папка — ESG_DATA_DIR.
"""

import csv
import re
from pathlib import Path

from app.config import Settings

# буквы рейтингов — порядковая шкала, методы переводят их в числа
RATING_SCALE = {"AAA", "AA", "A", "BBB", "BB", "B", "CCC", "CC", "C", "D"}
NUMBER = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def to_container(settings: Settings, host_path: str) -> Path | None:
    p = host_path.replace("\\", "/")
    host = settings.esg_data_host.replace("\\", "/").rstrip("/")
    if host and p.lower().startswith(host.lower() + "/"):
        return Path(settings.esg_data_dir) / p[len(host) + 1:]
    if p.startswith(settings.esg_data_dir.rstrip("/") + "/"):
        return Path(p)
    return None


def table_columns(path: Path, sample: int = 200) -> tuple[list[str], set[str]]:
    """Столбцы CSV/TSV и какие из них числовые (по первым строкам; пустые значения не мешают,
    буквенная шкала рейтингов AAA…CCC считается числовой). Не таблица — ValueError."""
    if path.suffix.lower() not in (".csv", ".tsv", ".txt"):
        raise ValueError(f"Общие методы читают CSV, а срез — {path.suffix or 'без расширения'}")
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        first = f.readline()
        f.seek(0)
        try:
            dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(first, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(f, dialect)
        columns = [c.strip() for c in next(reader, [])]
        seen: list[set[str]] = [set() for _ in columns]
        ok = [True] * len(columns)
        for i, row in enumerate(reader):
            if i >= sample:
                break
            for j, v in enumerate(row[: len(columns)]):
                v = v.strip()
                if not v:
                    continue
                seen[j].add(v)
                if not (NUMBER.fullmatch(v.replace(",", ".")) or v.upper() in RATING_SCALE):
                    ok[j] = False
    numeric = {c for c, good, vals in zip(columns, ok, seen, strict=True) if good and vals}
    return columns, numeric
