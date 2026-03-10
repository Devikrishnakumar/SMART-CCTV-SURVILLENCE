"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.Enum("operator", "dispatcher", "admin", name="userrole"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "cameras",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("location_name", sa.String(256), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("status", sa.Enum("active", "inactive", "maintenance", name="camerastatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("type", sa.Enum("accident", "violence", "fallen_person", name="incidenttype"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("camera_id", sa.String(36), sa.ForeignKey("cameras.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), index=True),
        sa.Column("snapshot_url", sa.Text(), nullable=True),
        sa.Column("video_clip_url", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("status", sa.Enum("pending", "verified", "dispatched", "resolved", "closed", name="incidentstatus"), nullable=False, server_default="pending"),
        sa.Column("assigned_unit", sa.String(128), nullable=True),
        sa.Column("response_time", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_timestamp", "incidents", ["timestamp"])

    op.create_table(
        "dispatch_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id"), nullable=False, index=True),
        sa.Column("action", sa.String(256), nullable=False),
        sa.Column("performed_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("metadata", sa.Text(), nullable=True),
    )
    op.create_index("ix_dispatch_logs_incident_id", "dispatch_logs", ["incident_id"])


def downgrade() -> None:
    op.drop_table("dispatch_logs")
    op.drop_table("incidents")
    op.drop_table("cameras")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS userrole")
    op.execute("DROP TYPE IF EXISTS camerastatus")
    op.execute("DROP TYPE IF EXISTS incidenttype")
    op.execute("DROP TYPE IF EXISTS incidentstatus")
