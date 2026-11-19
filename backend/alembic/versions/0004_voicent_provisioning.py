"""voicent provisioning

The state of the webhook that asks Voicent-App for a workspace when an onboarding is finished: whether one is waiting,
went through or failed, its delivery id (reused by retries), attempts, when to try next, our own error wording, and the
workspace id Voicent-App answered with.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('provision_state', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('provision_delivery_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('provision_attempts', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('provision_next_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('provision_error', sa.String(length=300), server_default='', nullable=False))
        batch_op.add_column(sa.Column('provisioned_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('voicent_workspace_id', sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.drop_column('voicent_workspace_id')
        batch_op.drop_column('provisioned_at')
        batch_op.drop_column('provision_error')
        batch_op.drop_column('provision_next_at')
        batch_op.drop_column('provision_attempts')
        batch_op.drop_column('provision_delivery_id')
        batch_op.drop_column('provision_state')
