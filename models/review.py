from database import db
from datetime import datetime


class Review(db.Model):
    __tablename__ = "reviews"

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
    # Review Details
    # =====================================================

    rating = db.Column(
        db.Integer,
        nullable=False
    )

    review = db.Column(
        db.Text,
        nullable=True
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending"
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

    user = db.relationship(
        "User",
        back_populates="reviews"
    )

    product = db.relationship(
        "Product",
        back_populates="reviews"
    )

    # =====================================================
    # Constraints
    # =====================================================

    __table_args__ = (
        db.CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name="check_review_rating"
        ),
        db.UniqueConstraint(
            "user_id",
            "product_id",
            name="uq_user_product_review"
        ),
    )

    # =====================================================
    # String Representation
    # =====================================================

    def __repr__(self):
        return (
            f"<Review User:{self.user_id} "
            f"Product:{self.product_id} "
            f"Rating:{self.rating}>"
        )
