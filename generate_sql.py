from sqlalchemy import create_engine, text
import datetime

engine = create_engine('postgresql://postgres:admin123@localhost:5432/tickets_db')

tables = [
    'hallazgo_sistema_normativo',
    'hallazgo_tipo_evento',
    'hallazgo_clasificacion',
    'hallazgo_origen_acr'
]

with open('catalogs_inserts.sql', 'w', encoding='utf-8') as f:
    with engine.connect() as conn:
        for table in tables:
            f.write(f"-- Data for {table}\n")
            result = conn.execute(text(f"SELECT * FROM {table}"))
            rows = result.fetchall()
            if not rows:
                f.write(f"-- No data found in {table}\n\n")
                continue
                
            columns = result.keys()
            
            for row in rows:
                cols = []
                vals = []
                for col, val in zip(columns, row):
                    cols.append(col)
                    if val is None:
                        vals.append('NULL')
                    elif isinstance(val, (int, float, bool)):
                        vals.append(str(val))
                    elif isinstance(val, datetime.datetime):
                        vals.append(f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'")
                    else:
                        val_str = str(val).replace("'", "''")
                        vals.append(f"'{val_str}'")
                f.write(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)});\n")
            f.write("\n")
