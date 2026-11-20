"""team and notifications

The team: invites for orgs with no Voicent tenant, a member's name and whether they want notifications by email, an owner
per onboarding and a team member per step (who on our side follows it up). Notifications for team members. Row level
security on the new tables, as on every other (see 0002).

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

NEW_TABLES = ['org_invites', 'notifications']


def upgrade() -> None:
    op.create_table('org_invites',
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('invited_by', sa.String(length=200), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('org_id', 'email')
    )
    with op.batch_alter_table('org_invites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_org_invites_org_id'), ['org_id'], unique=False)

    op.create_table('notifications',
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('member_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=40), nullable=False),
    sa.Column('onboarding_id', sa.String(length=36), nullable=True),
    sa.Column('step_key', sa.String(length=80), nullable=False),
    sa.Column('text', sa.String(length=300), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('email_state', sa.String(length=20), server_default='none', nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['member_id'], ['org_members.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['onboarding_id'], ['onboardings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index('ix_notifications_member_read', ['member_id', 'read_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_onboarding_id'), ['onboarding_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notifications_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_member_id', sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f('ix_onboardings_owner_member_id'), ['owner_member_id'], unique=False)
        batch_op.create_foreign_key('fk_onboardings_owner_member_id', 'org_members', ['owner_member_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('org_members', schema=None) as batch_op:
        batch_op.add_column(sa.Column('name', sa.String(length=200), server_default='', nullable=False))
        batch_op.add_column(sa.Column('notify_email', sa.Boolean(), server_default=sa.true(), nullable=False))

    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('team_assignee_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key('fk_steps_team_assignee_id', 'org_members', ['team_assignee_id'], ['id'], ondelete='SET NULL')

    if op.get_bind().dialect.name == 'postgresql':
        for t in NEW_TABLES:
            op.execute(f'ALTER TABLE {t} ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.drop_constraint('fk_steps_team_assignee_id', type_='foreignkey')
        batch_op.drop_column('team_assignee_id')

    with op.batch_alter_table('org_members', schema=None) as batch_op:
        batch_op.drop_column('notify_email')
        batch_op.drop_column('name')

    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.drop_constraint('fk_onboardings_owner_member_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_onboardings_owner_member_id'))
        batch_op.drop_column('owner_member_id')

    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notifications_org_id'))
        batch_op.drop_index(batch_op.f('ix_notifications_onboarding_id'))
        batch_op.drop_index('ix_notifications_member_read')

    op.drop_table('notifications')
    with op.batch_alter_table('org_invites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_org_invites_org_id'))

    op.drop_table('org_invites')
