"""Add device identity and publication controls."""

import sqlalchemy as sa
from alembic import op

revision = "b5949a67c210"
down_revision = "747ea0168a09"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("oauth_devices", "publishes"):
        for name in ("device_name", "agent_name"):
            op.add_column(table, sa.Column(name, sa.String(120)))
    op.add_column("oauth_devices", sa.Column("device_model", sa.String(120)))
    op.add_column("publishes", sa.Column("paused_at", sa.Integer()))
    op.add_column("publishes", sa.Column("source_cli", sa.Boolean()))


def downgrade():
    op.drop_column("publishes", "source_cli")
    op.drop_column("publishes", "paused_at")
    op.drop_column("oauth_devices", "device_model")
    for table in ("oauth_devices", "publishes"):
        for name in ("agent_name", "device_name"):
            op.drop_column(table, name)
