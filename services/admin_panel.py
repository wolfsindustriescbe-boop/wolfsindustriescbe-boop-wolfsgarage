import os
import re
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from flask import current_app
from werkzeug.utils import secure_filename

try:
    import cloudinary
    import cloudinary.uploader
except ImportError:  # Cloudinary is optional for local development.
    cloudinary = None

# ==========================================================
# Allowed Image Extensions
# ==========================================================

ALLOWED_IMAGE_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
    "svg",
}

# ==========================================================
# Upload Roots
# New uploads are stored inside:
# static/uploads/
# Legacy uploads may still exist inside:
# uploads/
# ==========================================================

def _primary_uploads_root() -> Path:
    root = Path(current_app.root_path) / "static" / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _legacy_uploads_root() -> Path:
    return Path(current_app.root_path) / "uploads"


def normalize_uploaded_path(relative_path: str | None) -> str:
    normalized = (relative_path or "").replace("\\", "/").lstrip("/")
    if normalized.startswith("uploads/"):
        normalized = normalized[len("uploads/"):]
    return normalized


def uploaded_file_locations(relative_path: str | None) -> list[Path]:
    normalized = normalize_uploaded_path(relative_path)
    if not normalized or is_remote_upload(normalized):
        return []
    return [
        _primary_uploads_root() / normalized,
        _legacy_uploads_root() / normalized,
    ]

# ==========================================================
# Validate Image
# ==========================================================

def allowed_image(filename: str) -> bool:
    if not filename:
        return False

    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_IMAGE_EXTENSIONS


def is_remote_upload(path: str | None) -> bool:
    normalized = (path or "").strip().lower()
    return normalized.startswith(("http://", "https://"))


def _cloudinary_configured() -> bool:
    if cloudinary is None:
        return False

    cloud_name = current_app.config.get("CLOUDINARY_CLOUD_NAME")
    api_key = current_app.config.get("CLOUDINARY_API_KEY")
    api_secret = current_app.config.get("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        return False

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    return True


def _cloudinary_public_id(image_url: str | None) -> str | None:
    if not is_remote_upload(image_url):
        return None

    parsed = urlparse(image_url)
    marker = "/upload/"
    if marker not in parsed.path:
        return None

    public_path = parsed.path.split(marker, 1)[1]
    parts = public_path.split("/")
    if parts and re.fullmatch(r"v\d+", parts[0]):
        parts = parts[1:]

    public_id = unquote("/".join(parts))
    if "." in public_id:
        public_id = public_id.rsplit(".", 1)[0]

    return public_id or None

# ==========================================================
# Slug Generator
# ==========================================================

def slugify_text(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)

    return value.strip("-")

# ==========================================================
# SKU Generator
# ==========================================================

def generate_sku(name: str, prefix: str = "WG") -> str:
    base = slugify_text(name)

    if not base:
        base = "ITEM"

    base = base.replace("-", "")[:8].upper()

    random_code = uuid.uuid4().hex[:6].upper()

    return f"{prefix}-{base}-{random_code}"

# ==========================================================
# Save Uploaded Image
# ==========================================================

def save_uploaded_file(file_storage, subfolder: str = "products") -> str | None:

    if file_storage is None:
        return None

    if not getattr(file_storage, "filename", ""):
        return None

    if not allowed_image(file_storage.filename):
        return None

    if _cloudinary_configured():
        result = cloudinary.uploader.upload(
            file_storage,
            folder=f"wolfs_garage/{subfolder}",
            resource_type="image",
        )
        return result.get("secure_url")

    filename = secure_filename(file_storage.filename)

    _, extension = os.path.splitext(filename)

    unique_filename = (
        f"{uuid.uuid4().hex}{extension.lower()}"
    )

    upload_folder = _primary_uploads_root() / subfolder
    upload_folder.mkdir(parents=True, exist_ok=True)

    save_path = upload_folder / unique_filename

    file_storage.save(save_path)

    # Save relative path only
    return f"uploads/{subfolder}/{unique_filename}"

# ==========================================================
# Delete Old Image
# ==========================================================

def remove_uploaded_file(relative_path: str | None) -> None:

    if not relative_path:
        return

    public_id = _cloudinary_public_id(relative_path)
    if public_id and _cloudinary_configured():
        try:
            cloudinary.uploader.destroy(public_id, resource_type="image")
        except Exception:
            pass
        return

    for file_path in uploaded_file_locations(relative_path):
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass
