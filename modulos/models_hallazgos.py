from app import db
from datetime import datetime

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
    
    descripcion = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    
    accion_contencion = db.Column(db.Text, nullable=True)
    impacto = db.Column(db.Integer, nullable=True)
    recurrencia = db.Column(db.Integer, nullable=True)
    potencialidad = db.Column(db.Integer, nullable=True)
    
    evaluacion = db.Column(db.String(50), nullable=True)
    accion_correctiva_id = db.Column(db.Integer, db.ForeignKey('hallazgo_accion_correctiva.id'), nullable=True)
    
    estado = db.Column(db.String(20), default='Abierto')
    estado_cierre = db.Column(db.String(20), default='Pendiente')
    firma_cierre = db.Column(db.String(150), nullable=True)
    pdf_cierre = db.Column(db.String(500), nullable=True)
    fecha_cierre = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

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
    
    descripcion = db.Column(db.Text, nullable=True)
    accion_contencion = db.Column(db.Text, nullable=True)
    consulta_trabajador = db.Column(db.Text, nullable=True)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    
    # Relaciones para usar en templates
    area = db.relationship('Area', foreign_keys=[area_id])
    responsable = db.relationship('Usuario', foreign_keys=[responsable_id])
    clasificacion = db.relationship('HallazgoClasificacion', foreign_keys=[clasificacion_id])
    
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
