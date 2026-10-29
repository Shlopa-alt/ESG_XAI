# Техническое задание: ESG Open Research

## 1. Назначение

Платформа для лаборатории, где исследователи ведут базу знаний по ESG, запускают и просматривают эксперименты и на их основе вносят изменения в методологию. Работает во внутренней сети НИЦ ИИ.

Научный контекст: грант лаборатории по применению ИНС в ESG-управлении, два направления:
1. ИНС как система поддержки решений для менеджмента компаний (каузальный граф ESG-факторов и финансовых результатов);
2. ИНС как рекомендательная система для регуляторов и рейтинговых агентств (аудит ESG-методик).

## 2. Экраны (макеты в `design/`)

| Экран | Файл | Суть |
|---|---|---|
| Обзор | `Main.dc.html` | Исследовательский цикл, последние эксперименты, открытые вопросы методологии, новое в БЗ |
| База знаний, список | `Knowledge.dc.html` | Фильтры по типу и направлению, карточки, паспорт выбранной карточки |
| База знаний, граф | `Graph.dc.html` | Граф связей статей, методов, датасетов, экспериментов; клик подсвечивает связи |
| Реестр экспериментов | `Experiments.dc.html` | Таблица, фильтр по статусу, выбор для сравнения |
| Карточка эксперимента | `Experiment.dc.html` | Гипотеза, постановка, результат, вывод, влияние на методологию, воспроизводимость, рецензии |
| Запуск экспериментов | `Run.dc.html` | Форма конфигурации, живой поток метрик и логов, очередь сервера |
| Методология | `Methodology.dc.html` | Разделы и их устойчивость, доска CR, история версий |

## 3. Модель данных

```
User(id, login, full_name, email, role[reader|researcher|reviewer|owner], nda_access bool)

KbCard(id, code UNIQUE, type[method|article|dataset|standard], title, summary,
       direction[1|2|methods|standards], source_url, doi, source_verified bool,
       passport JSONB, access_level[public|nda], created_by, created_at, updated_at)
KbCardRevision(id, card_id, data JSONB, author_id, created_at)        -- история правок
DatasetSnapshot(id, card_id, version, sha256, storage_path, row_count, created_at)

Edge(id, src_type, src_id, dst_type, dst_id,
     relation[cites|describes_method|uses_method|uses_data|follows_protocol|tested_in],
     origin[manual|openalex|crossref], created_at)
     -- узлы графа: KbCard и Experiment

Experiment(id, code UNIQUE, title, hypothesis, direction, status[draft|planned|running|review|done|failed],
           outcome[confirmed|rejected|inconclusive|null], method_card_id, dataset_snapshot_id,
           config JSONB, seed, runner_commit, env_lock, mlflow_run_id,
           result_summary, conclusion, limitations, author_id, created_at, finished_at)
Run(id, experiment_id, status[queued|running|done|failed|stopped], resource[cpu|gpu],
    celery_task_id, mlflow_run_id, started_at, finished_at, time_limit_s)

MethodologySection(id, number, title, stability[stable|draft|contested])
MethodologyVersion(id, version "0.2", sections_content JSONB, notes, created_by, created_at)
ChangeRequest(id, code UNIQUE, section_id, title, description,
              status[proposed|review|accepted|rejected], target_version, author_id, created_at)
CrBasis(cr_id, basis_type[experiment|card], basis_id)

Review(id, target_type[experiment|cr], target_id, reviewer_id, verdict[approve|changes|reject], text, created_at)
AuditLog(id, user_id, action, entity_type, entity_id, payload JSONB, created_at)
```

Инварианты (проверять в сервисном слое и покрыть тестами):
- `ChangeRequest.status = accepted` ⇒ ∃ CrBasis на Experiment(status=done) или KbCard(source_verified=true), и ∃ Review(verdict=approve).
- Принятие CR создаёт новую `MethodologyVersion` и меняет `stability` раздела.
- Experiment попадает в реестр (`status=done`) только при заполненных runner_commit, dataset_snapshot_id, env_lock, seed.
- Файлы DatasetSnapshot с `access_level=nda` отдаются только пользователям с `nda_access=true`.

## 4. API (REST, префикс `/api`)

