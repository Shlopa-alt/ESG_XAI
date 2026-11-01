"""методология: разделы, версии, CR и их основания; начальная версия 0.1 и CR-01

Наполнение — из раздела 8 docs/SPEC.md (методология 0.1 по постановке задачи лаборатории).

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

SECTIONS = [
    ("1", "Входные данные: ESG-инвестиции по статьям затрат", "draft",
     "На входе ИНС — объёмы инвестиций компании в ESG в денежном выражении по статьям, взятым "
     "из действующих в РФ методик ESG-рейтингов. Вариант 3 добавляет неденежные усилия компании."),
    ("2", "Выходные данные: финансовые результаты на горизонте 3–5 лет", "draft",
     "На выходе — финансовые результаты компании за период не менее 3–5 лет; вариант 2 добавляет "
     "нефинансовые ESG-эффекты с перечнем метрик и источников."),
    ("3", "Эффекты для бюджета региона и федерального бюджета", "draft",
     "Задания 2–3: зависимость результатов бюджета региона и федерального бюджета от "
     "ESG-инвестиций на горизонте 3 лет, в виде функциональной зависимости."),
    ("4", "Денежная оценка нефинансовых эффектов (ЧДД)", "contested",
     "Модуль отрицательного ЧДД при фактически принятом решении — оценка неценовых факторов. "
     "Оспаривается трактовка |ЧДД| как точной оценки: при принятом решении это нижняя граница; "
     "другие объяснения отрицательного ЧДД — ошибки прогноза, требования закона, интересы "
     "менеджмента."),
    ("5", "Проверка моделей", "draft",
     "Требования к проверке заявлений «ESG прогнозирует финансовый результат» — предложены в "
     "CR-01 по итогам EXP-007."),
]

CR01_TEXT = (
    "Любое заявление вида «ESG-показатели прогнозируют финансовый результат» проверяется так: "
    "(1) отложенная выборка, по которой не подбираются гиперпараметры; (2) не менее 30 случайных "
    "разбиений с отчётом среднего и разброса; (3) плацебо — та же процедура на перемешанной "
    "целевой переменной; (4) наивный бенчмарк «как в прошлом году» и прогноз средним; "
    "(5) контроль размера компании и отрасли."
)


def upgrade() -> None:
    op.create_table(
        "methodology_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("number", sa.String(16), nullable=False, unique=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "stability",
            sa.Enum("stable", "draft", "contested", name="stability", native_enum=False, length=16),
            nullable=False,
        ),
    )
    op.create_table(
        "methodology_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(16), nullable=False, unique=True),
        sa.Column("sections_content", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "change_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column(
            "section_id", sa.Integer(), sa.ForeignKey("methodology_sections.id"), nullable=False
        ),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("proposed_content", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.Enum("proposed", "review", "accepted", "rejected", name="cr_status",
                    native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("target_version", sa.String(16), nullable=False, server_default=""),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_change_requests_code", "change_requests", ["code"], unique=True)
    op.create_table(
        "cr_bases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cr_id", sa.Integer(), sa.ForeignKey("change_requests.id"), nullable=False),
        sa.Column(
            "basis_type",
            sa.Enum("experiment", "kb_fact", "kb_article", name="basis_type", native_enum=False,
                    length=16),
            nullable=False,
        ),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id"), nullable=True),
        sa.Column("kb_ref_id", sa.Integer(), sa.ForeignKey("kb_refs.id"), nullable=True),
    )

    conn = op.get_bind()
    sections = sa.table(
        "methodology_sections",
        sa.column("number"), sa.column("title"), sa.column("stability"), sa.column("content"),
    )
    op.bulk_insert(sections, [
        {"number": n, "title": t, "stability": s, "content": c} for n, t, s, c in SECTIONS
    ])
    versions = sa.table(
        "methodology_versions", sa.column("version"), sa.column("sections_content", sa.JSON),
        sa.column("notes"),
    )
    op.bulk_insert(versions, [{
        "version": "0.1",
        "sections_content": {n: {"title": t, "content": c, "stability": s} for n, t, s, c in SECTIONS},
        "notes": "Начальная версия по постановке задачи лаборатории для ИНС.",
    }])
    section5 = conn.execute(sa.text("SELECT id FROM methodology_sections WHERE number = '5'")).scalar()
    crs = sa.table(
        "change_requests", sa.column("code"), sa.column("section_id"), sa.column("title"),
        sa.column("description"), sa.column("proposed_content"), sa.column("status"),
        sa.column("target_version"),
    )
    op.bulk_insert(crs, [{
        "code": "CR-01",
        "section_id": section5,
        "title": "Обязательные проверки моделей: отложенная выборка, 30+ разбиений, плацебо, "
        "наивный бенчмарк, контроль размера и отрасли",
        "description": "По итогам EXP-007: заявленные в Hsu et al. (2025) метрики не "
        "воспроизводятся и согласуются с подбором гиперпараметров по тестовой выборке.",
        "proposed_content": CR01_TEXT,
        "status": "proposed",
        "target_version": "0.2",
    }])
    cr01 = conn.execute(sa.text("SELECT id FROM change_requests WHERE code = 'CR-01'")).scalar()
    exp7 = conn.execute(sa.text("SELECT id FROM experiments WHERE code = 'EXP-007'")).scalar()
    if exp7 is not None:
        bases = sa.table("cr_bases", sa.column("cr_id"), sa.column("basis_type"),
                         sa.column("experiment_id"))
        op.bulk_insert(bases, [{"cr_id": cr01, "basis_type": "experiment", "experiment_id": exp7}])


def downgrade() -> None:
    for table in ("cr_bases", "change_requests", "methodology_versions", "methodology_sections"):
        op.drop_table(table)
