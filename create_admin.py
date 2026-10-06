import os

from app import app
from database import db
from models.admin import Admin
from werkzeug.security import check_password_hash, generate_password_hash


INITIAL_ADMIN_USERNAME = "admin"


def _initial_admin_password():
    password = os.getenv("ADMIN_PASSWORD")
    if password:
        return password

    admin_code = os.getenv("ADMIN_CODE")
    if admin_code:
        return admin_code

    raise RuntimeError("Set ADMIN_PASSWORD or ADMIN_CODE before running create_admin.py.")


with app.app_context():
    username = INITIAL_ADMIN_USERNAME
    email = os.getenv("ADMIN_EMAIL", "admin@wolfsgarage.com")
    password = _initial_admin_password()

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
            print("Admin updated successfully!")
        else:
            print("Admin already exists.")
    else:
        new_admin = Admin(
            username=username,
            email=email,
            password=generate_password_hash(password),
            is_active=True,
        )

        db.session.add(new_admin)
        db.session.commit()

        print("Admin created successfully!")
        print("--------------------------------")
        print(f"Username : {username}")
        print(f"Email    : {email}")