```
POST /auth/login, POST /auth/logout, GET /auth/me

GET/POST        /cards                ?type=&direction=&q=
GET/PATCH       /cards/{code}
GET             /cards/{code}/revisions
POST            /cards/{code}/snapshots           (загрузка среза датасета)
GET             /graph                ?types=&focus={code}&depth=1
POST/DELETE     /edges
POST            /cards/{code}/resolve-citations   (подтянуть связи «цитирует» по DOI из OpenAlex)

GET/POST        /experiments          ?status=&direction=
GET/PATCH       /experiments/{code}
GET             /experiments/compare  ?codes=EXP-001,EXP-003

POST            /runs                 (конфиг из формы → Celery-задача)
GET             /runs                 (очередь)
GET             /runs/{id}
GET             /runs/{id}/stream     (SSE: события progress, metric, log, status)
POST            /runs/{id}/stop

GET             /methodology          (текущая версия + разделы)
GET             /methodology/versions, /methodology/versions/{v}, /methodology/diff?from=&to=
GET/POST        /change-requests
PATCH           /change-requests/{code}            (смена статуса с проверкой инварианта)
POST            /reviews
GET             /methodology/export.docx
```

## 5. Запуск экспериментов в реальном времени

1. Пользователь собирает конфиг: шаблон, CR или гипотеза, датасет (snapshot), метод, параметры (YAML), ресурс, seed, лимит.
2. `POST /runs` валидирует, фиксирует `runner_commit` и `env_lock`, ставит задачу в Celery (отдельные очереди `cpu` и `gpu`, лимит одновременных GPU-задач на пользователя).
3. Скрипт в `runner/` логирует метрики в MLflow и пишет события в Redis pub/sub канал `run:{id}`.
4. `GET /runs/{id}/stream` транслирует канал в SSE; фронтенд рисует прогресс, график и лог.
5. По завершении создаётся или обновляется Experiment, артефакты (модель, SHAP-значения) лежат в MLflow.
Остановка: `POST /runs/{id}/stop` → `revoke(terminate=True)`, частичные результаты сохраняются.

## 6. Граф связей

- Узлы: карточки БЗ и эксперименты. Рёбра: таблица `Edge`.
- «Цитирует» подтягивается автоматически по DOI (OpenAlex API, при отсутствии — Crossref), остальные связи задаются полями карточек и экспериментов.
- Отрисовка: Cytoscape.js, раскладка `cose` или фиксированная по колонкам типов (как в макете), фильтр типов, подсветка соседей выбранного узла.
- PostgreSQL достаточно; переход на Neo4j обсуждать только при сотнях статей и сложных запросах по путям.

## 7. Безопасность и инфраструктура

- nginx: `allow <подсеть центра>; deny all;`, TLS внутренним сертификатом.
- Вход через LDAP, роли хранятся в БД, назначает owner.
- AuditLog на все изменяющие действия.
- Бэкапы: ежедневный `pg_dump` + копия хранилища срезов данных и MLflow artifacts.

## 8. Начальное наполнение (только реальные данные)

- DS-01 «Dow30 — ESG-рейтинги трёх провайдеров» (S&P, Sustainalytics, MSCI; 30 компаний).
- DS-02 «World Bank WGI» (API Всемирного банка, скрипт `fetch_wgi_data.py`).
- DS-03 «Данные резидентов ОЭЗ» (статус: ожидается, NDA).
- M-01 «AHP + KNN» (бенчмарк, есть скрипт воспроизведения), M-02 «CatBoost + SHAP».
- S-01 «PRISMA-ScR».
- EXP-001 «Расхождение ESG-рейтингов провайдеров на Dow30»: ρ Спирмена S&P–MSCI = 0.27, Sustainalytics–MSCI = −0.32, S&P–Sustainalytics ≈ 0.00; гипотеза о согласованности отклонена.
- Статьи (A-xx) импортировать из карточек статей существующего архива базы знаний, а не придумывать.

## 9. Этапы

1. **Каркас**: репозиторий, docker compose (postgres, redis, mlflow, backend, frontend, nginx), миграции, LDAP-вход, роли, общий layout с боковым меню.
2. **База знаний**: CRUD карточек, паспорт, ревизии, срезы датасетов, список с фильтрами.
3. **Эксперименты**: реестр, карточка, сравнение, рецензии.
4. **Методология**: разделы, CR с инвариантом принятия, версии, diff, экспорт .docx.
5. **Запуск**: Celery + runner + MLflow + SSE, экран запуска и очередь.
6. **Граф**: Edge, импорт цитирований по DOI, экран графа.
7. **Эксплуатация**: бэкапы, AuditLog, лимиты GPU, нагрузочная проверка.
