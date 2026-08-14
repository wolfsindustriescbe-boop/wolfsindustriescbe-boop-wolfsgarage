import logging

from flask import (
    Blueprint,
    redirect,
    url_for,
    session,
    flash,
)

from authlib.integrations.flask_client import OAuth

from database import db
from models.user import User
from config import Config


logger = logging.getLogger(__name__)


# =====================================================
# Blueprint
# =====================================================

auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth"
)


# =====================================================
# OAuth
# =====================================================

oauth = OAuth()

google = oauth.register(
    name="google",
    client_id=Config.GOOGLE_CLIENT_ID,
    client_secret=Config.GOOGLE_CLIENT_SECRET,
    server_metadata_url=(
        "https://accounts.google.com/.well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": "openid email profile"
    }
)


# =====================================================
# Initialize OAuth
# =====================================================

def init_oauth(app):
    oauth.init_app(app)


# =====================================================
# Google Login
# =====================================================

@auth_bp.route("/login")
def login():
    return redirect(url_for("home"))


# =====================================================
# Google Callback
# =====================================================

@auth_bp.route("/callback")
def callback():

    try:

        # Get Google access token
        token = google.authorize_access_token()

        # Get user information
        user_info = token.get("userinfo")

        if not user_info:
            response = google.get(
                "https://www.googleapis.com/oauth2/v3/userinfo"
            )

            user_info = response.json()

        # Get email
        email = user_info.get("email")

        if not email:
            flash(
                "Unable to fetch Google account.",
                "danger"
            )

            return redirect(url_for("home"))

        # =================================================
        # Find Existing User
        # =================================================

        user = User.query.filter_by(
            email=email
        ).first()

        # =================================================
        # Create New User
        # =================================================

        if user is None:

            user = User(
                full_name=user_info.get("name"),
                email=email,
                google_id=user_info.get("sub"),
                profile_image=user_info.get("picture"),
                is_active=True
            )

            db.session.add(user)

        # =================================================
        # Update Existing User
        # =================================================

        else:

            user.full_name = user_info.get("name")
            user.google_id = user_info.get("sub")
            user.profile_image = user_info.get("picture")
            user.is_active = True

        # Save database changes
        db.session.commit()

        # =================================================
        # Create Session
        # =================================================

        session.clear()

        session["user_id"] = user.id
        session["user_name"] = user.full_name
        session["user_email"] = user.email
        session["logged_in"] = True

        flash(
            "Login Successful",
            "success"
        )

        return redirect(
            url_for("home")
        )

    except Exception:

        db.session.rollback()

        logger.exception(
            "Google login failed"
        )

        flash(
            "Google Login Failed",
            "danger"
        )

        return redirect(
            url_for("home")
        )


# =====================================================
# Logout
# =====================================================

@auth_bp.route("/logout")
def logout():

    for key in ("user_id", "user_name", "user_email", "logged_in"):
        session.pop(key, None)

    return redirect(
        url_for("home")
    )
