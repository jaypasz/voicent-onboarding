"""client outcome and tasks

A lost or stalled flag on a client (every other pipeline stage is worked out from what exists) and tasks: team to-dos about a
client and optionally one onboarding. Row level security on the new table, as on every other (see 0002).

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('outcome', sa.String(length=10), nullable=True))

    op.create_table('tasks',
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('client_id', sa.String(length=36), nullable=False),
    sa.Column('onboarding_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('assignee_id', sa.String(length=36), nullable=True),
    sa.Column('due_on', sa.Date(), nullable=True),
    sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['assignee_id'], ['org_members.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['onboarding_id'], ['onboardings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.create_index('ix_tasks_org_done_due', ['org_id', 'done_at', 'due_on'], unique=False)
        batch_op.create_index(batch_op.f('ix_tasks_assignee_id'), ['assignee_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tasks_client_id'), ['client_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tasks_onboarding_id'), ['onboarding_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tasks_org_id'), ['org_id'], unique=False)

    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE tasks ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table('tasks')
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.drop_column('outcome')
