"""проверки, у которых все расчёты закончились, — не «в работе»

До этой версии статус проверки после расчётов не менялся, и такие проверки висели «в работе»
(их нельзя было отправить на рецензию). Хоть один удачный расчёт — «на проверке», все упали
или остановлены — «сбой». То же правило теперь в app/services/experiments.py: refresh_after_runs.

Revision ID: 0024
Revises: 0023
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

FINISHED = """
    status IN ('planned', 'running')
    AND EXISTS (SELECT 1 FROM runs r WHERE r.experiment_id = experiments.id)
    AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.experiment_id = experiments.id
                    AND r.status IN ('queued', 'running'))
"""


def upgrade() -> None:
    op.execute(f"""UPDATE experiments SET status = 'review' WHERE {FINISHED}
        AND EXISTS (SELECT 1 FROM runs r WHERE r.experiment_id = experiments.id AND r.status = 'done')""")
    op.execute(f"UPDATE experiments SET status = 'failed' WHERE {FINISHED}")


def downgrade() -> None:
    # прежний «в работе» не восстанавливается: какие проверки висели, после обновления не известно
    pass
