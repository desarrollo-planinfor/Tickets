from extensions import db
from datetime import datetime

class Area(db.Model):
    """Modelo de Área (para usuarios)"""
    __tablename__ = 'area'
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activa = db.Column(db.Boolean, default=True)
    jefe_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    # Relación con Usuario para obtener el jefe
    jefe = db.relationship('Usuario', foreign_keys=[jefe_id], backref=db.backref('areas_a_cargo', lazy=True))

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
    area = db.relationship('Area', backref='usuarios', lazy=True, foreign_keys=[area_id])
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
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False, index=True)
    
    # Datos del ticket
    asunto = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    categoria = db.Column(db.String(50), default='general')
    prioridad = db.Column(db.String(20), default='Media')
    departamento = db.Column(db.String(50), default='soporte')
    
    # Estados: PENDIENTE, RECIBIDO, EN_PROCESO, RESUELTO, CERRADO, ATRASADO
    estado = db.Column(db.String(20), default='PENDIENTE', index=True)
    
    # Fechas principales
    fecha_creacion = db.Column(db.DateTime, default=datetime.now, index=True)
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
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False, index=True)
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
    fecha_creacion = db.Column(db.DateTime, default=datetime.now, index=True)
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

class Puerto(db.Model):
    """Modelo para Gestión de Puertos Abiertos"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    id = db.Column(db.Integer, primary_key=True)
    nombre_servicio = db.Column(db.String(200), nullable=False)
    numeros_puerto = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
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
    fecha_creacion = db.Column(db.DateTime, default=datetime.now, index=True)

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

# ==================== MODELOS SISTEMA DE EVENTOS ====================

class SistemaNormativo(db.Model):
    __tablename__ = 'sistema_normativo'
    def __init__(self, **kwargs):
        super(SistemaNormativo, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class TipoEvento(db.Model):
    __tablename__ = 'tipo_evento'
    def __init__(self, **kwargs):
        super(TipoEvento, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Clasificacion(db.Model):
    __tablename__ = 'clasificacion'
    def __init__(self, **kwargs):
        super(Clasificacion, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class OrigenACR(db.Model):
    __tablename__ = 'origen_acr'
    def __init__(self, **kwargs):
        super(OrigenACR, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Evento(db.Model):
    __tablename__ = 'evento'
    def __init__(self, **kwargs):
        super(Evento, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), nullable=False, unique=True)
    area_id = db.Column(db.Integer, db.ForeignKey('area.id'))
    area = db.relationship('Area')
    responsable_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    responsable = db.relationship('Usuario', foreign_keys=[responsable_id])
    sistema_normativo_id = db.Column(db.Integer, db.ForeignKey('sistema_normativo.id'))
    sistema_normativo = db.relationship('SistemaNormativo')
    tipo_evento_id = db.Column(db.Integer, db.ForeignKey('tipo_evento.id'))
    tipo_evento = db.relationship('TipoEvento')
    descripcion = db.Column(db.Text)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    accion_contencion = db.Column(db.Text)
    impacto = db.Column(db.Integer)
    recurrencia = db.Column(db.Integer)
    potencialidad = db.Column(db.Integer)
    evaluacion = db.Column(db.String(30))
    accion_correctiva_id = db.Column(db.Integer, db.ForeignKey('accion_correctiva.id'), nullable=True)
    estado = db.Column(db.String(20), default='Abierto')
    estado_cierre = db.Column(db.String(20), default='Pendiente')
    firma_cierre = db.Column(db.String(150))
    fecha_cierre = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class AccionCorrectiva(db.Model):
    __tablename__ = 'accion_correctiva'
    def __init__(self, **kwargs):
        super(AccionCorrectiva, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), nullable=False, unique=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'))
    evento = db.relationship('Evento', foreign_keys=[evento_id], backref='acciones_correctivas')
    origen = db.Column(db.String(100), default='Externa')
    area_id = db.Column(db.Integer, db.ForeignKey('area.id'))
    area = db.relationship('Area')
    responsable_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    responsable = db.relationship('Usuario', foreign_keys=[responsable_id])
    sistema_normativo_id = db.Column(db.Integer, db.ForeignKey('sistema_normativo.id'))
    sistema_normativo = db.relationship('SistemaNormativo')
    tipo_evento_id = db.Column(db.Integer, db.ForeignKey('tipo_evento.id'))
    tipo_evento = db.relationship('TipoEvento')
    clasificacion_id = db.Column(db.Integer, db.ForeignKey('clasificacion.id'))
    clasificacion = db.relationship('Clasificacion')
    descripcion = db.Column(db.Text)
    accion_contencion = db.Column(db.Text)
    consulta_trabajador = db.Column(db.Text)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    fecha_plazo = db.Column(db.Date)
    fecha_verificacion = db.Column(db.Date)
    iteracion_actual = db.Column(db.Integer, default=0)
    resultado_eficacia = db.Column(db.String(20), default='Pendiente')
    estado = db.Column(db.String(20), default='Abierto')
    estado_cierre = db.Column(db.String(20), default='Pendiente')
    firma_cierre = db.Column(db.String(150))
    fecha_cierre = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class IteracionACR(db.Model):
    __tablename__ = 'iteracion_acr'
    def __init__(self, **kwargs):
        super(IteracionACR, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    accion_id = db.Column(db.Integer, db.ForeignKey('accion_correctiva.id'), nullable=False)
    accion_correctiva = db.relationship('AccionCorrectiva', backref=db.backref('iteraciones_acr', lazy=True, cascade='all, delete-orphan'))
    numero_iteracion = db.Column(db.Integer, nullable=False, default=1)
    metodologia = db.Column(db.String(30))
    datos_acr = db.Column(db.JSON)
    causa_raiz = db.Column(db.Text)
    texto_accion_correctiva = db.Column(db.Text)
    evaluacion_nuevos_riesgos = db.Column(db.Text)
    congelado = db.Column(db.Boolean, default=False)
    eficacia_p1 = db.Column(db.Boolean)
    eficacia_p2 = db.Column(db.Boolean)
    resultado_eficacia = db.Column(db.String(20))
    evaluado_por = db.Column(db.String(150))
    motivo_falla = db.Column(db.Text)
    fecha_evaluacion = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class EvaluacionEficacia(db.Model):
    __tablename__ = 'evaluacion_eficacia'
    def __init__(self, **kwargs):
        super(EvaluacionEficacia, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    iteracion_id = db.Column(db.Integer, db.ForeignKey('iteracion_acr.id'), nullable=False)
    iteracion = db.relationship('IteracionACR', backref=db.backref('evaluaciones', lazy=True, cascade='all, delete-orphan'))
    clave_pregunta = db.Column(db.String(50), nullable=False)
    texto_pregunta = db.Column(db.Text, nullable=False)
    respuesta = db.Column(db.Boolean)
    created_at = db.Column(db.DateTime, default=datetime.now)

class ArchivoEvento(db.Model):
    __tablename__ = 'archivo_evento'
    def __init__(self, **kwargs):
        super(ArchivoEvento, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    evento = db.relationship('Evento', backref=db.backref('archivos', lazy=True, cascade='all, delete-orphan'))
    nombre_original = db.Column(db.String(300), nullable=False)
    nombre_almacenado = db.Column(db.String(300), nullable=False)
    mime_type = db.Column(db.String(100))
    tamano = db.Column(db.Integer)
    fecha_subida = db.Column(db.DateTime, default=datetime.now)

class ArchivoAC(db.Model):
    __tablename__ = 'archivo_ac'
    def __init__(self, **kwargs):
        super(ArchivoAC, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    accion_id = db.Column(db.Integer, db.ForeignKey('accion_correctiva.id'), nullable=False)
    accion = db.relationship('AccionCorrectiva', backref=db.backref('archivos', lazy=True, cascade='all, delete-orphan'))
    nombre_original = db.Column(db.String(300), nullable=False)
    nombre_almacenado = db.Column(db.String(300), nullable=False)
    mime_type = db.Column(db.String(100))
    tamano = db.Column(db.Integer)
    fecha_subida = db.Column(db.DateTime, default=datetime.now)

class HistorialEvento(db.Model):
    __tablename__ = 'historial_evento'
    def __init__(self, **kwargs):
        super(HistorialEvento, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('evento.id'), nullable=False)
    evento = db.relationship('Evento', backref=db.backref('historial', lazy=True, cascade='all, delete-orphan'))
    nombre_usuario = db.Column(db.String(150), nullable=False, default='Sistema')
    accion = db.Column(db.String(50), nullable=False)
    detalles = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

class HistorialAC(db.Model):
    __tablename__ = 'historial_ac'
    def __init__(self, **kwargs):
        super(HistorialAC, self).__init__(**kwargs)
    id = db.Column(db.Integer, primary_key=True)
    accion_id = db.Column(db.Integer, db.ForeignKey('accion_correctiva.id'), nullable=False)
    accion = db.relationship('AccionCorrectiva', backref=db.backref('historial', lazy=True, cascade='all, delete-orphan'))
    nombre_usuario = db.Column(db.String(150), nullable=False, default='Sistema')
    accion_texto = db.Column(db.String(50), nullable=False)
    detalles = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

class HallazgoSistemaNormativo(db.Model):
    __tablename__ = 'hallazgo_sistema_normativo'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class HallazgoTipoEvento(db.Model):
    __tablename__ = 'hallazgo_tipo_evento'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class HallazgoClasificacion(db.Model):
    __tablename__ = 'hallazgo_clasificacion'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class HallazgoOrigenACR(db.Model):
    __tablename__ = 'hallazgo_origen_acr'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False, unique=True)
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

class HallazgoEvento(db.Model):
    __tablename__ = 'hallazgo_evento'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), nullable=False, unique=True)
    
    area_id = db.Column(db.Integer, db.ForeignKey('area.id'), nullable=True)
    responsable_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    sistema_normativo_id = db.Column(db.Integer, db.ForeignKey('hallazgo_sistema_normativo.id'), nullable=True)
    tipo_evento_id = db.Column(db.Integer, db.ForeignKey('hallazgo_tipo_evento.id'), nullable=True)
    
    area = db.relationship('Area', foreign_keys=[area_id])
    responsable = db.relationship('Usuario', foreign_keys=[responsable_id])
    sistema_normativo = db.relationship('HallazgoSistemaNormativo', foreign_keys=[sistema_normativo_id])
    tipo_evento = db.relationship('HallazgoTipoEvento', foreign_keys=[tipo_evento_id])
    
    descripcion = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    
    accion_contencion = db.Column(db.Text, nullable=True)
    impacto = db.Column(db.Integer, nullable=True)
    recurrencia = db.Column(db.Integer, nullable=True)
    potencialidad = db.Column(db.Integer, nullable=True)
    
    evaluacion = db.Column(db.String(50), nullable=True)
    accion_correctiva_id = db.Column(db.Integer, db.ForeignKey('hallazgo_accion_correctiva.id'), nullable=True)
    accion_correctiva = db.relationship('HallazgoAccionCorrectiva', foreign_keys=[accion_correctiva_id], backref=db.backref('evento_asociado', uselist=False))
    
    estado = db.Column(db.String(20), default='Abierto')
    estado_cierre = db.Column(db.String(20), default='Pendiente')
    firma_cierre = db.Column(db.String(150), nullable=True)
    pdf_cierre = db.Column(db.String(500), nullable=True)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    historial = db.relationship('HallazgoHistorial', backref='evento', lazy='dynamic', cascade='all, delete-orphan')

class HallazgoHistorial(db.Model):
    __tablename__ = 'hallazgo_historial'
    id = db.Column(db.Integer, primary_key=True)
    evento_id = db.Column(db.Integer, db.ForeignKey('hallazgo_evento.id'), nullable=False)
    accion = db.Column(db.String(100), nullable=False)
    detalles = db.Column(db.Text, nullable=True)
    usuario = db.Column(db.String(150), default='Sistema')
    created_at = db.Column(db.DateTime, default=datetime.now)

class HallazgoAccionCorrectiva(db.Model):
    __tablename__ = 'hallazgo_accion_correctiva'
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), nullable=False, unique=True)
    
    evento_id = db.Column(db.Integer, db.ForeignKey('hallazgo_evento.id'), nullable=True)
    origen = db.Column(db.String(100), default='Externa')
    
    area_id = db.Column(db.Integer, db.ForeignKey('area.id'), nullable=True)
    responsable_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    sistema_normativo_id = db.Column(db.Integer, db.ForeignKey('hallazgo_sistema_normativo.id'), nullable=True)
    tipo_evento_id = db.Column(db.Integer, db.ForeignKey('hallazgo_tipo_evento.id'), nullable=True)
    clasificacion_id = db.Column(db.Integer, db.ForeignKey('hallazgo_clasificacion.id'), nullable=True)
    
    clasificacion = db.relationship('HallazgoClasificacion')
    responsable = db.relationship('Usuario', foreign_keys=[responsable_id])
    evento = db.relationship('HallazgoEvento', foreign_keys=[evento_id])
    area = db.relationship('Area', foreign_keys=[area_id])
    sistema_normativo = db.relationship('HallazgoSistemaNormativo', foreign_keys=[sistema_normativo_id])
    tipo_evento = db.relationship('HallazgoTipoEvento', foreign_keys=[tipo_evento_id])
    
    descripcion = db.Column(db.Text, nullable=True)
    accion_contencion = db.Column(db.Text, nullable=True)
    consulta_trabajador = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    
    fecha_plazo = db.Column(db.Date, nullable=True)
    fecha_verificacion = db.Column(db.Date, nullable=True)
    
    iteracion_actual = db.Column(db.Integer, default=0)
    resultado_eficacia = db.Column(db.String(20), default='Pendiente')
    
    estado = db.Column(db.String(20), default='Abierto')
    estado_cierre = db.Column(db.String(20), default='Pendiente')
    firma_cierre = db.Column(db.String(150), nullable=True)
    pdf_cierre = db.Column(db.String(500), nullable=True)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class HallazgoACRIteracion(db.Model):
    __tablename__ = 'hallazgo_acr_iteracion'
    id = db.Column(db.Integer, primary_key=True)
    accion_id = db.Column(db.Integer, db.ForeignKey('hallazgo_accion_correctiva.id'), nullable=False)
    numero_iteracion = db.Column(db.Integer, nullable=False, default=1)
    
    metodologia = db.Column(db.String(30), nullable=True)
    datos_acr = db.Column(db.JSON, nullable=True)
    
    causa_raiz = db.Column(db.Text, nullable=True)
    texto_accion_correctiva = db.Column(db.Text, nullable=True)
    evaluacion_nuevos_riesgos = db.Column(db.Text, nullable=True)
    
    pdf_acr = db.Column(db.String(500), nullable=True)
    congelado = db.Column(db.Boolean, default=False)
    
    eficacia_q1 = db.Column(db.Boolean, nullable=True)
    eficacia_q2 = db.Column(db.Boolean, nullable=True)
    resultado_eficacia = db.Column(db.String(20), nullable=True)
    evaluado_por = db.Column(db.String(150), nullable=True)
    motivo_falla = db.Column(db.Text, nullable=True)
    fecha_evaluacion = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

class HallazgoArchivo(db.Model):
    __tablename__ = 'hallazgo_archivo'
    id = db.Column(db.Integer, primary_key=True)
    accion_id = db.Column(db.Integer, db.ForeignKey('hallazgo_accion_correctiva.id'), nullable=True)
    accion = db.relationship('HallazgoAccionCorrectiva', backref=db.backref('archivos', lazy=True, cascade='all, delete-orphan'))
    evento_id = db.Column(db.Integer, db.ForeignKey('hallazgo_evento.id'), nullable=True)
    evento = db.relationship('HallazgoEvento', backref=db.backref('archivos', lazy=True, cascade='all, delete-orphan'))
    nombre_original = db.Column(db.String(300), nullable=False)
    nombre_almacenado = db.Column(db.String(300), nullable=False)
    mime_type = db.Column(db.String(100))
    tamano = db.Column(db.Integer)
    fecha_subida = db.Column(db.DateTime, default=datetime.now)
    subido_por = db.Column(db.String(150), default='Sistema')

