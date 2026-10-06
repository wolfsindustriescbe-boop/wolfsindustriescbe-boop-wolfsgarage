import os

from database import db
from models.admin import Admin
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


INITIAL_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_EMAIL = "admin@wolfsgarage.com"


def _initial_admin_password(required=True):
    password = os.getenv("ADMIN_PASSWORD")
    if password:
        return password

    admin_code = os.getenv("ADMIN_CODE")
    if admin_code:
        return admin_code

    if required:
        raise RuntimeError("Set ADMIN_PASSWORD or ADMIN_CODE before running create_admin.py.")
    return None


def bootstrap_initial_admin(required_secret=True):
    username = INITIAL_ADMIN_USERNAME
    email = os.getenv("ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    password = _initial_admin_password(required=required_secret)

    if not password:
        return "skipped"

    admin = Admin.query.filter_by(username=username).first()

    if admin:
        changed = False
        if not check_password_hash(admin.password, password):
            admin.password = generate_password_hash(password)
            changed = True
        if not admin.email:
            admin.email = email
            changed = True
        if admin.is_active is not True:
            admin.is_active = True
            changed = True

        if changed:
            db.session.commit()
            return "updated"
        return "exists"

    new_admin = Admin(
        username=username,
        email=email,
        password=generate_password_hash(password),
        is_active=True,
    )

    db.session.add(new_admin)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        admin = Admin.query.filter_by(username=username).first()
        if admin:
            return bootstrap_initial_admin(required_secret=required_secret)
        raise
    return "created"


def main():
    from app import app

    with app.app_context():
        result = bootstrap_initial_admin(required_secret=True)
        messages = {
            "created": "Admin created successfully.",
            "updated": "Admin updated successfully.",
            "exists": "Admin already exists.",
            "skipped": "Admin bootstrap skipped.",
        }
        print(messages[result])


if __name__ == "__main__":
    main()
