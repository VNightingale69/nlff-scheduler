"""repair current games assigned to retired generated fields

Revision ID: 20260818_0073
Revises: 20260818_0072

The update is deliberately relational and ambiguity-safe.  It changes an
existing game only when exactly one active generated instance with the same
availability, date, type, and decoded human label exists.  No game or score
row is recreated.
"""
from alembic import op


revision = '20260818_0073'
down_revision = '20260818_0072'
branch_labels = None
depends_on = None


_DECODED_NAME = "regexp_replace(fi.field_name, '^__retired_generated__[A-Za-z0-9-]+__(?:retired_generated__[A-Za-z0-9-]+__)*', '')"


def upgrade():
    op.execute(f"""
        WITH retired_assignments AS (
          SELECT g.id AS game_id, fi.id AS retired_id, fi.hosting_availability_id,
                 fi.instance_date, fi.field_type, {_DECODED_NAME} AS human_name
          FROM games g
          JOIN seasons s ON s.id = g.season_id AND s.is_active IS TRUE
          JOIN field_instances fi ON fi.id = g.field_instance_id
          WHERE (fi.is_active IS FALSE OR fi.field_name LIKE '__retired_generated__%')
        ), unique_replacements AS (
          SELECT retired.game_id, min(active.id::text)::uuid AS active_id
          FROM retired_assignments retired
          JOIN field_instances active
            ON active.hosting_availability_id = retired.hosting_availability_id
           AND active.instance_date = retired.instance_date
           AND active.field_type = retired.field_type
           AND active.is_active IS TRUE
           AND active.field_name NOT LIKE '__retired_generated__%'
           AND active.field_name = retired.human_name
          GROUP BY retired.game_id
          HAVING count(*) = 1
        )
        UPDATE games g
        SET field_instance_id = replacement.active_id,
            field_id = COALESCE(g.field_id, availability.field_id),
            field_display_name_snapshot = active.field_name
        FROM unique_replacements replacement
        JOIN field_instances active ON active.id = replacement.active_id
        JOIN hosting_availabilities availability ON availability.id = active.hosting_availability_id
        WHERE g.id = replacement.game_id
    """)


def downgrade():
    # This repair intentionally preserves the valid relationship.  Restoring a
    # retired assignment would reintroduce data corruption and is not safe.
    pass
