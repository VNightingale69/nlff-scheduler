"""turf and grass field configuration rules

Revision ID: 20260529_0017
Revises: 20260529_0016
Create Date: 2026-05-29 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260529_0017'
down_revision = '20260529_0016'
branch_labels = None
depends_on = None


def _add_column_if_missing(inspector, table_name: str, column: sa.Column) -> None:
    columns = {c['name'] for c in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    host_columns = {c['name'] for c in inspector.get_columns('host_locations')}
    if 'surface_type' in host_columns:
        op.execute("UPDATE host_locations SET surface_type = 'GRASS_FIELD' WHERE surface_type IS NULL OR surface_type IN ('', 'OTHER', 'MULTI_FIELD_COMPLEX')")
    else:
        op.add_column('host_locations', sa.Column('surface_type', sa.String(length=40), nullable=False, server_default='GRASS_FIELD'))
        op.alter_column('host_locations', 'surface_type', server_default=None)

    if 'host_location_configurations' in inspector.get_table_names():
        _add_column_if_missing(inspector, 'host_location_configurations', sa.Column('surface_type', sa.String(length=40), nullable=False, server_default='TURF_STADIUM'))
        _add_column_if_missing(inspector, 'host_location_configurations', sa.Column('space_used_yards', sa.Integer(), nullable=False, server_default='0'))
        _add_column_if_missing(inspector, 'host_location_configurations', sa.Column('remaining_yards', sa.Integer(), nullable=False, server_default='0'))
        _add_column_if_missing(inspector, 'host_location_configurations', sa.Column('large_field_count', sa.Integer(), nullable=False, server_default='0'))
        _add_column_if_missing(inspector, 'host_location_configurations', sa.Column('medium_field_count', sa.Integer(), nullable=False, server_default='0'))
        _add_column_if_missing(inspector, 'host_location_configurations', sa.Column('small_field_count', sa.Integer(), nullable=False, server_default='0'))

        config_updates = {
            'TWO_LARGE': (120, 0, 2, 0, 0),
            '2X53': (120, 0, 2, 0, 0),
            'ONE_MEDIUM_TWO_SMALL': (120, 0, 0, 1, 2),
            '1X53_PLUS_2X30': (120, 0, 0, 1, 2),
            'ONE_LARGE_ONE_MEDIUM': (115, 5, 1, 1, 0),
            'TWO_MEDIUM': (110, 10, 0, 2, 0),
            'THREE_SMALL': (100, 20, 0, 0, 3),
            '3X30': (100, 20, 0, 0, 3),
            'ONE_LARGE_ONE_SMALL': (90, 30, 1, 0, 1),
            'ONE_MEDIUM_ONE_SMALL': (85, 35, 0, 1, 1),
        }
        for name, (used, remaining, large, medium, small) in config_updates.items():
            op.execute(
                sa.text(
                    "UPDATE host_location_configurations SET surface_type = 'TURF_STADIUM', "
                    "space_used_yards = :used, remaining_yards = :remaining, large_field_count = :large, "
                    "medium_field_count = :medium, small_field_count = :small WHERE configuration_name = :name"
                ).bindparams(name=name, used=used, remaining=remaining, large=large, medium=medium, small=small)
            )

    if 'field_configuration_options' in inspector.get_table_names():
        _add_column_if_missing(inspector, 'field_configuration_options', sa.Column('configuration_name', sa.String(length=120), nullable=True))
        _add_column_if_missing(inspector, 'field_configuration_options', sa.Column('surface_type', sa.String(length=40), nullable=False, server_default='GRASS_FIELD'))
        _add_column_if_missing(inspector, 'field_configuration_options', sa.Column('space_used_yards', sa.Integer(), nullable=False, server_default='0'))
        _add_column_if_missing(inspector, 'field_configuration_options', sa.Column('remaining_yards', sa.Integer(), nullable=False, server_default='0'))
        _add_column_if_missing(inspector, 'field_configuration_options', sa.Column('large_field_count', sa.Integer(), nullable=False, server_default='0'))
        _add_column_if_missing(inspector, 'field_configuration_options', sa.Column('medium_field_count', sa.Integer(), nullable=False, server_default='0'))
        _add_column_if_missing(inspector, 'field_configuration_options', sa.Column('small_field_count', sa.Integer(), nullable=False, server_default='0'))
        op.execute(
            "UPDATE field_configuration_options SET "
            "configuration_name = COALESCE(configuration_name, name), "
            "surface_type = COALESCE(NULLIF(surface_type, ''), 'GRASS_FIELD'), "
            "small_field_count = CASE WHEN small_field_count = 0 THEN thirty_yard_capacity ELSE small_field_count END, "
            "large_field_count = CASE WHEN large_field_count = 0 THEN fifty_three_yard_capacity ELSE large_field_count END"
        )


def downgrade() -> None:
    pass
