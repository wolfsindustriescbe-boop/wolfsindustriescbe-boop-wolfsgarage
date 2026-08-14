from datetime import datetime

from database import db


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)

    category_id = db.Column(
        db.Integer,
        db.ForeignKey("categories.id"),
        nullable=False,
    )

    brand_id = db.Column(
        db.Integer,
        db.ForeignKey("brands.id"),
        nullable=False,
    )

    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    sku = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    discount_price = db.Column(db.Numeric(10, 2), nullable=True)
    stock = db.Column(db.Integer, default=0, nullable=False)
    main_image = db.Column(db.String(255), nullable=True)
    is_featured = db.Column(db.Boolean, default=False)
    is_trending = db.Column(db.Boolean, default=False)
    is_best_seller = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    category = db.relationship("Category", back_populates="products")
    brand = db.relationship("Brand", back_populates="products")
    images = db.relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy=True,
    )
    cart_items = db.relationship(
        "Cart",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy=True,
    )
    wishlist_items = db.relationship(
        "Wishlist",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy=True,
    )
    order_items = db.relationship(
        "OrderItem",
        back_populates="product",
        lazy=True,
    )
    reviews = db.relationship(
        "Review",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy=True,
    )

    @property
    def discount(self):
        return self.discount_price

    @discount.setter
    def discount(self, value):
        self.discount_price = value

    @property
    def image(self):
        return self.main_image

    @image.setter
    def image(self, value):
        self.main_image = value

    @property
    def featured(self):
        return self.is_featured

    @featured.setter
    def featured(self, value):
        self.is_featured = value

    @property
    def trending(self):
        return self.is_trending

    @trending.setter
    def trending(self, value):
        self.is_trending = value

    @property
    def best_seller(self):
        return self.is_best_seller

    @best_seller.setter
    def best_seller(self, value):
        self.is_best_seller = value

    @property
    def status(self):
        return self.is_active

    @status.setter
    def status(self, value):
        self.is_active = value

    def __repr__(self):
        return f"<Product {self.id} - {self.name}>"
