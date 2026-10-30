"""Загрузка открытых данных TWSE/MOPS для набора DS-04 (реконструкция Hsu et al., 2025).

    python fetch_mops.py <каталог>

Скачивает в каталог то, что читает build_dataset.py:
  esg_110_{1..7}.html      — сводные таблицы ESG MOPS t214sb02 за отчётный год 110 (2021)
  t163sb04_{110,111}.html  — отчёты о прибылях (годовые, 4 квартал) за 2021 и 2022
  t163sb05_{110,111}.html  — балансы за 2021 и 2022
  company_info.json        — справочник компаний TWSE с отраслью (OpenAPI t187ap03_L)
и пишет manifest.json: адрес, параметры запроса, размер и sha256 каждого файла.
"""

import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
MOPS = "https://mopsov.twse.com.tw/mops/web"
ESG_YEAR = 110


def requests_plan() -> list[tuple[str, str, dict[str, str] | None]]:
    plan: list[tuple[str, str, dict[str, str] | None]] = []
    for issue in range(1, 8):
        plan.append((f"esg_{ESG_YEAR}_{issue}.html", f"{MOPS}/ajax_t214sb02", {
            "encodeURIComponent": "1", "step": "2", "firstin": "1", "off": "1", "TYPEK": "sii",
            "MAR_KIND": "sii", "BCODE": "", "ISSUE": str(issue), "EYEAR": str(ESG_YEAR)}))
    for kind in ("t163sb04", "t163sb05"):
        for year in (110, 111):
            plan.append((f"{kind}_{year}.html", f"{MOPS}/ajax_{kind}", {
                "encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1",
                "isQuery": "Y", "TYPEK": "sii", "year": str(year), "season": "04"}))
    plan.append(("company_info.json", "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", None))
    return plan


def fetch(url: str, form: dict[str, str] | None, tries: int = 5) -> bytes:
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read()
            if len(body) > 500:
                return body
        except Exception as exc:  # noqa: BLE001 — сеть: повторяем с паузой
            print(f"  повтор {i + 1}: {exc}", flush=True)
        time.sleep(5 * (i + 1))
    raise RuntimeError(f"не скачалось: {url} {form}")


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for name, url, form in requests_plan():
        body = fetch(url, form)
        (out / name).write_bytes(body)
        files.append({"file": name, "url": url, "form": form, "bytes": len(body),
                      "sha256": hashlib.sha256(body).hexdigest()})
        print(f"{name}: {len(body)} байт", flush=True)
        time.sleep(3)  # MOPS не любит частые запросы
    manifest = {"source": "TWSE/MOPS", "fetched_at": datetime.now(UTC).isoformat(), "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
