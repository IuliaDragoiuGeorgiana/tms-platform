"""add completed trip stop status

Revision ID: 2a8c2b115d49
Revises: 69a58d7c6d31
Create Date: 2026-05-30 21:38:05.721760

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a8c2b115d49'
down_revision: Union[str, Sequence[str], None] = '69a58d7c6d31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE stopstatusenum ADD VALUE IF NOT EXISTS 'COMPLETED'")

    op.execute("""
        UPDATE trip_stops
        SET status = 'COMPLETED'
        WHERE status = 'DELIVERED'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE trip_stops
        SET status = 'DELIVERED'
        WHERE status = 'COMPLETED'
    """)