"""sync divisions schema with model and seed league-defined divisions

Revision ID: 20260522_0010
Revises: 20260521_0009
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa


revision = '20260522_0010'
down_revision = '20260521_0009'
branch_labels = None
depends_on = None


LEAGUE_DIVISION_SEED = [
    {'name': 'K/1st', 'division_group': 'COED', 'sort_order': 1, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '2nd/3rd', 'division_group': 'COED', 'sort_order': 2, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '4th/5th', 'division_group': 'COED', 'sort_order': 3, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '6th/7th', 'division_group': 'COED', 'sort_order': 4, 'required_field_layout_type': 'FIFTY_THREE_YARD_WIDTH', 'is_active': True},
    {'name': '8th', 'division_group': 'COED', 'sort_order': 5, 'required_field_layout_type': 'FIFTY_THREE_YARD_WIDTH', 'is_active': True},
    {'name': 'K/1st', 'division_group': 'GIRLS', 'sort_order': 1, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '2nd/3rd', 'division_group': 'GIRLS', 'sort_order': 2, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '4th/5th', 'division_group': 'GIRLS', 'sort_order': 3, 'required_field_layout_type': 'THIRTY_YARD_WIDTH', 'is_active': True},
    {'name': '6th/7th/8th', 'division_group': 'GIRLS', 'sort_order': 4, 'required_field_layout_type': 'FIFTY_THREE_YARD_WIDTH', 'is_active': True},
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    division_columns = {column['name'] for column in inspector.get_columns('divisions')}

    if 'division_group' not in division_columns:
        op.add_column('divisions', sa.Column('division_group', sa.String(length=20), nullable=False, server_default='COED'))
    if 'sort_order' not in division_columns:
        op.add_column('divisions', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
    if 'required_field_layout_type' not in division_columns:
        op.add_column('divisions', sa.Column('required_field_layout_type', sa.String(length=100), nullable=True))
    if 'is_active' not in division_columns:
        op.add_column('divisions', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))

    op.execute("UPDATE divisions SET division_group = 'COED' WHERE division_group IS NULL")
    op.execute('UPDATE divisions SET sort_order = 0 WHERE sort_order IS NULL')
    op.execute('UPDATE divisions SET is_active = true WHERE is_active IS NULL')

    op.alter_column('divisions', 'division_group', server_default=None)
    op.alter_column('divisions', 'sort_order', server_default=None)
    op.alter_column('divisions', 'is_active', server_default=None)

    for item in LEAGUE_DIVISION_SEED:
        op.execute(
            sa.text(
                """
                INSERT INTO divisions (id, name, division_group, sort_order, required_field_layout_type, is_active)
                VALUES (gen_random_uuid(), :name, :division_group, :sort_order, :required_field_layout_type, :is_active)
                ON CONFLICT (division_group, name)
                DO UPDATE SET
                    sort_order = EXCLUDED.sort_order,
                    required_field_layout_type = EXCLUDED.required_field_layout_type,
                    is_active = EXCLUDED.is_active
                """
            ).bindparams(**item)
        )

    op.execute(
        """
        UPDATE divisions d
        SET sort_order = s.sort_order,
            required_field_layout_type = s.required_field_layout_type,
            is_active = s.is_active
        FROM (VALUES
            ('COED', 'K/1st', 1, 'THIRTY_YARD_WIDTH', true),
            ('COED', '2nd/3rd', 2, 'THIRTY_YARD_WIDTH', true),
            ('COED', '4th/5th', 3, 'THIRTY_YARD_WIDTH', true),
            ('COED', '6th/7th', 4, 'FIFTY_THREE_YARD_WIDTH', true),
            ('COED', '8th', 5, 'FIFTY_THREE_YARD_WIDTH', true),
            ('GIRLS', 'K/1st', 1, 'THIRTY_YARD_WIDTH', true),
            ('GIRLS', '2nd/3rd', 2, 'THIRTY_YARD_WIDTH', true),
            ('GIRLS', '4th/5th', 3, 'THIRTY_YARD_WIDTH', true),
            ('GIRLS', '6th/7th/8th', 4, 'FIFTY_THREE_YARD_WIDTH', true)
        ) AS s(division_group, name, sort_order, required_field_layout_type, is_active)
        WHERE d.division_group = s.division_group AND d.name = s.name
        """
    )


def downgrade() -> None:
    op.drop_column('divisions', 'is_active')
    op.drop_column('divisions', 'required_field_layout_type')
    op.drop_column('divisions', 'sort_order')
    op.drop_column('divisions', 'division_group')
