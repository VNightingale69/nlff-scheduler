"""add login audit logs

Revision ID: 20260611_0047
Revises: 20260611_0046
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260611_0047'
down_revision = '20260611_0046'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'login_audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('email_attempted', sa.String(length=255), nullable=False),
        sa.Column('user_role', sa.String(length=100), nullable=True),
        sa.Column('community_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('community_name', sa.String(length=255), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('failure_reason', sa.String(length=100), nullable=True),
        sa.Column('ip_address', sa.String(length=100), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('login_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['community_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_login_audit_logs_login_at', 'login_audit_logs', ['login_at'])
    op.create_index('ix_login_audit_logs_email_attempted', 'login_audit_logs', ['email_attempted'])
    op.create_index('ix_login_audit_logs_success', 'login_audit_logs', ['success'])
    op.create_index('ix_login_audit_logs_community_id', 'login_audit_logs', ['community_id'])


def downgrade() -> None:
    op.drop_index('ix_login_audit_logs_community_id', table_name='login_audit_logs')
    op.drop_index('ix_login_audit_logs_success', table_name='login_audit_logs')
    op.drop_index('ix_login_audit_logs_email_attempted', table_name='login_audit_logs')
    op.drop_index('ix_login_audit_logs_login_at', table_name='login_audit_logs')
    op.drop_table('login_audit_logs')
