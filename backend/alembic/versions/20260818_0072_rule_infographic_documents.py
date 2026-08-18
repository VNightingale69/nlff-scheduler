"""support independently active rulebook documents

Revision ID: 20260818_0072
Revises: 20260818_0071
"""
from alembic import op
import sqlalchemy as sa

revision = '20260818_0072'
down_revision = '20260818_0071'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('rulebooks', sa.Column('document_type', sa.String(40), nullable=False, server_default='RULEBOOK'))
    op.drop_index('ix_rulebooks_active', table_name='rulebooks')
    op.create_index('ix_rulebooks_type_active', 'rulebooks', ['document_type', 'is_active'])


def downgrade():
    op.drop_index('ix_rulebooks_type_active', table_name='rulebooks')
    op.create_index('ix_rulebooks_active', 'rulebooks', ['is_active'])
    op.drop_column('rulebooks', 'document_type')
