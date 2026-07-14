import csv
from app import app, db, EquipoMantencion

CSV_PATH = 'Inventario equipos y mantenciones(Inventario).csv'

def importar():
    with app.app_context():
        print("Creando tablas si no existen...")
        db.create_all()
        
        print(f"Leyendo el archivo {CSV_PATH}...")
        
        try:
            with open(CSV_PATH, 'r', encoding='latin-1') as f:
                # El separador en este CSV es punto y coma (;)
                reader = csv.reader(f, delimiter=';')
                lines = list(reader)
                
                # Los datos reales comienzan en la fila 8 (índice 7), ignoramos los encabezados
                datos = lines[7:]
                
                # Limpiar la tabla antes de importar
                db.session.query(EquipoMantencion).delete()
                db.session.commit()
                
                contador = 0
                for row in datos:
                    # Si la fila está vacía o no tiene nombre, ignoramos (evita filas basura de Excel)
                    if not row or len(row) < 2 or not str(row[1]).strip():
                        continue
                    
                    # Asegurarnos de que tenga al menos 15 columnas, rellenar con strings vacíos si falta
                    while len(row) < 15:
                        row.append('')
                        
                    equipo = EquipoMantencion(
                        codigo=row[0].strip(),
                        nombre=row[1].strip(),
                        marca=row[2].strip(),
                        modelo=row[3].strip(),
                        serie=row[4].strip(),
                        area=row[5].strip(),
                        responsable=row[6].strip(),
                        ultima_mantencion=row[7].strip(),
                        frecuencia_mantencion=row[8].strip(),
                        proxima_mantencion=row[9].strip(),
                        alerta=row[10].strip(),
                        requerimiento=row[11].strip(),
                        tipo_mantencion=row[12].strip(),
                        estado=row[13].strip(),
                        ficha=row[14].strip()
                    )
                    
                    db.session.add(equipo)
                    contador += 1
                
                print(f"Importando {contador} registros...")
                db.session.commit()
                print("¡Importación exitosa!")
                
        except Exception as e:
            print(f"Error durante la importación: {e}")
            db.session.rollback()

if __name__ == '__main__':
    importar()
