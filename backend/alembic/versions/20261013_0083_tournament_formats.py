"""Tournament division formats and winner/loser feeder outcomes."""
from alembic import op
import sqlalchemy as sa
revision = '20261013_0083'
down_revision = '20260906_0082'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('tournament_divisions', sa.Column('bracket_type', sa.String(40), nullable=False, server_default='SINGLE_ELIMINATION'))
    for side in (1, 2):
        op.add_column('tournament_games', sa.Column(f'team_{side}_source_outcome', sa.String(10), nullable=False, server_default='WINNER'))

def downgrade():
    for side in (1, 2):
        op.drop_column('tournament_games', f'team_{side}_source_outcome')
    op.drop_column('tournament_divisions', 'bracket_type')
