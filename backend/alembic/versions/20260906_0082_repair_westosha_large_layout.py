"""Enforce Westosha's single-large-field facility capability.

Revision ID: 20260906_0082
Revises: 20260903_0081
"""
from alembic import op
import sqlalchemy as sa


revision = '20260906_0082'
down_revision = '20260903_0081'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    facilities = bind.execute(sa.text("""
        SELECT id FROM host_locations
        WHERE lower(trim(name)) IN (
          'westosha high school stadium', 'westosha stadium'
        )
    """)).scalars().all()
    for host_id in facilities:
        # Retire every spelling of the invalid layout, but only at Westosha.
        bind.execute(sa.text("""
            UPDATE host_location_configurations
            SET is_active = false, is_legacy = true, updated_at = now()
            WHERE host_location_id = :host_id
              AND upper(regexp_replace(trim(configuration_name), '[^A-Za-z0-9]+', '_', 'g'))
                  = 'TWO_LARGE'
        """), {'host_id': host_id})

        one_large_id = bind.execute(sa.text("""
            SELECT id FROM host_location_configurations
            WHERE host_location_id = :host_id
              AND upper(regexp_replace(trim(configuration_name), '[^A-Za-z0-9]+', '_', 'g'))
                  = 'ONE_LARGE'
            ORDER BY created_at, id LIMIT 1
        """), {'host_id': host_id}).scalar()
        if one_large_id is None:
            one_large_id = bind.execute(sa.text("""
                INSERT INTO host_location_configurations
                  (id, host_location_id, configuration_name, surface_type,
                   space_used_yards, remaining_yards, large_field_count,
                   medium_field_count, small_field_count, is_active, is_legacy,
                   sort_order, created_at, updated_at)
                VALUES
                  (gen_random_uuid(), :host_id, 'ONE_LARGE', 'TURF_STADIUM',
                   53, 67, 1, 0, 0, true, false, 4, now(), now())
                RETURNING id
            """), {'host_id': host_id}).scalar_one()
        bind.execute(sa.text("""
            UPDATE host_location_configurations
            SET configuration_name = 'ONE_LARGE', large_field_count = 1,
                medium_field_count = 0, small_field_count = 0,
                is_active = true, is_legacy = false, updated_at = now()
            WHERE id = :configuration_id
        """), {'configuration_id': one_large_id})
        # Collapse duplicate aliases without touching layouts at other hosts.
        bind.execute(sa.text("""
            UPDATE host_location_configurations
            SET is_active = false, is_legacy = true, updated_at = now()
            WHERE host_location_id = :host_id AND id <> :configuration_id
              AND upper(regexp_replace(trim(configuration_name), '[^A-Za-z0-9]+', '_', 'g'))
                  = 'ONE_LARGE'
        """), {'host_id': host_id, 'configuration_id': one_large_id})

        # Existing kickoff locks selected by the old resolver should resolve
        # through the repaired capability on the next readiness/publish pass.
        bind.execute(sa.text("""
            UPDATE timeslot_field_configurations AS slot
            SET configuration_id = :configuration_id, updated_at = now()
            FROM host_location_configurations AS old_configuration
            WHERE slot.host_location_id = :host_id
              AND slot.configuration_id = old_configuration.id
              AND old_configuration.host_location_id = :host_id
              AND upper(regexp_replace(trim(old_configuration.configuration_name),
                    '[^A-Za-z0-9]+', '_', 'g')) = 'TWO_LARGE'
        """), {'host_id': host_id, 'configuration_id': one_large_id})

        large_field_id = bind.execute(sa.text("""
            SELECT id FROM fields
            WHERE host_location_id = :host_id AND deleted_at IS NULL
              AND is_active = true AND lower(trim(name)) = 'large field 1'
              AND upper(trim(layout_type)) = 'LARGE'
            ORDER BY created_at, id LIMIT 1
        """), {'host_id': host_id}).scalar()
        if large_field_id is None:
            raise RuntimeError(
                'Cannot repair Westosha ONE_LARGE: active LARGE "Large Field 1" is missing.'
            )
        bind.execute(sa.text("""
            DELETE FROM field_configuration_members
            WHERE field_configuration_id = :configuration_id
        """), {'configuration_id': one_large_id})
        bind.execute(sa.text("""
            INSERT INTO field_configuration_members
              (id, field_configuration_id, field_id, created_at, updated_at)
            VALUES (gen_random_uuid(), :configuration_id, :field_id, now(), now())
        """), {'configuration_id': one_large_id, 'field_id': large_field_id})


def downgrade():
    # The invalid capability and potentially stale memberships must not be
    # recreated automatically.
    pass
