"""telling the client about changes

Two columns on onboardings for the batched "your onboarding was updated" notice: when the latest unannounced edit was made, and
what the client's steps looked like before the first of the batch.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('steps_changed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('client_seen_steps', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.drop_column('client_seen_steps')
        batch_op.drop_column('steps_changed_at')
