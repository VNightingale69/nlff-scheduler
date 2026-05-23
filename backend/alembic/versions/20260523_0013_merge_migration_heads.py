"""merge migration heads

Revision ID: 20260523_0013
Revises: 20260522_0012, 20260523_0012
Create Date: 2026-05-23

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision = '20260523_0013'
down_revision = ('20260522_0012', '20260523_0012')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
