"""add order service time fields

Revision ID: 1427bdb1f6fd
Revises: 2a8c2b115d49
Create Date: 2026-06-04 22:54:02.849640

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1427bdb1f6fd'
down_revision: Union[str, Sequence[str], None] = '2a8c2b115d49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    service_time_source_enum = sa.Enum(
        'AUTO',
        'MANUAL',
        name='servicetimesourceenum',
    )
    service_time_source_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'orders',
        sa.Column('pickup_service_minutes', sa.Integer(), nullable=True),
    )
    op.add_column(
        'orders',
        sa.Column('delivery_service_minutes', sa.Integer(), nullable=True),
    )
    op.add_column(
        'orders',
        sa.Column(
            'service_time_source',
            service_time_source_enum,
            server_default='AUTO',
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('orders', 'service_time_source')
    op.drop_column('orders', 'delivery_service_minutes')
    op.drop_column('orders', 'pickup_service_minutes')

    service_time_source_enum = sa.Enum(
        'AUTO',
        'MANUAL',
        name='servicetimesourceenum',
    )
    service_time_source_enum.drop(op.get_bind(), checkfirst=True)