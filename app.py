"""
Sistema de Gestión de Tickets de Soporte
Flask Application - Planinfor
"""

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
    """
    Calcula la diferencia en minutos entre dos fechas,
    contando solo el horario hábil: Lunes a Viernes, de 08:30 a 17:30.
    """
    if not inicio or not fin:
        return 0
    if inicio > fin:
        inicio, fin = fin, inicio

    minutos = 0
    actual = inicio

    while actual < fin:
        # Si es fin de semana, saltar al lunes a las 08:30
        if actual.weekday() >= 5:
            dias_sumar = 7 - actual.weekday()
            actual = actual.replace(hour=8, minute=30, second=0, microsecond=0) + timedelta(days=dias_sumar)
            continue
            
        hora_float = actual.hour + actual.minute / 60.0
        
        # Si es antes de las 08:30, saltar a las 08:30 del mismo día
        if hora_float < 8.5:
            actual = actual.replace(hour=8, minute=30, second=0, microsecond=0)
            continue
            
        # Si es después de las 17:30, saltar a las 08:30 del día siguiente
        if hora_float >= 17.5:
            actual = (actual + timedelta(days=1)).replace(hour=8, minute=30, second=0, microsecond=0)
            continue
            
        # Estamos en horario hábil. Avanzar hasta el fin de la jornada o hasta la fecha 'fin'
        fin_jornada = actual.replace(hour=17, minute=30, second=0, microsecond=0)
        proximo_paso = min(fin, fin_jornada)
        
        diff = proximo_paso - actual
        minutos += diff.total_seconds() / 60.0
        
        actual = proximo_paso

    return int(minutos)

