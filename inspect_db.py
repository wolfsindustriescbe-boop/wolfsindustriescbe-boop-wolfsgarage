from app import app
from database import db
from sqlalchemy import inspect
import logging

with app.app_context():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    print("Tables found:", tables)
    for table in tables:
        columns = inspector.get_columns(table)
        print(f"\nTable: {table}")
        for col in columns:
            print(f"  - {col['name']}: {col['type']}")
        
        # Count rows
        try:
            res = db.session.execute(db.text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  Row count: {res}")
        except Exception as e:
            print(f"  Could not count rows: {e}")
