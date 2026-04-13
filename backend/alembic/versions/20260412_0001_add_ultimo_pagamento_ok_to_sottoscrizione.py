"""Add ultimo_pagamento_ok to sottoscrizione.

Revision ID: 20260412_0001
Revises: None
Create Date: 2026-04-12 13:10:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260412_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for column in inspector.get_columns(table_name):
        if column.get("name") == column_name:
            return True
    return False


def upgrade() -> None:
    if op.get_context().as_sql:
        op.add_column(
            "sottoscrizione",
            sa.Column("ultimo_pagamento_ok", sa.Boolean(), nullable=True),
        )
        return

    if not _table_exists("sottoscrizione"):
        return
    if _column_exists("sottoscrizione", "ultimo_pagamento_ok"):
        return
    op.add_column(
        "sottoscrizione",
        sa.Column("ultimo_pagamento_ok", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        op.drop_column("sottoscrizione", "ultimo_pagamento_ok")
        return

    if not _table_exists("sottoscrizione"):
        return
    if not _column_exists("sottoscrizione", "ultimo_pagamento_ok"):
        return
    op.drop_column("sottoscrizione", "ultimo_pagamento_ok")
