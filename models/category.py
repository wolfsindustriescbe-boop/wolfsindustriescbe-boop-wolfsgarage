from datetime import datetime

from database import db


class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    image = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    products = db.relationship(
        "Product",
        back_populates="category",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def __repr__(self):
        return f"<Category {self.id} - {self.name}>"
