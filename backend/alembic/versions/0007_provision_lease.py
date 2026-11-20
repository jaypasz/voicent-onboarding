"""provision lease

When a delivery to Voicent-App is in flight, until when its claim holds. Kept apart from provision_next_at, which "send it
now" resets, so a manual send can tell a send under way from a retry that is only waiting for its time.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('provision_lease_until', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('onboardings', schema=None) as batch_op:
        batch_op.drop_column('provision_lease_until')
