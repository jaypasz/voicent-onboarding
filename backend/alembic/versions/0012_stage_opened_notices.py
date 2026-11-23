"""stage opened notices

Two columns on onboardings for telling the client the next stage is open (stage_notices.py): when a sign-off opened one, and
which stages opened since the last notice.

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stage_opened_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('stage_opened_keys', sa.JSON(), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.drop_column('stage_opened_keys')
        batch_op.drop_column('stage_opened_at')

