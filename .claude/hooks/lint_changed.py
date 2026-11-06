"""PostToolUse: сообщает о новых нарушениях ruff в изменённом файле Python.

В репозитории накоплен долг ruff, поэтому сравнение идёт с версией файла в HEAD: старые нарушения
не мешают работать, а новые возвращаются агенту. Сравниваются количества по коду правила: номера
строк при правке сдвигаются, а в тексте E501 меняется длина строки.

ESLint здесь нет: в Docker он идёт больше 30 секунд на файл, см. deploy/review/check-frontend.sh.
"""

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2]).resolve()
SCOPES = ("backend/", "runner/")


def find_ruff() -> str | None:
    for candidate in ("backend/.venv/Scripts/ruff.exe", "backend/.venv/bin/ruff"):
        if (ROOT / candidate).exists():
            return str(ROOT / candidate)
    return shutil.which("ruff")


def check(ruff: str, source: bytes, rel: str) -> list[dict]:
    done = subprocess.run(
        [ruff, "check", "--no-fix", "--output-format=json", "--stdin-filename", rel, "-"],
        input=source, capture_output=True, cwd=ROOT, check=False,
    )
    if done.returncode not in (0, 1):
        raise RuntimeError(done.stderr.decode("utf-8", "replace"))
    return json.loads(done.stdout or b"[]")


def head_version(rel: str) -> bytes:
    done = subprocess.run(["git", "show", f"HEAD:{rel}"], capture_output=True, cwd=ROOT, check=False)
    return done.stdout if done.returncode == 0 else b""


def main() -> int:
    # В Windows потоки Python по умолчанию не в UTF-8: кириллица в пути и в ответе ломается
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    payload = json.loads(sys.stdin.buffer.read())
    raw = payload.get("tool_input", {}).get("file_path") or ""
    if not raw.endswith(".py"):
        return 0
    try:
        rel = Path(raw).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return 0
    if not rel.startswith(SCOPES) or "/.venv/" in rel:
        return 0

    ruff = find_ruff()
    if ruff is None:
        note = "ruff не найден, проверка пропущена: создай backend/.venv (см. .claude/agents/backend-dev.md)."
        output = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note}}
        print(json.dumps(output, ensure_ascii=False))
        return 0

    now = check(ruff, (ROOT / rel).read_bytes(), rel)
    old = check(ruff, head_version(rel), rel)
    added = Counter(item["code"] for item in now) - Counter(item["code"] for item in old)
    if not added:
        return 0

    lines = [f"ruff: новые нарушения в {rel} по сравнению с HEAD ({dict(added)}). Строки с этими кодами:"]
    for item in now:
        if item["code"] in added:
            lines.append(f"  {rel}:{item['location']['row']} {item['code']} {item['message']}")
    print("\n".join(lines[:30]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
