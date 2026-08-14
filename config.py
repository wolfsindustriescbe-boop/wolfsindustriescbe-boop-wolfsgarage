import os
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv()


def _database_uri():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url

    db_user = os.getenv("DB_USER")
    db_password = quote_plus(os.getenv("DB_PASSWORD", ""))
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME")

    if all([db_user, db_host, db_name]):
        return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    return "sqlite:///wolfs_garage.db"


class Config:
    # ==========================
    # Flask
    # ==========================
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")

    # ==========================
    # Database
    # ==========================
    SQLALCHEMY_DATABASE_URI = _database_uri()

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Optional SQLAlchemy engine settings
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # ==========================
    # Session
    # ==========================
    SESSION_TYPE = "filesystem"
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True

    # ==========================
    # Google OAuth
    # ==========================
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    # ==========================
    # Cloudinary Uploads
    # ==========================
    CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

    # ==========================
    # Cashfree Payments
    # ==========================
    CASHFREE_CLIENT_ID = os.getenv("CASHFREE_CLIENT_ID")
    CASHFREE_CLIENT_SECRET = os.getenv("CASHFREE_CLIENT_SECRET")
    CASHFREE_ENV = os.getenv("CASHFREE_ENV", "sandbox").strip().lower()
    CASHFREE_API_BASE = os.getenv("CASHFREE_API_BASE")
    CASHFREE_API_VERSION = os.getenv("CASHFREE_API_VERSION", "2025-01-01")

    # ==========================
    # Customer Support
    # ==========================
    SUPPORT_PHONE = os.getenv("SUPPORT_PHONE", "").strip()
    SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "").strip()

    # ==========================
    # Admin
    # ==========================
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
    ADMIN_CODE = os.getenv("ADMIN_CODE")
