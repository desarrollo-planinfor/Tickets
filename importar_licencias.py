"""
Script para importar / poblar las licencias iniciales en la base de datos (Producción o Local).
Ejecución: python importar_licencias.py
"""

from app import app, db, Licencia
import datetime as _dt

def importar():
    with app.app_context():
        # Crear tablas si aún no existen
        db.create_all()

        cant_existente = Licencia.query.count()
        print(f"Licencias actualmente en la base de datos: {cant_existente}")

        if cant_existente > 0:
            respuesta = input("⚠️ Ya existen licencias en la BD. ¿Deseas agregar las licencias iniciales de todas formas? (s/n): ")
            if respuesta.lower() != 's':
                print("Operación cancelada.")
                return

        licencias_iniciales = [
            # SSL
            Licencia(
                nombre_servicio='portal.planinfor.cl',
                tipo='SSL',
                proveedor='Don Web',
                fecha_inicio=_dt.date(2026, 12, 21),
                fecha_expiracion=_dt.date(2027, 12, 21),
                responsable='Jorge Rodriguez',
                renovacion_automatica=False,
                estado='Activo',
                observaciones=''
            ),
            Licencia(
                nombre_servicio='planinfor.cl',
                tipo='SSL',
                proveedor='Don Web',
                fecha_inicio=_dt.date(2026, 5, 28),
                fecha_expiracion=_dt.date(2027, 5, 28),
                responsable='Jorge Rodriguez',
                renovacion_automatica=False,
                estado='Activo',
                observaciones=''
            ),
            # Software
            Licencia(
                nombre_servicio='DJI Terra 1 año',
                tipo='Software',
                proveedor='DJI',
                cantidad=1,
                responsable='Equipos Silvicultura (3)',
                fecha_inicio=_dt.date(2026, 1, 13),
                fecha_expiracion=_dt.date(2027, 1, 13),
                estado='Activo',
                observaciones='Una licencia para 3 equipos. (Tipo: Agricultura)'
            ),
            Licencia(
                nombre_servicio='DJI Terra 1 año',
                tipo='Software',
                proveedor='DJI',
                cantidad=1,
                responsable='Geomática',
                fecha_inicio=_dt.date(2025, 11, 11),
                fecha_expiracion=_dt.date(2026, 11, 11),
                estado='Activo',
                observaciones='Tipo: Standard'
            ),
            Licencia(
                nombre_servicio='Terrain Forestry',
                tipo='Software',
                proveedor='Softree',
                cantidad=4,
                responsable='Trazado',
                fecha_inicio=_dt.date(2026, 1, 28),
                fecha_expiracion=_dt.date(2027, 1, 31),
                estado='Activo',
                observaciones='Fecha de expiración corresponde a soporte. Licencias de red.'
            ),
            Licencia(
                nombre_servicio='Roadeng',
                tipo='Software',
                proveedor='Softree',
                cantidad=5,
                responsable='Trazado',
                fecha_inicio=_dt.date(2026, 1, 28),
                fecha_expiracion=_dt.date(2027, 1, 31),
                estado='Activo',
                observaciones='Fecha de expiración corresponde a soporte. Licencias de red.'
            ),
            # SaaS Microsoft
            Licencia(
                nombre_servicio='Aplicaciones de Microsoft 365 para negocios',
                tipo='SaaS',
                proveedor='Microsoft',
                cantidad=52,
                responsable='TI',
                fecha_inicio=None,
                fecha_expiracion=_dt.date(2026, 8, 21),
                renovacion_automatica=True,
                estado='Activo',
                observaciones='Licencia SaaS - Renovación Mensual (día 21)'
            ),
            Licencia(
                nombre_servicio='Power BI Pro',
                tipo='SaaS',
                proveedor='Microsoft',
                cantidad=7,
                responsable='TI',
                fecha_inicio=None,
                fecha_expiracion=_dt.date(2026, 8, 21),
                renovacion_automatica=True,
                estado='Activo',
                observaciones='Licencia SaaS - Renovación Mensual (día 21)'
            ),
            Licencia(
                nombre_servicio='Planner Plan 1',
                tipo='SaaS',
                proveedor='Microsoft',
                cantidad=1,
                responsable='TI',
                fecha_inicio=None,
                fecha_expiracion=_dt.date(2026, 8, 21),
                renovacion_automatica=True,
                estado='Activo',
                observaciones='Licencia SaaS - Renovación Mensual (día 21)'
            ),
            Licencia(
                nombre_servicio='Salas de Microsoft Teams Básico',
                tipo='SaaS',
                proveedor='Microsoft',
                cantidad=25,
                responsable='TI',
                fecha_inicio=None,
                fecha_expiracion=_dt.date(2026, 8, 21),
                renovacion_automatica=True,
                estado='Activo',
                observaciones='Licencia SaaS - Renovación Mensual (día 21)'
            )
        ]

        db.session.add_all(licencias_iniciales)
        db.session.commit()
        print(f"✅ ¡Se han importado exitosamente {len(licencias_iniciales)} licencias en la base de datos!")

if __name__ == '__main__':
    importar()
