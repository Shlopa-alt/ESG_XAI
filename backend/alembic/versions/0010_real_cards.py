"""реальные карточки вместо заглушек: источник DS-01, статус DS-03, EXP-001 по расчёту, гипотезы

DS-01 — выгрузка с Яндекс.Диска лаборатории (паспорт набора: Kaggle, Jennifer A. Duffy).
EXP-001 — результаты runner/dow30/run_exp001.py на срезе DS-01 от 30.10.2026 (запуск #2).
H-001, H-002 — гипотезы, из которых созданы EXP-001 и EXP-007, с опорами в KBRAG.
Миграция идемпотентна: на базе, где данные уже исправлены вручную, ничего не дублирует.

Revision ID: 0010
Revises: 0009
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

DS01 = {
    "source_url": "https://disk.yandex.ru/d/Rk1w36l_sMSZ6Q",
    "license": "Открытая публикация Kaggle (Jennifer A. Duffy, «ESG Ratings and Stock Data for Dow 30 "
               "Companies»), условия площадки",
    "description": (
        "Оценки S&P Global, Sustainalytics и MSCI для 30 компаний индекса Dow Jones и биржевые "
        "мультипликаторы, 46 столбцов. Полные оценки всех трёх провайдеров — у 26 компаний (нет данных: "
        "AMZN, GSBD — все три, DOW — MSCI, JNJ — S&P). Sustainalytics — шкала неуправляемого риска "
        "(больше — хуже), Sustainalytics_normalized = исходная оценка × 2,5; перед сравнением с MSCI и S&P "
        "обращать. Папка «Собранные материалы/Датасеты/03_Dow30_ESG_Stock_Data» на Яндекс.Диске "
        "лаборатории; первоисточник — "
        "kaggle.com/datasets/jenniferaduffy/esg-ratings-and-stock-data-for-dow-30-companies."
    ),
}

DS03 = {
    "source_url": "",
    "description": "ESG-проекты крупных резидентов особой экономической зоны. Данные под NDA лабораторией "
                   "ещё не получены; карточка заведена, чтобы связать с ними эксперименты, когда выгрузка "
                   "поступит.",
}

EXP001 = {
    "data_summary": "DS-01, срез 2026-10-30 · Dow30: 30 компаний, 26 с оценками всех трёх провайдеров",
    "setup": [
        "Ранговая корреляция Спирмена между оценками S&P Global (0–100), Sustainalytics (риск) и MSCI "
        "(CCC…AAA → 1…7) для каждой пары провайдеров.",
        "Основной расчёт — на 26 компаниях с оценками всех трёх провайдеров, шкала риска Sustainalytics "
        "обращена (у всех «больше — лучше»).",
        "Неопределённость: 95 % бутстреп-интервал (10 000 повторных выборок) и двусторонний "
        "перестановочный тест (10 000 перестановок), seed 42.",
    ],
    "results": [
        "S&P — MSCI: ρ = 0,27, 95 % интервал −0,13…0,59, p = 0,18.",
        "Sustainalytics — MSCI: ρ = +0,29 после обращения шкалы риска (−0,29 без обращения), "
        "интервал −0,10…0,61, p = 0,14.",
        "S&P — Sustainalytics: ρ = +0,02, интервал −0,40…0,45, p = 0,92.",
        "Расхождение −0,32 и −0,29 объяснено: −0,32 — на 27 компаниях, где есть обе оценки пары (с JNJ), "
        "−0,29 — на 26 компаниях с оценками всех трёх провайдеров.",
    ],
    "conclusion": "Гипотеза о согласованности отклонена: ни одна пара провайдеров не согласована значимо, "
                  "все 95 % интервалы включают ноль. Вывод об обратной связи Sustainalytics–MSCI снят: "
                  "знак был артефактом шкалы риска.",
    "limitations": [
        "30 компаний (26 с полными данными) и один срез: интервалы широкие, слабую согласованность нельзя "
        "ни подтвердить, ни исключить.",
        "В выгрузке вместо Goldman Sachs (GS) стоит GSBD — у этой строки нет ни одной оценки; состав "
        "соответствует Dow30 на дату публикации набора на Kaggle.",
        "MSCI — порядковая шкала из 7 букв: много совпадающих рангов.",
    ],
    "reproducibility": [
        "Код: runner/dow30/run_exp001.py, коммит 831b01b.",
        "Данные: DS-01, срез 2026-10-30, sha256 8e905429…; выгрузка с Яндекс.Диска лаборатории — "
        "manifest.json с sha256 каждого файла.",
        "Окружение: Python 3.12.10, runner/hsu2025/requirements.lock (numpy 2.5.4, pandas 3.1.0, "
        "scipy 1.18.1).",
        "Seed: бутстреп и перестановки 42.",
        "Запуск #2 от 30.10.2026 зарегистрирован в платформе и засчитан как воспроизводимый.",
    ],
}
EXP001_NEXT = [
    "Расширить сравнение на российские рейтинги (RAEX, АКРА, «Эксперт РА») — датасет DS-05.",
    "Повторить на выборке побольше (S&P 500, датасет 02 Яндекс.Диска), чтобы сузить интервалы.",
]

REFS = [
    {"kbrag_id": "10.2308_tar-2019-0506", "kb_path": "esg.causal",
     "title": "Christensen et al. (2021). Why is Corporate Virtue in the Eye of The Beholder? The Case of "
              "ESG Ratings. The Accounting Review",
     "doi": "10.2308/tar-2019-0506",
     "quote": "we find that greater ESG disclosure leads to greater ESG disagreement across ESG rating "
              "agencies", "page": 36},
    {"kbrag_id": "10.18288_1994-5124-2024-4-84-121", "kb_path": "esg.ratings",
     "title": "Divergence of ESG Ratings: International and Russian Experience (2024)",
     "doi": "10.18288/1994-5124-2024-4-84-121", "quote": "", "page": None},
]

HYPOTHESES = [
    {"code": "H-001", "exp": "EXP-001", "title": "ESG-рейтинги разных провайдеров согласованы",
     "rationale": "Рейтинги S&P Global, Sustainalytics и MSCI используются как взаимозаменяемая мера "
                  "ESG-качества компании. Если это так, они должны одинаково ранжировать одни и те же "
                  "компании. Литература (Christensen et al., 2021) сообщает обратное: расхождение агентств "
                  "растёт с объёмом раскрытия.",
     "decision_note": "Принята к проверке: оценки трёх провайдеров для одних и тех же компаний есть в "
                      "открытом наборе Dow30 (DS-01).",
     "refs": ["10.2308_tar-2019-0506", "10.18288_1994-5124-2024-4-84-121"]},
    {"code": "H-002", "exp": "EXP-007", "title": "Результаты Hsu et al. (2025) воспроизводятся",
     "rationale": "Hsu et al. (2025) сообщают R² = 0,71 / 0,72 для LSTM по 15 ESG-признакам. Если результат "
                  "верен, ESG-признаки сами по себе почти определяют финансовый результат — это прямо "
                  "относится к направлению 1 лаборатории.",
     "decision_note": "Принята к проверке: источники данных статьи (TWSE ESG InfoHub, MOPS) открыты, набор "
                      "можно реконструировать (DS-04).",
     "refs": ["10.3390_electronics14030417"]},
]


def upgrade() -> None:
    conn = op.get_bind()
    run = lambda sql, **kw: conn.execute(sa.text(sql), kw)  # noqa: E731

    run("UPDATE datasets SET source_url = :source_url, license = :license, description = :description "
        "WHERE code = 'DS-01'", **DS01)
    run("UPDATE datasets SET source_url = :source_url, description = :description WHERE code = 'DS-03'",
        **DS03)
    run("UPDATE experiments SET data_summary = :data_summary, setup = CAST(:setup AS json), "
        "results = CAST(:results AS json), conclusion = :conclusion, "
        "limitations = CAST(:limitations AS json), reproducibility = CAST(:reproducibility AS json) "
        "WHERE code = 'EXP-001'",
        **{k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in EXP001.items()})
    run("UPDATE experiments SET report = CAST(jsonb_set(CAST(report AS jsonb), '{analysis,next}', "
        "CAST(:next AS jsonb)) AS json) WHERE code = 'EXP-001' AND report IS NOT NULL",
        next=json.dumps(EXP001_NEXT, ensure_ascii=False))

    for ref in REFS:
        run("INSERT INTO kb_refs (kind, kbrag_id, kb_path, title, doi, quote, page) "
            "SELECT 'article', CAST(:kbrag_id AS varchar), :kb_path, :title, :doi, :quote, CAST(:page AS integer) "
            "WHERE NOT EXISTS (SELECT 1 FROM kb_refs WHERE kind = 'article' "
            "AND kbrag_id = CAST(:kbrag_id AS varchar))", **ref)
    for h in HYPOTHESES:
        run("INSERT INTO hypotheses (code, title, statement, rationale, direction, status, decision_note, "
            "experiment_id) SELECT CAST(:code AS varchar), :title, e.hypothesis, :rationale, e.direction, 'testing', "
            ":decision_note, e.id FROM experiments e WHERE e.code = :exp "
            "AND NOT EXISTS (SELECT 1 FROM hypotheses WHERE code = CAST(:code AS varchar))",
            code=h["code"], title=h["title"], rationale=h["rationale"], decision_note=h["decision_note"],
            exp=h["exp"])
        for kbrag_id in h["refs"]:
            run("INSERT INTO hypothesis_refs (hypothesis_id, kb_ref_id) "
                "SELECT h.id, r.id FROM hypotheses h, kb_refs r "
                "WHERE h.code = :code AND r.kind = 'article' AND r.kbrag_id = :kbrag_id "
                "AND NOT EXISTS (SELECT 1 FROM hypothesis_refs x WHERE x.hypothesis_id = h.id "
                "AND x.kb_ref_id = r.id)", code=h["code"], kbrag_id=kbrag_id)
    for kbrag_id in HYPOTHESES[0]["refs"]:
        run("INSERT INTO experiment_links (experiment_id, kb_ref_id, relation) "
            "SELECT e.id, r.id, 'motivated_by' FROM experiments e, kb_refs r "
            "WHERE e.code = 'EXP-001' AND r.kind = 'article' AND r.kbrag_id = :kbrag_id "
            "AND NOT EXISTS (SELECT 1 FROM experiment_links x WHERE x.experiment_id = e.id "
            "AND x.kb_ref_id = r.id)", kbrag_id=kbrag_id)


def downgrade() -> None:
    # данные, а не схема: откат не восстанавливает заглушки
    pass
