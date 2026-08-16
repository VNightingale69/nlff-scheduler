"""preserve historical game field display across field migrations

Revision ID: 20260816_0070
Revises: 20260816_0069
"""
from alembic import op
import sqlalchemy as sa

revision = '20260816_0070'
down_revision = '20260816_0069'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('games', sa.Column('field_display_name_snapshot', sa.String(120), nullable=True))
    op.add_column('games', sa.Column('physical_area_name_snapshot', sa.String(120), nullable=True))
    op.add_column('games', sa.Column('host_location_name_snapshot', sa.String(255), nullable=True))

    # Exact, ID-based evidence only.  No division/name inference is used.
    op.execute(sa.text('''
        UPDATE games AS g SET
          field_display_name_snapshot = COALESCE(
            (SELECT fi.field_name FROM field_instances fi WHERE fi.id = g.field_instance_id),
            (SELECT f.name FROM fields f WHERE f.id = g.field_id), g.previous_field_name),
          physical_area_name_snapshot = (SELECT pa.name FROM fields f JOIN physical_field_areas pa
            ON pa.id = f.physical_field_area_id WHERE f.id = g.field_id),
          host_location_name_snapshot = (SELECT h.name FROM host_locations h WHERE h.id = COALESCE(
            g.host_location_id,
            (SELECT f.host_location_id FROM fields f WHERE f.id = g.field_id),
            (SELECT fi.host_location_id FROM field_instances fi WHERE fi.id = g.field_instance_id)))
        WHERE g.field_display_name_snapshot IS NULL AND COALESCE(
          (SELECT fi.field_name FROM field_instances fi WHERE fi.id = g.field_instance_id),
          (SELECT f.name FROM fields f WHERE f.id = g.field_id), g.previous_field_name) IS NOT NULL
    '''))
    # A generated assignment is often stored only on its assigned slot.
    op.execute(sa.text('''
        UPDATE games AS g
        SET field_display_name_snapshot = fi.field_name,
            host_location_name_snapshot = h.name
        FROM game_slots AS gs
        JOIN field_instances AS fi ON fi.id = gs.field_instance_id
        LEFT JOIN host_locations AS h ON h.id = gs.host_location_id
        WHERE gs.assigned_game_id = g.id
          AND g.field_display_name_snapshot IS NULL
    '''))


def downgrade():
    op.drop_column('games', 'host_location_name_snapshot')
    op.drop_column('games', 'physical_area_name_snapshot')
    op.drop_column('games', 'field_display_name_snapshot')
