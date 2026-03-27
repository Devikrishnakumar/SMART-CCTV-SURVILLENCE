"""Align schema with event-verification workflow.

Revision ID: 002
Revises: 001
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as batch_op:
        batch_op.add_column(sa.Column("stream_url", sa.Text(), nullable=True))

    with op.batch_alter_table("incidents") as batch_op:
        batch_op.add_column(sa.Column("event_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("peak_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("evidence_frames", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("verification_source", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_incidents_event_id", ["event_id"], unique=False)

    with op.batch_alter_table("dispatch_logs") as batch_op:
        batch_op.alter_column("performed_by_id", existing_type=sa.String(length=36), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("dispatch_logs") as batch_op:
        batch_op.alter_column("performed_by_id", existing_type=sa.String(length=36), nullable=False)

    with op.batch_alter_table("incidents") as batch_op:
        batch_op.drop_index("ix_incidents_event_id")
        batch_op.drop_column("verification_source")
        batch_op.drop_column("evidence_frames")
        batch_op.drop_column("peak_confidence")
        batch_op.drop_column("event_id")

    with op.batch_alter_table("cameras") as batch_op:
        batch_op.drop_column("stream_url")
