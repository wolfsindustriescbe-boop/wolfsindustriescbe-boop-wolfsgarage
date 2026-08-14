from datetime import datetime

from database import db


class CustomerSupport(db.Model):
    __tablename__ = "customer_support"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id = db.Column(
        db.Integer,
        db.ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    subject = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Open")
    admin_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = db.relationship("User", backref="support_tickets")
    order = db.relationship("Order", backref="support_tickets")

    def __repr__(self):
        return f"<CustomerSupport {self.id} User:{self.user_id} Status:{self.status}>"
