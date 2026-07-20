"""Merge migration heads

Revision ID: 20260720_0051
Revises: 20260618_0050, 20260720_0050
"""

from typing import Sequence, Union


revision: str = "20260720_0051"
down_revision: Union[str, Sequence[str], None] = (
    "20260618_0050",
    "20260720_0050",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
