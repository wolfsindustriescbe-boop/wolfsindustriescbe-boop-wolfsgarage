from datetime import datetime

from database import db


class Brand(db.Model):
    __tablename__ = "brands"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), unique=True, nullable=False)
    logo = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    website = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    products = db.relationship(
        "Product",
        back_populates="brand",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def __repr__(self):
        return f"<Brand {self.id} - {self.name}>"