app = Flask(__name__, template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates')))
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'planinfor-ticket-system-secret-key-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://postgres:admin123@localhost:5432/tickets_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

# ==================== CONFIGURACIÓN SMTP ====================
# Datos proporcionados por el usuario
SMTP_SERVER = "mail.planinfor.cl"
SMTP_PORT = 25
SMTP_USER = "overseer.portal@planinfor.cl" 
SMTP_PASS = "Ed469618898d75b149e5c7c4b6a1c4"
BASE_URL = 'http://services.planinfor.cl:8080'

db = SQLAlchemy(app)

# ==================== AUTENTICACIÓN ====================

def login_required(f):
    """Decorator para rutas que requieren autenticación"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session:
            flash('Debe iniciar sesión para acceder a esta página', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def requiere_permiso(permiso):
    """Decorator para verificar si el usuario tiene un permiso específico"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not getattr(g, 'usuario', None):
                flash('Debe iniciar sesión.', 'error')
                return redirect(url_for('login'))
            if not g.usuario.tiene_permiso(permiso):
                flash('Acceso denegado. No tienes permisos para ver esta sección.', 'error')
                return redirect(url_for('mis_tickets'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.before_request
def load_user():
    """Cargar usuario en cada request"""
    g.usuario = None
    if 'usuario_id' in session:
        usuario = db.session.get(Usuario, session['usuario_id'])
        if usuario and not usuario.activo:
            session.clear()
            g.usuario = None
            flash('Su cuenta ha sido desactivada. Sesión cerrada.', 'error')
        else:
            g.usuario = usuario

# ==================== MODELOS DE BASE DE DATOS ====================

class Area(db.Model):
    """Modelo de Área (para usuarios)"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)

class AreaEquipo(db.Model):
    """Modelo de Área para Equipos (inventario)"""
    __tablename__ = 'area_equipo'
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False, unique=True)

class Usuario(db.Model):
    """Modelo de Usuario del sistema"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)  # Contraseña hasheada
    rol = db.Column(db.String(20), default='cliente')  # cliente, agente, admin
    activo = db.Column(db.Boolean, default=True)
    
    # Nuevos campos
    area_id = db.Column(db.Integer, db.ForeignKey('area.id'), nullable=True)
    area = db.relationship('Area', backref='usuarios', lazy=True)
    permisos = db.Column(db.Text, default='[]')
    
    tickets = db.relationship('Ticket', foreign_keys='Ticket.usuario_id', backref='usuario', lazy=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def tiene_permiso(self, permiso):
        if self.rol == 'admin':
            return True
        import json
        try:
            lista_permisos = json.loads(self.permisos) if self.permisos else []
            return permiso in lista_permisos
        except:
            return False

class Ticket(db.Model):
    """Modelo principal de Ticket"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    
    # Datos del ticket
    asunto = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    categoria = db.Column(db.String(50), default='general')
    prioridad = db.Column(db.String(20), default='Media')
    departamento = db.Column(db.String(50), default='soporte')
    
    # Estados: PENDIENTE, RECIBIDO, EN_PROCESO, RESUELTO, CERRADO, ATRASADO
    estado = db.Column(db.String(20), default='PENDIENTE')
    
    # Fechas principales
    fecha_creacion = db.Column(db.DateTime, default=datetime.now)
    fecha_recepcion = db.Column(db.DateTime, nullable=True)
    fecha_atencion_programada = db.Column(db.DateTime, nullable=True)
    fecha_inicio_atencion = db.Column(db.DateTime, nullable=True)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    
    # Tiempos calculados
    tiempo_respuesta = db.Column(db.Integer, nullable=True)  # minutos
    tiempo_resolucion = db.Column(db.Integer, nullable=True)  # minutos
    tiempo_estimado = db.Column(db.Integer, nullable=True)  # minutos
    
    # Asignación
    tecnico_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    tecnico = db.relationship('Usuario', foreign_keys=[tecnico_id])
    
    # Notas
    notas = db.Column(db.Text, nullable=True)
    
    # Logs de tiempo
    logs = db.relationship('TicketLog', backref='ticket', lazy=True)
    
    def tiempo_transcurrido_creacion(self):
        """Calcula tiempo transcurrido desde creación"""
        if self.fecha_creacion:
            return datetime.now() - self.fecha_creacion
        return None

    def get_tiempo_restante_sla(self):
        """Calcula el tiempo restante para la atención programada"""
        if self.fecha_atencion_programada and self.estado != 'CERRADO':
            ahora = datetime.now()
            if ahora < self.fecha_atencion_programada:
                diff = self.fecha_atencion_programada - ahora
                horas = diff.seconds // 3600
                minutos = (diff.seconds % 3600) // 60
                if diff.days > 0:
                    return f"{diff.days}d {horas}h restantes"
                return f"{horas}h {minutos}m restantes"
            else:
                return "Vencido"
        return None
    
    def tiempo_transcurrido_atencion(self):
        """Calcula tiempo transcurrido desde atención programada"""
        if self.fecha_atencion_programada:
            return datetime.now() - self.fecha_atencion_programada
        return None

@app.route('/favicon.ico')
def favicon():
    return send_file('static/P.ico', mimetype='image/x-icon')

@app.route('/tickets/todos')
@login_required
def todos_tickets():
    """Ver todos los tickets con paginación (Agentes, Admin, o permisos de área)"""
    if g.usuario.rol == 'cliente' and not g.usuario.tiene_permiso('ver_tickets_area'):
        flash('Acceso denegado.', 'error')
        return redirect(url_for('mis_tickets'))
        
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    
    query = Ticket.query.join(Usuario, Ticket.usuario_id == Usuario.id)
    
    # Filtro de área si no es admin ni agente (es un usuario con permiso de área)
    if g.usuario.rol not in ['admin', 'agente']:
        if g.usuario.area_id:
            query = query.filter(Usuario.area_id == g.usuario.area_id)
        else:
            query = query.filter(Usuario.id == -1) # No tiene área, no ve tickets de otros
    
    if search_query:
        query = query.filter(Usuario.nombre.ilike(f'%{search_query}%'))
        
    tickets_paginados = query.order_by(Ticket.fecha_creacion.desc()).paginate(page=page, per_page=15, error_out=False)
    
    return render_template('todos_tickets.html', tickets_paginados=tickets_paginados, search_query=search_query)

class TicketLog(db.Model):
    """Modelo para auditoría de cambios de estado"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    estado_anterior = db.Column(db.String(20), nullable=True)
    estado_nuevo = db.Column(db.String(20), nullable=False)
    descripcion = db.Column(db.Text)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    fecha_cambio = db.Column(db.DateTime, default=datetime.now)
    usuario = db.relationship('Usuario')


class TicketAdjunto(db.Model):
    """Archivos adjuntos para tickets"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    nombre_archivo = db.Column(db.String(255), nullable=False)
    ruta_archivo = db.Column(db.String(255), nullable=False)
    fecha_subida = db.Column(db.DateTime, default=datetime.now)
    
    usuario = db.relationship('Usuario')
    ticket = db.relationship('Ticket', backref=db.backref('adjuntos', lazy=True))

class Notificacion(db.Model):
    """Modelo de notificaciones del sistema"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=True)
    destinatario = db.Column(db.String(120), nullable=False)
    asunto = db.Column(db.String(200), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(20), default='email')  # email, slack, sistema
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, enviada, fallida
    fecha_creacion = db.Column(db.DateTime, default=datetime.now)
    fecha_envio = db.Column(db.DateTime, nullable=True)

class EquipoMantencion(db.Model):
    """Modelo de Equipos y Mantenciones (Inventario)"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=True) # ID original del Excel
    nombre = db.Column(db.String(200), nullable=True)
    marca = db.Column(db.String(100), nullable=True)
    modelo = db.Column(db.String(100), nullable=True)
    serie = db.Column(db.String(100), nullable=True)
    area = db.Column(db.String(100), nullable=True)
    responsable = db.Column(db.String(100), nullable=True)
    ultima_mantencion = db.Column(db.String(50), nullable=True)
    frecuencia_mantencion = db.Column(db.String(100), nullable=True)
    proxima_mantencion = db.Column(db.String(50), nullable=True)
    alerta = db.Column(db.String(50), nullable=True)
    requerimiento = db.Column(db.String(100), nullable=True)
    tipo_mantencion = db.Column(db.String(100), nullable=True)
    estado = db.Column(db.String(100), nullable=True)
    ficha = db.Column(db.String(255), nullable=True)
    historial = db.relationship('HistorialMantencion', backref='equipo', lazy='dynamic', cascade='all, delete-orphan')
    historial_responsables = db.relationship('HistorialResponsable', backref='equipo', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def estado_alerta(self):
        import datetime as _dt
        if not self.proxima_mantencion:
            return 'Gris'
        try:
            fecha_prox = _dt.datetime.strptime(self.proxima_mantencion, '%d/%m/%Y').date()
            hoy = _dt.date.today()
            dias_restantes = (fecha_prox - hoy).days
            
            if dias_restantes < 0:
                return 'Rojo'
            elif dias_restantes <= 30:
                return 'Amarillo'
            else:
                return 'Verde'
        except Exception:
            return 'Gris'

class HistorialMantencion(db.Model):
    """Registro histórico de mantenciones realizadas a un equipo"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    equipo_id = db.Column(db.Integer, db.ForeignKey('equipo_mantencion.id'), nullable=False)
    fecha_realizada = db.Column(db.DateTime, default=datetime.now)
    tecnico = db.Column(db.String(150), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    tipo = db.Column(db.String(100), nullable=True)  # Preventiva, Correctiva, etc.
    registrado_por = db.Column(db.String(150), nullable=True)

class HistorialResponsable(db.Model):
    """Registro histórico de responsables de un equipo"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    equipo_id = db.Column(db.Integer, db.ForeignKey('equipo_mantencion.id'), nullable=False)
    responsable = db.Column(db.String(150), nullable=False)
    fecha_inicio = db.Column(db.DateTime, default=datetime.now, nullable=False)
    fecha_fin = db.Column(db.DateTime, nullable=True)

class Licencia(db.Model):
    """Modelo para Gestión de Licencias (SSL, Software, SaaS)"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    nombre_servicio = db.Column(db.String(200), nullable=False)
    tipo = db.Column(db.String(50), nullable=False) # 'SSL', 'Software', 'SaaS'
    proveedor = db.Column(db.String(150), nullable=True)
    cantidad = db.Column(db.Integer, nullable=True)
    responsable = db.Column(db.String(150), nullable=True)
    fecha_inicio = db.Column(db.Date, nullable=True) # Emisión/Compra
    fecha_expiracion = db.Column(db.Date, nullable=False) # Expiración/Renovación
    renovacion_automatica = db.Column(db.Boolean, default=False)
    estado = db.Column(db.String(50), default='Activo')
    observaciones = db.Column(db.Text, nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.now)

    @property
    def dias_restantes(self):
        import datetime as _dt
        hoy = _dt.date.today()
        if self.fecha_expiracion:
            return (self.fecha_expiracion - hoy).days
        return 0
        
    @property
    def estado_alerta(self):
        dias = self.dias_restantes
        if dias < 0:
            return 'Rojo'
        elif dias <= 30:
            return 'Amarillo'
        else:
            return 'Verde'

# ==================== RUTAS DE LA APLICACIÓN ====================

@app.route('/')
def index():
    """Página principal - Redirecciona según rol"""
    if 'usuario_id' in session:
        usuario = db.session.get(Usuario, session['usuario_id'])
        if usuario and usuario.rol == 'admin':
            return redirect(url_for('panel_admin'))
        elif usuario and usuario.rol == 'agente':
            return redirect(url_for('panel_agente'))
        elif usuario and usuario.rol == 'cliente':
            return redirect(url_for('mis_tickets'))
    return redirect(url_for('login'))

# ---------- AUTENTICACIÓN ----------

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Verificar credenciales de admin (bypass inicial si no hay DB o para primer login)
        if email == 'admin@planinfor.cl' and password == 'admin123':
            admin = Usuario.query.filter_by(email='admin@planinfor.cl').first()
            if not admin:
                admin = Usuario(
                    nombre='Administrador',
                    email='admin@planinfor.cl',
                    password=generate_password_hash('admin123'),
                    rol='admin'
                )
                db.session.add(admin)
                db.session.commit()
            
            # Si el admin existe pero la clave es plana, permitir login y actualizar
            if admin and (admin.password == 'admin123' or check_password_hash(admin.password, 'admin123')):
                if admin.password == 'admin123':
                    admin.password = generate_password_hash('admin123')
                    db.session.commit()
                session['usuario_id'] = admin.id
                flash('Bienvenido Administrador', 'success')
                return redirect(url_for('panel_admin'))
        
        # Verificar usuario normal
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario:
            # Soporte para claves planas (migración transparente) o hasheadas
            if usuario.password == password or check_password_hash(usuario.password, password):
                if not usuario.activo:
                    flash('Su cuenta está desactivada. Contacte al administrador.', 'error')
                    return redirect(url_for('login'))
                
                # Si la clave era plana, actualizarla a hash ahora mismo
                if usuario.password == password:
                    usuario.password = generate_password_hash(password)
                    db.session.commit()
                    
                session['usuario_id'] = usuario.id
                if usuario.rol == 'admin':
                    return redirect(url_for('panel_admin'))
                elif usuario.rol == 'agente':
                    return redirect(url_for('panel_agente'))
                else:
                    return redirect(url_for('mis_tickets'))
        
        flash('Credenciales incorrectas', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Cerrar sesión"""
    session.clear()
    flash('Sesión cerrada correctamente', 'success')
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    """Registro de nuevos usuarios (clientes)"""
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validaciones
        if password != confirm_password:
            flash('Las contraseñas no coinciden', 'error')
            return redirect(url_for('registro'))
        
        # Verificar si el email ya existe
        if Usuario.query.filter_by(email=email).first():
            flash('El correo electrónico ya está registrado', 'error')
            return redirect(url_for('registro'))
        
        # Validar correo corporativo (contiene @planinfor o similar)
        if 'planinfor' not in email.lower():
            flash('Debe usar un correo corporativo de Planinfor', 'error')
            return redirect(url_for('registro'))
        
        # Crear usuario con clave hasheada
        usuario = Usuario(
            nombre=nombre,
            email=email,
            password=generate_password_hash(password),
            rol='cliente'
        )
        db.session.add(usuario)
        db.session.commit()
        
        flash('Cuenta creada exitosamente. Ahora puede iniciar sesión.', 'success')
        return redirect(url_for('login'))
    
    return render_template('registro.html')

# ---------- PORTAL CLIENTE ----------

@app.route('/portal')
@login_required
def portal_cliente():
    """Portal del cliente para crear tickets"""
    return render_template('portal_cliente.html')

@app.route('/portal/crear', methods=['POST'])
@login_required
def crear_ticket():
    """Crear nuevo ticket desde portal cliente"""
    try:
        usuario = g.usuario
        asunto = request.form.get('asunto')
        descripcion = request.form.get('descripcion')
        categoria = request.form.get('categoria', 'general')
        prioridad = 'Media'  # Solo modificable por admin, default Media
        departamento = 'soporte' # Default soporte
        
        ticket = Ticket(
            usuario_id=usuario.id,
            asunto=asunto,
            descripcion=descripcion,
            categoria=categoria,
            prioridad=prioridad,
            departamento=departamento,
            estado='PENDIENTE'
        )
        db.session.add(ticket)
        
        # Crear log inicial
        log = TicketLog(
            ticket_id=None,  # Se actualiza después
            estado_nuevo='PENDIENTE',
            descripcion='Ticket creado por el cliente',
            usuario_id=usuario.id
        )
        
        # Commit para obtener IDs
        db.session.flush()
        log.ticket_id = ticket.id
        db.session.commit()
        
        # Crear notificación de confirmación al cliente (eliminada a petición)
        # Solo dejaremos la alerta a soporte TI
        
        # Alerta para el equipo de soporte TI
        alerta_ti = Notificacion(
            ticket_id=ticket.id,
            destinatario='soporte.ti@planinfor.cl',
            asunto=f'[Soporte TI] Nuevo Ticket #{ticket.id} - {asunto}',
            mensaje=email_nuevo_ticket(ticket.id, asunto, descripcion, categoria, usuario.nombre, usuario.email),
            tipo='email'
        )
        db.session.add(alerta_ti)
        
        db.session.commit()
        
        flash(f'Ticket #{ticket.id} creado exitosamente. Te enviaremos una notificación cuando sea atendido.', 'success')
        return redirect(url_for('portal_cliente'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al crear ticket: {str(e)}', 'error')
        return redirect(url_for('portal_cliente'))


@app.route('/portal/mis-tickets')
@login_required
def mis_tickets():
    """Ver tickets del cliente (requiere login)"""
    usuario = g.usuario
    tickets = Ticket.query.filter_by(usuario_id=usuario.id).order_by(Ticket.fecha_creacion.desc()).all()
    return render_template('mis_tickets.html', tickets=tickets, usuario=usuario)

@app.route('/mis-tickets')
@login_required
def mis_tickets_alt():
    """Ver tickets del cliente - ruta alternativa"""
    return redirect(url_for('mis_tickets'))

# ---------- PANEL DE AGENTE ----------

@app.route('/agente')
@login_required
def panel_agente():
    """Dashboard del agente con semáforo de prioridades"""
    # Tickets pendientes sin hora de atención o atrasados (ROJO)
    tickets_rojos = Ticket.query.filter(
        Ticket.estado.in_(['PENDIENTE', 'ATRASADO'])
    ).order_by(Ticket.fecha_creacion.asc()).all()
    
    # Tickets recibidos con hora de atención programada (AMARILLO)
    tickets_amarillos = Ticket.query.filter(
        Ticket.estado == 'RECIBIDO'
    ).order_by(Ticket.fecha_atencion_programada.asc()).all()
    
    # Tickets en proceso (VERDE)
    tickets_verdes = Ticket.query.filter(
        Ticket.estado == 'EN_PROCESO'
    ).order_by(Ticket.fecha_inicio_atencion.asc()).all()
    
    # Tickets cerrados recientemente
    tickets_cerrados = Ticket.query.filter(
        Ticket.estado.in_(['RESUELTO', 'CERRADO'])
    ).order_by(Ticket.fecha_cierre.desc()).limit(10).all()
    
    # Estadísticas
    stats = {
        'total': Ticket.query.count(),
        'pendientes': Ticket.query.filter(Ticket.estado.in_(['PENDIENTE', 'ATRASADO'])).count(),
        'en_proceso': Ticket.query.filter(Ticket.estado.in_(['RECIBIDO', 'EN_PROCESO'])).count(),
        'cerrados': Ticket.query.filter(Ticket.estado.in_(['RESUELTO', 'CERRADO'])).count()
    }
    
    return render_template('panel_agente.html', 
                         tickets_rojos=tickets_rojos,
                         tickets_amarillos=tickets_amarillos,
                         tickets_verdes=tickets_verdes,
                         tickets_cerrados=tickets_cerrados,
                         stats=stats)

@app.route('/perfil/password', methods=['GET', 'POST'])
@login_required
def cambiar_password():
    """Permitir que el usuario cambie su propia contraseña"""
    if request.method == 'POST':
        actual = request.form.get('password_actual')
        nueva = request.form.get('nueva_password')
        confirmar = request.form.get('confirmar_password')
        
        usuario = g.usuario
        
        # Verificar clave actual
        if not check_password_hash(usuario.password, actual) and usuario.password != actual:
            flash('La contraseña actual es incorrecta', 'error')
            return redirect(url_for('cambiar_password'))
            
        if nueva != confirmar:
            flash('La nueva contraseña y la confirmación no coinciden', 'error')
            return redirect(url_for('cambiar_password'))
            
        if len(nueva) < 6:
            flash('La nueva contraseña debe tener al menos 6 caracteres', 'error')
            return redirect(url_for('cambiar_password'))
            
        # Actualizar a hash
        usuario.password = generate_password_hash(nueva)
        db.session.commit()
        
        flash('Contraseña actualizada correctamente', 'success')
        if usuario.rol == 'admin':
            return redirect(url_for('panel_admin'))
        elif usuario.rol == 'agente':
            return redirect(url_for('panel_agente'))
        else:
            return redirect(url_for('mis_tickets'))
            
    return render_template('cambiar_password.html')

@app.route('/agente/recibir/<int:ticket_id>', methods=['POST'])
@login_required
def recibir_ticket(ticket_id):
    """Admin/Agente marca ticket como recibido y asigna hora de atención"""
    try:
        hora_atencion = request.form.get('hora_atencion')
        nueva_prioridad = request.form.get('prioridad')
        nuevo_departamento = request.form.get('departamento')
        
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            flash('Ticket no encontrado', 'error')
            return redirect(url_for('panel_agente'))
        
        ticket.estado = 'RECIBIDO'
        ticket.fecha_recepcion = datetime.now()
        
        if hora_atencion:
            # Convertir hora string a datetime
            fecha_at = datetime.strptime(hora_atencion, '%d/%m/%Y %H:%M')
            ticket.fecha_atencion_programada = fecha_at
            
        if nueva_prioridad:
            ticket.prioridad = nueva_prioridad
        if nuevo_departamento:
            ticket.departamento = nuevo_departamento
        
        # Log de cambio
        log = TicketLog(
            ticket_id=ticket.id,
            estado_anterior='PENDIENTE',
            estado_nuevo='RECIBIDO',
            descripcion=f'Ticket recibido. Hora de atención programada: {hora_atencion}'
        )
        db.session.add(log)
        db.session.commit()
        
        # Notificar al equipo de TI
        nombre_usuario = ticket.usuario.nombre if ticket.usuario else 'Desconocido'
        notificacion = Notificacion(
            ticket_id=ticket.id,
            destinatario='soporte.ti@planinfor.cl',
            asunto=f'[Soporte TI] Ticket #{ticket.id} Aceptado - Atención Programada',
            mensaje=email_ticket_recibido(ticket.id, ticket.asunto, nombre_usuario, hora_atencion),
            tipo='email'
        )
        db.session.add(notificacion)
        db.session.commit()
        
        flash(f'Ticket #{ticket_id} marcado como recibido', 'success')
        return redirect(url_for('panel_agente'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('panel_agente'))

@app.route('/agente/atender/<int:ticket_id>')
@login_required
def atender_ticket(ticket_id):
    """Técnico inicia atención del ticket"""
    try:
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            flash('Ticket no encontrado', 'error')
            return redirect(url_for('panel_agente'))
        
        ticket.estado = 'EN_PROCESO'
        ticket.fecha_inicio_atencion = datetime.now()
        ticket.tecnico_id = g.usuario.id  # Asignar técnico que atiende
        
        # Calcular tiempo de respuesta
        if ticket.fecha_creacion:
            ticket.tiempo_respuesta = calcular_minutos_habiles(ticket.fecha_creacion, ticket.fecha_inicio_atencion)
        
        log = TicketLog(
            ticket_id=ticket.id,
            usuario_id=g.usuario.id,
            estado_anterior='RECIBIDO',
            estado_nuevo='EN_PROCESO',
            descripcion=f'Atención iniciada por {g.usuario.nombre}'
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f'Ticket #{ticket_id} en proceso', 'success')
        return redirect(url_for('panel_agente'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('panel_agente'))

@app.route('/agente/cerrar/<int:ticket_id>', methods=['POST'])
@login_required
def cerrar_ticket(ticket_id):
    """Cerrar ticket (inmediato o con estimación)"""
    try:
        tipo_cierre = request.form.get('tipo_cierre')  # inmediato, estimado
        notas = request.form.get('notas', '')
        
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            flash('Ticket no encontrado', 'error')
            return redirect(url_for('panel_agente'))
        
        ticket.fecha_cierre = datetime.now()
        ticket.notas = notas
        
        if tipo_cierre == 'inmediato':
            ticket.estado = 'CERRADO'
            estado_final = 'CERRADO'
        else:
            # Con estimación - queda en proceso
            tiempo_estimado = request.form.get('tiempo_estimado', 60)
            ticket.tiempo_estimado = int(tiempo_estimado)
            ticket.estado = 'EN_PROCESO'
            estado_final = 'EN_PROCESO (Con estimación)'
        
        # Calcular tiempo de resolución
        if ticket.fecha_inicio_atencion:
            ticket.tiempo_resolucion = calcular_minutos_habiles(ticket.fecha_inicio_atencion, ticket.fecha_cierre)
        
        log = TicketLog(
            ticket_id=ticket.id,
            estado_anterior='EN_PROCESO',
            estado_nuevo=estado_final,
            descripcion=f'Ticket cerrado. Notas: {notas}'
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f'Ticket #{ticket_id} cerrado', 'success')
        return redirect(url_for('panel_agente'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
        return redirect(url_for('panel_agente'))

import uuid
from werkzeug.utils import secure_filename

@app.route('/ticket/<int:ticket_id>/adjuntar', methods=['POST'])
@login_required
def adjuntar_archivo(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket no encontrado', 'error')
        return redirect(url_for('mis_tickets'))
        
    if g.usuario.rol == 'cliente' and ticket.usuario_id != g.usuario.id:
        flash('No tienes autorización', 'error')
        return redirect(url_for('mis_tickets'))
        
    if 'archivo' not in request.files:
        flash('No se seleccionó ningún archivo', 'error')
        return redirect(url_for('ver_ticket', ticket_id=ticket.id))
        
    archivo = request.files['archivo']
    if archivo.filename == '':
        flash('No se seleccionó ningún archivo', 'error')
        return redirect(url_for('ver_ticket', ticket_id=ticket.id))
        
    if archivo:
        filename = secure_filename(archivo.filename)
        # Generate unique name
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        upload_folder = os.path.join(app.root_path, 'static', 'uploads', 'adjuntos')
        os.makedirs(upload_folder, exist_ok=True)
        
        file_path = os.path.join(upload_folder, unique_filename)
        archivo.save(file_path)
        
        adjunto = TicketAdjunto(
            ticket_id=ticket.id,
            usuario_id=g.usuario.id,
            nombre_archivo=filename,
            ruta_archivo=f"uploads/adjuntos/{unique_filename}"
        )
        db.session.add(adjunto)
        
        # Agregar log
        log = TicketLog(
            ticket_id=ticket.id,
            estado_anterior=ticket.estado,
            estado_nuevo=ticket.estado,
            descripcion=f"Archivo adjuntado: {filename}",
            usuario_id=g.usuario.id
        )
        db.session.add(log)
        
        db.session.commit()
        flash('Archivo adjuntado exitosamente', 'success')
        
    return redirect(url_for('ver_ticket', ticket_id=ticket.id))

@app.route('/ticket/<int:ticket_id>')
@login_required
def ver_ticket(ticket_id):
    """Ver detalles de un ticket (Universal para cliente, agente y admin)"""
    ticket = Ticket.query.get_or_404(ticket_id)
    
    # Seguridad: Si es cliente, solo puede ver sus propios tickets
    if g.usuario.rol == 'cliente' and ticket.usuario_id != g.usuario.id:
        flash('No tienes autorización para ver este ticket.', 'error')
        return redirect(url_for('mis_tickets'))
    
    # Obtener historial de cambios
    logs = TicketLog.query.filter_by(ticket_id=ticket_id).order_by(TicketLog.fecha_cambio.asc()).all()
    
    return render_template('ver_ticket.html', ticket=ticket, logs=logs)

@app.route('/admin/ticket/actualizar_campos/<int:ticket_id>', methods=['POST'])
@login_required
def actualizar_campos_ticket(ticket_id):
    """Admin actualiza prioridad y departamento del ticket"""
    if g.usuario.rol != 'admin':
        flash('Acceso denegado. Solo administradores pueden realizar esta acción.', 'error')
        return redirect(url_for('ver_ticket', ticket_id=ticket_id))
        
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket no encontrado', 'error')
        return redirect(url_for('panel_admin'))
        
    try:
        nueva_prioridad = request.form.get('prioridad')
        nuevo_departamento = request.form.get('departamento')
        
        cambios = []
        if nueva_prioridad and nueva_prioridad != ticket.prioridad:
            cambios.append(f"Prioridad: {ticket.prioridad} -> {nueva_prioridad}")
            ticket.prioridad = nueva_prioridad
            
        if nuevo_departamento and nuevo_departamento != ticket.departamento:
            cambios.append(f"Departamento: {ticket.departamento} -> {nuevo_departamento}")
            ticket.departamento = nuevo_departamento
            
        if cambios:
            log = TicketLog(
                ticket_id=ticket.id,
                usuario_id=g.usuario.id,
                estado_nuevo=ticket.estado,
                descripcion="Actualización administrativa: " + " | ".join(cambios)
            )
            db.session.add(log)
            db.session.commit()
            flash('Campos actualizados correctamente', 'success')
        else:
            flash('No se realizaron cambios', 'info')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar: {str(e)}', 'error')
        
    return redirect(url_for('ver_ticket', ticket_id=ticket_id))

# ---------- GESTIÓN DE ESTADOS DE TICKET ----------

@app.route('/agente/aceptar/<int:ticket_id>')
@login_required
def aceptar_ticket(ticket_id):
    """Aceptar un ticket pendiente"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket no encontrado', 'error')
        return redirect(url_for('panel_agente'))
    
    try:
        # Cambiar estado a RECIBIDO
        estado_anterior = ticket.estado
        ticket.estado = 'RECIBIDO'
        ticket.fecha_recepcion = datetime.now()
        
        # Calcular tiempo de respuesta
        if ticket.fecha_creacion:
            ticket.tiempo_respuesta = calcular_minutos_habiles(ticket.fecha_creacion, ticket.fecha_recepcion)
        
        # Registrar log
        log = TicketLog(
            ticket_id=ticket.id,
            usuario_id=g.usuario.id,
            estado_nuevo='RECIBIDO',
            descripcion=f'Ticket aceptado por {g.usuario.nombre}'
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f'Ticket #{ticket_id} aceptado', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('ver_ticket', ticket_id=ticket_id))

@app.route('/agente/iniciar/<int:ticket_id>')
@login_required
def iniciar_ticket(ticket_id):
    """Iniciar trabajo en un ticket"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket no encontrado', 'error')
        return redirect(url_for('panel_agente'))
    
    try:
        ticket.estado = 'EN_PROCESO'
        ticket.fecha_inicio_atencion = datetime.now()
        ticket.tecnico_id = g.usuario.id
        
        # Registrar log
        log = TicketLog(
            ticket_id=ticket.id,
            usuario_id=g.usuario.id,
            estado_nuevo='EN_PROCESO',
            descripcion=f'Atención iniciada por {g.usuario.nombre}'
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f'Ticket #{ticket_id} en proceso', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('ver_ticket', ticket_id=ticket_id))

@app.route('/agente/pausar/<int:ticket_id>')
@login_required
def pausar_ticket(ticket_id):
    """Pausar un ticket en proceso"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket no encontrado', 'error')
        return redirect(url_for('panel_agente'))
    
    try:
        ticket.estado = 'PENDIENTE'
        
        # Registrar log
        log = TicketLog(
            ticket_id=ticket.id,
            usuario_id=g.usuario.id,
            estado_nuevo='PENDIENTE',
            descripcion=f'Ticket pausado por {g.usuario.nombre}'
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f'Ticket #{ticket_id} pausado', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('ver_ticket', ticket_id=ticket_id))

@app.route('/agente/reabrir/<int:ticket_id>')
@login_required
def reabrir_ticket(ticket_id):
    """Reabrir un ticket cerrado"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket no encontrado', 'error')
        return redirect(url_for('panel_agente'))
    
    try:
        ticket.estado = 'PENDIENTE'
        ticket.fecha_cierre = None
        ticket.notas = None
        
        # Registrar log
        log = TicketLog(
            ticket_id=ticket.id,
            usuario_id=g.usuario.id,
            estado_nuevo='PENDIENTE',
            descripcion=f'Ticket reopen by {g.usuario.nombre}'
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f'Ticket #{ticket_id} reopen', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('ver_ticket', ticket_id=ticket_id))

# ---------- PANEL DE ADMINISTRADOR ----------

@app.route('/admin')
@login_required
def panel_admin():
    """Panel de administración - solo para admin"""
    usuario = g.usuario
    if usuario.rol != 'admin':
        flash('Acceso denegado. Solo administradores.', 'error')
        if usuario.rol == 'agente':
            return redirect(url_for('panel_agente'))
        return redirect(url_for('mis_tickets'))
    
    # Estadísticas generales
    stats = {
        'total_tickets': Ticket.query.count(),
        'pendientes': Ticket.query.filter_by(estado='PENDIENTE').count(),
        'recibidos': Ticket.query.filter_by(estado='RECIBIDO').count(),
        'en_proceso': Ticket.query.filter(Ticket.estado.in_(['EN_PROCESO'])).count(),
        'cerrados': Ticket.query.filter(Ticket.estado.in_(['CERRADO', 'RESUELTO'])).count(),
        'atrasados': Ticket.query.filter_by(estado='ATRASADO').count(),
        'total_usuarios': Usuario.query.count(),
        'clientes': Usuario.query.filter_by(rol='cliente').count(),
        'agentes': Usuario.query.filter_by(rol='agente').count()
    }
    
    ultimos_tickets = Ticket.query.order_by(Ticket.fecha_creacion.desc()).limit(10).all()
    
    # Datos para Graficos
    from sqlalchemy import func
    tecnicos_stats = db.session.query(
        Usuario.nombre, func.count(Ticket.id)
    ).join(Ticket, Ticket.tecnico_id == Usuario.id).group_by(Usuario.nombre).all()
    chart_tecnicos = {'labels': [t[0] for t in tecnicos_stats], 'data': [t[1] for t in tecnicos_stats]}
    
    return render_template('panel_admin.html', stats=stats, ultimos_tickets=ultimos_tickets, chart_tecnicos=chart_tecnicos)

@app.route('/seguridad')
@login_required
def vista_seguridad():
    if g.usuario.rol != 'admin' and not g.usuario.tiene_permiso('ver_dashboard'):
        flash('Acceso denegado. Solo administradores o usuarios autorizados.', 'error')
        return redirect(url_for('panel_agente'))
    usuarios = Usuario.query.all()
    areas = Area.query.all()
    return render_template('seguridad.html', usuarios=usuarios, areas=areas)

@app.route('/admin/usuario/nuevo', methods=['POST'])
@login_required
def crear_usuario():
    """Crear nuevo usuario (admin)"""
    if g.usuario.rol != 'admin':
        flash('Acceso denegado', 'error')
        return redirect(url_for('vista_seguridad'))
    
    nombre = request.form.get('nombre')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    rol = request.form.get('rol')
    
    if password != confirm_password:
        flash('Las contraseñas no coinciden', 'error')
        return redirect(url_for('vista_seguridad'))
        
    if Usuario.query.filter_by(email=email).first():
        flash('El correo ya está registrado', 'error')
        return redirect(url_for('vista_seguridad'))
    
    import json
    
    area_id = request.form.get('area_id')
    nueva_area = request.form.get('nueva_area')
    if nueva_area:
        area_obj = Area(nombre=nueva_area)
        db.session.add(area_obj)
        db.session.flush()
        area_id = area_obj.id
    else:
        area_id = int(area_id) if area_id else None
        
    permisos = request.form.getlist('permisos')
    
    usuario = Usuario(
        nombre=nombre,
        email=email,
        password=generate_password_hash(password),
        rol=rol,
        area_id=area_id,
        permisos=json.dumps(permisos)
    )
    db.session.add(usuario)
    db.session.commit()
    
    flash(f'Usuario {nombre} creado exitosamente', 'success')
    return redirect(url_for('vista_seguridad'))

@app.route('/admin/usuario/toggle/<int:usuario_id>')
@login_required
def eliminar_usuario(usuario_id):
    """Desactivar/Activar usuario en lugar de eliminar para preservar historial"""
    if g.usuario.rol != 'admin' and not g.usuario.tiene_permiso('ver_seguridad'):
        flash('Acceso denegado. Solo administradores o usuarios autorizados.', 'error')
        return redirect(url_for('panel_admin'))
    
    usuario = db.session.get(Usuario, usuario_id)
    if usuario:
        if usuario.id == g.usuario.id:
            return jsonify({'status': 'error', 'message': 'No puedes desactivarte a ti mismo'}), 400
        else:
            usuario.activo = not usuario.activo
            db.session.commit()
            estado = "activado" if usuario.activo else "desactivado"
            return jsonify({
                'status': 'success', 
                'message': f'Usuario {usuario.nombre} ha sido {estado} correctamente',
                'nuevo_estado': usuario.activo
            })
    
    return jsonify({'status': 'error', 'message': 'Usuario no encontrado'}), 404

@app.route('/admin/usuario/editar/<int:usuario_id>', methods=['POST'])
@login_required
def editar_usuario(usuario_id):
    """Editar usuario (admin)"""
    if g.usuario.rol != 'admin':
        flash('Acceso denegado', 'error')
        return redirect(url_for('vista_seguridad'))
    
    usuario = db.session.get(Usuario, usuario_id)
    if usuario:
        usuario.nombre = request.form.get('nombre')
        nuevo_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        if nuevo_password:
            if nuevo_password != confirm_password:
                flash('Las contraseñas no coinciden', 'error')
                return redirect(url_for('vista_seguridad'))
            usuario.password = generate_password_hash(nuevo_password)
        if g.usuario.id != usuario.id:  # No cambiar rol, area ni permisos de uno mismo
            usuario.rol = request.form.get('rol')
            area_id = request.form.get('area_id')
            usuario.area_id = int(area_id) if area_id else None
            
            import json
            permisos = request.form.getlist('permisos')
            usuario.permisos = json.dumps(permisos)
            
        db.session.commit()
        flash('Usuario actualizado', 'success')
    
    return redirect(url_for('vista_seguridad'))

# ==================== API PARA CRON JOBS ====================

def _base_email_html(badge_color, badge_text, header_tag, filas_html, cuerpo_extra='', target_url=None):
    """Construye el esqueleto HTML compartido de todos los correos"""
    final_url = target_url if target_url else f"{BASE_URL}/agente"
    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin:0;padding:0;background-color:#f3f4f6;font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6;padding:30px 20px;">
            <tr><td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">

                    <!-- HEADER -->
                    <tr>
                        <td style="background-color:#111827;padding:24px 30px;border-bottom:4px solid #82C341;text-align:center;">
                            <span style="font-size:26px;font-weight:700;color:#ffffff;letter-spacing:-0.5px;">Plan<span style="color:#82C341;">infor</span></span>
                            <p style="margin:6px 0 0;font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Sistema de Soporte TI</p>
                        </td>
                    </tr>

                    <!-- BANNER TIPO -->
                    <tr>
                        <td style="background-color:{badge_color};padding:14px 30px;">
                            <span style="font-size:14px;font-weight:600;color:#ffffff;text-transform:uppercase;letter-spacing:0.5px;">{badge_text}</span>
                        </td>
                    </tr>

                    <!-- TITULO -->
                    <tr>
                        <td style="padding:28px 30px 10px;">
                            <h1 style="margin:0;font-size:20px;color:#111827;font-weight:600;">{header_tag}</h1>
                        </td>
                    </tr>

                    <!-- FILAS DE DATOS -->
                    <tr>
                        <td style="padding:10px 30px 20px;">
                            <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
                                {filas_html}
                            </table>
                        </td>
                    </tr>

                    {cuerpo_extra}

                    <!-- CTA BUTTON -->
                    <tr>
                        <td style="padding:10px 30px 30px;text-align:center;">
                            <a href="{final_url}"
                               style="display:inline-block;padding:13px 32px;background-color:#82C341;color:#111827;
                                      text-decoration:none;border-radius:8px;font-weight:700;font-size:15px;">&#9654; Ver Detalles del Ticket</a>
                        </td>
                    </tr>

                    <!-- FOOTER -->
                    <tr>
                        <td style="background-color:#f9fafb;padding:18px 30px;text-align:center;border-top:1px solid #e5e7eb;">
                            <p style="margin:0;font-size:12px;color:#9ca3af;">Este es un mensaje autom&#225;tico del <strong>Sistema de Gesti&#243;n de Tickets Planinfor</strong>.<br>Por favor no responda a este correo.</p>
                        </td>
                    </tr>

                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """

def _fila_dato(label, value, highlight=False):
    """Genera una fila de tabla para la tarjeta de datos del correo"""
    val_style = 'font-weight:600;color:#82C341;' if highlight else 'color:#374151;'
    return f"""
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:11px 16px;font-size:13px;color:#9ca3af;font-weight:500;width:38%;background:#f9fafb;">{label}</td>
            <td style="padding:11px 16px;font-size:14px;{val_style}">{value}</td>
        </tr>"""

def get_html_email_template(titulo, contenido):
    """Genera plantilla HTML generica para notificaciones simples (cron, alertas)"""
    filas = _fila_dato('Mensaje', contenido.replace('\n', ' | '))
    return _base_email_html('#4b5563', 'Notificaci&#243;n del Sistema', titulo, filas, target_url=f"{BASE_URL}/admin")

def email_nuevo_ticket(ticket_id, asunto, descripcion, categoria, nombre_usuario, email_usuario):
    """HTML para la notificacion de nuevo ticket creado"""
    filas = (
        _fila_dato('N&#250;mero de Ticket', f'#{ticket_id}', highlight=True) +
        _fila_dato('Asunto', asunto) +
        _fila_dato('Categor&#237;a', categoria.capitalize()) +
        _fila_dato('Solicitante', nombre_usuario) +
        _fila_dato('Correo', email_usuario) +
        _fila_dato('Descripci&#243;n', descripcion)
    )
    cuerpo_extra = """
    <tr><td style="padding:0 30px 10px;">
        <p style="margin:0;font-size:13px;color:#6b7280;line-height:1.6;">
            Un nuevo ticket de soporte ha sido creado y est&#225; en espera de ser asignado a un t&#233;cnico.
            Acceda al panel para revisarlo y programar una hora de atenci&#243;n.
        </p>
    </td></tr>
    """
    target_url = f"{BASE_URL}/ticket/{ticket_id}"
    return _base_email_html('#ef4444', '&#128276; Nuevo Ticket Recibido', f'Ticket #{ticket_id} - {asunto}', filas, cuerpo_extra, target_url=target_url)

def email_ticket_recibido(ticket_id, asunto, nombre_usuario, hora_atencion):
    """HTML para la notificacion de ticket marcado como recibido"""
    hora_fmt = hora_atencion if hora_atencion else 'Por definir'
    filas = (
        _fila_dato('N&#250;mero de Ticket', f'#{ticket_id}', highlight=True) +
        _fila_dato('Asunto', asunto) +
        _fila_dato('Solicitante', nombre_usuario) +
        _fila_dato('Nuevo Estado', 'RECIBIDO') +
        _fila_dato('Hora de Atenci&#243;n Programada', hora_fmt)
    )
    cuerpo_extra = """
    <tr><td style="padding:0 30px 10px;">
        <p style="margin:0;font-size:13px;color:#6b7280;line-height:1.6;">
            El ticket ha sido aceptado por el equipo de soporte y tiene una hora de atenci&#243;n asignada.
            Recuerde iniciar la atenci&#243;n puntualmente.
        </p>
    </td></tr>
    """
    target_url = f"{BASE_URL}/ticket/{ticket_id}"
    return _base_email_html('#f59e0b', '&#9200; Ticket Actualizado', f'Ticket #{ticket_id} - Atenci&#243;n Programada', filas, cuerpo_extra, target_url=target_url)

def cron_notificaciones_inminentes():
    """Cron: Notificar tickets con atención en próximos 15 min"""
    try:
        with app.app_context():
            hora_limite = datetime.now() + timedelta(minutes=15)
            
            tickets = Ticket.query.filter(
                Ticket.estado == 'RECIBIDO',
                Ticket.fecha_atencion_programada <= hora_limite,
                Ticket.fecha_atencion_programada > datetime.now() - timedelta(minutes=15)
            ).all()
            
            for ticket in tickets:
                # Buscar agente/admin para notificar
                agentes = Usuario.query.filter(Usuario.rol.in_(['agente', 'admin'])).all()
                for agente in agentes:
                    notificacion = Notificacion(
                        ticket_id=ticket.id,
                        destinatario=agente.email,
                        asunto=f'Alerta: Ticket #{ticket.id} requiere atención',
                        mensaje=f'El ticket "{ticket.asunto}" tiene atención programada en menos de 15 minutos',
                        tipo='sistema'
                    )
                    db.session.add(notificacion)
            
            db.session.commit()
            return jsonify({'status': 'success', 'tickets_notificados': len(tickets)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

def cron_tickets_huerfanos():
    """Cron: Alertar tickets huérfanos (sin atención > X horas)"""
    try:
        with app.app_context():
            horas_limite = 4
            limite = datetime.now() - timedelta(hours=horas_limite)
            
            tickets = Ticket.query.filter(
                Ticket.estado == 'PENDIENTE',
                Ticket.fecha_atencion_programada == None,
                Ticket.fecha_creacion < limite
            ).all()
            
            # Escalar al supervisor/admin
            for ticket in tickets:
                ticket.estado = 'ATRASADO'
                
                log = TicketLog(
                    ticket_id=ticket.id,
                    estado_anterior='PENDIENTE',
                    estado_nuevo='ATRASADO',
                    descripcion=f'Ticket escalado por inactividad (sin atención > {horas_limite} horas)'
                )
                db.session.add(log)
        
            db.session.commit()
            return jsonify({'status': 'success', 'tickets_escalados': len(tickets)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

def cron_estimaciones_expiradas():
    """Cron: Revisar estimaciones de tiempo expiradas"""
    try:
        with app.app_context():
            tickets = Ticket.query.filter(
                Ticket.estado == 'EN_PROCESO',
                Ticket.tiempo_estimado != None
            ).all()
            
            expirados = 0
            for ticket in tickets:
                if ticket.fecha_inicio_atencion and ticket.tiempo_estimado:
                    tiempo_limite = ticket.fecha_inicio_atencion + timedelta(minutes=ticket.tiempo_estimado)
                    if datetime.now() > tiempo_limite:
                        ticket.estado = 'ATRASADO'
                        expirados += 1
                        
                        log = TicketLog(
                            ticket_id=ticket.id,
                            estado_anterior='EN_PROCESO',
                            estado_nuevo='ATRASADO',
                            descripcion='Tiempo de estimación expirado'
                        )
                        db.session.add(log)
            
            db.session.commit()
            return jsonify({'status': 'success', 'tickets_expirados': expirados})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

def cron_reportes_semanales():
    """Cron: Generar reporte semanal de métricas"""
    try:
        with app.app_context():
            # Calcular métricas de la semana
            inicio_semana = datetime.now() - timedelta(days=7)
            
            tickets_creados = Ticket.query.filter(Ticket.fecha_creacion >= inicio_semana).count()
            tickets_cerrados = Ticket.query.filter(
                Ticket.fecha_cierre >= inicio_semana,
                Ticket.estado.in_(['CERRADO', 'RESUELTO'])
            ).count()
            
            # Tiempo promedio de respuesta
            tickets_con_respuesta = Ticket.query.filter(
                Ticket.tiempo_respuesta != None,
                Ticket.fecha_creacion >= inicio_semana
            ).all()
            
            avg_respuesta = 0
            if tickets_con_respuesta:
                avg_respuesta = sum(t.tiempo_respuesta for t in tickets_con_respuesta) / len(tickets_con_respuesta)
            
            # Tiempo promedio de resolución
            tickets_resueltos = Ticket.query.filter(
                Ticket.tiempo_resolucion != None,
                Ticket.fecha_creacion >= inicio_semana
            ).all()
            
            avg_resolucion = 0
            if tickets_resueltos:
                avg_resolucion = sum(t.tiempo_resolucion for t in tickets_resueltos) / len(tickets_resueltos)
            
            reporte = {
                'periodo': f'{inicio_semana.strftime("%Y-%m-%d")} a {datetime.now().strftime("%Y-%m-%d")}',
                'tickets_creados': tickets_creados,
                'tickets_cerrados': tickets_cerrados,
                'tiempo_promedio_respuesta_min': round(avg_respuesta, 2),
                'tiempo_promedio_resolucion_min': round(avg_resolucion, 2)
            }
            
            # Exportar base de datos a Excel (XLSX)
            os.makedirs('reportes', exist_ok=True)
            filename = f"reportes/tickets_bruto_{datetime.now().strftime('%Y%m%d')}.xlsx"
            
            wb = Workbook()
            ws = wb.active
            ws.title = "Base de Datos Tickets"
            
            # Encabezados
            headers = ['ID', 'Usuario ID', 'Nombre Usuario', 'Asunto', 'Descripción', 'Categoría', 'Departamento', 'Estado', 
                       'Fecha Creación', 'Fecha Recepción', 'Fecha Atención', 
                       'Inicio Atención', 'Fecha Cierre', 'T. Respuesta (min)', 
                       'T. Resolución (min)', 'T. Estimado (min)', 'Técnico ID', 'Notas']
            ws.append(headers)
            
            # Estilos de encabezado
            header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            for col in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=col)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
                
            # Congelar la primera fila
            ws.freeze_panes = "A2"
            
            def f_date(d):
                return d.strftime('%Y-%m-%d %H:%M') if d else ""
                
            for t in Ticket.query.all():
                nombre_usuario = t.usuario.nombre if t.usuario else "Desconocido"
                ws.append([
                    t.id, t.usuario_id, nombre_usuario, t.asunto, 
                    t.descripcion[:150] + '...' if t.descripcion and len(t.descripcion) > 150 else t.descripcion, 
                    t.categoria.capitalize() if t.categoria else "", 
                    t.departamento.capitalize() if t.departamento else "", t.estado, 
                    f_date(t.fecha_creacion), f_date(t.fecha_recepcion), f_date(t.fecha_atencion_programada), 
                    f_date(t.fecha_inicio_atencion), f_date(t.fecha_cierre), 
                    t.tiempo_respuesta, t.tiempo_resolucion, t.tiempo_estimado, 
                    t.tecnico_id, 
                    t.notas[:150] + '...' if t.notas and len(t.notas) > 150 else t.notas
                ])
                
            # Ajustar ancho de columnas automáticamente
            for col in ws.columns:
                max_length = 0
                column_letter = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 60) # Ancho máximo de 60
                ws.column_dimensions[column_letter].width = adjusted_width
                
            wb.save(filename)

            # Preparar y enviar correo con adjunto directamente
            correo_destino = 'ti.noreply@planinfor.cl'
            
            msg = MIMEMultipart('mixed')
            msg['From'] = SMTP_USER
            msg['To'] = correo_destino
            msg['Subject'] = 'Reporte Semanal de Tickets y Base de Datos'
            
            cuerpo = f'''Reporte Semanal del Sistema de Tickets:
            
Período: {reporte['periodo']}
Tickets creados: {reporte['tickets_creados']}
Tickets cerrados: {reporte['tickets_cerrados']}
Tiempo promedio de respuesta: {reporte['tiempo_promedio_respuesta_min']} minutos
Tiempo promedio de resolución: {reporte['tiempo_promedio_resolucion_min']} minutos

Se adjunta la base de datos en bruto (formato CSV/Excel).
'''
            html_content = get_html_email_template("Resumen del Reporte Semanal", cuerpo)
            
            alt_part = MIMEMultipart('alternative')
            alt_part.attach(MIMEText(cuerpo, 'plain', 'utf-8'))
            alt_part.attach(MIMEText(html_content, 'html', 'utf-8'))
            msg.attach(alt_part)
            
            # Adjuntar Excel (.xlsx)
            with open(filename, "rb") as f:
                adjunto = MIMEApplication(f.read(), _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                adjunto.add_header('Content-Disposition', 'attachment', filename=os.path.basename(filename))
                msg.attach(adjunto)
                
            try:
                server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(msg['From'], [correo_destino], msg.as_string())
                server.quit()
            except Exception as e:
                print(f"Error enviando reporte con adjunto: {e}")
                
            db.session.commit()
            return jsonify({'status': 'success', 'reporte': reporte})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

def cron_enviar_correos_pendientes():
    """Cron: Enviar correos reales en estado pendiente"""
    try:
        with app.app_context():
            notificaciones = Notificacion.query.filter_by(estado='pendiente', tipo='email').all()
            
            if not notificaciones:
                return
                
            enviados = 0
            try:
                # Si las credenciales no están configuradas, solo simular
                if SMTP_USER == "tu_correo@planinfor.cl":
                    print(f"⚠️ SMTP no configurado. Simulando envío de {len(notificaciones)} correos...")
                    for notif in notificaciones:
                        notif.estado = 'enviada'
                        notif.fecha_envio = datetime.now()
                        enviados += 1
                    db.session.commit()
                    return

                # Iniciar conexión SMTP real
                server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
                server.login(SMTP_USER, SMTP_PASS)
                
                for notif in notificaciones:
                    # Filtro de seguridad adicional: asegurar que el correo solo salga hacia ti.noreply
                    correo_destino = 'ti.noreply@planinfor.cl'
                    
                    msg = MIMEMultipart('alternative')
                    msg['From'] = SMTP_USER
                    msg['To'] = correo_destino
                    msg['Subject'] = notif.asunto
                    
                    # El campo mensaje ya contiene HTML enriquecido si fue creado con
                    # las funciones email_*. Se adjuntan ambas versiones.
                    plain_text = 'Este correo contiene información sobre un ticket de soporte. Por favor abra este correo en un cliente que soporte HTML.'
                    msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
                    msg.attach(MIMEText(notif.mensaje, 'html', 'utf-8'))
                    
                    # Usando sendmail como en tu código de ejemplo
                    server.sendmail(msg['From'], [correo_destino], msg.as_string())
                    
                    notif.estado = 'enviada'
                    notif.fecha_envio = datetime.now()
                    enviados += 1
                
                server.quit()
                db.session.commit()
                print(f"✅ Se enviaron {enviados} correos exitosamente.")
                return
                
                
            except Exception as e:
                print(f"❌ Error enviando correo: {str(e)}")
                
    except Exception as e:
        print(f"❌ Error general en cron de correos: {str(e)}")

# ==================== API ====================

@app.route('/api/tickets', methods=['GET'])
def api_get_tickets():
    """API para obtener todos los tickets con relaciones, omitiendo contraseñas"""
    include_logs = request.args.get('logs', 'true').lower() != 'false'
    tickets = Ticket.query.order_by(Ticket.fecha_creacion.desc()).all()
    tickets_list = []
    
    for t in tickets:
        # Serializar usuario creador
        creador = None
        if t.usuario:
            creador = {
                'id': t.usuario.id,
                'nombre': t.usuario.nombre,
                'email': t.usuario.email,
                'rol': t.usuario.rol,
                'activo': t.usuario.activo,
                'created_at': t.usuario.created_at.isoformat() if t.usuario.created_at else None
            }
            
        # Serializar técnico asignado
        tecnico = None
        if t.tecnico:
            tecnico = {
                'id': t.tecnico.id,
                'nombre': t.tecnico.nombre,
                'email': t.tecnico.email,
                'rol': t.tecnico.rol,
                'activo': t.tecnico.activo
            }
            
        # Serializar logs
        logs_list = []
        if include_logs:
            for log in t.logs:
                log_usuario = None
                if log.usuario:
                    log_usuario = {
                        'id': log.usuario.id,
                        'nombre': log.usuario.nombre,
                        'email': log.usuario.email,
                        'rol': log.usuario.rol
                    }
                logs_list.append({
                    'id': log.id,
                    'estado_anterior': log.estado_anterior,
                    'estado_nuevo': log.estado_nuevo,
                    'descripcion': log.descripcion,
                    'fecha_cambio': log.fecha_cambio.isoformat() if log.fecha_cambio else None,
                    'usuario': log_usuario
                })
            
        ticket_data = {
            'id': t.id,
            'asunto': t.asunto,
            'descripcion': t.descripcion,
            'categoria': t.categoria,
            'prioridad': t.prioridad,
            'departamento': t.departamento,
            'estado': t.estado,
            'fecha_creacion': t.fecha_creacion.isoformat() if t.fecha_creacion else None,
            'fecha_recepcion': t.fecha_recepcion.isoformat() if t.fecha_recepcion else None,
            'fecha_atencion_programada': t.fecha_atencion_programada.isoformat() if t.fecha_atencion_programada else None,
            'fecha_inicio_atencion': t.fecha_inicio_atencion.isoformat() if t.fecha_inicio_atencion else None,
            'fecha_cierre': t.fecha_cierre.isoformat() if t.fecha_cierre else None,
            'tiempo_respuesta': t.tiempo_respuesta,
            'tiempo_resolucion': t.tiempo_resolucion,
            'tiempo_estimado': t.tiempo_estimado,
            'notas': t.notas,
            'creador': creador,
            'tecnico': tecnico
        }
        
        if include_logs:
            ticket_data['historial_logs'] = logs_list
            
        tickets_list.append(ticket_data)
        
    return jsonify({'status': 'success', 'total': len(tickets_list), 'data': tickets_list})

@app.route('/api/tickets-simple', methods=['GET'])
def api_get_tickets_simple():
    """API para obtener todos los tickets con relaciones, omitiendo contraseñas e historial de logs"""
    tickets = Ticket.query.order_by(Ticket.fecha_creacion.desc()).all()
    tickets_list = []
    
    for t in tickets:
        # Serializar usuario creador
        creador = None
        if t.usuario:
            creador = {
                'id': t.usuario.id,
                'nombre': t.usuario.nombre,
                'email': t.usuario.email,
                'rol': t.usuario.rol,
                'activo': t.usuario.activo,
                'created_at': t.usuario.created_at.isoformat() if t.usuario.created_at else None
            }
            
        # Serializar técnico asignado
        tecnico = None
        if t.tecnico:
            tecnico = {
                'id': t.tecnico.id,
                'nombre': t.tecnico.nombre,
                'email': t.tecnico.email,
                'rol': t.tecnico.rol,
                'activo': t.tecnico.activo
            }
            
        ticket_data = {
            'id': t.id,
            'asunto': t.asunto,
            'descripcion': t.descripcion,
            'categoria': t.categoria,
            'prioridad': t.prioridad,
            'departamento': t.departamento,
            'estado': t.estado,
            'fecha_creacion': t.fecha_creacion.isoformat() if t.fecha_creacion else None,
            'fecha_recepcion': t.fecha_recepcion.isoformat() if t.fecha_recepcion else None,
            'fecha_atencion_programada': t.fecha_atencion_programada.isoformat() if t.fecha_atencion_programada else None,
            'fecha_inicio_atencion': t.fecha_inicio_atencion.isoformat() if t.fecha_inicio_atencion else None,
            'fecha_cierre': t.fecha_cierre.isoformat() if t.fecha_cierre else None,
            'tiempo_respuesta': t.tiempo_respuesta,
            'tiempo_resolucion': t.tiempo_resolucion,
            'tiempo_estimado': t.tiempo_estimado,
            'notas': t.notas,
            'creador': creador,
            'tecnico': tecnico
        }
        
        tickets_list.append(ticket_data)
        
    return jsonify({'status': 'success', 'total': len(tickets_list), 'data': tickets_list})

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

# ==================== SCHEDULER PARA CRON JOBS ====================

def iniciar_scheduler():
    """Iniciar el programador de tareas automáticas"""
    scheduler = BackgroundScheduler()
    
    # Notificación de atención inminente (cada 5 minutos)
    scheduler.add_job(
        func=cron_notificaciones_inminentes,
        trigger='interval',
        minutes=5,
        id='notificaciones_inminentes',
        name='Notificar tickets con atención en próximos 15 min'
    )
    
    # Tickets huérfanos (cada hora)
    scheduler.add_job(
        func=cron_tickets_huerfanos,
        trigger='interval',
        hours=1,
        id='tickets_huerfanos',
        name='Alertar tickets huérfanos sin atención'
    )
    
    # Estimaciones expiradas (cada 4 horas)
    scheduler.add_job(
        func=cron_estimaciones_expiradas,
        trigger='interval',
        hours=4,
        id='estimaciones_expiradas',
        name='Revisar estimaciones de tiempo expiradas'
    )
    
    # Reportes semanales (cada domingo a medianoche)
    scheduler.add_job(
        func=cron_reportes_semanales,
        trigger='cron',
        day_of_week='sun',
        hour=0,
        id='reportes_semanales',
        name='Generar reporte semanal de métricas'
    )
    
    # Envío de correos (cada 1 minuto)
    scheduler.add_job(
        func=cron_enviar_correos_pendientes,
        trigger='interval',
        minutes=1,
        id='enviar_correos',
        name='Enviar correos pendientes en la cola'
    )
    
    # Alerta de mantenciones atrasadas/próximas (cada día a las 8:00 AM)
    scheduler.add_job(
        func=cron_alertas_mantenciones,
        trigger='cron',
        hour=8,
        id='alertas_mantenciones',
        name='Alertar mantenciones atrasadas o próximas a vencer'
    )
    
    # Alerta de licencias próximas a vencer (cada día a las 9:00 AM)
    scheduler.add_job(
        func=cron_alertas_licencias,
        trigger='cron',
        hour=9,
        id='alertas_licencias',
        name='Alertar licencias próximas a vencer'
    )
    
    scheduler.start()
    return scheduler

# ==================== EQUIPOS Y MANTENCIONES ====================

@app.route('/equipos')
@login_required
@requiere_permiso('ver_inventario')
def lista_equipos():
    """Listado de equipos y mantenciones (Admin y Agentes)"""
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    area_filter = request.args.get('area', '').strip()
    responsable_filter = request.args.get('responsable', '').strip()
    marca_filter = request.args.get('marca', '').strip()
    tab = request.args.get('tab', 'programados').strip()
    
    query = EquipoMantencion.query
    
    # Separar por tipo de requerimiento
    if tab == 'por_uso':
        query = query.filter(EquipoMantencion.requerimiento == 'Calibración / Verificación')
    else:
        query = query.filter((EquipoMantencion.requerimiento != 'Calibración / Verificación') | (EquipoMantencion.requerimiento == None))
    
    if search_query:
        query = query.filter(EquipoMantencion.nombre.ilike(f'%{search_query}%') | EquipoMantencion.codigo.ilike(f'%{search_query}%'))
    if area_filter:
        query = query.filter(EquipoMantencion.area.ilike(f'%{area_filter}%'))
    if responsable_filter:
        query = query.filter(EquipoMantencion.responsable.ilike(f'%{responsable_filter}%'))
    if marca_filter:
        query = query.filter(EquipoMantencion.marca.ilike(f'%{marca_filter}%'))
        
    # Get distinct values for filters
    areas = [r[0] for r in db.session.query(EquipoMantencion.area).distinct().filter(EquipoMantencion.area != None, EquipoMantencion.area != '').all()]
    responsables = [r[0] for r in db.session.query(EquipoMantencion.responsable).distinct().filter(EquipoMantencion.responsable != None, EquipoMantencion.responsable != '').all()]
    marcas = [r[0] for r in db.session.query(EquipoMantencion.marca).distinct().filter(EquipoMantencion.marca != None, EquipoMantencion.marca != '').all()]
    
    equipos_paginados = query.order_by(EquipoMantencion.id.desc()).paginate(page=page, per_page=15, error_out=False)
    
    # Dashboard: calcular conteos de alertas sobre TODOS los equipos
    todos_equipos = EquipoMantencion.query.all()
    total_equipos = len(todos_equipos)
    total_atrasados = sum(1 for e in todos_equipos if e.estado_alerta == 'Rojo')
    total_proximos = sum(1 for e in todos_equipos if e.estado_alerta == 'Amarillo')
    total_al_dia = sum(1 for e in todos_equipos if e.estado_alerta == 'Verde')
    
    import datetime as _dt
    equipos_alerta_7_dias = []
    for e in todos_equipos:
        if e.proxima_mantencion:
            try:
                fecha_prox = _dt.datetime.strptime(e.proxima_mantencion, '%d/%m/%Y').date()
                dias = (fecha_prox - _dt.date.today()).days
                if 0 <= dias <= 7:
                    equipos_alerta_7_dias.append({'equipo': e, 'dias': dias})
            except Exception:
                pass
    equipos_alerta_7_dias.sort(key=lambda x: x['dias'])
    
    return render_template('equipos/lista.html',  
                           equipos_paginados=equipos_paginados, 
                           search_query=search_query,
                           area_filter=area_filter,
                           responsable_filter=responsable_filter,
                           marca_filter=marca_filter,
                           areas=sorted(areas),
                           responsables=sorted(responsables),
                           marcas=sorted(marcas),
                           total_equipos=total_equipos,
                           total_atrasados=total_atrasados,
                           total_proximos=total_proximos,
                           total_al_dia=total_al_dia,
                           equipos_alerta_7_dias=equipos_alerta_7_dias,
                           current_tab=tab)

@app.route('/equipos/nuevo', methods=['GET', 'POST'])
@login_required
@requiere_permiso('ver_inventario')
def nuevo_equipo():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        if nombre == '__otra__':
            nombre = request.form.get('nuevo_nombre')
            
        marca = request.form.get('marca')
        if marca == '__otra__':
            marca = request.form.get('nueva_marca')
            
        requerimiento = request.form.get('requerimiento')
        if requerimiento == '__otra__':
            requerimiento = request.form.get('nuevo_requerimiento')
            
        equipo = EquipoMantencion(
            codigo=request.form.get('codigo'),
            nombre=nombre,
            marca=marca,
            modelo=request.form.get('modelo'),
            serie=request.form.get('serie'),
            area=request.form.get('area'),
            responsable=request.form.get('responsable'),
            ultima_mantencion=request.form.get('ultima_mantencion'),
            frecuencia_mantencion=request.form.get('frecuencia_mantencion'),
            proxima_mantencion=request.form.get('proxima_mantencion'),
            requerimiento=requerimiento,
            tipo_mantencion=request.form.get('tipo_mantencion'),
            estado=request.form.get('estado'),
            ficha=request.form.get('ficha')
        )
        db.session.add(equipo)
        db.session.flush()
        
        responsable = request.form.get('responsable')
        if responsable and responsable.strip():
            hist_resp = HistorialResponsable(
                equipo_id=equipo.id,
                responsable=responsable.strip(),
                fecha_inicio=datetime.now(),
                fecha_fin=None
            )
            db.session.add(hist_resp)

        db.session.commit()
        flash('Equipo registrado exitosamente.', 'success')
        return redirect(url_for('lista_equipos'))
        
    nombres = [r[0] for r in db.session.query(EquipoMantencion.nombre).distinct().filter(EquipoMantencion.nombre != None, EquipoMantencion.nombre != '').all()]
    marcas = [r[0] for r in db.session.query(EquipoMantencion.marca).distinct().filter(EquipoMantencion.marca != None, EquipoMantencion.marca != '').all()]
    requerimientos = [r[0] for r in db.session.query(EquipoMantencion.requerimiento).distinct().filter(EquipoMantencion.requerimiento != None, EquipoMantencion.requerimiento != '').all()]
    areas_equipo = AreaEquipo.query.order_by(AreaEquipo.nombre).all()
    
    return render_template('equipos/formulario.html', equipo=None, nombres=sorted(nombres), marcas=sorted(marcas), requerimientos=sorted(requerimientos), areas_equipo=areas_equipo)

@app.route('/equipos/editar/<int:id>', methods=['GET', 'POST'])
@login_required
@requiere_permiso('ver_inventario')
def editar_equipo(id):
    equipo = db.session.get(EquipoMantencion, id)
    if not equipo:
        flash('Equipo no encontrado.', 'error')
        return redirect(url_for('lista_equipos'))
        
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        if nombre == '__otra__':
            nombre = request.form.get('nuevo_nombre')
            
        marca = request.form.get('marca')
        if marca == '__otra__':
            marca = request.form.get('nueva_marca')
            
        requerimiento = request.form.get('requerimiento')
        if requerimiento == '__otra__':
            requerimiento = request.form.get('nuevo_requerimiento')
            
        old_resp = (equipo.responsable or '').strip()
        new_resp = (request.form.get('responsable') or '').strip()
        if old_resp != new_resp:
            active_hist = HistorialResponsable.query.filter_by(equipo_id=equipo.id, fecha_fin=None).first()
            if active_hist:
                active_hist.fecha_fin = datetime.now()
            if new_resp:
                new_hist = HistorialResponsable(
                    equipo_id=equipo.id,
                    responsable=new_resp,
                    fecha_inicio=datetime.now(),
                    fecha_fin=None
                )
                db.session.add(new_hist)

        equipo.codigo = request.form.get('codigo')
        equipo.nombre = nombre
        equipo.marca = marca
        equipo.modelo = request.form.get('modelo')
        equipo.serie = request.form.get('serie')
        equipo.area = request.form.get('area')
        equipo.responsable = new_resp
        equipo.ultima_mantencion = request.form.get('ultima_mantencion')
        equipo.frecuencia_mantencion = request.form.get('frecuencia_mantencion')
        equipo.proxima_mantencion = request.form.get('proxima_mantencion')
        equipo.requerimiento = requerimiento
        equipo.tipo_mantencion = request.form.get('tipo_mantencion')
        equipo.estado = request.form.get('estado')
        equipo.ficha = request.form.get('ficha')
        
        db.session.commit()
        flash('Equipo actualizado exitosamente.', 'success')
        return redirect(url_for('lista_equipos'))
        
    nombres = [r[0] for r in db.session.query(EquipoMantencion.nombre).distinct().filter(EquipoMantencion.nombre != None, EquipoMantencion.nombre != '').all()]
    marcas = [r[0] for r in db.session.query(EquipoMantencion.marca).distinct().filter(EquipoMantencion.marca != None, EquipoMantencion.marca != '').all()]
    requerimientos = [r[0] for r in db.session.query(EquipoMantencion.requerimiento).distinct().filter(EquipoMantencion.requerimiento != None, EquipoMantencion.requerimiento != '').all()]
    areas_equipo = AreaEquipo.query.order_by(AreaEquipo.nombre).all()
    
    return render_template('equipos/formulario.html', equipo=equipo, nombres=sorted(nombres), marcas=sorted(marcas), requerimientos=sorted(requerimientos), areas_equipo=areas_equipo)

@app.route('/equipos/inactivar/<int:id>', methods=['POST'])
@login_required
@requiere_permiso('ver_inventario')
def inactivar_equipo(id):
    equipo = db.session.get(EquipoMantencion, id)
    if equipo:
        equipo.estado = 'Inactivo'
        db.session.commit()
        flash('Equipo marcado como Inactivo.', 'success')
    return redirect(url_for('lista_equipos'))

@app.route('/equipos/activar/<int:id>', methods=['POST'])
@login_required
@requiere_permiso('ver_inventario')
def activar_equipo(id):
    equipo = db.session.get(EquipoMantencion, id)
    if equipo:
        equipo.estado = 'Operativo'
        db.session.commit()
        flash('Equipo activado exitosamente.', 'success')
    return redirect(url_for('lista_equipos'))

@app.route('/equipos/<int:id>/pdf')
@login_required
@requiere_permiso('ver_inventario')
def descargar_ficha_pdf(id):
    equipo = db.session.get(EquipoMantencion, id)
    if not equipo:
        flash('Equipo no encontrado.', 'error')
        return redirect(url_for('lista_equipos'))
    
    # Obtener historial más reciente (si existe)
    historial_reciente = HistorialMantencion.query.filter_by(equipo_id=id).order_by(HistorialMantencion.fecha_realizada.desc()).first()
    
    import tempfile
    import os
    from flask import send_file
    from generador_pdf import crear_ficha_pdf
    
    fd, temp_path = tempfile.mkstemp(suffix='.pdf', prefix=f'Ficha_{equipo.codigo or id}_')
    os.close(fd)
    
    crear_ficha_pdf(equipo, historial_reciente, temp_path)
    
    return send_file(
        temp_path, 
        as_attachment=True, 
        download_name=f"Ficha_Mantencion_{equipo.codigo or id}.pdf",
        mimetype='application/pdf'
    )

@app.route('/mantencion/<int:id>/pdf')
@login_required
def descargar_pdf_mantencion(id):
    mantencion = db.session.get(HistorialMantencion, id)
    if not mantencion:
        flash('Mantención no encontrada.', 'error')
        return redirect(url_for('lista_equipos'))
        
    equipo = db.session.get(EquipoMantencion, mantencion.equipo_id)
    
    import tempfile
    import os
    from flask import send_file
    from generador_pdf import crear_ficha_pdf
    
    fd, temp_path = tempfile.mkstemp(suffix='.pdf', prefix=f'Mantencion_{mantencion.id}_')
    os.close(fd)
    
    crear_ficha_pdf(equipo, mantencion, temp_path)
    
    fecha_str = mantencion.fecha_realizada.strftime('%Y%m%d') if mantencion.fecha_realizada else 'sinfecha'
    
    return send_file(
        temp_path, 
        as_attachment=True, 
        download_name=f"Ficha_Mantencion_{equipo.codigo or equipo.id}_{fecha_str}.pdf",
        mimetype='application/pdf'
    )

@app.route('/equipos/descargar-masivo', methods=['POST'])
@login_required
@requiere_permiso('ver_inventario')
def descargar_fichas_masivo():
    equipo_ids = request.form.getlist('equipo_ids')
    if not equipo_ids:
        flash('No se seleccionó ningún equipo para descargar.', 'warning')
        return redirect(url_for('lista_equipos'))
        
    import tempfile
    import os
    import zipfile
    from flask import send_file
    from generador_pdf import crear_ficha_pdf
    
    # Crear un directorio temporal para el ZIP
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, 'Fichas_Mantencion.zip')
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for eid in equipo_ids:
            equipo = db.session.get(EquipoMantencion, int(eid))
            if not equipo:
                continue
                
            historial_reciente = HistorialMantencion.query.filter_by(equipo_id=equipo.id).order_by(HistorialMantencion.fecha_realizada.desc()).first()
            
            pdf_filename = f"Ficha_Mantencion_{equipo.codigo or equipo.id}.pdf"
            pdf_path = os.path.join(temp_dir, pdf_filename)
            
            crear_ficha_pdf(equipo, historial_reciente, pdf_path)
            zipf.write(pdf_path, arcname=pdf_filename)
            
    return send_file(
        zip_path,
        as_attachment=True,
        download_name='Fichas_Mantencion_Planinfor.zip',
        mimetype='application/zip'
    )

@app.route('/equipos/<int:id>/historial', methods=['GET', 'POST'])
@login_required
@requiere_permiso('ver_inventario')
def historial_equipo(id):
    """Ver historial de mantenciones de un equipo y registrar nuevas"""
    
    equipo = db.session.get(EquipoMantencion, id)
    if not equipo:
        flash('Equipo no encontrado.', 'error')
        return redirect(url_for('lista_equipos'))
    
    if request.method == 'POST':
        fecha_str = request.form.get('fecha_realizada', '').strip()
        tecnico = request.form.get('tecnico', '').strip()
        observaciones = request.form.get('observaciones', '').strip()
        tipo = request.form.get('tipo', '').strip()
        
        # Recopilar detalles del PDF
        detalles_adicionales = []
        for i in range(1, 4):
            act = request.form.get(f'actividad_{i}')
            if act:
                detalles_adicionales.append(f"Actividad: {act}")
        
        obs = request.form.get('observacion_tecnica')
        if obs:
            detalles_adicionales.append(f"Observacion: {obs}")
            
        res = request.form.get('resultado_pruebas')
        if res:
            detalles_adicionales.append(f"Resultado: {res}")
        
        if detalles_adicionales:
            texto_detalles = "--- Detalles Adicionales ---\n" + "\n".join(detalles_adicionales)
            if observaciones:
                observaciones = observaciones + "\n\n" + texto_detalles
            else:
                observaciones = texto_detalles
        
        # Parsear fecha
        fecha_realizada = datetime.now()
        if fecha_str:
            try:
                fecha_realizada = datetime.strptime(fecha_str, '%d/%m/%Y')
            except ValueError:
                pass
                
        # Capturar actividades adicionales
        actividades = []
        for key in request.form.keys():
            if key.startswith('actividad_tipo_'):
                idx = key.split('_')[-1]
                tipo_act = request.form.get(key, '').strip()
                valor_act = request.form.get(f'actividad_valor_{idx}', '').strip()
                if tipo_act and valor_act:
                    actividades.append(f"- {tipo_act}: {valor_act}")
        
        if actividades:
            texto_actividades = "\n".join(actividades)
            if observaciones:
                observaciones = observaciones + "\n\nActividades adicionales:\n" + texto_actividades
            else:
                observaciones = "Actividades adicionales:\n" + texto_actividades
        
        registro = HistorialMantencion(
            equipo_id=equipo.id,
            fecha_realizada=fecha_realizada,
            tecnico=tecnico,
            observaciones=observaciones,
            tipo=tipo,
            registrado_por=g.usuario.nombre
        )
        db.session.add(registro)
        
        # Actualizar última mantención del equipo
        equipo.ultima_mantencion = fecha_realizada.strftime('%d/%m/%Y')
        
        # Recalcular próxima mantención según frecuencia
        freq = (equipo.frecuencia_mantencion or '').strip().lower()
        if freq:
            from dateutil.relativedelta import relativedelta
            if 'anual' in freq:
                prox = fecha_realizada + relativedelta(years=1)
            elif 'semestral' in freq:
                prox = fecha_realizada + relativedelta(months=6)
            elif 'trimestral' in freq:
                prox = fecha_realizada + relativedelta(months=3)
            elif 'mensual' in freq:
                prox = fecha_realizada + relativedelta(months=1)
            elif 'bimestral' in freq:
                prox = fecha_realizada + relativedelta(months=2)
            else:
                prox = None
            
            if prox:
                equipo.proxima_mantencion = prox.strftime('%d/%m/%Y')
        
        db.session.commit()
        flash('Mantención registrada exitosamente.', 'success')
        return redirect(url_for('historial_equipo', id=equipo.id))
    
    historial = HistorialMantencion.query.filter_by(equipo_id=equipo.id).order_by(HistorialMantencion.fecha_realizada.desc()).all()
    historial_responsables = HistorialResponsable.query.filter_by(equipo_id=equipo.id).order_by(HistorialResponsable.fecha_inicio.desc()).all()

    return render_template('equipos/historial.html', equipo=equipo, historial=historial, responsables=historial_responsables)

def cron_alertas_mantenciones():
    """Cron: Enviar alerta solo cuando equipos están a 30, 15 o 1 días de mantención"""
    try:
        with app.app_context():
            import datetime as _dt
            equipos = EquipoMantencion.query.all()
            
            # Solo nos interesan los que están en los umbrales específicos
            proximos = []
            for e in equipos:
                if not e.proxima_mantencion:
                    continue
                try:
                    fecha_prox = _dt.datetime.strptime(e.proxima_mantencion, '%d/%m/%Y').date()
                    dias = (fecha_prox - _dt.date.today()).days
                    if dias in [30, 15, 1]:
                        proximos.append((e, dias))
                except Exception:
                    continue
            
            if not proximos:
                return
            
            # Ordenar por días restantes (más urgente primero)
            proximos.sort(key=lambda x: x[1])
            
            # Construir contenido del correo
            filas = _fila_dato('Equipos por mantener', str(len(proximos)), highlight=True)
            
            detalle = '<tr><td style="padding:20px 30px;">'
            detalle += '<p style="margin:0 0 10px;font-size:14px;font-weight:600;color:#f59e0b;">⚠️ Equipos que requieren mantención:</p>'
            detalle += '<ul style="margin:0;padding-left:20px;font-size:13px;color:#374151;">'
            for e, dias in proximos[:20]:
                urgencia = f'<span style="color:#ef4444;font-weight:600;">en {dias} días</span>'
                responsable = e.responsable if e.responsable else "Sin responsable asignado"
                detalle += f'<li><strong>{e.nombre or e.codigo}</strong> — {urgencia} ({e.proxima_mantencion}) — {responsable}</li>'
            if len(proximos) > 20:
                detalle += f'<li>...y {len(proximos) - 20} más</li>'
            detalle += '</ul></td></tr>'
            
            html_correo = _base_email_html(
                '#f59e0b',
                '&#9888; Mantenciones Próximas',
                f'{len(proximos)} equipo(s) necesitan mantención pronto',
                filas,
                detalle,
                target_url=f'{BASE_URL}/equipos'
            )
            
            notif = Notificacion(
                destinatario='ti.noreply@planinfor.cl',
                asunto=f'[Mantenciones] {len(proximos)} equipo(s) necesitan mantención pronto',
                mensaje=html_correo,
                tipo='email',
                estado='pendiente'
            )
            db.session.add(notif)
            db.session.commit()
            
    except Exception as e:
        print(f'Error en cron_alertas_mantenciones: {e}')

def cron_alertas_licencias():
    """Cron: Alerta de licencias a punto de expirar"""
    try:
        with app.app_context():
            import datetime as _dt
            licencias = Licencia.query.all()
            proximos = []
            hoy = _dt.date.today()
            for l in licencias:
                if not l.fecha_expiracion or l.renovacion_automatica:
                    continue
                dias = (l.fecha_expiracion - hoy).days
                if dias in [30, 15, 7, 1, 0]:
                    proximos.append((l, dias))
            
            if not proximos:
                return
                
            proximos.sort(key=lambda x: x[1])
            filas = _fila_dato('Licencias por expirar', str(len(proximos)), highlight=True)
            
            detalle = '<tr><td style="padding:20px 30px;">'
            detalle += '<p style="margin:0 0 10px;font-size:14px;font-weight:600;color:#ef4444;">🚨 Licencias próximas a expirar o expiradas:</p>'
            detalle += '<ul style="margin:0;padding-left:20px;font-size:13px;color:#374151;">'
            for l, dias in proximos:
                urgencia = f'<span style="color:#ef4444;font-weight:600;">en {dias} días</span>' if dias > 0 else f'<span style="color:#ef4444;font-weight:600;">HOY</span>'
                detalle += f'<li><strong>{l.nombre_servicio}</strong> ({l.tipo}) — expira {urgencia} ({l.fecha_expiracion})</li>'
            detalle += '</ul></td></tr>'
            
            html_correo = _base_email_html(
                '#ef4444',
                '&#128680; Licencias por expirar',
                f'{len(proximos)} licencia(s) expiran pronto',
                filas,
                detalle,
                target_url=f'{BASE_URL}/licencias'
            )
            
            notif = Notificacion(
                destinatario='ti.noreply@planinfor.cl',
                asunto=f'[Licencias] {len(proximos)} licencia(s) expiran pronto',
                mensaje=html_correo,
                tipo='email',
                estado='pendiente'
            )
            db.session.add(notif)
            db.session.commit()
    except Exception as e:
        print(f'Error en cron_alertas_licencias: {e}')

# ==================== GESTIÓN DE LICENCIAS ====================

@app.route('/licencias')
@login_required
@requiere_permiso('ver_licencias')
def licencias():
    
    import datetime as _dt
    hoy = _dt.date.today()
    
    tab = request.args.get('tab', 'todas').strip()
    search_query = request.args.get('q', '').strip()
    
    query = Licencia.query
    
    # Filtro por tipo (tab)
    if tab == 'ssl':
        query = query.filter(Licencia.tipo == 'SSL')
    elif tab == 'software':
        query = query.filter(Licencia.tipo == 'Software')
    elif tab == 'saas':
        query = query.filter(Licencia.tipo == 'SaaS')
    
    # Búsqueda
    if search_query:
        query = query.filter(
            Licencia.nombre_servicio.ilike(f'%{search_query}%') |
            Licencia.proveedor.ilike(f'%{search_query}%') |
            Licencia.responsable.ilike(f'%{search_query}%')
        )
    
    licencias_list = query.order_by(Licencia.fecha_expiracion.asc()).all()
    
    # Estadísticas globales (sin filtro de tab/búsqueda)
    todas = Licencia.query.all()
    total = len(todas)
    total_ssl = sum(1 for l in todas if l.tipo == 'SSL')
    total_software = sum(1 for l in todas if l.tipo == 'Software')
    total_saas = sum(1 for l in todas if l.tipo == 'SaaS')
    expiradas = sum(1 for l in todas if l.fecha_expiracion and l.fecha_expiracion < hoy)
    proximas = sum(1 for l in todas if l.fecha_expiracion and 0 <= (l.fecha_expiracion - hoy).days <= 30)
    vigentes = sum(1 for l in todas if l.fecha_expiracion and (l.fecha_expiracion - hoy).days > 30)
    
    stats = {
        'total': total,
        'total_ssl': total_ssl,
        'total_software': total_software,
        'total_saas': total_saas,
        'expiradas': expiradas,
        'proximas': proximas,
        'vigentes': vigentes
    }
    
    licencias_sin_renovacion = [
        l for l in todas 
        if not l.renovacion_automatica and l.fecha_expiracion and (l.fecha_expiracion - hoy).days <= 30
    ]
    
    return render_template('licencias.html',
        licencias=licencias_list,
        vista='licencias',
        stats=stats,
        current_tab=tab,
        search_query=search_query,
        licencias_alerta_manual=licencias_sin_renovacion
    )

@app.route('/licencias/nueva', methods=['POST'])
@login_required
@requiere_permiso('ver_licencias')
def nueva_licencia():
    if g.usuario.rol not in ['admin', 'agente']:
        return jsonify({'success': False, 'message': 'Acceso denegado'})
    
    import datetime as _dt
    try:
        f_inicio = request.form.get('fecha_inicio')
        f_expiracion = request.form.get('fecha_expiracion')
        
        f_inicio_obj = _dt.datetime.strptime(f_inicio, '%d/%m/%Y').date() if f_inicio else None
        f_exp_obj = _dt.datetime.strptime(f_expiracion, '%d/%m/%Y').date() if f_expiracion else None
        
        if not f_exp_obj:
            flash('La fecha de expiración es obligatoria.', 'error')
            return redirect(url_for('licencias'))

        lic = Licencia(
            nombre_servicio=request.form.get('nombre_servicio'),
            tipo=request.form.get('tipo'),
            proveedor=request.form.get('proveedor'),
            cantidad=request.form.get('cantidad') or None,
            responsable=request.form.get('responsable'),
            fecha_inicio=f_inicio_obj,
            fecha_expiracion=f_exp_obj,
            renovacion_automatica=request.form.get('renovacion_automatica') == 'on',
            estado=request.form.get('estado', 'Activo'),
            observaciones=request.form.get('observaciones')
        )
        db.session.add(lic)
        db.session.commit()
        flash('Licencia agregada exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al agregar licencia: {e}', 'error')
        
    return redirect(url_for('licencias'))

@app.route('/licencias/editar/<int:id>', methods=['POST'])
@login_required
@requiere_permiso('ver_licencias')
def editar_licencia(id):
    if g.usuario.rol not in ['admin', 'agente']:
        return jsonify({'success': False, 'message': 'Acceso denegado'})
    
    lic = db.session.get(Licencia, id)
    if not lic:
        flash('Licencia no encontrada.', 'error')
        return redirect(url_for('licencias'))
        
    import datetime as _dt
    try:
        f_inicio = request.form.get('fecha_inicio')
        f_expiracion = request.form.get('fecha_expiracion')
        
        f_inicio_obj = _dt.datetime.strptime(f_inicio, '%d/%m/%Y').date() if f_inicio else None
        f_exp_obj = _dt.datetime.strptime(f_expiracion, '%d/%m/%Y').date() if f_expiracion else None
        
        if not f_exp_obj:
            flash('La fecha de expiración es obligatoria.', 'error')
            return redirect(url_for('licencias'))

        lic.nombre_servicio = request.form.get('nombre_servicio')
        lic.tipo = request.form.get('tipo')
        lic.proveedor = request.form.get('proveedor')
        lic.cantidad = request.form.get('cantidad') or None
        lic.responsable = request.form.get('responsable')
        lic.fecha_inicio = f_inicio_obj
        lic.fecha_expiracion = f_exp_obj
        lic.renovacion_automatica = (request.form.get('renovacion_automatica') == 'on')
        lic.estado = request.form.get('estado', 'Activo')
        lic.observaciones = request.form.get('observaciones')

        db.session.commit()
        flash('Licencia actualizada exitosamente.', 'success')
    except Exception as e:
        flash(f'Error al actualizar licencia: {e}', 'error')
        
    return redirect(url_for('licencias'))

@app.route('/licencias/eliminar/<int:id>', methods=['POST'])
@login_required
@requiere_permiso('ver_licencias')
def eliminar_licencia(id):
    if g.usuario.rol not in ['admin', 'agente']:
        return jsonify({'success': False, 'message': 'Acceso denegado'})
    lic = db.session.get(Licencia, id)
    if lic:
        db.session.delete(lic)
        db.session.commit()
        flash('Licencia eliminada.', 'success')
    return redirect(url_for('licencias'))

from io import BytesIO
from flask import send_file
from openpyxl.styles import Font, PatternFill

@app.route('/exportar/tickets')
@login_required
def exportar_tickets():
    if g.usuario.rol == 'cliente' and not g.usuario.tiene_permiso('ver_tickets_area'):
        flash('Acceso denegado', 'error')
        return redirect(url_for('mis_tickets'))
        
    query = Ticket.query.join(Usuario, Ticket.usuario_id == Usuario.id)
    if g.usuario.rol not in ['admin', 'agente']:
        if g.usuario.area_id:
            query = query.filter(Usuario.area_id == g.usuario.area_id)
        else:
            query = query.filter(Usuario.id == -1)
            
    tickets = query.order_by(Ticket.fecha_creacion.desc()).all()
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Tickets"
    
    headers = ['ID', 'Asunto', 'Usuario', 'Estado', 'Prioridad', 'Fecha Creación', 'Técnico Asignado']
    ws.append(headers)
    
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="111827", end_color="111827", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        
    for t in tickets:
        tecnico_nombre = t.tecnico.nombre if t.tecnico else 'Sin asignar'
        ws.append([
            t.id, 
            t.asunto, 
            t.usuario.nombre if t.usuario else 'Desconocido', 
            t.estado, 
            t.prioridad, 
            t.fecha_creacion.strftime('%d/%m/%Y %H:%M') if t.fecha_creacion else '',
            tecnico_nombre
        ])
        
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return send_file(output, download_name="tickets_reporte.xlsx", as_attachment=True)

@app.route('/exportar/inventario')
@login_required
@requiere_permiso('ver_inventario')
def exportar_inventario():
    equipos = EquipoMantencion.query.order_by(EquipoMantencion.id.desc()).all()
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventario"
    
    headers = ['ID', 'Tipo', 'Marca', 'Modelo', 'N/S', 'Estado', 'Asignado A']
    ws.append(headers)
    
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="111827", end_color="111827", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        
    for eq in equipos:
        ws.append([
            eq.id,
            eq.tipo_equipo,
            eq.marca,
            eq.modelo,
            eq.numero_serie,
            eq.estado,
            eq.usuario_asignado.nombre if eq.usuario_asignado else 'Sin Asignar'
        ])
        
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return send_file(output, download_name="inventario_reporte.xlsx", as_attachment=True)

if __name__ == '__main__':
    asegurar_base_de_datos()
    crear_datos_iniciales()
    scheduler = iniciar_scheduler()
    
    try:
        print("Iniciando Sistema de Tickets...")
        
        # Usamos el puerto 5500 que está libre
        app.run(host='127.0.0.1', port=5500, debug=True, use_reloader=False)
        
    finally:
        if scheduler:
            print("Apagando el scheduler...")
            scheduler.shutdown()

