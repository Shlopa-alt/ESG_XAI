"""DS-02: индикаторы качества государственного управления (World Bank WGI) через открытый API.

    py -3.12 runner/wgi/fetch_wgi_data.py <файл.csv>

Одна строка — страна за год, шесть показателей (оценка от примерно −2,5 до 2,5). Только стандартная
библиотека: скачанный файл загружается на платформу новой версией данных DS-02.
"""

import csv
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

API = "https://api.worldbank.org/v2/country/all/indicator/{code}?source=3&format=json&per_page=20000&page={page}"
INDICATORS = {
    "GOV_WGI_CC.EST": "control_of_corruption",
    "GOV_WGI_GE.EST": "government_effectiveness",
    "GOV_WGI_PV.EST": "political_stability",
    "GOV_WGI_RQ.EST": "regulatory_quality",
    "GOV_WGI_RL.EST": "rule_of_law",
    "GOV_WGI_VA.EST": "voice_and_accountability",
}


def fetch(code: str) -> list[dict]:
    rows: list[dict] = []
    page, pages = 1, 1
    while page <= pages:
        req = Request(API.format(code=code, page=page), headers={"User-Agent": "esg-open-research"})
        for attempt in range(4):
            try:
                with urlopen(req, timeout=120) as r:
                    head, data = json.loads(r.read())
                break
            except (OSError, ValueError):
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
        pages = int(head.get("pages") or 1)
        rows += data or []
        page += 1
    return rows


def main(out: Path) -> int:
    table: dict[tuple[str, str, int], dict[str, float]] = {}
    for code, name in INDICATORS.items():
        got = fetch(code)
        print(code, len(got), flush=True)
        for row in got:
            iso3 = row.get("countryiso3code") or ""  # у части стран API код не отдаёт
            if row.get("value") is None:
                continue
            key = (row["country"]["value"], iso3, int(row["date"]))
            table.setdefault(key, {})[name] = float(row["value"])
    out.parent.mkdir(parents=True, exist_ok=True)
    columns = list(INDICATORS.values())
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["country", "iso3", "year", *columns])
        for (country, iso3, year), values in sorted(table.items(), key=lambda kv: (kv[0][0], kv[0][2])):
            w.writerow([country, iso3, year, *[values.get(c, "") for c in columns]])
    print(f"{out}: строк {len(table)}, стран {len({k[0] for k in table})}, годы {min(k[2] for k in table)}–{max(k[2] for k in table)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
