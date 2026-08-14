from database import db
from datetime import datetime


class Wishlist(db.Model):
    __tablename__ = "wishlist"

    # =====================================================
    # Primary Key
    # =====================================================

    id = db.Column(db.Integer, primary_key=True)

    # =====================================================
    # Foreign Keys
    # =====================================================

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )

    # =====================================================
    # Timestamp
    # =====================================================

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    # =====================================================
    # Relationships
    # =====================================================

    user = db.relationship(
        "User",
        back_populates="wishlist_items"
    )

    product = db.relationship(
        "Product",
        back_populates="wishlist_items"
    )

    # Prevent duplicate wishlist entries
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "product_id",
            name="uq_user_product_wishlist"
        ),
    )

    # =====================================================
    # String Representation
    # =====================================================

    def __repr__(self):
        return f"<Wishlist User:{self.user_id} Product:{self.product_id}>"