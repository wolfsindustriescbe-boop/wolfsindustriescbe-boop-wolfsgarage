from database import db
from datetime import datetime


class Payment(db.Model):
    __tablename__ = "payments"

    # =====================================================
    # Primary Key
    # =====================================================

    id = db.Column(db.Integer, primary_key=True)

    # =====================================================
    # Foreign Key
    # =====================================================

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )

    # =====================================================
    # Payment Details
    # =====================================================

    payment_method = db.Column(
        db.String(50),
        nullable=False
    )  # COD, Razorpay, Stripe, UPI, Net Banking

    transaction_id = db.Column(
        db.String(255),
        unique=True,
        nullable=True
    )

    gateway_order_id = db.Column(
        db.String(255),
        nullable=True
    )

    gateway_payment_id = db.Column(
        db.String(255),
        nullable=True
    )

    gateway_signature = db.Column(
        db.String(255),
        nullable=True
    )

    amount = db.Column(
        db.Numeric(10, 2),
        nullable=False
    )

    currency = db.Column(
        db.String(10),
        default="INR"
    )

    payment_status = db.Column(
        db.String(30),
        default="Pending"
    )  # Pending, Paid, Failed, Refunded

    # =====================================================
    # Timestamp
    # =====================================================

    paid_at = db.Column(
        db.DateTime,
        nullable=True
    )

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
        back_populates="payment"
    )

    # =====================================================
    # String Representation
    # =====================================================

    def __repr__(self):
        return (
            f"<Payment Order:{self.order_id} "
            f"Status:{self.payment_status}>"
        )