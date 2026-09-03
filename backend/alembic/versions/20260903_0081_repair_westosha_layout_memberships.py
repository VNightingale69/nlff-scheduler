"""Repair canonical Westosha Stadium layout memberships.

Revision ID: 20260903_0081
Revises: 20260821_0080
"""
from alembic import op
import sqlalchemy as sa


revision = '20260903_0081'
down_revision = '20260821_0080'
branch_labels = None
depends_on = None


EXPECTED = {
    'ONE_LARGE_ONE_SMALL': ('Large Field 1', 'Small Field 1'),
    'THREE_SMALL': ('Small Field 1', 'Small Field 2', 'Small Field 3'),
    'TWO_MEDIUM': ('Medium 1', 'Medium 2'),
}


def upgrade():
    connection = op.get_bind()
    # Only repair the specifically known facility and only when every desired
    # canonical Field row exists uniquely. Deleting a membership cannot delete
    # a Field or a scheduled Game, and the insert is idempotent.
    facilities = connection.execute(sa.text("""
        SELECT id FROM host_locations
        WHERE lower(trim(name)) IN (
          'westosha high school stadium', 'westosha stadium'
        )
    """)).scalars().all()
    for facility_id in facilities:
        for code, names in EXPECTED.items():
            configuration_id = connection.execute(sa.text("""
                SELECT id FROM host_location_configurations
                WHERE host_location_id = :facility_id
                  AND upper(trim(configuration_name)) = :code
                  AND is_active = true
            """), {'facility_id': facility_id, 'code': code}).scalar()
            if not configuration_id:
                continue
            rows = connection.execute(sa.text("""
                SELECT id, name FROM fields
                WHERE host_location_id = :facility_id
                  AND deleted_at IS NULL AND is_active = true
                  AND lower(trim(name)) IN :names
            """).bindparams(sa.bindparam('names', expanding=True)), {
                'facility_id': facility_id,
                'names': tuple(name.lower() for name in names),
            }).all()
            by_name = {}
            for field_id, name in rows:
                by_name.setdefault(name.strip().lower(), []).append(field_id)
            if any(len(by_name.get(name.lower(), ())) != 1 for name in names):
                continue
            canonical_ids = [by_name[name.lower()][0] for name in names]
            connection.execute(sa.text("""
                DELETE FROM field_configuration_members
                WHERE id IN (
                  SELECT id FROM (
                    SELECT id, row_number() OVER (
                      PARTITION BY field_configuration_id, field_id
                      ORDER BY created_at, id
                    ) AS duplicate_number
                    FROM field_configuration_members
                    WHERE field_configuration_id = :configuration_id
                  ) duplicates
                  WHERE duplicate_number > 1
                )
            """), {'configuration_id': configuration_id})
            connection.execute(sa.text("""
                DELETE FROM field_configuration_members
                WHERE field_configuration_id = :configuration_id
                  AND field_id NOT IN :field_ids
            """).bindparams(sa.bindparam('field_ids', expanding=True)), {
                'configuration_id': configuration_id, 'field_ids': tuple(canonical_ids),
            })
            for field_id in canonical_ids:
                connection.execute(sa.text("""
                    INSERT INTO field_configuration_members
                      (id, field_configuration_id, field_id, created_at, updated_at)
                    SELECT gen_random_uuid(), :configuration_id, :field_id, now(), now()
                    WHERE NOT EXISTS (
                      SELECT 1 FROM field_configuration_members
                      WHERE field_configuration_id = :configuration_id
                        AND field_id = :field_id
                    )
                """), {'configuration_id': configuration_id, 'field_id': field_id})


def downgrade():
    # A stale relationship cannot be reconstructed safely.
    pass
