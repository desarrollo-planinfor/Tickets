"""
Sistema de Gestión de Tickets de Soporte
Flask Application - Planinfor
"""
import sys
# Alias para evitar inicialización doble cuando se ejecuta como `python app.py` y luego se importa
sys.modules['app'] = sys.modules[__name__]

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, g
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from functools import wraps
from waitress import serve
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from werkzeug.security import generate_password_hash, check_password_hash
from cron_jobs import iniciar_scheduler

# Cargar variables de entorno
load_dotenv()

# Forzar codificación UTF-8 para evitar errores con psycopg2 en Windows
os.environ['PGCLIENTENCODING'] = 'utf-8'

def asegurar_base_de_datos():
    """Verifica si la base de datos existe, si no, intenta crearla"""
    db_url = os.getenv('DATABASE_URL')
    if not db_url or not db_url.startswith('postgresql'):
        return

    db_name = 'tickets_db'
    db_user = 'postgres'
    db_password = 'admin123'
    db_host = 'localhost'
    db_port = '5432'

    try:
        # Intentar conectar a la base de datos específica
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        conn.close()
    except Exception as e:
        # Si hay un error de decodificación, es probable que sea porque la base de datos no existe
        # y el mensaje contiene caracteres especiales (« ») en codificación local.
        error_msg = str(e)
        if "does not exist" in error_msg or "no existe" in error_msg or "utf-8" in error_msg:
            try:
                print(f"La base de datos '{db_name}' no existe o no se pudo conectar. Intentando crearla...")
                # Conectar a la base de datos predeterminada 'postgres'
                conn = psycopg2.connect(
                    dbname='postgres',
                    user=db_user,
                    password=db_password,
                    host=db_host,
                    port=db_port
                )
                conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
                cur = conn.cursor()
                cur.execute(f'CREATE DATABASE "{db_name}"')
                cur.close()
                conn.close()
                print(f"Base de datos '{db_name}' creada exitosamente.")
            except Exception as create_e:
                print(f"No se pudo crear la base de datos automáticamente: {create_e}")
        else:
            print(f"Error de conexión a PostgreSQL: {e}")

def calcular_minutos_habiles(inicio, fin):
    from utils import calcular_minutos_habiles as _calc
    return _calc(inicio, fin)

app = Flask(__name__, template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates')))
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fallback-key-only-for-dev')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

# ==================== CONFIGURACIÓN SMTP ====================
# Datos proporcionados por el usuario
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT', 25))
SMTP_USER = os.getenv('SMTP_USER')
SMTP_PASS = os.getenv('SMTP_PASS')
BASE_URL = os.getenv('BASE_URL')

from extensions import db
db.init_app(app)

from models import *


# ==================== INICIALIZACIÓN ====================

def crear_datos_iniciales():
    """Crear datos iniciales de prueba"""
    with app.app_context():
        try:
            db.create_all()
            from sqlalchemy import text
            try:
                db.session.execute(text("ALTER TABLE usuario ADD COLUMN area_id INTEGER"))
                db.session.execute(text("ALTER TABLE usuario ADD CONSTRAINT fk_usuario_area FOREIGN KEY(area_id) REFERENCES area(id)"))
                db.session.execute(text("ALTER TABLE usuario ADD COLUMN permisos TEXT DEFAULT '[]'"))
                db.session.commit()
            except Exception:
                db.session.rollback()
                
            # Poblar áreas iniciales (para usuarios)
            areas_iniciales = [
                "Trazado de Caminos", "Planificacion Silvicola", "Programacion de Cosecha",
                "Planificacion de Cosecha", "Topografia LIDAR"
            ]
            for nombre_area in areas_iniciales:
                if not Area.query.filter_by(nombre=nombre_area).first():
                    db.session.add(Area(nombre=nombre_area))

            # Poblar áreas de equipos (inventario)
            areas_equipo_iniciales = [
                "Desarrollo y Soporte TI",
                "Planificación Silvícola",
                "Administración",
                "Trazado de Caminos",
                "Planificación y Programación de Cosecha",
                "Geomática y Procesos SIG",
                "Control de Calidad de Producción de Plantas",
                "Gerencia",
                "Soporte IT y Desarrollo",
            ]
            for nombre_ae in areas_equipo_iniciales:
                if not AreaEquipo.query.filter_by(nombre=nombre_ae).first():
                    db.session.add(AreaEquipo(nombre=nombre_ae))
            db.session.commit()
        except Exception as e:
            print(f"⚠️ Error al crear tablas (posible problema de conexión): {e}")
            return
        
        # Crear usuario admin si no existe
        if not Usuario.query.filter_by(email='admin@planinfor.cl').first():
            admin = Usuario(
                nombre='Administrador',
                email='admin@planinfor.cl',
                password=generate_password_hash('admin123'),
                rol='admin'
            )
            db.session.add(admin)
        
        # Crear agente de prueba si no existe
        if not Usuario.query.filter_by(email='agente@planinfor.cl').first():
            agente = Usuario(
                nombre='Agente de Soporte',
                email='agente@planinfor.cl',
                password=generate_password_hash('agente123'),
                rol='agente'
            )
            db.session.add(agente)
        
        # Poblar licencias iniciales si no hay ninguna
        if Licencia.query.count() == 0:
            import datetime as _dt
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


from modulos.rutas_admin import admin_bp
from modulos.rutas_auth import auth_bp
from modulos.rutas_tickets import tickets_bp
from modulos.rutas_equipos import equipos_bp
from modulos.rutas_infra import infra_bp
from modulos.rutas_hallazgos import hallazgos_bp

app.register_blueprint(admin_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(tickets_bp)
app.register_blueprint(equipos_bp)
app.register_blueprint(infra_bp)
app.register_blueprint(hallazgos_bp, url_prefix='/eventos')

if __name__ == '__main__':
    asegurar_base_de_datos()
    crear_datos_iniciales()
    scheduler = iniciar_scheduler()
    
    try:
        print("Iniciando Sistema de Tickets...")
        is_debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
        app.run(host='127.0.0.1', port=5500, debug=is_debug, use_reloader=False)
    finally:
        if scheduler:
            print("Apagando el scheduler...")
            scheduler.shutdown()
