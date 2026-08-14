"""Add review status

Revision ID: b1c0d0f0aa01
Revises: 78aa1efdece9
Create Date: 2026-08-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1c0d0f0aa01"
# This migration was created after the database had already reached the
# consolidated schema revision. Keeping it on the old parent created a second
# Alembic head, so `flask db upgrade` could not select a target revision.
down_revision = "78aa1efdece9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "reviews",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
    )


def downgrade():
    op.drop_column("reviews", "status")
