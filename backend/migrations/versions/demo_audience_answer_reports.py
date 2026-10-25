"""Internal demo usage tracked apart from public usage; answer problem reports

Revision ID: demo_audience_answer_reports
Revises: add_demo_questions
Create Date: 2026-10-23 12:00:00.000000

WHY
---
1. `nl2sql_demo_questions.audience` (public | internal). Signed-in users with a verified
   email on an internal domain (aidemos.com, futuresmart.ai) have no free-question limit,
   but their questions are still recorded. The column keeps their usage and cost apart from
   public usage, so the $150 monthly budget is spent only by public users and the adoption
   figures are not inflated by the team's own testing. Every existing row was a public
   question, hence the default.

2. `nl2sql_answer_reports`: a person who got a wrong or broken answer reports it from the
   answer itself. The report stores what they said (what was wrong, what they expected) and
   a server-side snapshot of the conversation up to that answer: every question, the SQL,
   the answer text, rows returned and the chart, read from `nl2sql_logs` by chat_id. The
   snapshot is what makes a report reproducible: `nl2sql_logs.sql_query` can later be
   overwritten by a corrected-SQL feedback, and the session can be deleted.

Timestamps are UTC without a time zone, like every other table in this database.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'demo_audience_answer_reports'
down_revision = 'add_demo_questions'
branch_labels = None
depends_on = None

QUESTIONS = 'nl2sql_demo_questions'
REPORTS = 'nl2sql_answer_reports'


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c['name'] for c in inspector.get_columns(QUESTIONS)}
    if 'audience' not in columns:
        op.add_column(QUESTIONS, sa.Column('audience', sa.String(16), nullable=False,
                                           server_default='public'))
        op.create_check_constraint('ck_nl2sql_demo_questions_audience', QUESTIONS,
                                   "audience in ('public', 'internal')")
        op.create_index('ix_nl2sql_demo_questions_audience_created', QUESTIONS,
                        ['audience', 'created_at'])

    if REPORTS not in inspector.get_table_names():
        op.create_table(
            REPORTS,
            sa.Column('report_id', sa.String(32), primary_key=True),
            sa.Column('agent_id', sa.String(64), nullable=False),
            sa.Column('session_id', sa.String(64), nullable=False),
            sa.Column('chat_id', sa.String(64), nullable=False),
            sa.Column('user_id', sa.String(320), nullable=False),
            # wrong_answer | wrong_chart | lost_context | error | slow | other
            sa.Column('category', sa.String(32), nullable=False),
            sa.Column('note', sa.Text(), nullable=False),
            sa.Column('expected', sa.Text(), nullable=True),
            sa.Column('snapshot', postgresql.JSONB(), nullable=False),
            # open | triaged | fixed | not_a_bug
            sa.Column('status', sa.String(16), nullable=False, server_default='open'),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.text("(now() at time zone 'utc')")),
        )
        op.create_index('ix_nl2sql_answer_reports_created', REPORTS, ['created_at'])
        op.create_index('ix_nl2sql_answer_reports_agent_created', REPORTS,
                        ['agent_id', 'created_at'])


def downgrade():
    op.drop_index('ix_nl2sql_answer_reports_agent_created', table_name=REPORTS)
    op.drop_index('ix_nl2sql_answer_reports_created', table_name=REPORTS)
    op.drop_table(REPORTS)
    op.drop_index('ix_nl2sql_demo_questions_audience_created', table_name=QUESTIONS)
    op.drop_constraint('ck_nl2sql_demo_questions_audience', QUESTIONS, type_='check')
    op.drop_column(QUESTIONS, 'audience')
