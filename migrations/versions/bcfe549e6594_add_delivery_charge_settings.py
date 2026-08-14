"""add delivery charge settings

Revision ID: bcfe549e6594
Revises: b1c0d0f0aa01
Create Date: 2026-08-11 10:14:29.078982

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bcfe549e6594'
down_revision = 'b1c0d0f0aa01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('site_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.execute(
        """
        INSERT INTO site_settings (key, value, created_at, updated_at)
        VALUES ('delivery_charge', 0.00, NOW(), NOW())
        """
    )

    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subtotal_amount', sa.Numeric(precision=10, scale=2), nullable=True))

    op.execute(
        """
        UPDATE orders
        SET subtotal_amount = item_totals.subtotal
        FROM (
            SELECT order_id, COALESCE(SUM(price * quantity), 0) AS subtotal
            FROM order_items
            GROUP BY order_id
        ) AS item_totals
        WHERE item_totals.order_id = orders.id
        """
    )
    op.execute("UPDATE orders SET subtotal_amount = 0.00 WHERE subtotal_amount IS NULL")

    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.alter_column(
            'subtotal_amount',
            existing_type=sa.Numeric(precision=10, scale=2),
            nullable=False,
        )


def downgrade():
    with op.batch_alter_table('orders', schema=None) as batch_op:
        batch_op.drop_column('subtotal_amount')

    op.drop_table('site_settings')
