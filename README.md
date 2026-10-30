# ESG_XAI

Материалы по ESG (`docs/ESG.md`) и платформа **ESG Open Research** — внутренний сервис лаборатории НИЦ ИИ.
ТЗ: `docs/SPEC.md`, правила разработки: `CLAUDE.md`, макеты: `design/`.

## Запуск одной командой

```
cp deploy/.env.example deploy/.env        # задайте POSTGRES_PASSWORD и SECRET_KEY
docker compose -f deploy/docker-compose.yml up -d --build
```

Откройте http://localhost:8080. В режиме `AUTH_BACKEND=local` войти можно под любым логином
с паролем `LOCAL_DEV_PASSWORD` — задайте свой: с пустым или `dev` backend не стартует. Роль нового пользователя — `LOCAL_DEV_ROLE`.
Для боевого режима поставьте `AUTH_BACKEND=ldap`, заполните `LDAP_*`, `ALLOWED_SUBNET` и `INITIAL_OWNER_LOGINS`.
Миграции применяются при старте backend.

## Разработка без Docker

```
cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/pytest && .venv/Scripts/ruff check . && .venv/Scripts/mypy app
cd frontend && npm install && npm run dev      # прокси /api -> localhost:8000
npm run lint && npm run build && npm test
```
