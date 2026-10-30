"""начальное наполнение: датасеты и эксперименты из docs/SPEC.md, раздел 8

Только реальные записи из ТЗ; чего нет — явные заглушки [...] (CLAUDE.md, правило 7).

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

DATASETS = [
    {
        "code": "DS-01",
        "title": "Dow30 — ESG-рейтинги трёх провайдеров",
        "description": (
            "Оценки S&P, Sustainalytics и MSCI для 30 компаний индекса Dow Jones. "
            "Sustainalytics_normalized — исходная оценка × 2,5, то есть шкала риска "
            "(больше — хуже); перед сравнением с MSCI и S&P обращать."
        ),
        "source_url": "[ссылка на выгрузку]",
        "access_level": "public",
    },
    {
        "code": "DS-02",
        "title": "World Bank WGI",
        "description": "Индикаторы качества государственного управления, API Всемирного банка, "
        "скрипт fetch_wgi_data.py.",
        "source_url": "https://info.worldbank.org/governance/wgi/",
        "access_level": "public",
    },
    {
        "code": "DS-03",
        "title": "Данные резидентов ОЭЗ",
        "description": "ESG-проекты крупных резидентов особой экономической зоны. Статус: ожидается.",
        "source_url": "[ожидается]",
        "access_level": "nda",
    },
    {
        "code": "DS-04",
        "title": "TWSE ESG + MOPS: реконструкция набора Hsu et al. (2025)",
        "description": (
            "194 тайваньские компании: 15 ESG-признаков за 2021 г. (MOPS t214sb02), ROA/ROE за "
            "2021–2022 гг. (t163sb04/t163sb05), отрасль (OpenAPI TWSE). Срез пересобрать "
            "скриптом: исходные выгрузки утрачены."
        ),
        "source_url": "https://mopsov.twse.com.tw",
        "access_level": "public",
    },
    {
        "code": "DS-05",
        "title": "Ранги E/S/G RAEX и методики российских агентств",
        "description": (
            "Шесть срезов рэнкинга RAEX (12.2024–01.2026), 163 компании; шкала Банка России, "
            "веса АКРА и «Эксперт РА» (файл лаборатории ESG.xlsx)."
        ),
        "source_url": "https://raex-rr.com/ESG/ESG_companies/ESG_rating_companies/",
        "access_level": "public",
    },
]

EXPERIMENTS = [
    {
        "code": "EXP-001",
        "title": "Расхождение ESG-рейтингов провайдеров на Dow30",
        "direction": "Напр. 2",
        "status": "review",
        "outcome": "rejected",
        "data_summary": "DS-01 · Dow30 (S&P, Sustainalytics, MSCI)",
        "hypothesis": "ESG-рейтинги разных провайдеров согласованы между собой.",
        "method": "Ранговая корреляция Спирмена",
        "setup": ["Ранговая корреляция Спирмена между оценками трёх провайдеров для 30 компаний."],
        "results": [
            "ρ(S&P, MSCI) = 0,27.",
            "ρ(Sustainalytics, MSCI) = −0,32 в исходном расчёте; после обращения шкалы риска "
            "Sustainalytics — около +0,29.",
            "ρ(S&P, Sustainalytics) ≈ 0,00 (после обращения шкалы ≈ +0,02).",
        ],
        "conclusion": "Гипотеза о согласованности отклонена: связь между провайдерами слабая. "
        "Вывод об обратной связи Sustainalytics–MSCI снят: знак был артефактом шкалы риска.",
        "limitations": [
            "30 компаний, один срез; расхождение −0,32 и −0,29 в разных расчётах нужно сверить."
        ],
        "reproducibility": ["Срез данных: DS-01@[срез]", "Код: [скрипт расчёта]"],
        "report_path": "",
    },
    {
        "code": "EXP-007",
        "title": "Воспроизведение Hsu et al. (2025): прогноз ROA/ROE по ESG-данным "
        "глубоким обучением",
        "direction": "Напр. 1",
        "status": "review",
        "outcome": "rejected",
        "data_summary": "DS-04 · TWSE ESG + MOPS, 194 компании",
        "hypothesis": "Результаты статьи воспроизводятся на тех же открытых источниках: LSTM "
        "даёт R² ≈ 0,7 по ROA/ROE и превосходит бустинг и линейную регрессию.",
        "method": "MLR, XGBoost, LightGBM, LSTM, DT, RF, CNN + Optuna",
        "setup": [
            "ESG 2021 г. → ROA/ROE 2022 г. (регрессия) и рост ROA/ROE (классификация), "
            "разбиение 80/20, seed 42.",
            "Модели статьи: MLR, XGBoost, LightGBM, LSTM, DT, RF, CNN; Optuna, 100 испытаний.",
            "Протокол paper — подбор по тестовой выборке; протокол honest — 5-кратная CV "
            "на обучающей.",
            "Проверки: 30 случайных разбиений, плацебо на перемешанной цели, наивный прогноз "
            "«как в прошлом году».",
        ],
        "results": [
            "LSTM: R² 0,03 / 0,06 (paper) и −0,03 / −0,12 (honest) против 0,71 / 0,72 в статье.",
            "Лучшее на ESG-признаках: LightGBM, honest, R² 0,13 / 0,16.",
            "Классификация: 67–80 % при протоколе paper, 49–67 % при honest; CNN по ROE — F1 = 0.",
            "30 разбиений: средний R² всех моделей от −0,03 до −0,27; наивный прогноз лучше всех.",
            "Плацебо при протоколе paper — R² до 0,35 без всякой связи.",
        ],
        "conclusion": "Гипотеза отклонена. ESG-признаки сами по себе не прогнозируют ROA/ROE "
        "лучше среднего; высокие метрики статьи согласуются с подбором гиперпараметров по тесту.",
        "limitations": [
            "194 компании вместо 179, признак X8 заменён средней зарплатой, финансовые показатели "
            "— из MOPS, а не TEJ.",
            "Протокол paper — прочтение статьи: как авторы использовали тест, не описано.",
            "Один год ESG и горизонт в один год; связи ассоциативные.",
        ],
        "reproducibility": [
            "Код: runner/hsu2025 (build_dataset, replicate_hsu, robustness, lab_method).",
            "Seed: разбиение 42, Optuna 0, повторы 0…29.",
            "Срез данных: [нужно пересобрать — исходные выгрузки утрачены].",
            "Окружение: [версии библиотек не зафиксированы].",
        ],
        "report_path": "docs/experiments/EXP-007_hsu2025_replication.md",
    },
]


def upgrade() -> None:
    datasets = sa.table(
        "datasets",
        sa.column("code", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.Text),
        sa.column("source_url", sa.String),
        sa.column("license", sa.String),
        sa.column("access_level", sa.String),
    )
    op.bulk_insert(datasets, [{"license": "", **d} for d in DATASETS])
    experiments = sa.table(
        "experiments",
        *(sa.column(k) for k in ("code", "title", "direction", "status", "outcome", "data_summary",
                                 "hypothesis", "method", "conclusion", "report_path")),
        *(sa.column(k, sa.JSON) for k in ("setup", "results", "limitations", "reproducibility",
                                          "config")),
    )
    op.bulk_insert(experiments, [{"config": {}, **e} for e in EXPERIMENTS])


def downgrade() -> None:
    codes = [e["code"] for e in EXPERIMENTS]
    op.execute(sa.text("DELETE FROM experiments WHERE code = ANY(:c)").bindparams(c=codes))
    codes = [d["code"] for d in DATASETS]
    op.execute(sa.text("DELETE FROM datasets WHERE code = ANY(:c)").bindparams(c=codes))
