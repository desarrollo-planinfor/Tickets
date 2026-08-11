from functools import wraps
from flask import session, flash, redirect, url_for, g
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from datetime import datetime, timedelta


def calcular_minutos_habiles(inicio, fin):
    """Calcula minutos entre dos fechas en horario hábil (L-V, 08:30-17:30)."""
    if not inicio or not fin:
        return 0
    if inicio > fin:
        inicio, fin = fin, inicio

    minutos = 0
    actual = inicio

    while actual < fin:
        if actual.weekday() >= 5:
            dias_sumar = 7 - actual.weekday()
            actual = actual.replace(hour=8, minute=30, second=0, microsecond=0) + timedelta(days=dias_sumar)
            continue

        hora_float = actual.hour + actual.minute / 60.0

        if hora_float < 8.5:
            actual = actual.replace(hour=8, minute=30, second=0, microsecond=0)
            continue

        if hora_float >= 17.5:
            actual = (actual + timedelta(days=1)).replace(hour=8, minute=30, second=0, microsecond=0)
            continue

        fin_jornada = actual.replace(hour=17, minute=30, second=0, microsecond=0)
        proximo_paso = min(fin, fin_jornada)

        diff = proximo_paso - actual
        minutos += diff.total_seconds() / 60.0

        actual = proximo_paso

    return int(minutos)


def parsear_fecha_hora(valor):
    """Parsea fechas enviadas por flatpickr u otros formatos comunes."""
    if not valor or not str(valor).strip():
        return None
    valor = str(valor).strip()
    formatos = (
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%d/%m/%Y %H:%M:%S',
        '%Y-%m-%d',
        '%d/%m/%Y',
    )
    for fmt in formatos:
        try:
            return datetime.strptime(valor, fmt)
        except ValueError:
            continue
    raise ValueError(f"Formato de fecha no reconocido: {valor}")

def sincronizar_areas_jefe(usuario_id, area_ids):
    """Sincroniza las áreas donde un usuario es jefe (Area.jefe_id)."""
    from models import Area, Usuario

    area_ids = {int(a) for a in area_ids if a}
    reemplazos = []

    for area in Area.query.filter_by(jefe_id=usuario_id).all():
        if area.id not in area_ids:
            area.jefe_id = None

    for area_id in area_ids:
        area = Area.query.get(area_id)
        if not area:
            continue
        if area.jefe_id and area.jefe_id != usuario_id:
            jefe_anterior = Usuario.query.get(area.jefe_id)
            reemplazos.append((area.nombre, jefe_anterior.nombre if jefe_anterior else 'Desconocido'))
        area.jefe_id = usuario_id

    return reemplazos


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session:
            flash('Debe iniciar sesión para acceder a esta página', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def requiere_permiso(permiso):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if g.usuario.rol == 'admin':
                return f(*args, **kwargs)
            if not g.usuario.tiene_permiso(permiso):
                flash('No tiene permisos para realizar esta acción.', 'error')
                return redirect(url_for('tickets.mis_tickets'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
