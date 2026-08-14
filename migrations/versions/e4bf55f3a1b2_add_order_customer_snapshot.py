"""Add order customer snapshot fields

Revision ID: e4bf55f3a1b2
Revises: d8f0a5c3b7e1
Create Date: 2026-08-14 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e4bf55f3a1b2"
down_revision = "d8f0a5c3b7e1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("customer_name", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("customer_email", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("customer_phone", sa.String(length=15), nullable=True))
        batch_op.add_column(sa.Column("shipping_address_line1", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("shipping_address_line2", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("shipping_city", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("shipping_state", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("shipping_pincode", sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column("shipping_country", sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_column("shipping_country")
        batch_op.drop_column("shipping_pincode")
        batch_op.drop_column("shipping_state")
        batch_op.drop_column("shipping_city")
        batch_op.drop_column("shipping_address_line2")
        batch_op.drop_column("shipping_address_line1")
        batch_op.drop_column("customer_phone")
        batch_op.drop_column("customer_email")
        batch_op.drop_column("customer_name")
