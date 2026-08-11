from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, g, send_file, Response, session
from datetime import datetime, timedelta, date
from extensions import db

from sqlalchemy.orm import joinedload
from models import *
from utils import login_required, requiere_permiso, sincronizar_areas_jefe
import os
import json
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash


admin_bp = Blueprint('admin', __name__, template_folder='templates')

@admin_bp.route('/admin/ticket/actualizar_campos/<int:ticket_id>', methods=['POST'])
@login_required
def actualizar_campos_ticket(ticket_id):
    """Admin actualiza prioridad y departamento del ticket"""
    if g.usuario.rol != 'admin':
        flash('Acceso denegado. Solo administradores pueden realizar esta acción.', 'error')
        return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))
        
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket no encontrado', 'error')
        return redirect(url_for('admin.panel_admin'))
        
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
        
    return redirect(url_for('tickets.ver_ticket', ticket_id=ticket_id))

@admin_bp.route('/admin')
@login_required
def panel_admin():
    """Panel de administración - solo para admin"""
    usuario = g.usuario
    if usuario.rol != 'admin':
        flash('Acceso denegado. Solo administradores.', 'error')
        if usuario.rol == 'agente':
            return redirect(url_for('tickets.panel_agente'))
        return redirect(url_for('tickets.mis_tickets'))
    
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
    
    ultimos_tickets = Ticket.query.options(
        joinedload(Ticket.tecnico)
    ).order_by(Ticket.fecha_creacion.desc()).limit(10).all()
    
    # Datos para Graficos
    from sqlalchemy import func
    tecnicos_stats = db.session.query(
        Usuario.nombre, func.count(Ticket.id)
    ).join(Ticket, Ticket.tecnico_id == Usuario.id).group_by(Usuario.nombre).all()
    chart_tecnicos = {'labels': [t[0] for t in tecnicos_stats], 'data': [t[1] for t in tecnicos_stats]}
    chart_tecnicos['max'] = max(chart_tecnicos['data']) if chart_tecnicos['data'] else 1
    
    return render_template('panel_admin.html', stats=stats, ultimos_tickets=ultimos_tickets, chart_tecnicos=chart_tecnicos)

@admin_bp.route('/seguridad')
@login_required
def vista_seguridad():
    if g.usuario.rol != 'admin' and not g.usuario.tiene_permiso('ver_dashboard'):
        flash('Acceso denegado. Solo administradores o usuarios autorizados.', 'error')
        return redirect(url_for('tickets.panel_agente'))
    from sqlalchemy.orm import joinedload
    usuarios = Usuario.query.options(
        joinedload(Usuario.area),
        joinedload(Usuario.areas_a_cargo)
    ).order_by(Usuario.nombre).all()
    areas = Area.query.options(joinedload(Area.jefe)).filter_by(activa=True).order_by(Area.nombre).all()
    return render_template('seguridad.html', usuarios=usuarios, areas=areas)

@admin_bp.route('/admin/usuario/nuevo', methods=['POST'])
@login_required
def crear_usuario():
    """Crear nuevo usuario (admin)"""
    if g.usuario.rol != 'admin':
        flash('Acceso denegado', 'error')
        return redirect(url_for('admin.vista_seguridad'))
    
    nombre = request.form.get('nombre')
    email = request.form.get('email')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    rol = request.form.get('rol')
    
    if password != confirm_password:
        flash('Las contraseñas no coinciden', 'error')
        return redirect(url_for('admin.vista_seguridad'))
        
    if Usuario.query.filter_by(email=email).first():
        flash('El correo ya está registrado', 'error')
        return redirect(url_for('admin.vista_seguridad'))
    
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
    db.session.flush()

    areas_a_cargo = request.form.getlist('areas_a_cargo')
    if not area_id and areas_a_cargo:
        usuario.area_id = int(areas_a_cargo[0])
    if areas_a_cargo:
        reemplazos = sincronizar_areas_jefe(usuario.id, areas_a_cargo)
        if reemplazos:
            detalle = ', '.join(f'{a} (antes: {j})' for a, j in reemplazos)
            flash(f'Usuario creado. Áreas reasignadas: {detalle}', 'success')
        else:
            flash(f'Usuario {nombre} creado exitosamente', 'success')
    else:
        flash(f'Usuario {nombre} creado exitosamente', 'success')

    db.session.commit()
    return redirect(url_for('admin.vista_seguridad'))

@admin_bp.route('/admin/usuario/toggle/<int:usuario_id>')
@login_required
def eliminar_usuario(usuario_id):
    """Desactivar/Activar usuario en lugar de eliminar para preservar historial"""
    if g.usuario.rol != 'admin' and not g.usuario.tiene_permiso('ver_seguridad'):
        flash('Acceso denegado. Solo administradores o usuarios autorizados.', 'error')
        return redirect(url_for('admin.panel_admin'))
    
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

@admin_bp.route('/admin/usuario/editar/<int:usuario_id>', methods=['POST'])
@login_required
def editar_usuario(usuario_id):
    """Editar usuario (admin)"""
    if g.usuario.rol != 'admin':
        flash('Acceso denegado', 'error')
        return redirect(url_for('admin.vista_seguridad'))
    
    usuario = db.session.get(Usuario, usuario_id)
    if usuario:
        usuario.nombre = request.form.get('nombre')
        nuevo_password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        if nuevo_password:
            if nuevo_password != confirm_password:
                flash('Las contraseñas no coinciden', 'error')
                return redirect(url_for('admin.vista_seguridad'))
            usuario.password = generate_password_hash(nuevo_password)
        if g.usuario.id != usuario.id:  # No cambiar rol, area ni permisos de uno mismo
            usuario.rol = request.form.get('rol')
            area_id = request.form.get('area_id')
            usuario.area_id = int(area_id) if area_id else None
            
            import json
            permisos = request.form.getlist('permisos')
            usuario.permisos = json.dumps(permisos)

            areas_a_cargo = request.form.getlist('areas_a_cargo')
            if not usuario.area_id and areas_a_cargo:
                usuario.area_id = int(areas_a_cargo[0])
            reemplazos = sincronizar_areas_jefe(usuario.id, areas_a_cargo)
            if reemplazos:
                detalle = ', '.join(f'{a} (antes: {j})' for a, j in reemplazos)
                flash(f'Usuario actualizado. Áreas reasignadas: {detalle}', 'success')
            else:
                flash('Usuario actualizado', 'success')
        else:
            flash('Usuario actualizado', 'success')

        db.session.commit()
    
    return redirect(url_for('admin.vista_seguridad'))

