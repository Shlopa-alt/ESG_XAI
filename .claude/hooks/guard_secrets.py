"""PreToolUse: не даёт командам оболочки читать секреты, закрытые данные и трогать рабочий сервер.

Правила deny в settings.json закрывают только файловые инструменты, команды оболочки они не видят.
Это защита от случайности, а не граница безопасности: обойти разбор строки команды можно.
Папки с закрытыми данными на этой машине задаёт ESG_PRIVATE_PATHS (через «;»)
в .claude/settings.local.json.
"""

import json
import os
import re
import sys

BLOCKED = [
    (r"(^|[\s\"'=/])\.local([/\s\"']|$)", "папка .local: секреты и настройки туннеля"),
    (r"(^|[\s\"'=/])\.env(?![.\w-])", "файл .env: пароли и токены"),
    (r"deploy/certs", "сертификаты и ключи"),
    (r"51\.250\.71\.182", "рабочий сервер: агенты работают только со стендом 127.0.0.1:5180"),
    (r"docker(\s+|-)compose\b.*\sconfig\b", "docker compose config печатает секреты"),
    (r"docker\s+inspect\b(?!.*--format)", "docker inspect без --format печатает окружение"),
    (r"docker\s+inspect\b.*\bEnv\b", "окружение контейнера содержит секреты"),
    (r"docker\s+(compose\s+)?exec\b.*\b(printenv|env)\b", "окружение контейнера содержит секреты"),
]


def private_paths() -> list[str]:
    """Пути без буквы диска: в Git Bash тот же путь пишется как /c/Users/..., а не C:/Users/..."""
    paths = []
    for raw in os.environ.get("ESG_PRIVATE_PATHS", "").split(";"):
        path = re.sub(r"^[a-z]:", "", raw.strip().replace("\\", "/").lower()).strip("/")
        if path:
            paths.append(path)
    return paths


def reason_to_block(command: str) -> str | None:
    text = command.replace("\\", "/")
    for pattern, reason in BLOCKED:
        if re.search(pattern, text, re.IGNORECASE):
            return reason
    lowered = text.lower()
    if any(path in lowered for path in private_paths()):
        return "папка с данными (возможны данные под NDA, правило домена 6)"
    return None


def main() -> int:
    # В Windows потоки Python по умолчанию не в UTF-8: кириллица в команде и в ответе ломается
    sys.stderr.reconfigure(encoding="utf-8")
    payload = json.loads(sys.stdin.buffer.read())
    reason = reason_to_block(str(payload.get("tool_input", {}).get("command", "")))
    if reason is None:
        return 0
    print(
        f"Команда остановлена: {reason}. Обходить проверку нельзя: "
        "если доступ действительно нужен, попроси человека выполнить команду самому.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
