"""Persistent reviewed promotion intent, result and immutable audit.

Revision ID: 0049_promotions
Revises: 0045_registry_v2
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0049_promotions"
down_revision = "0045_registry_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "promotion_events",
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("candidate_digest", sa.Text(), nullable=False),
        sa.Column("approval_reference", sa.Text(), nullable=False),
        sa.Column("approval_identity", sa.Text(), nullable=False),
        sa.Column("previous_channel_version", sa.Text(), nullable=True),
        sa.Column("new_channel_version", sa.Text(), nullable=False),
        sa.Column("intent", JSONB(), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column(
            "committed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "version"],
            ["module_versions.module_id", "module_versions.version"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("module_id", "version"),
        sa.CheckConstraint("channel IN ('stable', 'beta', 'nightly')", name="channel"),
        sa.CheckConstraint("candidate_digest ~ '^[0-9a-f]{64}$'", name="candidate_digest"),
        sa.CheckConstraint("new_channel_version = version", name="target"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM promotion_events)")):
        raise RuntimeError("Cannot discard committed promotion audit; restore compatible service")
    op.drop_table("promotion_events")
