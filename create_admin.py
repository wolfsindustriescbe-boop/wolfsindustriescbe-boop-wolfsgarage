import os

from app import app
from database import db
from models.admin import Admin
from werkzeug.security import generate_password_hash


with app.app_context():
    username = os.getenv("ADMIN_USERNAME", "admin")
    email = os.getenv("ADMIN_EMAIL", "admin@wolfsgarage.com")
    password = os.getenv("ADMIN_PASSWORD")

    if not password:
        raise RuntimeError("Set ADMIN_PASSWORD before running create_admin.py.")

    admin = Admin.query.filter_by(username=username).first()

    if admin:
        print("Admin already exists.")
    else:
        new_admin = Admin(
            username=username,
            email=email,
            password=generate_password_hash(password),
        )

        db.session.add(new_admin)
        db.session.commit()

        print("Admin created successfully!")
        print("--------------------------------")
        print(f"Username : {username}")
        print(f"Email    : {email}")
