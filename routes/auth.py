import logging
from flask import (
    Blueprint,
    redirect,
    url_for,
    session,
)

logger = logging.getLogger(__name__)

auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/auth"
)


def init_oauth(app):
    pass


@auth_bp.route("/login")
def login():
    return redirect(url_for("customer_login"))


@auth_bp.route("/logout")
def logout():
    for key in ("user_id", "user_name", "user_email", "logged_in"):
        session.pop(key, None)

    return redirect(
        url_for("home")
    )
