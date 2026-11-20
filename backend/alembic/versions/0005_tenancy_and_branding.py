"""tenancy and branding

Follows Voicent-App's tenancy: an org can be linked to one Voicent tenant (direct customer or reseller), and carries that
tenant's brand plus what Voicent-App doesn't have (the name clients see and the senders that reach them). Memberships say
where they came from, so ones copied from Voicent-App can be withdrawn when Voicent-App withdraws them. Clients get
paying_since: a Voicent workspace is only asked for once a client pays.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('orgs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('voicent_tenant_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('account_type', sa.String(length=20), server_default='direct', nullable=False))
        batch_op.add_column(sa.Column('brand', sa.JSON(), server_default=sa.text("'{}'"), nullable=False))
        batch_op.add_column(sa.Column('brand_name', sa.String(length=120), server_default='', nullable=False))
        batch_op.add_column(sa.Column('email_from_name', sa.String(length=120), server_default='', nullable=False))
        batch_op.add_column(sa.Column('reply_to_email', sa.String(length=200), server_default='', nullable=False))
        batch_op.add_column(sa.Column('sms_from', sa.String(length=20), server_default='', nullable=False))
        batch_op.create_unique_constraint('uq_orgs_voicent_tenant_id', ['voicent_tenant_id'])
    with op.batch_alter_table('org_members', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String(length=20), server_default='local', nullable=False))
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('paying_since', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.drop_column('paying_since')
    with op.batch_alter_table('org_members', schema=None) as batch_op:
        batch_op.drop_column('source')
    with op.batch_alter_table('orgs', schema=None) as batch_op:
        batch_op.drop_constraint('uq_orgs_voicent_tenant_id', type_='unique')
        batch_op.drop_column('sms_from')
        batch_op.drop_column('reply_to_email')
        batch_op.drop_column('email_from_name')
        batch_op.drop_column('brand_name')
        batch_op.drop_column('brand')
        batch_op.drop_column('account_type')
        batch_op.drop_column('voicent_tenant_id')
