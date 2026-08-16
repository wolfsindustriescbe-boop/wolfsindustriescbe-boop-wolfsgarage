import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from uuid import uuid4

from flask import (
    Flask,
    Response,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_migrate import Migrate
from flask_session import Session
from sqlalchemy import asc, desc, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.security import generate_password_hash
from werkzeug.exceptions import NotFound

from config import Config
from database import db
from routes.auth import auth_bp, init_oauth
from routes.admin_auth import admin_auth_bp
from services.admin_panel import (
    is_remote_upload,
    generate_sku,
    normalize_uploaded_path,
    remove_uploaded_file,
    save_uploaded_file,
    slugify_text,
    uploaded_file_locations,
)
from services.cashfree import (
    CashfreeAPIError,
    CashfreeConfigError,
    cashfree_mode,
    create_order as cashfree_create_order,
    parse_webhook_payload,
    verify_order as cashfree_verify_order,
    verify_payment as cashfree_verify_payment,
    verify_webhook as cashfree_verify_webhook,
)


# =====================================================
# Create Flask App
# =====================================================

app = Flask(__name__)
app.config.from_object(Config)
app.config.setdefault("UPLOAD_FOLDER", str(Path(app.root_path) / "uploads"))


# =====================================================
# Session Configuration
# =====================================================

app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True

Session(app)


# =====================================================
# Logging
# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# =====================================================
# Initialize Extensions
# =====================================================

db.init_app(app)
migrate = Migrate(app, db)


# =====================================================
# Import Models
# =====================================================

from models.user import User
from models.admin import Admin
from models.category import Category
from models.brand import Brand
from models.product import Product
from models.product_image import ProductImage
from models.cart import Cart
from models.wishlist import Wishlist
from models.address import Address
from models.order import Order
from models.order_item import OrderItem
from models.payment import Payment
from models.review import Review
from models.site_setting import SiteSetting
from models.customer_support import CustomerSupport


# =====================================================
# Blueprint Registration
# =====================================================

init_oauth(app)

app.register_blueprint(auth_bp)
app.register_blueprint(admin_auth_bp)


# =====================================================
# Jinja Filters
# =====================================================


TWOPLACES = Decimal("0.01")
DELIVERY_CHARGE_SETTING_KEY = "delivery_charge"


def money(value):
    if value is None:
        return Decimal("0.00")

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")

    return amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def format_currency(value):
    return f"Rs. {money(value):,.2f}"


app.jinja_env.filters["currency"] = format_currency


def delivery_charge_display(value):
    amount = money(value)
    return "Included" if amount == Decimal("0.00") else format_currency(amount)


app.jinja_env.filters["delivery_display"] = delivery_charge_display


# =====================================================
# Shared Helpers
# =====================================================


def ensure_storefront_session():
    user_id = session.get("user_id")
    if user_id and db.session.get(User, user_id):
        return True

    guest_user = User(
        full_name="Guest Customer",
        email=f"guest-{uuid4().hex}@wolfs.local",
        is_active=True,
    )
    db.session.add(guest_user)
    db.session.commit()

    session["user_id"] = guest_user.id
    session["user_name"] = guest_user.full_name
    session["user_email"] = guest_user.email
    return True


def require_customer_session():
    return ensure_storefront_session()


def require_admin_session():
    if "admin_logged_in" not in session:
        flash("Please sign in as an administrator.", "warning")
        return False
    return True


def admin_redirect(endpoint):
    return redirect(url_for(endpoint))


def get_current_admin():
    admin_id = session.get("admin_id")
    if admin_id:
        admin = db.session.get(Admin, admin_id)
        if admin:
            return admin

    username = session.get("admin_username")
    if username:
        return Admin.query.filter_by(username=username).first()

    return None


def parse_decimal(value, default=None):
    raw_value = (value or "").strip()
    if not raw_value:
        return default
    try:
        return Decimal(raw_value)
    except (InvalidOperation, ValueError):
        return default


def parse_int(value, default=None):
    raw_value = (value or "").strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


def parse_bool(value):
    return str(value).lower() in {"1", "true", "yes", "on"}


def normalize_status(value, allowed, default):
    value = (value or "").strip().lower()
    if value in allowed:
        return value
    return default


def status_counts(query, column):
    rows = query.with_entities(func.lower(column), func.count()).group_by(func.lower(column)).all()
    return {str(status): count for status, count in rows}


def get_order_queryset():
    return Order.query.options(
        joinedload(Order.user),
        joinedload(Order.address),
        joinedload(Order.payment),
        selectinload(Order.order_items).joinedload(OrderItem.product),
    )


def get_product_queryset():
    return Product.query.options(
        joinedload(Product.category),
        joinedload(Product.brand),
        selectinload(Product.images),
        selectinload(Product.reviews),
        selectinload(Product.order_items),
    )


def delete_product_media(product):
    remove_uploaded_file(product.main_image)
    for image in list(product.images):
        remove_uploaded_file(image.image_url)


def ensure_unique_product_fields(product, slug_value, sku_value):
    slug_exists = Product.query.filter(Product.slug == slug_value)
    sku_exists = Product.query.filter(Product.sku == sku_value)

    if product is not None:
        slug_exists = slug_exists.filter(Product.id != product.id)
        sku_exists = sku_exists.filter(Product.id != product.id)

    if slug_exists.first():
        return "Slug already exists."

    if sku_exists.first():
        return "SKU already exists."

    return None


def build_dashboard_context():
    order_query = Order.query
    product_query = Product.query
    user_query = User.query
    category_query = Category.query
    brand_query = Brand.query
    review_query = Review.query

    revenue = db.session.query(func.coalesce(func.sum(Order.total_amount), 0)).scalar() or 0
    pending_orders = order_query.filter(func.lower(Order.order_status) == "pending").count()
    completed_orders = order_query.filter(func.lower(Order.order_status).in_(["delivered", "completed"])).count()
    cancelled_orders = order_query.filter(func.lower(Order.order_status).in_(["cancelled", "canceled"])).count()

    recent_orders = (
        get_order_queryset()
        .order_by(Order.created_at.desc())
        .limit(5)
        .all()
    )

    recent_products = (
        get_product_queryset()
        .order_by(Product.created_at.desc())
        .limit(6)
        .all()
    )

    recent_customers = (
        User.query.options(
            selectinload(User.orders),
            selectinload(User.addresses),
            selectinload(User.cart_items),
            selectinload(User.wishlist_items),
            selectinload(User.reviews),
        )
        .order_by(User.created_at.desc())
        .limit(6)
        .all()
    )

    recent_reviews = (
        Review.query.options(
            joinedload(Review.user),
            joinedload(Review.product),
        )
        .order_by(Review.created_at.desc())
        .limit(5)
        .all()
    )

    low_stock_products = (
        Product.query.options(joinedload(Product.category), joinedload(Product.brand))
        .filter(Product.stock <= 5)
        .order_by(Product.stock.asc(), Product.created_at.desc())
        .limit(5)
        .all()
    )

    active_products = product_query.filter(Product.is_active.is_(True)).count()
    inactive_products = product_query.filter(Product.is_active.is_(False)).count()
    featured_products = product_query.filter(Product.is_featured.is_(True)).count()
    trending_products = product_query.filter(Product.is_trending.is_(True)).count()

    return {
        "products_count": product_query.count(),
        "active_products": active_products,
        "inactive_products": inactive_products,
        "featured_products": featured_products,
        "trending_products": trending_products,
        "orders_count": order_query.count(),
        "pending_orders": pending_orders,
        "completed_orders": completed_orders,
        "cancelled_orders": cancelled_orders,
        "customers_count": user_query.count(),
        "categories_count": category_query.count(),
        "brands_count": brand_query.count(),
        "reviews_count": review_query.count(),
        "revenue_total": revenue,
        "low_stock_count": product_query.filter(Product.stock <= 5).count(),
        "recent_orders": recent_orders,
        "recent_products": recent_products,
        "recent_customers": recent_customers,
        "recent_reviews": recent_reviews,
        "low_stock_products": low_stock_products,
    }


def current_product_price(product):
    """Return the sell price without duplicating pricing logic in templates."""
    if product is None:
        return Decimal("0.00")
    return money(product.discount_price if product.discount_price is not None else product.price)


def product_discount_amount(product):
    if product is None or product.discount_price is None:
        return Decimal("0.00")
    return money(max(money(product.price) - money(product.discount_price), Decimal("0.00")))

def get_delivery_charge(force_refresh=False):
    cached_value = getattr(g, "_delivery_charge", None)
    if cached_value is not None and not force_refresh:
        return cached_value

    setting = SiteSetting.query.filter_by(key=DELIVERY_CHARGE_SETTING_KEY).first()
    charge = money(setting.value if setting is not None else Decimal("0.00"))
    g._delivery_charge = charge
    return charge


def cart_totals(items, delivery_charge=None):
    product_total = Decimal("0.00")
    subtotal = Decimal("0.00")
    discount = Decimal("0.00")
    for item in items:
        if item.product is None:
            continue
        original_unit_price = money(item.product.price)
        unit_price = current_product_price(item.product)
        line_total = money(unit_price * item.quantity)
        line_discount = money(product_discount_amount(item.product) * item.quantity)

        product_total += money(original_unit_price * item.quantity)
        subtotal += line_total
        discount += line_discount

    subtotal = money(subtotal)
    discount = money(discount)
    product_total = money(product_total)
    resolved_delivery_charge = money(delivery_charge if delivery_charge is not None else get_delivery_charge())
    if subtotal == Decimal("0.00"):
        resolved_delivery_charge = Decimal("0.00")

    total = money(subtotal + resolved_delivery_charge)
    return {
        "product_total": product_total,
        "subtotal": subtotal,
        "discount": discount,
        "selling_total": subtotal,
        "delivery_charge": resolved_delivery_charge,
        "gst": Decimal("0.00"),
        "total": total,
    }


def cashfree_customer_phone(user, address):
    digits = "".join(ch for ch in str(getattr(address, "phone", "") or getattr(user, "phone", "")) if ch.isdigit())
    if len(digits) >= 10:
        return digits[-10:]
    return "9999999999"


def cart_signature(items, address_id, totals):
    parts = [
        f"addr:{address_id}",
        f"total:{money(totals['total'])}",
        f"shipping:{money(totals['delivery_charge'])}",
    ]
    for item in sorted(items, key=lambda row: row.product_id):
        parts.append(f"{item.product_id}:{item.quantity}:{money(current_product_price(item.product))}")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def order_matches_cart(order, items, address_id, totals):
    if order is None or order.address_id != address_id:
        return False
    if money(order.total_amount) != money(totals["total"]):
        return False
    if money(order.subtotal_amount) != money(totals["subtotal"]):
        return False
    if money(order.shipping_charge) != money(totals["delivery_charge"]):
        return False
    if money(order.discount_amount) != money(totals["discount"]):
        return False

    order_snapshot = sorted(
        (item.product_id, item.quantity, money(item.price))
        for item in order.order_items
    )
    cart_snapshot = sorted(
        (item.product_id, item.quantity, money(current_product_price(item.product)))
        for item in items
    )
    return order_snapshot == cart_snapshot


def find_pending_cashfree_order(user_id, address_id, items, totals):
    candidates = (
        Order.query.options(selectinload(Order.order_items), joinedload(Order.payment))
        .filter(
            Order.user_id == user_id,
            Order.address_id == address_id,
            Order.payment_method == "Cashfree",
            func.lower(Order.order_status).in_(["pending", "confirmed"]),
            func.lower(Order.payment_status).in_(["pending", "failed"]),
        )
        .order_by(Order.created_at.desc())
        .limit(10)
        .all()
    )
    for order in candidates:
        if order_matches_cart(order, items, address_id, totals):
            return order
    return None


def create_pending_cashfree_order(user, address, items, totals, customer_snapshot):
    signature = cart_signature(items, address.id, totals)[:8].upper()
    order = Order(
        user_id=user.id,
        address_id=address.id,
        order_number=f"WG-CF-{datetime.utcnow():%Y%m%d%H%M%S}-{signature}",
        subtotal_amount=totals["subtotal"],
        total_amount=totals["total"],
        shipping_charge=totals["delivery_charge"],
        discount_amount=totals["discount"],
        order_status="Pending",
        payment_status="Pending",
        payment_method="Cashfree",
    )
    apply_order_customer_snapshot(order, customer_snapshot)
    db.session.add(order)
    for item in items:
        product = item.product
        order.order_items.append(OrderItem(
            product_id=product.id,
            product_name=product.name,
            quantity=item.quantity,
            price=current_product_price(product),
        ))
    db.session.flush()
    db.session.add(Payment(
        order_id=order.id,
        payment_method="Cashfree",
        amount=totals["total"],
        currency="INR",
        payment_status="Pending",
    ))
    db.session.flush()
    return order


def lock_cashfree_user(user_id):
    # Serializes payment-session creation per customer on PostgreSQL.
    db.session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": int(user_id)})


def parse_cashfree_datetime(value):
    if not value:
        return datetime.utcnow()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return datetime.utcnow()


def latest_cashfree_payment(payments):
    if not payments:
        return None
    return sorted(payments, key=lambda row: row.get("payment_time") or row.get("payment_completion_time") or "", reverse=True)[0]


def successful_cashfree_payment(payments):
    for payment in payments:
        if str(payment.get("payment_status", "")).upper() == "SUCCESS":
            return payment
    return None


def cashfree_payment_amount(payment_data):
    if not payment_data:
        return None
    amount = payment_data.get("payment_amount", payment_data.get("order_amount"))
    return money(amount) if amount is not None else None


def remove_order_items_from_cart(order):
    for order_item in order.order_items:
        remaining = order_item.quantity
        cart_rows = (
            Cart.query
            .filter_by(user_id=order.user_id, product_id=order_item.product_id)
            .order_by(Cart.created_at.asc(), Cart.id.asc())
            .all()
        )
        for cart_row in cart_rows:
            if remaining <= 0:
                break
            if cart_row.quantity <= remaining:
                remaining -= cart_row.quantity
                db.session.delete(cart_row)
            else:
                cart_row.quantity -= remaining
                remaining = 0


def finalize_paid_cashfree_order(order, payment, cf_order, cf_payment):
    if (payment.payment_status or "").lower() == "paid" and (order.payment_status or "").lower() == "paid":
        return

    cf_amount = cashfree_payment_amount(cf_payment) or money(cf_order.get("order_amount"))
    if cf_amount != money(payment.amount) or cf_amount != money(order.total_amount):
        raise ValueError("Cashfree paid amount does not match local order amount.")

    products = {
        product.id: product
        for product in Product.query.filter(Product.id.in_([item.product_id for item in order.order_items])).with_for_update().all()
    }
    for item in order.order_items:
        product = products.get(item.product_id)
        if product is None or product.stock < item.quantity:
            raise ValueError(f"Insufficient stock while finalizing order {order.order_number}.")

    for item in order.order_items:
        products[item.product_id].stock -= item.quantity

    payment.payment_status = "Paid"
    payment.gateway_order_id = cf_order.get("order_id") or payment.gateway_order_id
    gateway_payment_id = cf_payment.get("cf_payment_id") or payment.gateway_payment_id
    if gateway_payment_id:
        payment.gateway_payment_id = str(gateway_payment_id)
    transaction_id = (
        cf_payment.get("bank_reference")
        or cf_payment.get("cf_payment_id")
        or payment.transaction_id
    )
    if transaction_id:
        payment.transaction_id = str(transaction_id)
    payment.currency = cf_payment.get("payment_currency") or cf_order.get("order_currency") or payment.currency or "INR"
    payment.paid_at = parse_cashfree_datetime(
        cf_payment.get("payment_completion_time") or cf_payment.get("payment_time")
    )

    order.payment_status = "Paid"
    order.order_status = "Confirmed"
    order.payment_method = "Cashfree"
    remove_order_items_from_cart(order)


def reconcile_cashfree_order(cf_order_id, user_id=None, webhook_signature=None):
    payment = (
        Payment.query.options(joinedload(Payment.order).selectinload(Order.order_items))
        .filter_by(gateway_order_id=cf_order_id)
        .with_for_update()
        .first()
    )
    if payment is None:
        order = (
            Order.query.options(joinedload(Order.payment), selectinload(Order.order_items))
            .filter_by(order_number=cf_order_id, payment_method="Cashfree")
            .with_for_update()
            .first()
        )
        payment = order.payment if order and order.payment else None
    if payment is None or payment.order is None:
        return None, "not_found"

    order = payment.order
    if user_id is not None and order.user_id != user_id:
        return order, "forbidden"

    cf_order = cashfree_verify_order(cf_order_id)
    cf_payments = cashfree_verify_payment(cf_order_id)
    success_payment = successful_cashfree_payment(cf_payments)
    latest_payment = latest_cashfree_payment(cf_payments)

    if webhook_signature:
        payment.gateway_signature = webhook_signature
    payment.gateway_order_id = cf_order.get("order_id") or cf_order_id

    if success_payment and str(cf_order.get("order_status", "")).upper() == "PAID":
        finalize_paid_cashfree_order(order, payment, cf_order, success_payment)
        db.session.commit()
        return order, "paid"

    latest_status = str((latest_payment or {}).get("payment_status", "")).upper()
    if latest_payment:
        gateway_payment_id = latest_payment.get("cf_payment_id") or payment.gateway_payment_id
        if gateway_payment_id:
            payment.gateway_payment_id = str(gateway_payment_id)

    if latest_status == "FAILED":
        payment.payment_status = "Failed"
        order.payment_status = "Failed"
        order.order_status = "Pending"
        db.session.commit()
        return order, "failed"

    if latest_status in {"USER_DROPPED", "CANCELLED", "VOID"}:
        payment.payment_status = "Pending"
        order.payment_status = "Pending"
        order.order_status = "Pending"
        db.session.commit()
        return order, "cancelled"

    payment.payment_status = "Pending"
    order.payment_status = "Pending"
    order.order_status = "Pending"
    db.session.commit()
    return order, "pending"


def order_timeline(order):
    statuses = ["Pending", "Confirmed", "Packed", "Shipped", "Out For Delivery", "Delivered"]
    current = (order.order_status or "Pending").lower()
    if current in {"cancelled", "canceled"}:
        return [{"label": status, "done": status == "Pending"} for status in statuses] + [{"label": "Cancelled", "done": True}]
    try:
        active_index = [status.lower() for status in statuses].index(current)
    except ValueError:
        active_index = 0
    return [{"label": status, "done": index <= active_index} for index, status in enumerate(statuses)]


def order_allows_review(order):
    if order is None:
        return False
    return (
        (order.payment_status or "").lower() == "paid"
        and (order.order_status or "").lower() in {"confirmed", "packed", "shipped", "out for delivery", "delivered"}
    )


def reviewable_order_items(order):
    if not order_allows_review(order):
        return []

    seen_product_ids = set()
    product_ids = []
    for item in order.order_items:
        if item.product_id not in seen_product_ids:
            seen_product_ids.add(item.product_id)
            product_ids.append(item.product_id)

    if not product_ids:
        return []

    reviewed_ids = {
        row.product_id
        for row in Review.query.filter(
            Review.user_id == order.user_id,
            Review.product_id.in_(product_ids),
        ).all()
    }
    return [item for item in order.order_items if item.product_id not in reviewed_ids]


def should_show_review_prompt(order):
    dismissed = session.get("dismissed_review_order_ids", [])
    return order.id not in dismissed and bool(reviewable_order_items(order))


def dismiss_review_prompt(order_id):
    dismissed = set(session.get("dismissed_review_order_ids", []))
    dismissed.add(order_id)
    session["dismissed_review_order_ids"] = list(dismissed)
    session.modified = True


def support_contact_context():
    return {
        "support_phone": app.config.get("SUPPORT_PHONE", ""),
        "support_email": app.config.get("SUPPORT_EMAIL", ""),
    }


def delivery_date():
    return datetime.utcnow() + timedelta(days=5)


def wants_json():
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def cart_items_query(user_id):
    return Cart.query.options(joinedload(Cart.product).joinedload(Product.brand)).filter_by(user_id=user_id)


def serialize_cart_item(item):
    product = item.product
    unit_price = current_product_price(product) if product else Decimal("0")
    return {
        "id": item.id,
        "product_id": item.product_id,
        "quantity": item.quantity,
        "stock": product.stock if product else 0,
        "unit_price": format_currency(unit_price),
        "line_total": format_currency(unit_price * item.quantity),
        "discount": format_currency(product_discount_amount(product) * item.quantity),
        "available": bool(product and product.is_active and product.stock >= item.quantity),
    }


def cart_payload(user_id, message=None):
    items = cart_items_query(user_id).order_by(Cart.created_at.asc()).all()
    totals = cart_totals(items)
    payload_totals = {key: format_currency(value) for key, value in totals.items()}
    payload_totals["delivery_charge"] = delivery_charge_display(totals["delivery_charge"])
    return {
        "ok": True,
        "message": message,
        "cart_count": sum(item.quantity for item in items),
        "item_count": len(items),
        "empty": len(items) == 0,
        "items": [serialize_cart_item(item) for item in items],
        "totals": payload_totals,
    }


def json_or_redirect(endpoint, payload=None, category="success", message=None):
    if wants_json():
        return jsonify(payload or {"ok": True, "message": message})
    if message:
        flash(message, category)
    return redirect(url_for(endpoint))


def merge_duplicate_cart_rows(user_id, product):
    rows = Cart.query.filter_by(user_id=user_id, product_id=product.id).order_by(Cart.id.asc()).all()
    if len(rows) <= 1:
        return rows[0] if rows else None

    keep = rows[0]
    keep.quantity = min(sum(row.quantity for row in rows), product.stock)
    keep.price = current_product_price(product)
    for duplicate in rows[1:]:
        db.session.delete(duplicate)
    return keep


def customer_product_queryset():
    return Product.query.options(
        joinedload(Product.category),
        joinedload(Product.brand),
        selectinload(Product.images),
        selectinload(Product.reviews),
    ).filter(Product.is_active.is_(True), Product.stock >= 0)


def get_current_user():
    user_id = session.get("user_id")
    return db.session.get(User, user_id) if user_id else None


def save_address_from_form(user, address=None):
    full_name = (request.form.get("full_name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    line1 = (request.form.get("address_line1") or "").strip()
    line2 = (request.form.get("address_line2") or "").strip()
    city = (request.form.get("city") or "").strip()
    state = (request.form.get("state") or "").strip()
    pincode = (request.form.get("pincode") or "").strip()
    country = (request.form.get("country") or "India").strip()
    is_default = parse_bool(request.form.get("is_default"))

    if not all([full_name, phone, line1, city, state, pincode]):
        return None, "Name, phone, address, city, state, and pincode are required."

    if len(phone) < 7 or len(phone) > 15:
        return None, "Please enter a valid phone number."

    if len(pincode) < 4 or len(pincode) > 10:
        return None, "Please enter a valid pincode."

    has_existing_address = Address.query.filter_by(user_id=user.id).count() > 0

    is_new_address = address is None
    if is_new_address:
        address = Address(user_id=user.id)

    if is_default:
        Address.query.filter(Address.user_id == user.id, Address.id != (address.id or 0)).update({"is_default": False})

    address.full_name = full_name
    address.phone = phone
    address.address_line1 = line1
    address.address_line2 = line2 or None
    address.city = city
    address.state = state
    address.pincode = pincode
    address.country = country or "India"
    address.is_default = is_default or not has_existing_address
    if is_new_address:
        db.session.add(address)
    return address, None


def order_customer_snapshot(user, address):
    snapshot = {
        "customer_name": ((address.full_name if address else None) or user.full_name or "").strip(),
        "customer_email": (user.email or "").strip(),
        "customer_phone": ((address.phone if address else None) or user.phone or "").strip(),
        "shipping_address_line1": ((address.address_line1 if address else None) or "").strip(),
        "shipping_address_line2": ((address.address_line2 if address else None) or "").strip() or None,
        "shipping_city": ((address.city if address else None) or "").strip(),
        "shipping_state": ((address.state if address else None) or "").strip(),
        "shipping_pincode": ((address.pincode if address else None) or "").strip(),
        "shipping_country": ((address.country if address else None) or "India").strip() or "India",
    }
    required = [
        "customer_name",
        "customer_email",
        "customer_phone",
        "shipping_address_line1",
        "shipping_city",
        "shipping_state",
        "shipping_pincode",
    ]
    if any(not snapshot[field] for field in required):
        return None, "Please complete your name, email, phone, and delivery address before placing the order."
    return snapshot, None


def apply_order_customer_snapshot(order, snapshot):
    for field, value in snapshot.items():
        setattr(order, field, value)


def ensure_default_address(user_id):
    addresses = Address.query.filter_by(user_id=user_id).order_by(Address.created_at.desc()).all()
    if not addresses:
        return
    default_seen = False
    for address in addresses:
        if address.is_default and not default_seen:
            default_seen = True
        elif address.is_default:
            address.is_default = False
    if default_seen:
        return
    addresses[0].is_default = True


def build_analytics_context():
    monthly_revenue = (
        db.session.query(
            func.date_trunc("month", Order.created_at).label("month"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
            func.count(Order.id).label("orders"),
        )
        .group_by("month")
        .order_by("month")
        .all()
    )

    order_status_breakdown = (
        db.session.query(
            func.lower(Order.order_status).label("status"),
            func.count(Order.id).label("total"),
        )
        .group_by("status")
        .order_by(desc("total"))
        .all()
    )

    payment_status_breakdown = (
        db.session.query(
            func.lower(Order.payment_status).label("status"),
            func.count(Order.id).label("total"),
        )
        .group_by("status")
        .order_by(desc("total"))
        .all()
    )

    top_products = (
        db.session.query(
            Product.id,
            Product.name,
            Product.sku,
            Product.stock,
            Product.price,
            func.coalesce(func.sum(OrderItem.quantity), 0).label("units_sold"),
            func.coalesce(func.sum(OrderItem.quantity * OrderItem.price), 0).label("revenue"),
        )
        .outerjoin(OrderItem, OrderItem.product_id == Product.id)
        .group_by(Product.id)
        .order_by(desc("units_sold"), desc("revenue"))
        .limit(10)
        .all()
    )

    low_stock_products = (
        Product.query.options(joinedload(Product.category), joinedload(Product.brand))
        .filter(Product.stock <= 5)
        .order_by(Product.stock.asc(), Product.created_at.desc())
        .all()
    )

    return {
        "monthly_revenue": monthly_revenue,
        "order_status_breakdown": order_status_breakdown,
        "payment_status_breakdown": payment_status_breakdown,
        "top_products": top_products,
        "low_stock_products": low_stock_products,
    }


def save_order_status(order):
    order_status = normalize_status(
        request.form.get("order_status"),
        {"pending", "confirmed", "processing", "packed", "shipped", "out for delivery", "delivered", "cancelled", "canceled"},
        order.order_status.lower() if order.order_status else "pending",
    )

    payment_status = normalize_status(
        request.form.get("payment_status"),
        {"pending", "paid", "failed", "refunded"},
        order.payment_status.lower() if order.payment_status else "pending",
    )

    payment_method = (request.form.get("payment_method") or order.payment_method or "COD").strip()

    order.order_status = order_status.title()
    order.payment_status = payment_status.title()
    order.payment_method = payment_method.upper() if payment_method.lower() in {"cod", "upi"} else payment_method.title()

    if order.payment is not None:
        order.payment.payment_status = order.payment_status
        order.payment.payment_method = order.payment_method


def upload_route_filename(filename):
    return normalize_uploaded_path(filename)


@app.context_processor
def inject_upload_helpers():
    def uploaded_url(filename):
        if is_remote_upload(filename):
            return filename
        return url_for("uploaded_file", filename=upload_route_filename(filename))

    base_url = app.config.get("SITE_URL", "https://wolfsindustries.in").rstrip("/")
    return {
        "uploaded_url": uploaded_url,
        "site_url": base_url,
    }


@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response


# =====================================================
# SEO & Sitemap Routes
# =====================================================


@app.route("/sitemap.xml", methods=["GET"])
def sitemap():
    base_url = app.config.get("SITE_URL", "https://wolfsindustries.in").rstrip("/")
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        '  <url>',
        f'    <loc>{base_url}/home</loc>',
        '    <changefreq>daily</changefreq>',
        '    <priority>1.0</priority>',
        '  </url>',
    ]

    try:
        active_products = (
            customer_product_queryset()
            .order_by(Product.updated_at.desc(), Product.id.desc())
            .all()
        )
        for product in active_products:
            if product and product.slug:
                lastmod_dt = product.updated_at or product.created_at
                lastmod_str = lastmod_dt.strftime("%Y-%m-%d") if lastmod_dt else datetime.utcnow().strftime("%Y-%m-%d")
                xml_lines.extend([
                    '  <url>',
                    f'    <loc>{base_url}/products/{product.slug}</loc>',
                    f'    <lastmod>{lastmod_str}</lastmod>',
                    '    <changefreq>weekly</changefreq>',
                    '    <priority>0.8</priority>',
                    '  </url>',
                ])
    except Exception as e:
        app.logger.error("Error building dynamic sitemap: %s", e)

    xml_lines.append('</urlset>')
    return Response("\n".join(xml_lines), mimetype="application/xml; charset=utf-8")


@app.route("/robots.txt", methods=["GET"])
def robots():
    base_url = app.config.get("SITE_URL", "https://wolfsindustries.in").rstrip("/")
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /cart",
        "Disallow: /wishlist",
        "Disallow: /dashboard",
        "Disallow: /orders",
        "Disallow: /orders/",
        "Disallow: /profile",
        "Disallow: /checkout",
        "Disallow: /payment",
        "Disallow: /cashfree/",
        "Disallow: /place-order",
        "Allow: /static/",
        "Allow: /uploads/",
        "Allow: /products/",
        "Allow: /home",
        "",
        f"Sitemap: {base_url}/sitemap.xml",
    ]
    return Response("\n".join(lines), mimetype="text/plain; charset=utf-8")


# =====================================================
# Upload Route
# =====================================================


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    normalized = upload_route_filename(filename)

    for file_path in uploaded_file_locations(normalized):
        if file_path.is_file():
            return send_from_directory(file_path.parent, file_path.name)

    app.logger.error(
        "Uploaded file not found for request '%s'. Normalized path '%s'. Checked %s",
        filename,
        normalized,
        [str(path) for path in uploaded_file_locations(normalized)],
    )
    raise NotFound()


# =====================================================
# Customer Routes
# =====================================================


@app.route("/")
def login():
    return redirect(url_for("home"))


@app.route("/home")
def home():
    search = (request.args.get("q") or "").strip()
    category_id = parse_int(request.args.get("category"))
    brand_id = parse_int(request.args.get("brand"))
    products = customer_product_queryset().filter(Product.is_trending.is_(True))
    if search:
        term = f"%{search}%"
        products = products.filter(or_(Product.name.ilike(term), Product.sku.ilike(term)))
    if category_id:
        products = products.filter(Product.category_id == category_id)
    if brand_id:
        products = products.filter(Product.brand_id == brand_id)

    trending_products = products.order_by(Product.created_at.desc()).limit(8).all()
    brands = (
        Brand.query.options(selectinload(Brand.products))
        .filter_by(is_active=True)
        .order_by(Brand.name)
        .all()
    )
    return render_template(
        "user/home.html",
        trending_products=trending_products,
        brands=brands,
        search=search,
    )


@app.route("/cart")
def cart():
    if not require_customer_session():
        return redirect(url_for("home"))

    items = cart_items_query(session["user_id"]).order_by(Cart.created_at.asc()).all()
    return render_template("user/cart.html", cart_items=items, totals=cart_totals(items), delivery_date=delivery_date())


@app.route("/dashboard")
def customer_dashboard():
    if not require_customer_session():
        return redirect(url_for("home"))

    user = get_current_user()
    cart_items = Cart.query.options(joinedload(Cart.product)).filter_by(user_id=user.id).all()
    wishlist_items = Wishlist.query.options(joinedload(Wishlist.product)).filter_by(user_id=user.id).limit(4).all()
    recent_orders = (
        Order.query.options(selectinload(Order.order_items).joinedload(OrderItem.product), joinedload(Order.address), joinedload(Order.payment))
        .filter_by(user_id=user.id)
        .order_by(Order.created_at.desc())
        .limit(5)
        .all()
    )
    recent_products = customer_product_queryset().order_by(Product.updated_at.desc()).limit(6).all()
    return render_template(
        "user/dashboard.html",
        user=user,
        addresses=user.addresses,
        cart_items=cart_items,
        cart_totals=cart_totals(cart_items),
        wishlist_items=[item for item in wishlist_items if item.product and item.product.is_active],
        recent_orders=recent_orders,
        recently_viewed_products=recent_products,
    )


@app.route("/wishlist")
def wishlist():
    if not require_customer_session():
        return redirect(url_for("home"))

    items = Wishlist.query.options(joinedload(Wishlist.product)).filter_by(user_id=session["user_id"]).all()
    items = [item for item in items if item.product and item.product.is_active]
    return render_template("user/wishlist.html", wishlist_items=items)


@app.route("/orders")
def user_orders():
    if not require_customer_session():
        return redirect(url_for("home"))

    orders = Order.query.options(
        joinedload(Order.address),
        joinedload(Order.payment),
        selectinload(Order.order_items).joinedload(OrderItem.product),
    ).filter_by(
        user_id=session["user_id"]
    ).order_by(Order.created_at.desc()).all()
    return render_template("user/orders.html", orders=orders)


@app.route("/orders/<int:order_id>")
def user_order_detail(order_id):
    if not require_customer_session():
        return redirect(url_for("home"))

    order = get_order_queryset().filter(Order.id == order_id, Order.user_id == session["user_id"]).first_or_404()
    return render_template("user/order_detail.html", order=order, timeline=order_timeline(order))


@app.route("/orders/<int:order_id>/invoice")
def user_order_invoice(order_id):
    if not require_customer_session():
        return redirect(url_for("home"))

    order = get_order_queryset().filter(Order.id == order_id, Order.user_id == session["user_id"]).first_or_404()
    return render_template("user/invoice.html", order=order)


@app.post("/orders/<int:order_id>/cancel")
def user_order_cancel(order_id):
    if not require_customer_session():
        return redirect(url_for("home"))

    order = Order.query.filter_by(id=order_id, user_id=session["user_id"]).first_or_404()
    if (order.order_status or "").lower() in {"pending", "confirmed"}:
        order.order_status = "Cancelled"
        order.payment_status = "Refunded" if (order.payment_status or "").lower() == "paid" else order.payment_status
        db.session.commit()
        flash("Order cancelled.", "success")
    else:
        flash("This order can no longer be cancelled online.", "warning")
    return redirect(url_for("user_order_detail", order_id=order.id))


@app.route("/profile")
def profile():
    if not require_customer_session():
        return redirect(url_for("home"))

    user = get_current_user()
    ensure_default_address(user.id)
    db.session.commit()
    recent_orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).limit(3).all()
    addresses = Address.query.filter_by(user_id=user.id).order_by(Address.is_default.desc(), Address.created_at.desc()).all()
    return render_template("user/profile.html", user=user, addresses=addresses, recent_orders=recent_orders)


@app.post("/profile")
def profile_update():
    if not require_customer_session():
        return redirect(url_for("home"))

    user = get_current_user()
    full_name = (request.form.get("full_name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    if not full_name:
        flash("Name is required.", "danger")
        return redirect(url_for("profile"))
    user.full_name = full_name
    user.phone = phone or None
    db.session.commit()
    flash("Profile updated.", "success")
    return redirect(url_for("profile"))


@app.post("/addresses/save")
def address_save():
    if not require_customer_session():
        return redirect(url_for("home"))

    user = get_current_user()
    address_id = parse_int(request.form.get("address_id"))
    address = Address.query.filter_by(id=address_id, user_id=user.id).first() if address_id else None
    address, error = save_address_from_form(user, address)
    if error:
        flash(error, "danger")
    else:
        try:
            ensure_default_address(user.id)
            db.session.commit()
            flash("Address saved.", "success")
        except Exception:
            db.session.rollback()
            logging.exception("Address save failed for user %s", user.id)
            flash("We could not save this address. Please check the details and try again.", "danger")
    return redirect(request.referrer or url_for("profile"))


@app.post("/addresses/<int:address_id>/default")
def address_default(address_id):
    if not require_customer_session():
        return redirect(url_for("home"))

    address = Address.query.filter_by(id=address_id, user_id=session["user_id"]).first_or_404()
    Address.query.filter(Address.user_id == session["user_id"]).update({"is_default": False})
    address.is_default = True
    db.session.commit()
    flash("Default address updated.", "success")
    return redirect(request.referrer or url_for("profile"))


@app.post("/addresses/<int:address_id>/delete")
def address_delete(address_id):
    if not require_customer_session():
        return redirect(url_for("home"))

    address = Address.query.filter_by(id=address_id, user_id=session["user_id"]).first_or_404()
    if address.orders:
        flash("Address is linked to an order and cannot be deleted.", "warning")
        return redirect(request.referrer or url_for("profile"))
    was_default = address.is_default
    db.session.delete(address)
    if was_default:
        replacement = Address.query.filter(Address.user_id == session["user_id"], Address.id != address_id).order_by(Address.created_at.desc()).first()
        if replacement:
            replacement.is_default = True
    ensure_default_address(session["user_id"])
    db.session.commit()
    flash("Address deleted.", "success")
    return redirect(request.referrer or url_for("profile"))


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if not require_customer_session():
        return redirect(url_for("home"))

    user = get_current_user()
    ensure_default_address(user.id)
    db.session.commit()
    items = Cart.query.options(joinedload(Cart.product).joinedload(Product.brand)).filter_by(user_id=user.id).all()
    if request.method == "POST":
        address_id = parse_int(request.form.get("address_id"))
        address = Address.query.filter_by(id=address_id, user_id=user.id).first() if address_id else None
        if address is None:
            flash("Please select a delivery address.", "danger")
            return redirect(url_for("checkout"))
        if not items:
            flash("Your cart is empty.", "warning")
            return redirect(url_for("cart"))
        if any(item.product is None or not item.product.is_active or item.quantity > item.product.stock for item in items):
            flash("One or more cart items are unavailable or out of stock.", "danger")
            return redirect(url_for("cart"))
        return redirect(url_for("payment", address_id=address.id, coupon=(request.form.get("coupon") or "").strip()))

    addresses = Address.query.filter_by(user_id=user.id).order_by(Address.is_default.desc(), Address.created_at.desc()).all()
    return render_template("user/checkout.html", cart_items=items, totals=cart_totals(items), addresses=addresses)


@app.route("/payment")
def payment():
    if not require_customer_session():
        return redirect(url_for("home"))

    user = get_current_user()
    address_id = parse_int(request.args.get("address_id"))
    address = Address.query.filter_by(id=address_id, user_id=user.id).first() if address_id else None
    items = Cart.query.options(joinedload(Cart.product).joinedload(Product.brand)).filter_by(user_id=user.id).all()
    if not items:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("cart"))
    if address is None:
        flash("Please select a delivery address.", "danger")
        return redirect(url_for("checkout"))

    return render_template(
        "user/payment.html",
        cart_items=items,
        totals=cart_totals(items),
        address=address,
        cashfree_mode=cashfree_mode(),
    )


@app.post("/cashfree/create-session")
def cashfree_create_session():
    if not require_customer_session():
        return jsonify({"ok": False, "message": "Please sign in to continue."}), 401

    user = get_current_user()
    payload = request.get_json(silent=True) or request.form
    address_id = parse_int(payload.get("address_id") if payload else None)
    address = Address.query.filter_by(id=address_id, user_id=user.id).first() if address_id else None
    items = Cart.query.options(joinedload(Cart.product).joinedload(Product.brand)).filter_by(user_id=user.id).all()

    if address is None:
        return jsonify({"ok": False, "message": "Please select a delivery address."}), 400
    if not items:
        return jsonify({"ok": False, "message": "Your cart is empty."}), 400
    if any(item.product is None or not item.product.is_active or item.quantity > item.product.stock for item in items):
        return jsonify({"ok": False, "message": "One or more cart items are unavailable or out of stock."}), 400

    customer_snapshot, snapshot_error = order_customer_snapshot(user, address)
    if snapshot_error:
        return jsonify({"ok": False, "message": snapshot_error}), 400

    totals = cart_totals(items)
    if money(totals["total"]) < Decimal("1.00"):
        return jsonify({"ok": False, "message": "Online payment amount must be at least Rs. 1.00."}), 400

    try:
        lock_cashfree_user(user.id)
        order = find_pending_cashfree_order(user.id, address.id, items, totals)
        if order is None:
            order = create_pending_cashfree_order(user, address, items, totals, customer_snapshot)
        else:
            apply_order_customer_snapshot(order, customer_snapshot)
            order.payment_status = "Pending"
            order.order_status = "Pending"
            if order.payment:
                order.payment.payment_status = "Pending"
                order.payment.amount = totals["total"]
                order.payment.currency = "INR"
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to create pending Cashfree order for user %s", user.id)
        return jsonify({"ok": False, "message": "Unable to start payment. Please try again."}), 500

    order = get_order_queryset().filter(Order.id == order.id, Order.user_id == user.id).first()
    payment = order.payment if order else None
    if order is None or payment is None:
        app.logger.error("Pending Cashfree order/payment disappeared for user %s", user.id)
        return jsonify({"ok": False, "message": "Unable to start payment. Please try again."}), 500

    return_url = url_for("cashfree_verify", _external=True) + "?order_id={order_id}"
    notify_url = url_for("cashfree_webhook", _external=True)
    cf_order_id = payment.gateway_order_id or order.order_number
    session_payload = None

    try:
        if payment.gateway_order_id:
            try:
                existing_cf_order = cashfree_verify_order(payment.gateway_order_id)
                existing_status = str(existing_cf_order.get("order_status", "")).upper()
                if existing_status == "PAID":
                    return jsonify({"ok": True, "redirect_url": url_for("user_order_detail", order_id=order.id)})
                if existing_status == "ACTIVE" and existing_cf_order.get("payment_session_id"):
                    session_payload = existing_cf_order
                else:
                    cf_order_id = f"{order.order_number}-{uuid4().hex[:6].upper()}"
            except CashfreeAPIError as exc:
                if exc.status_code != 404:
                    raise
                cf_order_id = f"{order.order_number}-{uuid4().hex[:6].upper()}"

        if session_payload is None:
            customer = {
                "id": user.id,
                "name": user.full_name,
                "email": user.email,
                "phone": cashfree_customer_phone(user, address),
            }
            try:
                session_payload = cashfree_create_order(
                    order_id=cf_order_id,
                    amount=totals["total"],
                    customer=customer,
                    return_url=return_url,
                    notify_url=notify_url,
                    note=f"Wolfs Garage order {order.order_number}",
                    tags={"local_order_id": str(order.id), "user_id": str(user.id)},
                    idempotency_key=cf_order_id,
                )
            except CashfreeAPIError as exc:
                if exc.status_code != 409:
                    raise
                session_payload = cashfree_verify_order(cf_order_id)

        payment_session_id = session_payload.get("payment_session_id")
        if not payment_session_id:
            raise CashfreeAPIError("Cashfree did not return a payment session.")

        payment.gateway_order_id = session_payload.get("order_id") or cf_order_id
        payment.payment_status = "Pending"
        order.payment_status = "Pending"
        order.order_status = "Pending"
        db.session.commit()

        return jsonify({
            "ok": True,
            "payment_session_id": payment_session_id,
            "order_id": payment.gateway_order_id,
        })
    except CashfreeConfigError:
        db.session.rollback()
        app.logger.exception("Cashfree credentials are missing or invalid.")
        return jsonify({"ok": False, "message": "Unable to start payment. Please try again."}), 503
    except CashfreeAPIError as exc:
        db.session.rollback()
        app.logger.exception("Cashfree session creation failed: %s", exc)
        return jsonify({"ok": False, "message": "Unable to start payment. Please try again."}), 502
    except Exception:
        db.session.rollback()
        app.logger.exception("Unexpected Cashfree session creation error.")
        return jsonify({"ok": False, "message": "Unable to start payment. Please try again."}), 500


@app.get("/cashfree/verify")
def cashfree_verify():
    if not require_customer_session():
        return redirect(url_for("home"))

    cf_order_id = (request.args.get("order_id") or "").strip()
    if not cf_order_id:
        flash("Unable to verify payment. Please try again.", "danger")
        return redirect(url_for("orders"))

    try:
        order, status = reconcile_cashfree_order(cf_order_id, user_id=session["user_id"])
    except CashfreeConfigError:
        db.session.rollback()
        app.logger.exception("Cashfree credentials are missing during payment verification.")
        flash("Unable to verify payment. Please try again.", "danger")
        return redirect(url_for("orders"))
    except (CashfreeAPIError, ValueError):
        db.session.rollback()
        app.logger.exception("Cashfree payment verification failed for order %s", cf_order_id)
        flash("Unable to verify payment. Please try again.", "danger")
        return redirect(url_for("orders"))

    if order is None or status == "not_found":
        flash("Unable to find this payment.", "danger")
        return redirect(url_for("orders"))
    if status == "forbidden":
        flash("You do not have access to this payment.", "danger")
        return redirect(url_for("orders"))
    if status == "paid":
        flash("Order Confirmed", "success")
        return redirect(url_for("user_order_detail", order_id=order.id))
    if status == "failed":
        flash("Payment failed. Please retry payment.", "danger")
        return redirect(url_for("payment", address_id=order.address_id))
    if status == "cancelled":
        flash("Payment was cancelled. You can retry payment.", "warning")
        return redirect(url_for("payment", address_id=order.address_id))

    flash("Payment is still being processed.", "warning")
    return redirect(url_for("payment", address_id=order.address_id))


@app.post("/cashfree/webhook")
def cashfree_webhook():
    raw_body = request.get_data()
    signature = request.headers.get("x-webhook-signature")
    timestamp = request.headers.get("x-webhook-timestamp")
    if not cashfree_verify_webhook(raw_body, signature, timestamp):
        app.logger.warning("Rejected Cashfree webhook with invalid signature.")
        return jsonify({"ok": False}), 400

    try:
        payload = parse_webhook_payload(raw_body)
        cf_order_id = (
            payload.get("data", {})
            .get("order", {})
            .get("order_id")
        )
        if not cf_order_id:
            app.logger.warning("Cashfree webhook missing order_id.")
            return jsonify({"ok": True}), 200
        order, status = reconcile_cashfree_order(cf_order_id, webhook_signature=signature)
        app.logger.info("Cashfree webhook reconciled order %s with status %s", cf_order_id, status)
        return jsonify({"ok": True}), 200
    except (CashfreeAPIError, ValueError):
        db.session.rollback()
        app.logger.exception("Cashfree webhook reconciliation failed.")
        return jsonify({"ok": False}), 500
    except Exception:
        db.session.rollback()
        app.logger.exception("Unexpected Cashfree webhook error.")
        return jsonify({"ok": False}), 500


@app.post("/place-order")
def place_order():
    if not require_customer_session():
        return redirect(url_for("home"))

    user = get_current_user()
    address_id = parse_int(request.form.get("address_id"))
    payment_method = normalize_status(
        request.form.get("payment_method"),
        {"upi", "credit_card", "debit_card", "net_banking", "cash_on_delivery", "wallet"},
        "cash_on_delivery",
    )
    display_payment_method = {
        "upi": "UPI",
        "credit_card": "Credit Card",
        "debit_card": "Debit Card",
        "net_banking": "Net Banking",
        "cash_on_delivery": "Cash on Delivery",
        "wallet": "Wallet",
    }[payment_method]

    address = Address.query.filter_by(id=address_id, user_id=user.id).first() if address_id else None
    items = Cart.query.options(joinedload(Cart.product)).filter_by(user_id=user.id).all()
    if address is None:
        flash("Please select a delivery address.", "danger")
        return redirect(url_for("checkout"))
    if not items:
        flash("Your cart is empty.", "warning")
        return redirect(url_for("cart"))
    if any(item.product is None or not item.product.is_active or item.quantity > item.product.stock for item in items):
        flash("One or more cart items are unavailable or out of stock.", "danger")
        return redirect(url_for("cart"))

    customer_snapshot, snapshot_error = order_customer_snapshot(user, address)
    if snapshot_error:
        flash(snapshot_error, "danger")
        return redirect(url_for("checkout"))

    totals = cart_totals(items)
    order = Order(
        user_id=user.id,
        address_id=address.id,
        order_number=f"WG-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid4().hex[:6].upper()}",
        subtotal_amount=totals["subtotal"],
        total_amount=totals["total"],
        shipping_charge=totals["delivery_charge"],
        discount_amount=totals["discount"],
        order_status="Pending",
        payment_status="Pending",
        payment_method=display_payment_method,
    )
    apply_order_customer_snapshot(order, customer_snapshot)
    db.session.add(order)
    for item in items:
        product = item.product
        product.stock -= item.quantity
        order.order_items.append(OrderItem(
            product_id=product.id,
            product_name=product.name,
            quantity=item.quantity,
            price=current_product_price(product),
        ))
        db.session.delete(item)

    db.session.flush()
    db.session.add(Payment(
        order_id=order.id,
        payment_method=display_payment_method,
        amount=totals["total"],
        payment_status="Pending",
    ))
    db.session.commit()
    flash("Order placed successfully.", "success")
    return redirect(url_for("user_order_detail", order_id=order.id))


@app.route("/products/<slug>")
def product_detail(slug):
    product = customer_product_queryset().filter(Product.slug == slug).first_or_404()
    return render_template("user/product_detail.html", product=product, product_price=current_product_price(product))


@app.post("/cart/add/<int:product_id>")
def cart_add(product_id):
    if not require_customer_session():
        if wants_json():
            return jsonify({"ok": False, "message": "Please sign in to continue."}), 401
        return redirect(url_for("home"))
    product = customer_product_queryset().filter(Product.id == product_id).first_or_404()
    quantity = max(parse_int(request.form.get("quantity"), 1), 1)
    item = merge_duplicate_cart_rows(session["user_id"], product)
    new_quantity = (item.quantity if item else 0) + quantity
    if new_quantity > product.stock:
        payload = cart_payload(session["user_id"], "Requested quantity is not available.")
        payload["ok"] = False
        if wants_json():
            return jsonify(payload), 400
        flash("Requested quantity is not available.", "warning")
        return redirect(request.referrer or url_for("home"))
    if item is None:
        item = Cart(user_id=session["user_id"], product_id=product.id, quantity=quantity, price=current_product_price(product))
        db.session.add(item)
    else:
        item.quantity = new_quantity
        item.price = current_product_price(product)
    db.session.commit()
    if wants_json():
        return jsonify(cart_payload(session["user_id"], "Product added to cart."))
    flash("Product added to cart.", "success")
    return redirect(request.referrer or url_for("cart"))


@app.post("/cart/<int:item_id>/update")
def cart_update(item_id):
    if not require_customer_session():
        if wants_json():
            return jsonify({"ok": False, "message": "Please sign in to continue."}), 401
        return redirect(url_for("home"))
    item = Cart.query.options(joinedload(Cart.product)).filter_by(id=item_id, user_id=session["user_id"]).first_or_404()
    quantity = parse_int(request.form.get("quantity"))
    if quantity is None or quantity < 1 or quantity > item.product.stock:
        payload = cart_payload(session["user_id"], "Invalid quantity.")
        payload["ok"] = False
        if wants_json():
            return jsonify(payload), 400
        flash("Invalid quantity.", "danger")
    else:
        item.quantity = quantity
        item.price = current_product_price(item.product)
        db.session.commit()
        if wants_json():
            return jsonify(cart_payload(session["user_id"], "Cart updated."))
        flash("Cart updated.", "success")
    return redirect(url_for("cart"))


@app.post("/cart/<int:item_id>/remove")
def cart_remove(item_id):
    if not require_customer_session():
        if wants_json():
            return jsonify({"ok": False, "message": "Please sign in to continue."}), 401
        return redirect(url_for("home"))
    item = Cart.query.filter_by(id=item_id, user_id=session["user_id"]).first_or_404()
    db.session.delete(item)
    db.session.commit()
    if wants_json():
        return jsonify(cart_payload(session["user_id"], "Item removed from cart."))
    flash("Item removed from cart.", "success")
    return redirect(url_for("cart"))


@app.post("/cart/<int:item_id>/wishlist")
def cart_move_to_wishlist(item_id):
    if not require_customer_session():
        if wants_json():
            return jsonify({"ok": False, "message": "Please sign in to continue."}), 401
        return redirect(url_for("home"))
    item = Cart.query.filter_by(id=item_id, user_id=session["user_id"]).first_or_404()
    existing = Wishlist.query.filter_by(user_id=session["user_id"], product_id=item.product_id).first()
    if existing is None:
        db.session.add(Wishlist(user_id=session["user_id"], product_id=item.product_id))
    db.session.delete(item)
    db.session.commit()
    if wants_json():
        return jsonify(cart_payload(session["user_id"], "Item moved to wishlist."))
    flash("Item moved to wishlist.", "success")
    return redirect(url_for("cart"))


@app.post("/wishlist/toggle/<int:product_id>")
def wishlist_toggle(product_id):
    if not require_customer_session():
        return redirect(url_for("home"))
    product = customer_product_queryset().filter(Product.id == product_id).first_or_404()
    item = Wishlist.query.filter_by(user_id=session["user_id"], product_id=product.id).first()
    if item:
        db.session.delete(item)
        message = "Removed from wishlist."
    else:
        db.session.add(Wishlist(user_id=session["user_id"], product_id=product.id))
        message = "Added to wishlist."
    db.session.commit()
    flash(message, "success")
    return redirect(request.referrer or url_for("home"))


# =====================================================
# Admin Dashboard
# =====================================================


@app.route("/admin/dashboard")
def admin_dashboard():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    return render_template("admin/dashboard.html", **build_dashboard_context())


@app.route("/admin/analytics")
def admin_analytics():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    context = build_dashboard_context()
    context.update(build_analytics_context())
    return render_template("admin/analytics.html", **context)


@app.route("/admin/profile", methods=["GET", "POST"])
def admin_profile():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    admin = get_current_admin()
    if admin is None:
        flash("Admin account not found.", "danger")
        return redirect(url_for("admin_auth.logout"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        new_password = (request.form.get("new_password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()

        if not username or not email:
            flash("Username and email are required.", "danger")
            return redirect(url_for("admin_profile"))

        username_exists = Admin.query.filter(Admin.username == username, Admin.id != admin.id).first()
        email_exists = Admin.query.filter(Admin.email == email, Admin.id != admin.id).first()

        if username_exists:
            flash("Username already exists.", "danger")
            return redirect(url_for("admin_profile"))

        if email_exists:
            flash("Email already exists.", "danger")
            return redirect(url_for("admin_profile"))

        if new_password or confirm_password:
            if len(new_password) < 8:
                flash("Password must be at least 8 characters.", "danger")
                return redirect(url_for("admin_profile"))

            if new_password != confirm_password:
                flash("Passwords do not match.", "danger")
                return redirect(url_for("admin_profile"))

            admin.password = generate_password_hash(new_password)

        admin.username = username
        admin.email = email

        db.session.commit()
        session["admin_username"] = admin.username

        flash("Profile updated successfully.", "success")
        return redirect(url_for("admin_profile"))

    return render_template(
        "admin/profile.html",
        admin=admin,
        **build_dashboard_context(),
    )


@app.route("/admin/settings", methods=["GET", "POST"])
def admin_settings():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    setting = SiteSetting.query.filter_by(key=DELIVERY_CHARGE_SETTING_KEY).first()

    if request.method == "POST":
        delivery_charge = parse_decimal(request.form.get("delivery_charge"))
        if delivery_charge is None:
            flash("Delivery charge must be a valid number.", "danger")
            return redirect(url_for("admin_settings"))
        if delivery_charge < 0:
            flash("Delivery charge cannot be negative.", "danger")
            return redirect(url_for("admin_settings"))

        if setting is None:
            setting = SiteSetting(key=DELIVERY_CHARGE_SETTING_KEY, value=Decimal("0.00"))
            db.session.add(setting)

        setting.value = money(delivery_charge)
        db.session.commit()
        flash("Delivery charge updated successfully.", "success")
        return redirect(url_for("admin_settings"))

    context = build_dashboard_context()
    context.update(
        {
            "uploads_path": app.config["UPLOAD_FOLDER"],
            "database_uri": app.config.get("SQLALCHEMY_DATABASE_URI", ""),
            "admin_code_configured": bool(Config.ADMIN_CODE),
            "delivery_charge": money(setting.value if setting is not None else Decimal("0.00")),
        }
    )
    return render_template("admin/settings.html", **context)


# =====================================================
# Products
# =====================================================


@app.route("/admin/products")
def products():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    search = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "all").strip().lower()
    sort = (request.args.get("sort") or "newest").strip().lower()
    category_id = parse_int(request.args.get("category"))
    brand_id = parse_int(request.args.get("brand"))
    page = request.args.get("page", default=1, type=int)

    query = get_product_queryset()

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Product.name.ilike(search_term),
                Product.slug.ilike(search_term),
                Product.sku.ilike(search_term),
            )
        )

    if status_filter == "active":
        query = query.filter(Product.is_active.is_(True))
    elif status_filter == "inactive":
        query = query.filter(Product.is_active.is_(False))
    elif status_filter == "featured":
        query = query.filter(Product.is_featured.is_(True))
    elif status_filter == "trending":
        query = query.filter(Product.is_trending.is_(True))
    elif status_filter == "best_seller":
        query = query.filter(Product.is_best_seller.is_(True))

    if category_id:
        query = query.filter(Product.category_id == category_id)

    if brand_id:
        query = query.filter(Product.brand_id == brand_id)

    sort_map = {
        "newest": desc(Product.created_at),
        "oldest": asc(Product.created_at),
        "name_asc": asc(Product.name),
        "name_desc": desc(Product.name),
        "price_asc": asc(Product.price),
        "price_desc": desc(Product.price),
        "stock_asc": asc(Product.stock),
        "stock_desc": desc(Product.stock),
    }

    query = query.order_by(sort_map.get(sort, desc(Product.created_at)))
    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template(
        "admin/products.html",
        products=pagination.items,
        pagination=pagination,
        categories=Category.query.order_by(Category.name).all(),
        brands=Brand.query.order_by(Brand.name).all(),
        search=search,
        status_filter=status_filter,
        sort=sort,
        selected_category=category_id,
        selected_brand=brand_id,
        **build_dashboard_context(),
    )


@app.route("/admin/products/new", methods=["GET", "POST"])
def admin_product_new():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    categories = Category.query.order_by(Category.name).all()
    brands = Brand.query.order_by(Brand.name).all()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        category_id = parse_int(request.form.get("category_id"))
        brand_id = parse_int(request.form.get("brand_id"))
        price = parse_decimal(request.form.get("price"))
        discount_price = parse_decimal(request.form.get("discount_price"))
        stock = parse_int(request.form.get("stock"), 0)
        description = (request.form.get("description") or "").strip()
        slug_value = slugify_text(request.form.get("slug") or name)
        sku_value = (request.form.get("sku") or "").strip() or generate_sku(name)
        is_featured = parse_bool(request.form.get("is_featured"))
        is_trending = parse_bool(request.form.get("is_trending"))
        is_best_seller = parse_bool(request.form.get("is_best_seller"))
        is_active = parse_bool(request.form.get("is_active", "on"))

        if not name or not category_id or not brand_id or price is None or stock is None or stock < 0 or not description:
            flash("Please complete all required product fields.", "danger")
            return render_template(
                "admin/product_form.html",
                product=None,
                categories=categories,
                brands=brands,
                form_data=request.form,
                **build_dashboard_context(),
            )

        if discount_price is not None and discount_price > price:
            flash("Discount price cannot exceed the base price.", "danger")
            return render_template(
                "admin/product_form.html",
                product=None,
                categories=categories,
                brands=brands,
                form_data=request.form,
                **build_dashboard_context(),
            )

        uniqueness_error = ensure_unique_product_fields(None, slug_value, sku_value)
        if uniqueness_error:
            flash(uniqueness_error, "danger")
            return render_template(
                "admin/product_form.html",
                product=None,
                categories=categories,
                brands=brands,
                form_data=request.form,
                **build_dashboard_context(),
            )

        if db.session.get(Category, category_id) is None:
            flash("Selected category does not exist.", "danger")
            return redirect(url_for("admin_product_new"))

        if db.session.get(Brand, brand_id) is None:
            flash("Selected brand does not exist.", "danger")
            return redirect(url_for("admin_product_new"))

        product = Product(
            name=name,
            category_id=category_id,
            brand_id=brand_id,
            slug=slug_value,
            sku=sku_value,
            description=description,
            price=price,
            discount_price=discount_price,
            stock=stock,
            is_featured=is_featured,
            is_trending=is_trending,
            is_best_seller=is_best_seller,
            is_active=is_active,
        )

        main_image = save_uploaded_file(request.files.get("main_image"), "products")
        if main_image:
            product.main_image = main_image

        db.session.add(product)
        db.session.flush()

        gallery_files = request.files.getlist("gallery_images")
        gallery_paths = []
        for file_storage in gallery_files:
            saved = save_uploaded_file(file_storage, "products")
            if saved:
                gallery_paths.append(saved)

        if not product.main_image and gallery_paths:
            product.main_image = gallery_paths[0]
            gallery_paths = gallery_paths[1:]

        if product.main_image:
            db.session.add(
                ProductImage(
                    product=product,
                    image_url=product.main_image,
                    is_primary=True,
                )
            )

        for image_path in gallery_paths:
            db.session.add(
                ProductImage(
                    product=product,
                    image_url=image_path,
                    is_primary=False,
                )
            )

        db.session.commit()
        flash("Product created successfully.", "success")
        return redirect(url_for("products"))

    return render_template(
        "admin/product_form.html",
        product=None,
        categories=categories,
        brands=brands,
        form_data={},
        **build_dashboard_context(),
    )


@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
def admin_product_edit(product_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    product = get_product_queryset().filter(Product.id == product_id).first()
    if product is None:
        flash("Product not found.", "danger")
        return redirect(url_for("products"))

    categories = Category.query.order_by(Category.name).all()
    brands = Brand.query.order_by(Brand.name).all()

    if request.method == "POST":
        uploads_to_remove = []
        name = (request.form.get("name") or "").strip()
        category_id = parse_int(request.form.get("category_id"))
        brand_id = parse_int(request.form.get("brand_id"))
        price = parse_decimal(request.form.get("price"))
        discount_price = parse_decimal(request.form.get("discount_price"))
        stock = parse_int(request.form.get("stock"), 0)
        description = (request.form.get("description") or "").strip()
        slug_value = slugify_text(request.form.get("slug") or name)
        sku_value = (request.form.get("sku") or "").strip()
        is_featured = parse_bool(request.form.get("is_featured"))
        is_trending = parse_bool(request.form.get("is_trending"))
        is_best_seller = parse_bool(request.form.get("is_best_seller"))
        is_active = parse_bool(request.form.get("is_active", "on"))

        if not name or not category_id or not brand_id or price is None or stock is None or stock < 0 or not description or not sku_value:
            flash("Please complete all required product fields.", "danger")
            return render_template(
                "admin/product_form.html",
                product=product,
                categories=categories,
                brands=brands,
                form_data=request.form,
                **build_dashboard_context(),
            )

        if discount_price is not None and discount_price > price:
            flash("Discount price cannot exceed the base price.", "danger")
            return render_template(
                "admin/product_form.html",
                product=product,
                categories=categories,
                brands=brands,
                form_data=request.form,
                **build_dashboard_context(),
            )

        uniqueness_error = ensure_unique_product_fields(product, slug_value, sku_value)
        if uniqueness_error:
            flash(uniqueness_error, "danger")
            return render_template(
                "admin/product_form.html",
                product=product,
                categories=categories,
                brands=brands,
                form_data=request.form,
                **build_dashboard_context(),
            )

        if db.session.get(Category, category_id) is None:
            flash("Selected category does not exist.", "danger")
            return redirect(url_for("admin_product_edit", product_id=product.id))

        if db.session.get(Brand, brand_id) is None:
            flash("Selected brand does not exist.", "danger")
            return redirect(url_for("admin_product_edit", product_id=product.id))

        product.name = name
        product.category_id = category_id
        product.brand_id = brand_id
        product.slug = slug_value
        product.sku = sku_value
        product.description = description
        product.price = price
        product.discount_price = discount_price
        product.stock = stock
        product.is_featured = is_featured
        product.is_trending = is_trending
        product.is_best_seller = is_best_seller
        product.is_active = is_active

        main_image = save_uploaded_file(request.files.get("main_image"), "products")
        remove_main_image = parse_bool(request.form.get("remove_main_image"))
        if main_image:
            previous_main_image = product.main_image
            product.main_image = main_image
            primary_image = next((image for image in product.images if image.is_primary), None)
            if primary_image is not None:
                primary_image.image_url = main_image
            else:
                db.session.add(
                    ProductImage(
                        product=product,
                        image_url=main_image,
                        is_primary=True,
                    )
                )
            if previous_main_image and previous_main_image != main_image:
                uploads_to_remove.append(previous_main_image)
        elif remove_main_image:
            previous_main_image = product.main_image
            product.main_image = None
            primary_image = next((image for image in product.images if image.is_primary), None)
            if primary_image is not None:
                db.session.delete(primary_image)
            if previous_main_image:
                uploads_to_remove.append(previous_main_image)

        gallery_files = request.files.getlist("gallery_images")
        for file_storage in gallery_files:
            saved = save_uploaded_file(file_storage, "products")
            if saved:
                is_primary = False
                if not product.main_image:
                    product.main_image = saved
                    is_primary = True
                db.session.add(
                    ProductImage(
                        product=product,
                        image_url=saved,
                        is_primary=is_primary,
                    )
                )

        active_images = [image for image in product.images if image not in db.session.deleted]

        if product.main_image is None:
            remaining = next(iter(active_images), None)
            if remaining is not None:
                product.main_image = remaining.image_url
                remaining.is_primary = True

        if product.main_image:
            for image in active_images:
                image.is_primary = image.image_url == product.main_image

        db.session.commit()
        for relative_path in uploads_to_remove:
            remove_uploaded_file(relative_path)
        flash("Product updated successfully.", "success")
        return redirect(url_for("admin_product_edit", product_id=product.id))

    return render_template(
        "admin/product_form.html",
        product=product,
        categories=categories,
        brands=brands,
        form_data={},
        **build_dashboard_context(),
    )


@app.route("/admin/products/<int:product_id>/toggle", methods=["POST"])
def admin_product_toggle(product_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    product = db.session.get(Product, product_id)
    if product is None:
        flash("Product not found.", "danger")
        return redirect(url_for("products"))

    product.is_active = not product.is_active
    db.session.commit()
    flash("Product status updated.", "success")
    return redirect(url_for("products"))


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
def admin_product_delete(product_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    product = get_product_queryset().filter(Product.id == product_id).first()
    if product is None:
        flash("Product not found.", "danger")
        return redirect(url_for("products"))

    if product.order_items:
        flash("This product cannot be deleted because it has linked orders.", "warning")
        return redirect(url_for("products"))

    delete_product_media(product)
    db.session.delete(product)
    db.session.commit()
    flash("Product deleted successfully.", "success")
    return redirect(url_for("products"))


@app.route("/admin/products/<int:product_id>/images/<int:image_id>/delete", methods=["POST"])
def admin_product_image_delete(product_id, image_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    product = db.session.get(Product, product_id)
    if product is None:
        flash("Product not found.", "danger")
        return redirect(url_for("products"))

    image = ProductImage.query.filter_by(id=image_id, product_id=product_id).first()
    if image is None:
        flash("Image not found.", "danger")
        return redirect(url_for("admin_product_edit", product_id=product_id))

    if image.is_primary and product.main_image == image.image_url:
        product.main_image = None

    remove_uploaded_file(image.image_url)
    db.session.delete(image)

    if product.main_image is None:
        remaining = ProductImage.query.filter_by(product_id=product_id).order_by(ProductImage.created_at.asc()).first()
        if remaining is not None:
            product.main_image = remaining.image_url
            remaining.is_primary = True

    db.session.commit()
    flash("Image removed.", "success")
    return redirect(url_for("admin_product_edit", product_id=product_id))


# =====================================================
# Categories
# =====================================================


@app.route("/admin/categories", methods=["GET", "POST"])
def admin_categories():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    edit_id = parse_int(request.args.get("edit"))
    editing_category = db.session.get(Category, edit_id) if edit_id else None

    if request.method == "POST":
        category_id = parse_int(request.form.get("category_id"))
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        is_active = parse_bool(request.form.get("is_active", "on"))

        if not name:
            flash("Category name is required.", "danger")
            return redirect(url_for("admin_categories", edit=category_id or ""))

        duplicate = Category.query.filter(Category.name.ilike(name))
        if category_id:
            duplicate = duplicate.filter(Category.id != category_id)
        if duplicate.first():
            flash("Category name already exists.", "danger")
            return redirect(url_for("admin_categories", edit=category_id or ""))

        if category_id:
            category = db.session.get(Category, category_id)
            if category is None:
                flash("Category not found.", "danger")
                return redirect(url_for("admin_categories"))
        else:
            category = Category()
            db.session.add(category)

        image = save_uploaded_file(request.files.get("image"), "categories")
        replace_image = parse_bool(request.form.get("replace_image"))
        if image:
            remove_uploaded_file(category.image)
            category.image = image
        elif replace_image:
            remove_uploaded_file(category.image)
            category.image = None

        category.name = name
        category.description = description or None
        category.is_active = is_active

        db.session.commit()
        flash("Category saved successfully.", "success")
        return redirect(url_for("admin_categories"))

    categories = (
        Category.query.options(selectinload(Category.products))
        .order_by(Category.name)
        .all()
    )

    return render_template(
        "admin/categories.html",
        categories=categories,
        editing_category=editing_category,
        **build_dashboard_context(),
    )


@app.route("/admin/categories/<int:category_id>/delete", methods=["POST"])
def admin_category_delete(category_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    category = db.session.get(Category, category_id)
    if category is None:
        flash("Category not found.", "danger")
        return redirect(url_for("admin_categories"))

    if category.products:
        flash("Please move or delete products before deleting this category.", "warning")
        return redirect(url_for("admin_categories"))

    remove_uploaded_file(category.image)
    db.session.delete(category)
    db.session.commit()
    flash("Category deleted successfully.", "success")
    return redirect(url_for("admin_categories"))


@app.route("/admin/categories/<int:category_id>/toggle", methods=["POST"])
def admin_category_toggle(category_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    category = db.session.get(Category, category_id)
    if category is None:
        flash("Category not found.", "danger")
        return redirect(url_for("admin_categories"))

    category.is_active = not category.is_active
    db.session.commit()
    flash("Category status updated.", "success")
    return redirect(url_for("admin_categories"))


# =====================================================
# Brands
# =====================================================


@app.route("/admin/brands", methods=["GET", "POST"])
def admin_brands():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    edit_id = parse_int(request.args.get("edit"))
    editing_brand = db.session.get(Brand, edit_id) if edit_id else None

    if request.method == "POST":
        brand_id = parse_int(request.form.get("brand_id"))
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        website = (request.form.get("website") or "").strip()
        is_active = parse_bool(request.form.get("is_active", "on"))

        if not name:
            flash("Brand name is required.", "danger")
            return redirect(url_for("admin_brands", edit=brand_id or ""))

        duplicate = Brand.query.filter(Brand.name.ilike(name))
        if brand_id:
            duplicate = duplicate.filter(Brand.id != brand_id)
        if duplicate.first():
            flash("Brand name already exists.", "danger")
            return redirect(url_for("admin_brands", edit=brand_id or ""))

        if brand_id:
            brand = db.session.get(Brand, brand_id)
            if brand is None:
                flash("Brand not found.", "danger")
                return redirect(url_for("admin_brands"))
        else:
            brand = Brand()
            db.session.add(brand)

        logo = save_uploaded_file(request.files.get("logo"), "brands")
        replace_logo = parse_bool(request.form.get("replace_logo"))
        if logo:
            remove_uploaded_file(brand.logo)
            brand.logo = logo
        elif replace_logo:
            remove_uploaded_file(brand.logo)
            brand.logo = None

        brand.name = name
        brand.description = description or None
        brand.website = website or None
        brand.is_active = is_active

        db.session.commit()
        flash("Brand saved successfully.", "success")
        return redirect(url_for("admin_brands"))

    brands = (
        Brand.query.options(selectinload(Brand.products))
        .order_by(Brand.name)
        .all()
    )

    return render_template(
        "admin/brands.html",
        brands=brands,
        editing_brand=editing_brand,
        **build_dashboard_context(),
    )


@app.route("/admin/brands/<int:brand_id>/delete", methods=["POST"])
def admin_brand_delete(brand_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    brand = db.session.get(Brand, brand_id)
    if brand is None:
        flash("Brand not found.", "danger")
        return redirect(url_for("admin_brands"))

    if brand.products:
        flash("Please move or delete products before deleting this brand.", "warning")
        return redirect(url_for("admin_brands"))

    remove_uploaded_file(brand.logo)
    db.session.delete(brand)
    db.session.commit()
    flash("Brand deleted successfully.", "success")
    return redirect(url_for("admin_brands"))


@app.route("/admin/brands/<int:brand_id>/toggle", methods=["POST"])
def admin_brand_toggle(brand_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    brand = db.session.get(Brand, brand_id)
    if brand is None:
        flash("Brand not found.", "danger")
        return redirect(url_for("admin_brands"))

    brand.is_active = not brand.is_active
    db.session.commit()
    flash("Brand status updated.", "success")
    return redirect(url_for("admin_brands"))


# =====================================================
# Orders
# =====================================================


@app.route("/admin/orders")
def orders():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    status_filter = (request.args.get("status") or "all").strip().lower()
    payment_filter = (request.args.get("payment") or "all").strip().lower()
    page = request.args.get("page", default=1, type=int)

    query = get_order_queryset()

    if status_filter != "all":
        query = query.filter(func.lower(Order.order_status) == status_filter)

    if payment_filter != "all":
        query = query.filter(func.lower(Order.payment_status) == payment_filter)

    query = query.order_by(Order.created_at.desc())
    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template(
        "admin/orders.html",
        orders=pagination.items,
        pagination=pagination,
        status_filter=status_filter,
        payment_filter=payment_filter,
        **build_dashboard_context(),
    )


@app.route("/admin/orders/<int:order_id>/update", methods=["POST"])
def admin_order_update(order_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    order = db.session.get(Order, order_id)
    if order is None:
        flash("Order not found.", "danger")
        return redirect(url_for("orders"))

    save_order_status(order)
    db.session.commit()
    flash("Order updated successfully.", "success")
    return redirect(request.referrer or url_for("orders"))


@app.route("/admin/orders/<int:order_id>")
def admin_order_detail(order_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    order = get_order_queryset().filter(Order.id == order_id).first()
    if order is None:
        flash("Order not found.", "danger")
        return redirect(url_for("orders"))

    return render_template(
        "admin/order_detail.html",
        order=order,
        timeline=order_timeline(order),
        **build_dashboard_context(),
    )


@app.route("/admin/orders/<int:order_id>/invoice")
def admin_order_invoice(order_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    order = get_order_queryset().filter(Order.id == order_id).first()
    if order is None:
        flash("Order not found.", "danger")
        return redirect(url_for("orders"))

    return render_template(
        "admin/invoice.html",
        order=order,
        **build_dashboard_context(),
    )


# =====================================================
# Customers
# =====================================================


@app.route("/admin/customers")
def customers():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    search = (request.args.get("q") or "").strip()
    page = request.args.get("page", default=1, type=int)

    query = User.query.options(
        selectinload(User.orders),
        selectinload(User.addresses),
        selectinload(User.cart_items),
        selectinload(User.wishlist_items),
        selectinload(User.reviews),
    )

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                User.full_name.ilike(search_term),
                User.email.ilike(search_term),
                User.phone.ilike(search_term),
            )
        )

    query = query.order_by(User.created_at.desc())
    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template(
        "admin/customers.html",
        customers=pagination.items,
        pagination=pagination,
        search=search,
        **build_dashboard_context(),
    )


# =====================================================
# Reviews
# =====================================================


@app.route("/admin/reviews")
def reviews():
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    status_filter = (request.args.get("status") or "all").strip().lower()
    page = request.args.get("page", default=1, type=int)

    query = Review.query.options(joinedload(Review.user), joinedload(Review.product))

    if status_filter != "all":
        query = query.filter(func.lower(Review.status) == status_filter)

    query = query.order_by(Review.created_at.desc())
    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template(
        "admin/reviews.html",
        reviews=pagination.items,
        pagination=pagination,
        status_filter=status_filter,
        review_status_counts=status_counts(Review.query, Review.status),
        **build_dashboard_context(),
    )


@app.route("/admin/reviews/<int:review_id>/status", methods=["POST"])
def admin_review_status(review_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    review = db.session.get(Review, review_id)
    if review is None:
        flash("Review not found.", "danger")
        return redirect(url_for("reviews"))

    review.status = normalize_status(request.form.get("status"), {"pending", "approved", "hidden"}, review.status or "pending").title()
    db.session.commit()
    flash("Review status updated.", "success")
    return redirect(url_for("reviews"))


@app.route("/admin/reviews/<int:review_id>/delete", methods=["POST"])
def admin_review_delete(review_id):
    if not require_admin_session():
        return redirect(url_for("admin_auth.login"))

    review = db.session.get(Review, review_id)
    if review is None:
        flash("Review not found.", "danger")
        return redirect(url_for("reviews"))

    db.session.delete(review)
    db.session.commit()
    flash("Review deleted successfully.", "success")
    return redirect(url_for("reviews"))


# =====================================================
# Error Pages
# =====================================================


@app.errorhandler(404)
def page_not_found(error):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def internal_server_error(error):
    db.session.rollback()
    return render_template("errors/500.html"), 500


# =====================================================
# Health Check
# =====================================================


@app.route("/health")
def health():
    return {
        "status": "running",
        "database": "connected",
    }, 200


# =====================================================
# Database Check
# =====================================================


def check_database():
    with app.app_context():
        try:
            with db.engine.connect():
                logging.info("PostgreSQL connected successfully.")
        except Exception:
            logging.exception("Database connection failed.")


# =====================================================
# Run Application
# =====================================================


if __name__ == "__main__":
    check_database()

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
        use_reloader=False,
    )
