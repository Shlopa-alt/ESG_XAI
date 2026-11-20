"""Каталог компонентов Студии — в JSON для платформы (на сервере нет pandas, движок там не считает).

    python studio/catalog.py > studio/catalog.json

Тест test_studio.py::test_catalog_file_is_current следит, чтобы файл совпадал с кодом.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio.components import catalog  # noqa: E402
from studio.engine import FORMAT  # noqa: E402


def dump() -> str:
    return json.dumps({"format": FORMAT, "components": catalog()}, ensure_ascii=False, indent=1) + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stdout.write(dump())
