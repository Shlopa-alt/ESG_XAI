#!/usr/bin/env bash
# Проверка фронтенда в контейнере: на машине разработки может не быть Node, а node_modules собран для Linux.
# Без аргументов — вся папка src; с аргументами — ESLint только по этим файлам (пути от frontend/).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && (pwd -W 2>/dev/null || pwd))"
TARGETS="${*:-src}"
MSYS_NO_PATHCONV=1 docker run --rm -e "TARGETS=$TARGETS" -v "$ROOT/frontend:/app" -w /app node:22-alpine sh -c '
  [ -x node_modules/.bin/eslint ] || npm ci --no-audit --no-fund
  status=0
  echo "--- tsc";    npx --no-install tsc --noEmit     || status=1
  echo "--- eslint"; npx --no-install eslint $TARGETS  || status=1
  echo "--- vitest"; npx --no-install vitest run       || status=1
  exit $status
'
