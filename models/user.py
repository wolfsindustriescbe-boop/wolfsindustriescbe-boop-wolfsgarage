from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

from database import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    google_id = db.Column(db.String(255), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(15), nullable=True)
    profile_image = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    cart_items = db.relationship(
        "Cart",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy=True,
    )

    wishlist_items = db.relationship(
        "Wishlist",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy=True,
    )

    addresses = db.relationship(
        "Address",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy=True,
    )

    orders = db.relationship(
        "Order",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy=True,
    )

    reviews = db.relationship(
        "Review",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.id} - {self.email}>"

