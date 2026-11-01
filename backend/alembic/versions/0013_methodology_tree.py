"""методика — дерево: направления → варианты → задания, разделы на любом уровне

Постановка лаборатории («Постановка задачи для ИНС», ветка esg.lab базы знаний): направление 1 —
ИНС «ESG-инвестиции → результаты» с тремя вариантами; в варианте 1 три задания, во втором одно,
третий не расписан. Направление 2 — ESG-рейтинги и их методики. Тексты вариантов и заданий —
дословно из постановки; пять прежних разделов переходят в дерево без правки текста, CR-01 остаётся
у «Проверки моделей». Раздел действует на всё, что ниже его узла: общие — на всю методику.

Номера: О1 — общий раздел; Н1 — направление, Н1.В1 — вариант, Н1.В1.З1 — задание,
<узел>.Р1 — раздел узла. Снимок версии 0.1 переписан на новые номера (тексты те же), чтобы
сравнение версий работало. CR может не только менять узел, но и добавлять новый (action=add).

Revision ID: 0013
Revises: 0012
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

RENUMBER = {  # прежний номер → (новый номер, вид, родитель, позиция)
    "1": ("Н1.Р1", "section", "Н1", 1),
    "2": ("Н1.Р2", "section", "Н1", 2),
    "3": ("Н1.В1.Р1", "section", "Н1.В1", 1),
    "4": ("Н1.В2.Р1", "section", "Н1.В2", 1),
    "5": ("О1", "section", None, 1),
}

TASK_TEXT = ("оценить зависимость между объемом инвестиций в различные статьи ESG-затрат (перечень этих "
             "затрат определяется на основе статей применяемых в настоящее время в РФ методик составления "
             "ESG-рейтингов компаний) и {what} на период 3 года от момента совершения инвестиций. "
             "Результат представить в виде функциональной зависимости.")

NODES = [  # номер, вид, родитель, позиция, заголовок, текст, устойчивость
    ("Н1", "direction", None, 1, "Направление 1. ИНС: ESG-инвестиции и результаты",
     "Использование ИНС для выявления неочевидных зависимостей между ESG-параметрами бизнеса и финансовыми "
     "результатами в долгосрочной перспективе; результатом должна быть модель подобных зависимостей, которая "
     "могла бы использоваться для прогнозирования будущих финансовых результатов при тех или иных объемах "
     "ESG-инвестирования, а также (на основе СППР в виде ориентированного графа) для поддержки принятия "
     "решений по каждой из статей ESG-инвестирования (во что целесообразно вкладывать, а во что нет). При этом "
     "мы исходим из фиксированной и установленной извне (в виде принятых систем рейтингования и "
     "законодательных ограничений) системы ESG-критериев эффективности.", "draft"),
    ("Н1.В1", "variant", "Н1", 1, "Вариант 1 (задача-минимум): ESG-инвестиции → экономические результаты",
     "На входе ИНС должны быть показатели объемов инвестиций компании в ESG (в денежном эквиваленте), на выходе "
     "— показатели финансовых результатов за определенный период (минимум 3–5 лет).", "draft"),
    ("Н1.В1.З1", "task", "Н1.В1", 1, "Задание 1. Экономические результаты компаний",
     "Задание 1: " + TASK_TEXT.format(what="экономическими результатами этих компаний"), "draft"),
    ("Н1.В1.З2", "task", "Н1.В1", 2, "Задание 2. Результаты для бюджета региона",
     "Задание 2: " + TASK_TEXT.format(what="экономическими результатами для бюджета того региона, в котором "
                                           "функционируют эти компании"), "draft"),
    ("Н1.В1.З3", "task", "Н1.В1", 3, "Задание 3. Результаты для федерального бюджета",
     "Задание 3: " + TASK_TEXT.format(what="экономическими результатами для федерального бюджета РФ"), "draft"),
    ("Н1.В2", "variant", "Н1", 2, "Вариант 2: + нефинансовые ESG-эффекты на выходе",
     "Второй (усложненный) вариант сети: на входе — те же самые показатели, а на выходе к показателям "
     "финансовых результатов добавляются нефинансовые показатели ESG-эффектов. Нужно составить перечень таких "
     "метрик и оценить возможные источники сбора данных по ним.", "draft"),
    ("Н1.В2.З1", "task", "Н1.В2", 1, "Задание 1. Нефинансовые результаты региона",
     "Задание 1: оценить зависимость между объемом инвестиций в различные статьи ESG-затрат (перечень этих "
     "затрат определяется на основе статей применяемых в настоящее время в РФ методик составления "
     "ESG-рейтингов компаний) и нефинансовыми результатами региона их функционирования на период 3 года от "
     "момента совершения инвестиций. В качестве нефинансовых результатов использовать денежные оценки "
     "косвенных экономических эффектов от инвестирования; в тех случаях, где оценить экономический эффект в "
     "денежном эквиваленте не удается, привести нефинансовый эффект в словесной форме (к примеру: создано "
     "рабочих мест — 50, устранено источников вредного воздействия на окружающую среду — 5, и т. п.).", "draft"),
    ("Н1.В3", "variant", "Н1", 3, "Вариант 3: + неденежные усилия компании на входе",
     "Третий (еще более усложненный) вариант — то же, что и второй, но теперь еще и на входе добавить "
     "неденежные инвестиционные показатели (характеризующие прикладываемые компанией усилия, направленные на "
     "достижение ESG-эффектов и не переводимые в денежный эквивалент). Задания не расписаны — их добавляет "
     "лаборатория через CR.", "draft"),
    ("Н2", "direction", None, 2, "Направление 2. ESG-рейтинги и их методики",
     "ESG-рейтинги и методики их составления: согласованность провайдеров, критерии и веса российских "
     "агентств. Задания не расписаны — их добавляет лаборатория через CR.", "draft"),
]

LINKS = {"experiments": {"EXP-001": "Н2", "EXP-007": "Н1.В1.З1"},
         "hypotheses": {"H-001": "Н2", "H-002": "Н1.В1.З1"}}


def upgrade() -> None:
    op.add_column("methodology_sections", sa.Column("kind", sa.String(16), nullable=False, server_default="section"))
    op.add_column("methodology_sections", sa.Column("parent_id", sa.Integer(),
                                                    sa.ForeignKey("methodology_sections.id"), nullable=True))
    op.add_column("methodology_sections", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("change_requests", sa.Column("action", sa.String(8), nullable=False, server_default="edit"))
    # CR на добавление общего раздела или направления — у корня методики родителя нет
    op.alter_column("change_requests", "section_id", existing_type=sa.Integer(), nullable=True)
    op.add_column("change_requests", sa.Column("new_kind", sa.String(16), nullable=False, server_default=""))
    op.add_column("change_requests", sa.Column("new_title", sa.String(512), nullable=False, server_default=""))
    for table in ("experiments", "hypotheses"):
        op.add_column(table, sa.Column("methodology_node_id", sa.Integer(),
                                       sa.ForeignKey("methodology_sections.id"), nullable=True))

    conn = op.get_bind()
    run = lambda sql, **kw: conn.execute(sa.text(sql), kw)  # noqa: E731
    ids: dict[str, int] = {}
    for number, kind, parent, pos, title, content, stability in NODES:
        if run("SELECT 1 FROM methodology_sections WHERE number = :n", n=number).first():
            continue
        new_id = run("INSERT INTO methodology_sections (number, title, content, stability, kind, parent_id, "
                     "position) VALUES (:n, :t, :c, :s, :k, :p, :pos) RETURNING id", n=number, t=title,
                     c=content, s=stability, k=kind, p=ids.get(parent) if parent else None, pos=pos).scalar()
        ids[number] = int(new_id)
    for old, (new, kind, parent, pos) in RENUMBER.items():
        run("UPDATE methodology_sections SET number = :new, kind = :k, parent_id = :p, position = :pos "
            "WHERE number = :old", new=new, k=kind, p=ids.get(parent) if parent else None, pos=pos, old=old)
    # снимок 0.1 — на новые номера, тексты прежние
    for vid, raw in run("SELECT id, sections_content FROM methodology_versions").all():
        data = raw if isinstance(raw, dict) else json.loads(raw)
        if not any(k in RENUMBER for k in data):
            continue
        renamed = {RENUMBER[k][0] if k in RENUMBER else k: v for k, v in data.items()}
        run("UPDATE methodology_versions SET sections_content = CAST(:d AS json) WHERE id = :id",
            d=json.dumps(renamed, ensure_ascii=False), id=vid)
    for table, codes in LINKS.items():
        for code, number in codes.items():
            run(f"UPDATE {table} SET methodology_node_id = (SELECT id FROM methodology_sections "  # noqa: S608
                f"WHERE number = :n) WHERE code = :c", n=number, c=code)


def downgrade() -> None:
    for table in ("hypotheses", "experiments"):
        op.drop_column(table, "methodology_node_id")
    for column in ("new_title", "new_kind", "action"):
        op.drop_column("change_requests", column)
    for column in ("position", "parent_id", "kind"):
        op.drop_column("methodology_sections", column)
