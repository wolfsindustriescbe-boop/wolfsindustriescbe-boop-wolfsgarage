from database import db
from datetime import datetime


class OrderItem(db.Model):
    __tablename__ = "order_items"

    # =====================================================
    # Primary Key
    # =====================================================

    id = db.Column(db.Integer, primary_key=True)

    # =====================================================
    # Foreign Keys
    # =====================================================

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False
    )

    # =====================================================
    # Product Details
    # =====================================================

    product_name = db.Column(
        db.String(200),
        nullable=False
    )

    quantity = db.Column(
        db.Integer,
        nullable=False,
        default=1
    )

    price = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    # =====================================================
    # Timestamp
    # =====================================================

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # =====================================================
    # Relationships
    # =====================================================

    order = db.relationship(
        "Order",
        back_populates="order_items"
    )

    product = db.relationship(
        "Product",
        back_populates="order_items"
    )

    # =====================================================
    # String Representation
    # =====================================================

    def __repr__(self):
        return (
            f"<OrderItem Order:{self.order_id} "
            f"Product:{self.product_name}>"
        )