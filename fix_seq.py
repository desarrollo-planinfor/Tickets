from app import app, db
from sqlalchemy import text
tables = ['hallazgo_sistema_normativo', 'hallazgo_tipo_evento', 'hallazgo_clasificacion', 'hallazgo_origen', 'area']
with app.app_context():
    for table in tables:
        try:
            db.session.execute(text(f"SELECT setval('{table}_id_seq', COALESCE((SELECT MAX(id)+1 FROM {table}), 1), false);"))
            db.session.commit()
            print(f'Sequence updated for {table}')
        except Exception as e:
            db.session.rollback()
            print(f'Error updating {table}: {e}')
