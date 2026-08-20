"""repair unambiguous missing host layout memberships

Revision ID: 20260820_0077
Revises: 20260820_0076

Persisted per-size counts are legacy layout evidence.  This repair fills a
partially populated configuration only when the number of unreferenced active
same-host fields exactly equals the number of missing positions.  It therefore
repairs canonical IDs without guessing among physical fields or changing games.
"""
import logging

from alembic import op
import sqlalchemy as sa


revision = '20260820_0077'
down_revision = '20260820_0076'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')


_REPAIR_MISSING_MEMBERSHIPS_SQL = """WITH sizes(size) AS (
  VALUES ('SMALL'), ('MEDIUM'), ('LARGE')
), expected AS (
  SELECT c.id configuration_id, c.host_location_id, sizes.size,
    CASE sizes.size WHEN 'SMALL' THEN c.small_field_count
      WHEN 'MEDIUM' THEN c.medium_field_count ELSE c.large_field_count END expected_count
  FROM host_location_configurations c CROSS JOIN sizes
  WHERE c.is_active=TRUE
), current_counts AS (
  SELECT e.configuration_id, e.size, count(f.id) current_count
  FROM expected e LEFT JOIN field_configuration_members m
    ON m.field_configuration_id=e.configuration_id
  LEFT JOIN fields f ON f.id=m.field_id AND f.host_location_id=e.host_location_id
    AND f.is_active=TRUE AND f.deleted_at IS NULL AND upper(f.layout_type)=e.size
  GROUP BY e.configuration_id, e.size
), candidates AS (
  SELECT e.configuration_id, e.size, f.id field_id,
    e.expected_count-current.current_count missing_count,
    count(*) OVER (PARTITION BY e.configuration_id, e.size) candidate_count
  FROM expected e JOIN current_counts current
    ON current.configuration_id=e.configuration_id AND current.size=e.size
  JOIN fields f ON f.host_location_id=e.host_location_id AND f.is_active=TRUE
    AND f.deleted_at IS NULL AND upper(f.layout_type)=e.size
  WHERE e.expected_count>current.current_count
    AND NOT EXISTS (SELECT 1 FROM field_configuration_members m
      WHERE m.field_configuration_id=e.configuration_id AND m.field_id=f.id)
), unambiguous AS (
  SELECT configuration_id, field_id FROM candidates
  WHERE missing_count=candidate_count
), inserted AS (
  INSERT INTO field_configuration_members
    (id, field_configuration_id, field_id, created_at, updated_at)
  SELECT gen_random_uuid(), configuration_id, field_id, now(), now()
  FROM unambiguous ON CONFLICT(field_configuration_id, field_id) DO NOTHING
  RETURNING id
)
SELECT (SELECT count(*) FROM candidates) candidates_inspected,
  (SELECT count(*) FROM unambiguous) unambiguous_candidates,
  (SELECT count(*) FROM inserted) memberships_repaired"""


def upgrade() -> None:
    bind = op.get_bind()
    counts = bind.execute(sa.text(_REPAIR_MISSING_MEMBERSHIPS_SQL)).mappings().one()
    logger.info(
        'Missing configuration membership repair: candidates=%s; unambiguous=%s; repaired=%s',
        counts['candidates_inspected'], counts['unambiguous_candidates'], counts['memberships_repaired'],
    )

    # Concise host-agnostic deployment audit. It exposes the exact persisted
    # IDs/configurations needed to diagnose unresolved layouts without adding
    # noisy request-time logging or field-name compatibility behavior.
    bind.execute(sa.text("""DO $$ DECLARE row record; BEGIN
      FOR row IN SELECT h.id host_id, h.name host_name, f.id field_id, f.name field_name,
        array_remove(array_agg(DISTINCT c.configuration_name), NULL) configurations
      FROM host_locations h JOIN fields f ON f.host_location_id=h.id
      LEFT JOIN field_configuration_members m ON m.field_id=f.id
      LEFT JOIN host_location_configurations c ON c.id=m.field_configuration_id AND c.is_active
      WHERE f.is_active AND f.deleted_at IS NULL
      GROUP BY h.id, h.name, f.id, f.name
      LOOP RAISE NOTICE 'HOST CONFIGURATION MEMBERSHIP AUDIT host=% (%) field=% (%) active configurations=%',
        row.host_name, row.host_id, row.field_name, row.field_id, row.configurations;
      END LOOP;
    END $$"""))


def downgrade() -> None:
    # An unambiguous data integrity repair must survive code rollback.
    pass
