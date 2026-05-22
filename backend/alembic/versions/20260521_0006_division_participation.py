"""league defined divisions and organization participation

Revision ID: 20260521_0006
Revises: 20260521_0005
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260521_0006'
down_revision = '20260521_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('divisions', sa.Column('division_group', sa.String(length=20), nullable=True))
    op.add_column('divisions', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
    op.execute("UPDATE divisions SET division_group='COED' WHERE division_group IS NULL")
    op.alter_column('divisions', 'division_group', nullable=False)


    bind = op.get_bind()
    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints('divisions')

    has_group_name_unique = False
    for constraint in unique_constraints:
        columns = constraint.get('column_names') or []
        name = constraint.get('name')

        if columns == ['name'] and name:
            op.drop_constraint(name, 'divisions', type_='unique')

        if columns == ['division_group', 'name']:
            has_group_name_unique = True

    if not has_group_name_unique:
        op.create_unique_constraint('uq_division_group_name', 'divisions', ['division_group', 'name'])

    op.create_table(
        'organization_division_participations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('organization_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('division_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('is_participating', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('team_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['division_id'], ['divisions.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'division_id', name='uq_org_division_participation'),
    )

    op.execute("DELETE FROM divisions")
    op.execute("""
    INSERT INTO divisions (id, name, division_group, sort_order, required_field_layout_type, is_active)
    VALUES
      (gen_random_uuid(), 'K/1st', 'COED', 1, 'THIRTY_YARD_WIDTH', true),
      (gen_random_uuid(), '2nd/3rd', 'COED', 2, 'THIRTY_YARD_WIDTH', true),
      (gen_random_uuid(), '4th/5th', 'COED', 3, 'FIFTY_THREE_YARD_WIDTH', true),
      (gen_random_uuid(), '6th/7th', 'COED', 4, 'FIFTY_THREE_YARD_WIDTH', true),
      (gen_random_uuid(), '8th', 'COED', 5, 'FIFTY_THREE_YARD_WIDTH', true),
      (gen_random_uuid(), 'K/1st', 'GIRLS', 1, 'THIRTY_YARD_WIDTH', true),
      (gen_random_uuid(), '2nd/3rd', 'GIRLS', 2, 'THIRTY_YARD_WIDTH', true),
      (gen_random_uuid(), '4th/5th', 'GIRLS', 3, 'FIFTY_THREE_YARD_WIDTH', true),
      (gen_random_uuid(), '6th/7th/8th', 'GIRLS', 4, 'FIFTY_THREE_YARD_WIDTH', true)
    """)


def downgrade() -> None:
    op.drop_table('organization_division_participations')
    op.drop_constraint('uq_division_group_name', 'divisions', type_='unique')
    op.create_unique_constraint('divisions_name_key', 'divisions', ['name'])
    op.drop_column('divisions', 'sort_order')
    op.drop_column('divisions', 'division_group')
