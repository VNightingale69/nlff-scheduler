"""repair unambiguous canonical host layout memberships

Revision ID: 20260820_0076
Revises: 20260820_0075

This data repair is host-agnostic and idempotent. It uses each layout's
persisted legacy counts only when they identify the host's complete active
inventory unambiguously. It never changes game assignments or matches layouts
by display name.
"""
from alembic import op
import sqlalchemy as sa


revision = '20260820_0076'
down_revision = '20260820_0075'
branch_labels = None
depends_on = None


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
    bind.execute(sa.text("""WITH replacements AS (
      SELECT m.id member_id, min(n.id) new_field_id
      FROM field_configuration_members m
      JOIN host_location_configurations c ON c.id=m.field_configuration_id
      JOIN fields old ON old.id=m.field_id
      JOIN fields n ON n.host_location_id=c.host_location_id
       AND lower(regexp_replace(trim(n.name), '\\s+', ' ', 'g'))=
           lower(regexp_replace(trim(old.name), '\\s+', ' ', 'g'))
       AND n.is_active=TRUE AND n.deleted_at IS NULL
      WHERE (old.is_active=FALSE OR old.deleted_at IS NOT NULL)
      GROUP BY m.id HAVING count(n.id)=1
    ) UPDATE field_configuration_members m SET field_id=r.new_field_id,
      updated_at=now() FROM replacements r WHERE m.id=r.member_id
      AND NOT EXISTS (SELECT 1 FROM field_configuration_members x
        WHERE x.field_configuration_id=m.field_configuration_id
          AND x.field_id=r.new_field_id AND x.id<>m.id)"""))

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
