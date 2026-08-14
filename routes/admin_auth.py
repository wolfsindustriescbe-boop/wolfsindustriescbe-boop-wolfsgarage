import logging
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)
from database import db
from models.admin import Admin
from config import Config

logger = logging.getLogger(__name__)

admin_auth_bp = Blueprint(
    "admin_auth",
    __name__,
    url_prefix="/admin"
)


@admin_auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        try:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            admin_code = request.form.get("admin_code", "").strip()

            if not username or not password or not admin_code:
                flash("All fields are required.", "danger")
                return redirect(url_for("admin_auth.login"))

            if not Config.ADMIN_CODE:
                flash("Admin code is not configured.", "danger")
                return redirect(url_for("admin_auth.login"))

            admin = Admin.query.filter_by(username=username).first()

            if admin is None:
                flash("Invalid Username", "danger")
                return redirect(url_for("admin_auth.login"))

            if admin_code != Config.ADMIN_CODE:
                flash("Invalid Admin Code", "danger")
                return redirect(url_for("admin_auth.login"))

            if not check_password_hash(admin.password, password):
                flash("Invalid Password", "danger")
                return redirect(url_for("admin_auth.login"))

            session.clear()
            session["admin_logged_in"] = True
            session["admin_id"] = admin.id
            session["admin_username"] = admin.username

            flash("Login Successful", "success")
            return redirect(url_for("admin_dashboard"))

        except Exception:
            db.session.rollback()
            logger.exception("Admin login failed")
            flash("Something went wrong.", "danger")
            return redirect(url_for("admin_auth.login"))

    return render_template("admin/login.html")


@admin_auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form.get("username", "").strip()

        if not username:
            flash("Username is required.", "danger")
            return redirect(url_for("admin_auth.forgot_password"))

        admin = Admin.query.filter_by(username=username).first()

        if admin is None:
            flash("Username not found.", "danger")
            return redirect(url_for("admin_auth.forgot_password"))

        session["reset_admin_id"] = admin.id
        return redirect(url_for("admin_auth.reset_password"))

    return render_template("admin/forgot_password.html")


@admin_auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if "reset_admin_id" not in session:
        return redirect(url_for("admin_auth.forgot_password"))

    if request.method == "POST":
        try:
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not new_password or not confirm_password:
                flash("All fields are required.", "danger")
                return redirect(url_for("admin_auth.reset_password"))

            if len(new_password) < 8:
                flash("Password must be at least 8 characters.", "danger")
                return redirect(url_for("admin_auth.reset_password"))

            if new_password != confirm_password:
                flash("Passwords do not match.", "danger")
                return redirect(url_for("admin_auth.reset_password"))

            admin = db.session.get(Admin, session["reset_admin_id"])

            if admin is None:
                flash("Admin not found.", "danger")
                return redirect(url_for("admin_auth.forgot_password"))

            admin.password = generate_password_hash(new_password)

            db.session.commit()

            session.pop("reset_admin_id", None)

            flash("Password Reset Successfully.", "success")

            return redirect(url_for("admin_auth.login"))

        except Exception:
            db.session.rollback()
            logger.exception("Password reset failed")
            flash("Unable to reset password.", "danger")
            return redirect(url_for("admin_auth.reset_password"))

    return render_template("admin/reset_password.html")


@admin_auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("admin_auth.login"))
