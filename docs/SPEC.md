# Техническое задание: ESG Open Research

## 1. Назначение

Платформа для лаборатории, где исследователи работают с базой знаний по ESG, запускают и просматривают эксперименты и на их основе вносят изменения в методологию. Работает во внутренней сети НИЦ ИИ.

База знаний — отдельный сервис **KBRAG** (репозиторий `6snowyfox6/ESG`): статьи в PDF разбираются на фрагменты с номерами страниц, по ним работают поиск и граф фактов «от — связь — к» с дословной цитатой, которую проверяет код. Платформа не хранит своих карточек статей: она берёт статьи, факты и граф из KBRAG через его API и связывает их с экспериментами и методологией. Дерево баз ESG в KBRAG — ветка `esg` (`esg.lab`, `esg.finance`, `esg.xai`, `esg.causal`, `esg.decision`, `esg.ratings`, `esg.valuation`, `esg.russia`), настройки — `config/kbs/esg`.

Научный контекст: грант лаборатории по применению ИНС в ESG-управлении, два направления:
1. ИНС как система поддержки решений для менеджмента компаний (каузальный граф ESG-факторов и финансовых результатов);
2. ИНС как рекомендательная система для регуляторов и рейтинговых агентств (аудит ESG-методик).

## 2. Экраны (макеты в `design/`)

| Экран | Файл | Суть |
|---|---|---|
| Обзор | `Main.dc.html` | Исследовательский цикл, последние эксперименты, открытые вопросы методологии, новое в БЗ |
| База знаний, список | `Knowledge.dc.html` | Поиск по корпусу KBRAG, статьи с фильтром по ветке `esg.*`, паспорт выбранной статьи (метаданные, фрагменты, факты с цитатами, эксперименты, где она использована), срезы датасетов платформы |
| База знаний, граф | `Graph.dc.html` | Граф фактов KBRAG (сущности и статьи) с наложенными узлами экспериментов платформы; клик подсвечивает связи, внизу — факты о сущности с цитатами |
| Импорт статей | — | Researcher загружает статью PDF-файлом (метаданные — поля формы, OpenAlex по DOI или сам PDF) или по DOI (открытый PDF скачивается); статья встаёт в очередь, её разбирает и кладёт в ветку KBRAG обработчик на сервере; статус виден всем |
| Задачи Qwen | — | Только owner. Состояние модели (выключена / поднимается / работает) и память видеокарты, очередь и история задач Qwen с итогами; кнопки «Достроить граф» и «Проверить модель», снятие задачи с очереди |
| Гипотезы | — | Предложить гипотезу может любой вошедший (в т.ч. reader), с опорой на статью или факт KBRAG; Qwen предлагает гипотезы сама после пополнения базы (импорт статьи, новый срез данных) — по каждому заданию методики, с опорами-цитатами, предложенным датасетом и методом, помечены «предложила Qwen»; рецензент принимает к проверке или отклоняет с объяснением; researcher создаёт из принятой эксперимент |
| Реестр экспериментов | `Experiments.dc.html` | Таблица, фильтр по статусу, выбор для сравнения |
| Карточка эксперимента | `Experiment.dc.html` | Гипотеза, постановка, результат, вывод, влияние на методологию, воспроизводимость, рецензии |
| Запуск экспериментов | `Run.dc.html` | Форма конфигурации, живой поток метрик и логов, очередь сервера |
| Методология | `Methodology.dc.html` | Дерево постановки лаборатории: направление → вариант → задание (направление 1 — ИНС «ESG-инвестиции → результаты»: вариант 1 — задания 1–3, вариант 2 — задание 1, вариант 3 не расписан; направление 2 — ESG-рейтинги). Разделы висят на любом узле и действуют на всё ниже, общие — на всю методику. CR меняет узел или добавляет новый; доска CR, история версий, выгрузка .docx |

## 3. Модель данных

