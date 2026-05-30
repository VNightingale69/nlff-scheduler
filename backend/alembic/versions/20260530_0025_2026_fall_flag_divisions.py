"""update divisions for 2026 fall flag

Revision ID: 20260530_0025
Revises: 20260530_0024
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa


revision = '20260530_0025'
down_revision = '20260530_0024'
branch_labels = None
depends_on = None


ACTIVE_DIVISIONS = [
    {'division_group': 'COED', 'name': 'K-1', 'sort_order': 1, 'required_field_layout_type': 'SMALL'},
    {'division_group': 'COED', 'name': '2-3', 'sort_order': 2, 'required_field_layout_type': 'SMALL'},
    {'division_group': 'COED', 'name': '4-5', 'sort_order': 3, 'required_field_layout_type': 'MEDIUM'},
    {'division_group': 'COED', 'name': '6-7', 'sort_order': 4, 'required_field_layout_type': 'LARGE'},
    {'division_group': 'COED', 'name': '8', 'sort_order': 5, 'required_field_layout_type': 'LARGE'},
    {'division_group': 'GIRLS', 'name': 'K-2', 'sort_order': 6, 'required_field_layout_type': 'SMALL'},
    {'division_group': 'GIRLS', 'name': '3-5', 'sort_order': 7, 'required_field_layout_type': 'MEDIUM'},
    {'division_group': 'GIRLS', 'name': '6-8', 'sort_order': 8, 'required_field_layout_type': 'LARGE'},
]

COED_RENAMES = [
    ('K/1st', 'K-1'),
    ('2nd/3rd', '2-3'),
    ('4th/5th', '4-5'),
    ('6th/7th', '6-7'),
    ('8th', '8'),
]

OLD_GIRLS_NAMES = ('K/1st', '2nd/3rd', '4th/5th', '6th/7th/8th')


def _execute_seed(active: bool) -> None:
    for item in ACTIVE_DIVISIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO divisions (id, name, division_group, sort_order, required_field_layout_type, is_active)
                VALUES (gen_random_uuid(), :name, :division_group, :sort_order, :required_field_layout_type, :is_active)
                ON CONFLICT (division_group, name)
                DO UPDATE SET
                    sort_order = EXCLUDED.sort_order,
                    required_field_layout_type = EXCLUDED.required_field_layout_type,
                    is_active = EXCLUDED.is_active
                """
            ).bindparams(**item, is_active=active)
        )


def upgrade() -> None:
    # Preserve COED IDs and dependent participation/team/schedule references by renaming in place.
    for old_name, new_name in COED_RENAMES:
        op.execute(
            sa.text(
                """
                UPDATE divisions old_division
                SET name = :new_name
                WHERE old_division.division_group = 'COED'
                  AND old_division.name = :old_name
                  AND NOT EXISTS (
                      SELECT 1 FROM divisions existing
                      WHERE existing.division_group = 'COED' AND existing.name = :new_name
                  )
                """
            ).bindparams(old_name=old_name, new_name=new_name)
        )

    _execute_seed(active=True)

    op.execute(
        """
        UPDATE divisions
        SET is_active = false
        WHERE division_group = 'GIRLS'
          AND name IN ('K/1st', '2nd/3rd', '4th/5th', '6th/7th/8th')
        """
    )


def downgrade() -> None:
    for old_name, new_name in reversed(COED_RENAMES):
        op.execute(
            sa.text(
                """
                UPDATE divisions new_division
                SET name = :old_name
                WHERE new_division.division_group = 'COED'
                  AND new_division.name = :new_name
                  AND NOT EXISTS (
                      SELECT 1 FROM divisions existing
                      WHERE existing.division_group = 'COED' AND existing.name = :old_name
                  )
                """
            ).bindparams(old_name=old_name, new_name=new_name)
        )

    op.execute(
        """
        UPDATE divisions
        SET is_active = true
        WHERE division_group = 'GIRLS'
          AND name IN ('K/1st', '2nd/3rd', '4th/5th', '6th/7th/8th')
        """
    )
