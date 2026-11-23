"""stages and sign-off

An onboarding's sections become stages: one our team signs off (stage_signoffs) before the next opens to the client. A start day per
step for the schedule. Row level security on the new table, as on every other (see 0002).

Onboardings already sent are left as they were: each of their sections is marked as not needing a sign-off, so nobody is
suddenly locked out of a stage. Drafts, templates and onboardings made from now on need a sign-off per section unless it is
turned off.

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('stage_signoffs',
    sa.Column('org_id', sa.String(length=36), nullable=False),
    sa.Column('onboarding_id', sa.String(length=36), nullable=False),
    sa.Column('section_key', sa.String(length=80), nullable=False),
    sa.Column('member_id', sa.String(length=36), nullable=True),
    sa.Column('signed_by', sa.String(length=200), nullable=False),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['member_id'], ['org_members.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['onboarding_id'], ['onboardings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('onboarding_id', 'section_key')
    )
    with op.batch_alter_table('stage_signoffs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stage_signoffs_onboarding_id'), ['onboarding_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stage_signoffs_org_id'), ['org_id'], unique=False)

    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.add_column(sa.Column('start_on', sa.Date(), nullable=True))

    if op.get_bind().dialect.name == 'postgresql':
        op.execute('ALTER TABLE stage_signoffs ENABLE ROW LEVEL SECURITY')

    bind = op.get_bind()
    onboardings = sa.Table('onboardings', sa.MetaData(), autoload_with=bind)
    for row in bind.execute(sa.select(onboardings.c.id, onboardings.c.document).where(onboardings.c.status != 'draft')).all():
        doc = row.document
        if not isinstance(doc, dict) or not doc.get('sections'):
            continue
        new = dict(doc, sections=[dict(s, signoff=s.get('signoff', False)) for s in doc['sections']])
        bind.execute(onboardings.update().where(onboardings.c.id == row.id).values(document=new))


def downgrade() -> None:
    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.drop_column('start_on')

    with op.batch_alter_table('stage_signoffs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stage_signoffs_org_id'))
        batch_op.drop_index(batch_op.f('ix_stage_signoffs_onboarding_id'))

    op.drop_table('stage_signoffs')
