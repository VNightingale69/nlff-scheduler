"""seed required game statuses

Revision ID: 20260522_0012
Revises: 20260522_0011
Create Date: 2026-05-22
"""

from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa


revision = '20260522_0012'
down_revision = '20260522_0011'
branch_labels = None
depends_on = None


REQUIRED = [
    ('SCHEDULED', 'Scheduled'),
    ('COMPLETED', 'Completed'),
    ('CANCELLED', 'Cancelled'),
    ('POSTPONED', 'Postponed'),
    ('FORFEIT', 'Forfeit'),
]


def upgrade() -> None:
    bind = op.get_bind()
    for code, label in REQUIRED:
        exact = bind.execute(
            sa.text('SELECT id FROM game_statuses WHERE code = :code LIMIT 1'),
            {'code': code},
        ).first()
        if exact:
            bind.execute(
                sa.text('UPDATE game_statuses SET label = :label, is_active = true WHERE id = :id'),
                {'id': exact.id, 'label': label},
            )
            continue

        existing = bind.execute(
            sa.text('SELECT id FROM game_statuses WHERE lower(code) = lower(:code) ORDER BY created_at ASC LIMIT 1'),
            {'code': code},
        ).first()
        if existing:
            bind.execute(
                sa.text('UPDATE game_statuses SET code = :code, label = :label, is_active = true WHERE id = :id'),
                {'id': existing.id, 'code': code, 'label': label},
            )
            continue

        bind.execute(
            sa.text('INSERT INTO game_statuses (id, code, label, is_active) VALUES (:id, :code, :label, true)'),
            {'id': str(uuid.uuid4()), 'code': code, 'label': label},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code, _ in REQUIRED:
        bind.execute(sa.text('DELETE FROM game_statuses WHERE code = :code'), {'code': code})
