"""reminders and aios sync bookkeeping

Client time zone, onboarding attention flag, AIOS sync version counters, per-step last-synced state, and the
nudge round number with a unique (onboarding, contact, channel, round) so a reminder can't be sent twice.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('timezone', sa.String(length=64), server_default='America/New_York', nullable=False))

    with op.batch_alter_table('nudges', schema=None) as batch_op:
        batch_op.add_column(sa.Column('round', sa.Integer(), server_default='1', nullable=False))
        batch_op.create_unique_constraint('uq_nudges_attempt', ['onboarding_id', 'contact_id', 'channel', 'round'])

    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('aios_status', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('attention', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('sync_version', sa.Integer(), server_default='1', nullable=False))
        batch_op.add_column(sa.Column('synced_version', sa.Integer(), server_default='0', nullable=False))
        batch_op.alter_column('aios_project_id',
               existing_type=sa.VARCHAR(length=40),
               type_=sa.String(length=80),
               existing_nullable=True)

    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('aios_status', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('aios_comment_revision', sa.Integer(), server_default='0', nullable=False))



def downgrade() -> None:
    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.drop_column('aios_comment_revision')
        batch_op.drop_column('aios_status')

    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.alter_column('aios_project_id',
               existing_type=sa.String(length=80),
               type_=sa.VARCHAR(length=40),
               existing_nullable=True)
        batch_op.drop_column('synced_version')
        batch_op.drop_column('sync_version')
        batch_op.drop_column('attention')
        batch_op.drop_column('aios_status')

    with op.batch_alter_table('nudges', schema=None) as batch_op:
        batch_op.drop_constraint('uq_nudges_attempt', type_='unique')
        batch_op.drop_column('round')

    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.drop_column('timezone')

