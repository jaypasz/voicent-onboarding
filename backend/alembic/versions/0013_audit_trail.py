"""audit trail

The audit_events table: who changed what and when (audit.py). Row level security on, with no policies, like every table.

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('audit_events',
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor_kind', sa.String(length=20), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=True),
    sa.Column('actor_label', sa.String(length=200), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('onboarding_id', sa.String(length=36), nullable=True),
    sa.Column('client_id', sa.String(length=36), nullable=True),
    sa.Column('step_key', sa.String(length=80), nullable=False),
    sa.Column('summary', sa.String(length=500), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['onboarding_id'], ['onboardings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.create_index('ix_audit_events_client_at', ['client_id', 'at'], unique=False)
        batch_op.create_index('ix_audit_events_onboarding_at', ['onboarding_id', 'at'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_events_org_id'), ['org_id'], unique=False)
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY')



def downgrade() -> None:
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_events_org_id'))
        batch_op.drop_index('ix_audit_events_onboarding_at')
        batch_op.drop_index('ix_audit_events_client_at')

    op.drop_table('audit_events')