```
User(id, login, full_name, email, role[reader|researcher|reviewer|owner], nda_access bool)

-- Статьи, фрагменты, факты и граф хранит KBRAG; платформа держит только ссылки на них.
KbRef(id, kind[article|fact|entity], kbrag_id, kb_path, title, doi, quote, page,
      fetched_at)                                    -- снимок того, на что сослались
Dataset(id, code UNIQUE, title, description, source_url, license,
        access_level[public|nda], created_by, created_at)
DatasetSnapshot(id, dataset_id, version, sha256, storage_path, row_count, created_at)

ExperimentLink(experiment_id, kb_ref_id, relation[tests|uses_method|replicates|motivated_by])

Hypothesis(id, code H-001 UNIQUE, title, statement, rationale, direction,
           status[proposed|accepted|rejected|testing|tested], decision_note, decided_by,
           experiment_id, author_id, created_at)
HypothesisRef(hypothesis_id, kb_ref_id)                 -- опоры гипотезы в базе знаний
     -- узлы платформы (эксперименты) на графе KBRAG

Experiment(id, code UNIQUE, title, hypothesis, direction, status[draft|planned|running|review|done|failed],
           outcome[confirmed|rejected|inconclusive|null], method, dataset_snapshot_id,
           config JSONB, seed, runner_commit, env_lock, mlflow_run_id,
           result_summary, conclusion, limitations, author_id, created_at, finished_at)
Run(id, experiment_id, status[queued|running|done|failed|stopped], resource[cpu|gpu],
    celery_task_id, mlflow_run_id, started_at, finished_at, time_limit_s)

MethodologySection(id, number, title, stability[stable|draft|contested])
MethodologyVersion(id, version "0.2", sections_content JSONB, notes, created_by, created_at)
ChangeRequest(id, code UNIQUE, section_id, title, description,
              status[proposed|review|accepted|rejected], target_version, author_id, created_at)
CrBasis(cr_id, basis_type[experiment|kb_fact|kb_article], basis_id)

Review(id, target_type[experiment|cr], target_id, reviewer_id, verdict[approve|changes|reject], text, created_at)
AuditLog(id, user_id, action, entity_type, entity_id, payload JSONB, created_at)
```

Инварианты (проверять в сервисном слое и покрыть тестами):
- `ChangeRequest.status = accepted` ⇒ ∃ CrBasis на Experiment(status=done), или на факт KBRAG (KbRef kind=fact с непустой цитатой, прошедший проверку KBRAG), или на статью KBRAG с DOI либо ссылкой на источник; и ∃ Review(verdict=approve).
- Статья KBRAG без DOI и без ссылки на источник помечается «требует источника» и не может быть основанием CR.
- Принятие CR создаёт новую `MethodologyVersion` и меняет `stability` раздела.
- Hypothesis отклоняется только с объяснением (`decision_note`); эксперимент создаётся только из принятой гипотезы, опоры переносятся как ExperimentLink(motivated_by).
- Experiment попадает в реестр (`status=done`) только при заполненных runner_commit, dataset_snapshot_id, env_lock, seed.
- Файлы DatasetSnapshot с `access_level=nda` отдаются только пользователям с `nda_access=true`.

## 4. API (REST, префикс `/api`)

