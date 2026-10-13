"""Independent bracket-only publication."""
from alembic import op
import sqlalchemy as sa
revision = '20261013_0084'
down_revision = '20261013_0083'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('tournaments', sa.Column('bracket_is_published', sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column('tournaments', 'bracket_is_published')
