"""repair unambiguous empty layouts and audit invalid memberships

Revision ID: 20260814_0067
Revises: 20260813_0066

The repair is intentionally ID-scoped.  It never derives membership from a
layout name alone: the known repair requires one Johnsburg Hiller Park host,
one empty ``4 Small`` row, and all four exact physical field rows at that host.
Ambiguous or incomplete data remains visible for administrator correction.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260814_0067'
down_revision = '20260813_0066'
branch_labels = None
depends_on = None


HILLER_SMALL_FIELDS = (
    'Johnsburg - Hiller - Small - NE',
    'Johnsburg - Hiller - Small - NW',
    'Johnsburg - Hiller - Small - SE',
    'Johnsburg - Hiller - Small - SW',
)


def upgrade() -> None:
    bind = op.get_bind()

    # A relationship can never be valid across hosts. Removing these rows is
    # safe: validators could not use them and the API refuses to recreate them.
    bind.execute(sa.text("""DELETE FROM field_configuration_members m
        USING host_location_configurations c, fields f
        WHERE m.field_configuration_id=c.id AND m.field_id=f.id
          AND c.host_location_id<>f.host_location_id"""))

    candidates = bind.execute(sa.text("""SELECT c.id, c.host_location_id
        FROM host_location_configurations c
        JOIN host_locations h ON h.id=c.host_location_id
        JOIN organizations o ON o.id=h.organization_id
        LEFT JOIN field_configuration_members m ON m.field_configuration_id=c.id
        WHERE UPPER(TRIM(o.name)) IN ('JOHNSBURG', 'JOHNSBURG SKYHAWKS')
          AND UPPER(TRIM(h.name))='HILLER PARK'
          AND UPPER(TRIM(c.configuration_name))='4 SMALL'
          AND c.is_active=TRUE
        GROUP BY c.id, c.host_location_id HAVING COUNT(m.id)=0""")).all()

    if len(candidates) == 1:
        configuration_id, host_id = candidates[0]
        fields = bind.execute(sa.text("""SELECT id, name FROM fields
            WHERE host_location_id=:host AND deleted_at IS NULL AND is_active=TRUE
              AND name IN :names ORDER BY name""").bindparams(
                  sa.bindparam('names', expanding=True)),
            {'host': host_id, 'names': HILLER_SMALL_FIELDS}).all()
        if len(fields) == 4 and {name for _field_id, name in fields} == set(HILLER_SMALL_FIELDS):
            for field_id, _name in fields:
                bind.execute(sa.text("""INSERT INTO field_configuration_members
                    (id, field_configuration_id, field_id, created_at, updated_at)
                    VALUES (gen_random_uuid(), :configuration, :field, now(), now())
                    ON CONFLICT (field_configuration_id, field_id) DO NOTHING"""),
                    {'configuration': configuration_id, 'field': field_id})
            bind.execute(sa.text("""UPDATE host_location_configurations
                SET small_field_count=4, medium_field_count=0, large_field_count=0,
                    updated_at=now() WHERE id=:configuration"""),
                {'configuration': configuration_id})

    # Emit a deployment audit for every unresolved data-quality class. These
    # layouts remain visible in administration rather than being guessed at.
    bind.execute(sa.text("""DO $$ DECLARE problems integer; BEGIN
      SELECT COUNT(*) INTO problems FROM host_location_configurations c
      WHERE c.is_active AND NOT EXISTS
        (SELECT 1 FROM field_configuration_members m WHERE m.field_configuration_id=c.id);
      RAISE NOTICE 'active field layouts with zero members after repair: %', problems;
      SELECT COUNT(*) INTO problems FROM field_configuration_members m
        JOIN host_location_configurations c ON c.id=m.field_configuration_id
        JOIN fields f ON f.id=m.field_id
        WHERE c.is_active AND (NOT f.is_active OR f.deleted_at IS NOT NULL);
      RAISE NOTICE 'inactive/deleted fields referenced by active layouts: %', problems;
    END $$"""))


def downgrade() -> None:
    # Data repair is not reversed: removing explicit memberships would restore
    # the production readiness defect.
    pass