```
POST /auth/login, POST /auth/logout, GET /auth/me

-- прокси к KBRAG (служебный токен KBRAG; роли и NDA проверяет платформа)
GET             /kb/kbs                               (дерево баз esg.*)
GET             /kb/search          ?q=&kb=           (→ KBRAG /api/search)
GET             /kb/articles        ?kb=              (→ /api/documents)
GET             /kb/articles/{doc_id}                 (→ /api/document, /api/article)
GET             /kb/graph           ?kb=&focus=       (→ /api/network + узлы экспериментов из ExperimentLink)
GET             /kb/facts           ?entity=&kb=      (→ /api/facts)
POST            /kb/refs                              (зафиксировать KbRef на статью или факт)
GET             /kb-imports                           (очередь импорта статей, видна всем)
POST            /kb-imports         multipart: file, kb_path, doi?, title?, year?, authors?   (researcher+)
POST            /kb-imports/doi     {doi, kb_path}    (метаданные и открытый PDF — OpenAlex; researcher+)
POST            /kb-imports/{id}/retry                (повтор неудавшегося)
POST            /kb-imports/worker/{requeue|next|{id}/result}   (обработчик на машине KBRAG, X-Import-Token)
GET             /qwen/status                           (модель, видеокарта, очередь — по отметке обработчика)
GET/POST        /qwen/jobs                             (POST — researcher+: graph, ping; повтор той же задачи не создаётся)
POST            /qwen/jobs/{id}/cancel
POST            /qwen/worker/{heartbeat|requeue|peek|next|{id}/result}   (обработчик Qwen, X-Qwen-Token)

GET/POST        /datasets                              (POST — researcher+, код DS-NN по порядку)
GET/PATCH       /datasets/{code}                       (карточка, срезы, эксперименты; NDA — уровень меняет owner)
POST            /datasets/{code}/snapshots             multipart: file, version?  (срез с сайта, sha256 и строки считает сервер)
POST            /datasets/{code}/snapshots/register    {path, version?}  (файл из каталога датасета на сервере)
GET             /datasets/{code}/files                 (файлы каталога датасета; NDA — только owner)
GET             /datasets/{code}
POST            /datasets/{code}/snapshots            (загрузка среза датасета)

GET/POST        /hypotheses                          (POST — любой вошедший)
GET             /hypotheses/{code}
POST            /hypotheses/{code}/refs              (автор или researcher+)
PATCH           /hypotheses/{code}                   (reviewer/owner: accepted | rejected с причиной)
POST            /hypotheses/{code}/experiment        (researcher/owner: эксперимент из принятой)

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

1. Пользователь (researcher+) выбирает шаблон запуска (`backend/app/services/run_templates.py`: расчёт из `runner/`, эксперимент, датасет, параметры с границами, ресурс, лимит времени), срез датасета и параметры.
2. `POST /runs` проверяет параметры и срез, создаёт Run (queued) и ставит задачу `runner.execute` в Celery (брокер Redis, очереди `cpu` и `gpu`); на видеокарте у человека не больше `GPU_RUNS_PER_USER` запусков одновременно.
3. Исполнитель (`runner/worker`, контейнер `runner-cpu`) сверяет sha256 файла среза с записанным, запускает скрипт в окружении ровно по `requirements.lock`, строки вывода и события `@event {...}` (ход, метрики) публикует в Redis — канал `run:{id}` и журнал `run:{id}:log`; метрики, параметры и файлы результатов пишет в MLflow.
4. `GET /runs/{id}/stream` отдаёт SSE: сначала журнал, затем новые события (без пропусков и повторов по `seq`); страница запуска показывает ход, метрики, параметры воспроизводимости и лог.
5. Скрипт пишет `run.json` (коммит, срез, окружение, seed, части, отчёт); исполнитель возвращает его платформе (`/runs/worker/{id}`, токен `RUNNER_TOKEN`). Удачный запуск с чистым коммитом заполняет воспроизводимость эксперимента и его отчёт, как и регистрация `run.json` вручную (`python -m app.manage import-run`).
Остановка: `POST /runs/{id}/stop` (автор или owner) — из очереди снимается сразу (`revoke`), идущий останавливает исполнитель по флагу `run:{id}:stop` (SIGTERM группе процессов), частичные результаты остаются в каталоге результатов. Перезапуск исполнителя помечает его прерванные запуски упавшими.

## 6. Граф связей

- Источник графа — KBRAG: сущности и статьи из `/api/network`, факты «от — связь — к» с цитатой из `/api/facts`. Факты выписывает Qwen3 по правилам `config/kbs/esg/graph-rules.txt` (связи с направлением: «повышает», «снижает», «не влияет на» и др.), код KBRAG проверяет, что цитата есть в статье и содержит оба конца факта; разные написания сводит словарь `synonyms.yaml`.
- Платформа добавляет к графу узлы экспериментов и рёбра из `ExperimentLink`; сам граф фактов в платформе не хранится и не редактируется.
- Отрисовка: Cytoscape.js, раскладка `cose`, фильтр по ветке `esg.*` и по связи, подсветка соседей выбранного узла, внизу — факты о выбранной сущности с цитатами и ссылками на статьи.
- Граф строится на видеокарте сервера KBRAG (RTX 5070 Ti, ~1,3 с на фрагмент); новые статьи достраивают граф без пересчёта готового.

## 7. Безопасность и инфраструктура

- nginx: `allow <подсеть центра>; deny all;`, TLS внутренним сертификатом.
- Вход через LDAP, роли хранятся в БД, назначает owner.
- Импорт статей: PDF проверяется по сигнатуре и размеру (KB_IMPORT_MAX_MB), повтор отсекается по sha256 и DOI; PDF по DOI скачивается только с публичных адресов (проверка на каждом перенаправлении). Файлы — в папке приёма KB_INBOX_DIR: KBRAG ссылается на них, удалять нельзя, папка входит в бэкап.
- AuditLog на все изменяющие действия.
- Нагрузка: `python deploy/loadtest.py site|kbrag --users N --minutes M` — N одновременных пользователей по типичным страницам, задержки p50/p95/max и ошибки по адресам. Замер KBRAG 30.10.2026 (пилот ~300 статей, векторы запроса на процессоре): 10 пользователей — поиск p50 0,9 с / p95 2,5 с, граф и статистика < 0,25 с, 25,6 запроса/с; 25 пользователей — поиск p95 3,9 с, граф p95 1,3 с, ~22 запроса/с, ошибок нет. Узкое место — векторизация запроса BGE-M3 на процессоре; запуски ограничены очередью исполнителя, а не числом зрителей.
- Видеокарта: на ней Qwen3 — по требованию. Задачи Qwen (граф фактов, дальше — гипотезы, предложения экспериментов, отчёты) копятся в очереди `/qwen/jobs`; обработчик `runner/qwen/worker.py` на машине с видеокартой поднимает vLLM, когда есть работа, выполняет задачи по одной и выключает модель после 10 минут простоя (модель, запущенную вручную, не трогает). Импорт статьи сам ставит задачи «достроить граф» и «гипотезы», новый срез данных — «гипотезы» (повтор ждущей задачи не создаётся). Гипотезы: по каждому заданию методики (и направлению без заданий; вариант без заданий пропускается) Qwen составляет короткие поисковые запросы и ключевые сущности, по ним из KBRAG берутся фрагменты статей и факты графа с цитатами; Qwen предлагает до 3 гипотез со ссылками на опоры; второй проход Qwen отклоняет гипотезу, если она не о результате задания, опоры не о том или в ней есть сказанное сверх опор; платформа сохраняет только гипотезы с опорой, без повторов, не больше 3 нерассмотренных от Qwen на задание; метод из библиотеки — только для своего датасета. Чат-бота в платформе нет; разбор импортируемых статей и векторы — на процессоре. Запуск на видеокарте — не больше `GPU_RUNS_PER_USER` на человека; отдельного исполнителя очереди `gpu` пока нет, шаблонов с видеокартой тоже.
- Бэкапы: ежедневный `pg_dump` + копия хранилища срезов данных и MLflow artifacts.

## 8. Начальное наполнение (только реальные данные)

Датасеты платформы:
- DS-01 «Dow30 — ESG-рейтинги трёх провайдеров» (S&P, Sustainalytics, MSCI; 30 компаний). Внимание: `Sustainalytics_normalized` — исходная оценка × 2,5, то есть шкала риска (больше — хуже); перед сравнением с MSCI и S&P обращать.
- DS-02 «World Bank WGI» (API Всемирного банка, скрипт `fetch_wgi_data.py`).
- DS-03 «Данные резидентов ОЭЗ» (статус: ожидается, NDA).
- DS-04 «TWSE ESG + MOPS: реконструкция набора Hsu et al. (2025)» — 194 компании, 15 ESG-признаков за 2021 г., ROA/ROE за 2021–2022 гг.; срез пересобрать скриптом (исходные выгрузки утрачены).
- DS-05 «Ранги E/S/G RAEX и методики российских агентств» — шесть срезов 12.2024–01.2026, 163 компании; шкала Банка России, веса АКРА и «Эксперт РА» (файл лаборатории `ESG.xlsx`).

Эксперименты:
- EXP-001 «Расхождение ESG-рейтингов провайдеров на Dow30» — отчёт `docs/experiments/EXP-001_dow30_ratings.md`, код `runner/dow30`, срез DS-01 от 30.10.2026: ρ Спирмена S&P–MSCI = 0,27; Sustainalytics–MSCI = +0,29 после обращения шкалы риска (−0,29 без обращения; −0,32 — на 27 компаниях вместо 26); S&P–Sustainalytics = +0,02; все 95 % интервалы включают ноль. Гипотеза о согласованности отклонена; вывод об обратной связи Sustainalytics–MSCI снят как артефакт шкалы.
- EXP-007 «Воспроизведение Hsu et al. (2025)» — отчёт `docs/experiments/EXP-007_hsu2025_replication.md`, код `runner/hsu2025`; гипотеза отклонена, повтор на зафиксированном срезе DS-04 воспроизводим; статус review до решения рецензента.

Методология 0.1: разделы по постановке задачи лаборатории для ИНС (входы — ESG-инвестиции по статьям затрат; выходы — финансовые результаты на 3–5 лет; эффекты для бюджета региона и РФ; денежная оценка нефинансовых эффектов через ЧДД; проверка моделей). CR-01 «обязательные проверки моделей», основание — EXP-007.

База знаний (KBRAG): статьи импортируются из корпуса лаборатории (5 996 PDF открытого доступа, 2018+, OpenAlex/DOAJ/КиберЛенинка) и материалов лаборатории (`esg.lab`), а не придумываются. Методы (AHP + KNN, CatBoost + SHAP, методика ЧДД) и стандарты (PRISMA-ScR) — статьи и документы в KBRAG; их коды M-xx и S-xx больше не используются.

## 9. Этапы

1. **Каркас**: репозиторий, docker compose (postgres, redis, mlflow, backend, frontend, nginx), миграции, LDAP-вход, роли, общий layout с боковым меню.
2. **База знаний**: KBRAG с веткой `esg` (пилот ~300 статей, затем весь корпус), прокси `/api/kb/*` со служебным токеном, экран базы знаний поверх KBRAG, датасеты и их срезы, KbRef.
3. **Эксперименты**: реестр, карточка, сравнение, рецензии.
4. **Методология**: разделы, CR с инвариантом принятия, версии, diff, экспорт .docx.
5. **Запуск**: Celery + runner + MLflow + SSE, экран запуска и очередь.
6. **Граф**: граф фактов KBRAG по ветке `esg`, ExperimentLink, экран графа в Cytoscape.
7. **Эксплуатация**: бэкапы, AuditLog, лимиты GPU, нагрузочная проверка.
