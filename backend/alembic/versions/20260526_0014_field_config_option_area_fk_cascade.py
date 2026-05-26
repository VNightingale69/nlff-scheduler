"""add cascade delete to field configuration option area fk

Revision ID: 20260526_0014
Revises: 20260523_0013
Create Date: 2026-05-26
"""

from alembic import op

revision = '20260526_0014'
down_revision = '20260523_0013'
branch_labels = None
depends_on = None


FK_NAME = 'field_configuration_options_physical_field_area_id_fkey'


def upgrade() -> None:
    op.drop_constraint(FK_NAME, 'field_configuration_options', type_='foreignkey')
    op.create_foreign_key(
        FK_NAME,
        'field_configuration_options',
        'physical_field_areas',
        ['physical_field_area_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint(FK_NAME, 'field_configuration_options', type_='foreignkey')
    op.create_foreign_key(
        FK_NAME,
        'field_configuration_options',
        'physical_field_areas',
        ['physical_field_area_id'],
        ['id'],
    )
