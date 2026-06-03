"""add user_id to jobs

Revision ID: c8f4a3d92e10
Revises: b3e9f1a2c4d5
Create Date: 2026-05-21 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c8f4a3d92e10'
down_revision: Union[str, None] = 'b3e9f1a2c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'jobs',
        sa.Column('user_id', sa.UUID(), nullable=True),
    )
    op.create_index('ix_jobs_user_id', 'jobs', ['user_id'], unique=False)
    op.create_foreign_key(
        'fk_jobs_user_id',
        'jobs', 'users',
        ['user_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_jobs_user_id', 'jobs', type_='foreignkey')
    op.drop_index('ix_jobs_user_id', table_name='jobs')
    op.drop_column('jobs', 'user_id')
