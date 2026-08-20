"""repair unambiguous canonical host layout memberships

Revision ID: 20260820_0076
Revises: 20260820_0075

This data repair is host-agnostic and idempotent. It uses each layout's
persisted legacy counts only when they identify the host's complete active
inventory unambiguously. It never changes game assignments or matches layouts
by display name.
"""
import logging

from alembic import op
import sqlalchemy as sa


revision = '20260820_0076'
down_revision = '20260820_0075'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')


_REPAIR_RETIRED_MEMBERSHIPS_SQL = """WITH eligible_members AS (
  SELECT m.id AS member_id, m.field_configuration_id, old.name AS old_name
  FROM field_configuration_members m
  JOIN host_location_configurations c ON c.id=m.field_configuration_id
  JOIN fields old ON old.id=m.field_id
  WHERE old.is_active=FALSE OR old.deleted_at IS NOT NULL
), candidates AS (
  SELECT e.member_id, e.field_configuration_id, n.id AS new_field_id
  FROM eligible_members e
  JOIN host_location_configurations c ON c.id=e.field_configuration_id
  JOIN fields n ON n.host_location_id=c.host_location_id
   AND lower(regexp_replace(trim(n.name), '\\s+', ' ', 'g'))=
       lower(regexp_replace(trim(e.old_name), '\\s+', ' ', 'g'))
   AND n.is_active=TRUE AND n.deleted_at IS NULL
), candidate_counts AS (
  SELECT e.member_id, count(c.new_field_id) AS candidate_count
  FROM eligible_members e
  LEFT JOIN candidates c ON c.member_id=e.member_id
  GROUP BY e.member_id
), unambiguous AS (
  SELECT c.member_id, c.field_configuration_id, c.new_field_id
  FROM candidates c
  JOIN candidate_counts counts ON counts.member_id=c.member_id
  WHERE counts.candidate_count=1
), repairable AS (
  SELECT u.*
  FROM unambiguous u
  WHERE NOT EXISTS (SELECT 1 FROM field_configuration_members x
    WHERE x.field_configuration_id=u.field_configuration_id
      AND x.field_id=u.new_field_id AND x.id<>u.member_id)
), repaired AS (
  UPDATE field_configuration_members m SET field_id=r.new_field_id,
    updated_at=now() FROM repairable r
  WHERE m.id=r.member_id AND m.field_id IS DISTINCT FROM r.new_field_id
  RETURNING m.id
)
SELECT
  (SELECT count(*) FROM candidates) AS candidates_inspected,
  (SELECT count(*) FROM repaired) AS unambiguous_repairs,
  (SELECT count(*) FROM candidate_counts WHERE candidate_count>1) AS ambiguous_skipped,
  (SELECT count(*) FROM candidate_counts WHERE candidate_count=0) AS no_match_skipped,
  ((SELECT count(*) FROM unambiguous)-(SELECT count(*) FROM repairable)) AS existing_target_skipped"""


def upgrade() -> None:
    bind = op.get_bind()
    # Remove impossible cross-host links before attempting a canonical repair.
    bind.execute(sa.text("""DELETE FROM field_configuration_members m
        USING host_location_configurations c, fields f
        WHERE m.field_configuration_id=c.id AND m.field_id=f.id
          AND c.host_location_id<>f.host_location_id"""))

    # Replace a retired member only where its normalized label has exactly one
    # active successor at the same host. Names are migration evidence only;
    # runtime matching remains entirely ID-based.
    repair_counts = bind.execute(
        sa.text(_REPAIR_RETIRED_MEMBERSHIPS_SQL)
    ).mappings().one()
    logger.info(
        'Canonical membership repair: Candidates inspected: %s; '
        'Unambiguous repairs: %s; Ambiguous mappings skipped: %s; '
        'No-match mappings skipped: %s; Existing target memberships skipped: %s',
        repair_counts['candidates_inspected'],
        repair_counts['unambiguous_repairs'],
        repair_counts['ambiguous_skipped'],
        repair_counts['no_match_skipped'],
        repair_counts['existing_target_skipped'],
    )

    # Empty legacy layouts are safe to reconstruct only if every required size
    # count equals the complete active inventory for that host. Extra fields of
    # a required size make the mapping ambiguous and leave the row unresolved.
    bind.execute(sa.text("""WITH candidates AS (
      SELECT c.id configuration_id, f.id field_id
      FROM host_location_configurations c JOIN fields f ON f.host_location_id=c.host_location_id
      WHERE c.is_active=TRUE AND f.is_active=TRUE AND f.deleted_at IS NULL
        AND NOT EXISTS (SELECT 1 FROM field_configuration_members m WHERE m.field_configuration_id=c.id)
        AND CASE upper(f.layout_type)
          WHEN 'SMALL' THEN c.small_field_count
          WHEN 'MEDIUM' THEN c.medium_field_count
          WHEN 'LARGE' THEN c.large_field_count ELSE 0 END > 0
        AND (c.small_field_count=0 OR c.small_field_count=(SELECT count(*) FROM fields x WHERE x.host_location_id=c.host_location_id AND x.is_active AND x.deleted_at IS NULL AND upper(x.layout_type)='SMALL'))
        AND (c.medium_field_count=0 OR c.medium_field_count=(SELECT count(*) FROM fields x WHERE x.host_location_id=c.host_location_id AND x.is_active AND x.deleted_at IS NULL AND upper(x.layout_type)='MEDIUM'))
        AND (c.large_field_count=0 OR c.large_field_count=(SELECT count(*) FROM fields x WHERE x.host_location_id=c.host_location_id AND x.is_active AND x.deleted_at IS NULL AND upper(x.layout_type)='LARGE'))
    ) INSERT INTO field_configuration_members(id, field_configuration_id, field_id, created_at, updated_at)
      SELECT gen_random_uuid(), configuration_id, field_id, now(), now() FROM candidates
      ON CONFLICT(field_configuration_id, field_id) DO NOTHING"""))

    bind.execute(sa.text("""DO $$ DECLARE host record; BEGIN
      FOR host IN SELECT h.id, h.name,
        count(DISTINCT f.id) FILTER (WHERE f.is_active AND f.deleted_at IS NULL) active_fields,
        count(DISTINCT c.id) FILTER (WHERE c.is_active) active_configs,
        count(DISTINCT c.id) FILTER (WHERE c.is_active AND m.id IS NULL) missing
        FROM host_locations h LEFT JOIN fields f ON f.host_location_id=h.id
        LEFT JOIN host_location_configurations c ON c.host_location_id=h.id
        LEFT JOIN field_configuration_members m ON m.field_configuration_id=c.id
        GROUP BY h.id, h.name
      LOOP RAISE NOTICE 'HOST CONFIGURATION REPAIR % (id=%): active fields=%, active configurations=%, unresolved empty configurations=%',
        host.name, host.id, host.active_fields, host.active_configs, host.missing; END LOOP;
    END $$"""))


def downgrade() -> None:
    # Canonical relationship repairs intentionally survive code rollback.
    pass
