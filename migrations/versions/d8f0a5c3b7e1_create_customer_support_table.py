"""create customer support table

Revision ID: d8f0a5c3b7e1
Revises: bcfe549e6594
Create Date: 2026-08-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d8f0a5c3b7e1"
down_revision = "bcfe549e6594"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_support",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("subject", sa.String(length=180), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="Open"),
        sa.Column("admin_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customer_support_order_id"), "customer_support", ["order_id"], unique=False)
    op.create_index(op.f("ix_customer_support_user_id"), "customer_support", ["user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_customer_support_user_id"), table_name="customer_support")
    op.drop_index(op.f("ix_customer_support_order_id"), table_name="customer_support")
    op.drop_table("customer_support")
