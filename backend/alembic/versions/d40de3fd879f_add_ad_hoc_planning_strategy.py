"""add ad hoc planning strategy

Revision ID: d40de3fd879f
Revises: 7b382f799f84
Create Date: 2026-06-18 13:53:46.729928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd40de3fd879f'
down_revision: Union[str, Sequence[str], None] = '7b382f799f84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE planningstrategyenum ADD VALUE IF NOT EXISTS 'AD_HOC'"
        )


def downgrade() -> None:
    """Downgrade schema."""
    pass
