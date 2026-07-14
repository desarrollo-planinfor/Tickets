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

class Usuario(db.Model):
    """Modelo de Usuario del sistema"""
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)  # Contraseña hasheada
    rol = db.Column(db.String(20), default='cliente')  # cliente, agente, admin
    activo = db.Column(db.Boolean, default=True)
    tickets = db.relationship('Ticket', foreign_keys='Ticket.usuario_id', backref='usuario', lazy=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Ticket(db.Model):
    """Modelo principal de Ticket"""
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

@app.route('/tickets/todos')
@login_required
def todos_tickets():
    """Ver todos los tickets con paginación (Agentes y Admin)"""
    if g.usuario.rol == 'cliente':
        flash('Acceso denegado.', 'error')
        return redirect(url_for('mis_tickets'))
        
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    
    query = Ticket.query.join(Usuario, Ticket.usuario_id == Usuario.id)
    
    if search_query:
        query = query.filter(Usuario.nombre.ilike(f'%{search_query}%'))
        
    tickets_paginados = query.order_by(Ticket.fecha_creacion.desc()).paginate(page=page, per_page=15, error_out=False)
    
    return render_template('todos_tickets.html', tickets_paginados=tickets_paginados, search_query=search_query)

class TicketLog(db.Model):
    """Modelo para auditoría de cambios de estado"""
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    estado_anterior = db.Column(db.String(20), nullable=True)
    estado_nuevo = db.Column(db.String(20), nullable=False)
    descripcion = db.Column(db.Text)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    fecha_cambio = db.Column(db.DateTime, default=datetime.now)
    usuario = db.relationship('Usuario')

class Notificacion(db.Model):
    """Modelo de notificaciones del sistema"""
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=True)
    destinatario = db.Column(db.String(120), nullable=False)
    asunto = db.Column(db.String(200), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(20), default='email')  # email, slack, sistema
    estado = db.Column(db.String(20), default='pendiente')  # pendiente, enviada, fallida
    fecha_creacion = db.Column(db.DateTime, default=datetime.now)
    fecha_envio = db.Column(db.DateTime, nullable=True)

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
            fecha_at = datetime.strptime(hora_atencion, '%Y-%m-%dT%H:%M')
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

@app.route('/portal/ticket/<int:ticket_id>')
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
    
    # Lista de usuarios
    usuarios = Usuario.query.order_by(Usuario.created_at.desc()).all()
    
    # Últimos tickets
    ultimos_tickets = Ticket.query.order_by(Ticket.fecha_creacion.desc()).limit(10).all()
    
    return render_template('panel_admin.html', stats=stats, usuarios=usuarios, ultimos_tickets=ultimos_tickets)

@app.route('/admin/usuario/nuevo', methods=['POST'])
@login_required
def crear_usuario():
    """Crear nuevo usuario (admin)"""
    if g.usuario.rol != 'admin':
        flash('Acceso denegado', 'error')
        return redirect(url_for('panel_admin'))
    
    nombre = request.form.get('nombre')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    rol = request.form.get('rol')
    
    if password != confirm_password:
        flash('Las contraseñas no coinciden', 'error')
        return redirect(url_for('panel_admin'))
        
    if Usuario.query.filter_by(email=email).first():
        flash('El correo ya está registrado', 'error')
        return redirect(url_for('panel_admin'))
    
    usuario = Usuario(
        nombre=nombre,
        email=email,
        password=generate_password_hash(password),
        rol=rol
    )
    db.session.add(usuario)
    db.session.commit()
    
    flash(f'Usuario {nombre} creado exitosamente', 'success')
    return redirect(url_for('panel_admin'))

@app.route('/admin/usuario/toggle/<int:usuario_id>')
@login_required
def eliminar_usuario(usuario_id):
    """Desactivar/Activar usuario en lugar de eliminar para preservar historial"""
    if g.usuario.rol != 'admin':
        flash('Acceso denegado. Solo administradores.', 'error')
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
        return redirect(url_for('panel_admin'))
    
    usuario = db.session.get(Usuario, usuario_id)
    if usuario:
        usuario.nombre = request.form.get('nombre')
        nuevo_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        if nuevo_password:
            if nuevo_password != confirm_password:
                flash('Las contraseñas no coinciden', 'error')
                return redirect(url_for('panel_admin'))
            usuario.password = generate_password_hash(nuevo_password)
        if g.usuario.id != usuario.id:  # No cambiar rol de uno mismo
            usuario.rol = request.form.get('rol')
        db.session.commit()
        flash('Usuario actualizado', 'success')
    
    return redirect(url_for('panel_admin'))

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
                return jsonify({'status': 'success', 'enviados': 0})
                
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
                    return jsonify({'status': 'simulated', 'enviados': enviados})

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
                return jsonify({'status': 'success', 'enviados': enviados})
                
            except Exception as e:
                print(f"❌ Error enviando correo: {str(e)}")
                return jsonify({'status': 'error_smtp', 'message': str(e)})
                
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

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
    
    scheduler.start()
    return scheduler
if __name__ == '__main__':
    asegurar_base_de_datos()
    crear_datos_iniciales()
    scheduler = iniciar_scheduler()
    
    try:
        print("Iniciando Sistema de Tickets...")
        
        # Usamos el puerto 5500 que está libre
        serve(app, host='127.0.0.1', port=5500)
        
    finally:
        if scheduler:
            print("Apagando el scheduler...")
            scheduler.shutdown()