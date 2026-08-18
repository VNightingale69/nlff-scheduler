"""retire legacy girls divisions safely

Revision ID: 20260818_0071
Revises: 20260816_0070
Create Date: 2026-08-18
"""

from alembic import op


revision = '20260818_0071'
down_revision = '20260816_0070'
branch_labels = None
depends_on = None


LEGACY_NAMES_SQL = "'K/1st', '2nd/3rd', '4th/5th', '6th/7th/8th'"


def upgrade() -> None:
    # There is no evidence-based one-to-one mapping from the four former grade
    # bands to the three current bands. Refuse to guess if current data uses one.
    op.execute(f"""
        DO $$
        DECLARE current_game_count integer;
        DECLARE current_team_count integer;
        BEGIN
          SELECT count(DISTINCT g.id) INTO current_game_count
          FROM games g
          JOIN seasons s ON s.id = g.season_id AND s.is_active = true
          JOIN teams ht ON ht.id = g.home_team_id
          JOIN teams at ON at.id = g.away_team_id
          JOIN divisions d ON d.id IN (ht.division_id, at.division_id)
          WHERE d.division_group = 'GIRLS' AND d.name IN ({LEGACY_NAMES_SQL});

          SELECT count(DISTINCT t.id) INTO current_team_count
          FROM teams t JOIN divisions d ON d.id = t.division_id
          WHERE t.is_active = true AND t.deleted_at IS NULL
            AND d.division_group = 'GIRLS' AND d.name IN ({LEGACY_NAMES_SQL});

          IF current_game_count > 0 OR current_team_count > 0 THEN
            RAISE EXCEPTION 'Legacy Girls division repair stopped: % current-season games and % active teams require evidence-based reassignment', current_game_count, current_team_count;
          END IF;
          RAISE NOTICE 'Legacy Girls division audit: no current games or active teams reference retired divisions';
        END $$;
    """)
    op.execute(f"""
        UPDATE organization_division_participations p
        SET is_active = false, is_participating = false, updated_at = now()
        FROM divisions d
        WHERE p.division_id = d.id AND d.division_group = 'GIRLS'
          AND d.name IN ({LEGACY_NAMES_SQL})
          AND (p.is_active = true OR p.is_participating = true)
    """)
    op.execute(f"""
        UPDATE divisions SET is_active = false, updated_at = now()
        WHERE division_group = 'GIRLS' AND name IN ({LEGACY_NAMES_SQL})
          AND is_active = true
    """)


def downgrade() -> None:
    # Deliberately do not reactivate retired configuration. Historical rows and
    # references were never deleted and remain readable through season scoping.
    pass
