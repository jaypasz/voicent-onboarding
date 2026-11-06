"""enable row level security on Postgres

Supabase serves every table in the public schema through its Data API to anyone holding
the publishable key, which ships in the frontend bundle. With RLS on and no policies,
that API sees nothing. The backend connects as the table owner, which RLS doesn't apply to,
and enforces org and onboarding scope in code (see CLAUDE.md).

Revision ID: 0002
Revises: 0001
"""
from alembic import op


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

TABLES = [
    'orgs', 'org_members', 'clients', 'contacts', 'templates', 'template_versions', 'onboardings', 'steps',
    'responses', 'files', 'step_comments', 'magic_links', 'nudges', 'sync_log', 'alembic_version',
]


def upgrade() -> None:
    if op.get_bind().dialect.name != 'postgresql':
        return
    for t in TABLES:
        op.execute(f'ALTER TABLE {t} ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    if op.get_bind().dialect.name != 'postgresql':
        return
    for t in TABLES:
        op.execute(f'ALTER TABLE {t} DISABLE ROW LEVEL SECURITY')
