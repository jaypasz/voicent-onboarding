"""one task step

The internal task step becomes the general `task` step (for the client or for the team), and a team to-do that belonged to an
onboarding becomes a team task step in that onboarding's flow. Standalone to-dos stay in `tasks`, which no longer points at an onboarding.

Revision ID: 0010
Revises: 0009
"""
import datetime as dt
import uuid

from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def _convert(doc):
    """The same document with every internal_task step turned into a team task step. None when there was nothing to change."""
    if not isinstance(doc, dict) or not any(s.get('type') == 'internal_task' for s in doc.get('steps', [])):
        return None
    out = dict(doc)
    out['steps'] = [dict(s, type='task', config=dict(s.get('config') or {}, audience='team'), visibility='internal') if s.get('type') == 'internal_task' else s
                    for s in doc['steps']]
    return out


def upgrade() -> None:
    bind = op.get_bind()
    meta = sa.MetaData()
    steps, onboardings, versions, tasks = (sa.Table(n, meta, autoload_with=bind) for n in ('steps', 'onboardings', 'template_versions', 'tasks'))

    bind.execute(steps.update().where(steps.c.type == 'internal_task').values(type='task'))
    for table in (onboardings, versions):
        for row in bind.execute(sa.select(table.c.id, table.c.document)).all():
            new = _convert(row.document)
            if new is not None:
                bind.execute(table.update().where(table.c.id == row.id).values(document=new))

    now = dt.datetime.now(dt.timezone.utc)
    linked = bind.execute(sa.select(tasks).where(tasks.c.onboarding_id.is_not(None)).order_by(tasks.c.created_at)).all()
    for t in linked:
        ob = bind.execute(sa.select(onboardings.c.document).where(onboardings.c.id == t.onboarding_id)).first()
        if ob is None or not isinstance(ob.document, dict):
            continue
        doc = dict(ob.document)
        existing = doc.get('steps', [])
        key = 'task_' + uuid.uuid4().hex[:8]
        doc['steps'] = existing + [{'key': key, 'type': 'task', 'title': t.title, 'description': '', 'section': '', 'visibility': 'internal',
                                    'assignee_role': '', 'due_offset_days': None, 'config': {'audience': 'team'}, 'show_if': None}]
        bind.execute(onboardings.update().where(onboardings.c.id == t.onboarding_id)
                     .values(document=doc, sync_version=onboardings.c.sync_version + 1))
        bind.execute(steps.insert().values(
            id=str(uuid.uuid4()), created_at=now, updated_at=now, org_id=t.org_id, onboarding_id=t.onboarding_id, key=key, type='task',
            title=t.title, section='', position=len(existing), visibility='internal', team_assignee_id=t.assignee_id,
            status='done' if t.done_at else 'pending', completed_at=t.done_at,
            due_at=dt.datetime.combine(t.due_on, dt.time(12), tzinfo=dt.timezone.utc) if t.due_on else None))
    bind.execute(tasks.delete().where(tasks.c.onboarding_id.is_not(None)))

    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_index('ix_tasks_onboarding_id')
        batch_op.drop_column('onboarding_id')


def downgrade() -> None:
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('onboarding_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key('fk_tasks_onboarding_id', 'onboardings', ['onboarding_id'], ['id'], ondelete='CASCADE')
        batch_op.create_index('ix_tasks_onboarding_id', ['onboarding_id'], unique=False)
    # Task steps stay task steps: the old code doesn't know the type, so a downgrade needs them converted back by hand.
