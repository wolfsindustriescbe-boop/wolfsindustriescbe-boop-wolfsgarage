from datetime import datetime
from decimal import Decimal, InvalidOperation

from database import db


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    address_id = db.Column(
        db.Integer,
        db.ForeignKey("addresses.id"),
        nullable=False,
    )

    order_number = db.Column(db.String(30), unique=True, nullable=False)
    subtotal_amount = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    shipping_charge = db.Column(db.Numeric(10, 2), default=0)
    discount_amount = db.Column(db.Numeric(10, 2), default=0)
    order_status = db.Column(db.String(30), default="Pending")
    payment_status = db.Column(db.String(30), default="Pending")
    payment_method = db.Column(db.String(30), default="COD")
    customer_name = db.Column(db.String(150), nullable=True)
    customer_email = db.Column(db.String(120), nullable=True)
    customer_phone = db.Column(db.String(15), nullable=True)
    shipping_address_line1 = db.Column(db.String(255), nullable=True)
    shipping_address_line2 = db.Column(db.String(255), nullable=True)
    shipping_city = db.Column(db.String(100), nullable=True)
    shipping_state = db.Column(db.String(100), nullable=True)
    shipping_pincode = db.Column(db.String(10), nullable=True)
    shipping_country = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = db.relationship("User", back_populates="orders")
    address = db.relationship("Address", backref="orders")
    order_items = db.relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy=True,
    )
    payment = db.relationship(
        "Payment",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def subtotal_value(self):
        if self.subtotal_amount is not None:
            return self.subtotal_amount

        subtotal = Decimal("0.00")
        for item in self.order_items or []:
            try:
                subtotal += Decimal(str(item.price or 0)) * item.quantity
            except (InvalidOperation, TypeError, ValueError):
                continue
        return subtotal.quantize(Decimal("0.01"))

    @property
    def display_customer_name(self):
        return self.customer_name or (self.address.full_name if self.address else None) or (self.user.full_name if self.user else None)

    @property
    def display_customer_email(self):
        return self.customer_email or (self.user.email if self.user else None)

    @property
    def display_customer_phone(self):
        return self.customer_phone or (self.address.phone if self.address else None) or (self.user.phone if self.user else None)

    @property
    def display_address_line1(self):
        return self.shipping_address_line1 or (self.address.address_line1 if self.address else None)

    @property
    def display_address_line2(self):
        return self.shipping_address_line2 or (self.address.address_line2 if self.address else None)

    @property
    def display_city(self):
        return self.shipping_city or (self.address.city if self.address else None)

    @property
    def display_state(self):
        return self.shipping_state or (self.address.state if self.address else None)

    @property
    def display_pincode(self):
        return self.shipping_pincode or (self.address.pincode if self.address else None)

    @property
    def display_country(self):
        return self.shipping_country or (self.address.country if self.address else None)

    def __repr__(self):
        return f"<Order {self.order_number}>"
