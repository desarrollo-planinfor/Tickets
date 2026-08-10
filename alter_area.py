from app import app, db
from sqlalchemy import text
with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE area ADD COLUMN jefe_id INTEGER REFERENCES usuario(id);"))
        db.session.commit()
        print("Column jefe_id added to area table")
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
