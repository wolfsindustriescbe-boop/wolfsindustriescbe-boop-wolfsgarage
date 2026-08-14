from app import app, upload_route_filename
from io import BytesIO
from werkzeug.datastructures import FileStorage
from services.admin_panel import save_uploaded_file, remove_uploaded_file
from models.product import Product

client = app.test_client()
with app.app_context():
    fs = FileStorage(stream=BytesIO(b"test image bytes"), filename="probe.jpg", content_type="image/jpeg")
    path = save_uploaded_file(fs, "products")
    print("saved path:", path)
    tests = [
        "/uploads/" + path.replace("uploads/", ""),
        "/uploads/" + path,
        "/uploads/products/fog.jpg",
        "/uploads/products/c4fd3b6a20544b75a1e2d07d74941c04.jpg",
        "/uploads/categories/image_fd0fa2fe.png",
        "/uploads/brands/51PB36C0ZBL_35cb6f7e.jpg",
    ]
    for url_path in tests:
        r = client.get(url_path)
        print(url_path, "->", r.status_code)
    remove_uploaded_file(path)
    with app.test_request_context():
        from flask import url_for
        from app import inject_upload_helpers
        uploaded_url = inject_upload_helpers()["uploaded_url"]
        test_path = "uploads/products/4a248b79a2274086b47bbf19e6a042bc.jpg"
        # recreate file for url test
        fs2 = FileStorage(stream=BytesIO(b"x"), filename="x.jpg", content_type="image/jpeg")
        p2 = save_uploaded_file(fs2, "products")
        url = uploaded_url(p2)
        print("uploaded_url ->", url)
        r = client.get(url.replace("http://localhost", ""))
        print("uploaded_url status", r.status_code)
        remove_uploaded_file(p2)
    p = Product.query.get(2)
    if p and p.main_image:
        norm = upload_route_filename(p.main_image)
        url = "/uploads/" + norm
        r = client.get(url)
        print("product2", url, "->", r.status_code)
