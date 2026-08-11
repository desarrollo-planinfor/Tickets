from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, g, send_file, Response, session
from datetime import datetime, timedelta, date
from extensions import db
from models import *
from utils import login_required, requiere_permiso
import os
import json
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash


auth_bp = Blueprint('auth', __name__, template_folder='templates')

# ==================== AUTENTICACIÓN ====================

@auth_bp.before_app_request
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

@auth_bp.route('/login', methods=['GET', 'POST'])
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
                return redirect(url_for('admin.panel_admin'))
        
        # Verificar usuario normal
        usuario = Usuario.query.filter_by(email=email).first()
        if usuario:
            # Validación de contraseña mediante hash bcrypt (se removió fallback plano por seguridad)
            if check_password_hash(usuario.password, password):
                if not usuario.activo:
                    flash('Su cuenta está desactivada. Contacte al administrador.', 'error')
                    return redirect(url_for('auth.login'))
                
                # Si la clave era plana, actualizarla a hash ahora mismo
                if usuario.password == password:
                    usuario.password = generate_password_hash(password)
                    db.session.commit()
                    
                session['usuario_id'] = usuario.id
                if usuario.rol == 'admin':
                    return redirect(url_for('admin.panel_admin'))
                elif usuario.rol == 'agente':
                    return redirect(url_for('tickets.panel_agente'))
                else:
                    return redirect(url_for('tickets.mis_tickets'))
        
        flash('Credenciales incorrectas', 'error')
    
    return render_template('login.html')

@auth_bp.route('/logout')
def logout():
    """Cerrar sesión"""
    session.clear()
    flash('Sesión cerrada correctamente', 'success')
    return redirect(url_for('auth.login'))

@auth_bp.route('/registro', methods=['GET', 'POST'])
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
            return redirect(url_for('auth.registro'))
        
        # Verificar si el email ya existe
        if Usuario.query.filter_by(email=email).first():
            flash('El correo electrónico ya está registrado', 'error')
            return redirect(url_for('auth.registro'))
        
        # Validar correo corporativo (contiene @planinfor o similar)
        if 'planinfor' not in email.lower():
            flash('Debe usar un correo corporativo de Planinfor', 'error')
            return redirect(url_for('auth.registro'))
        
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
        return redirect(url_for('auth.login'))
    
    return render_template('registro.html')

@auth_bp.route('/perfil/password', methods=['GET', 'POST'])
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
            return redirect(url_for('auth.cambiar_password'))
            
        if nueva != confirmar:
            flash('La nueva contraseña y la confirmación no coinciden', 'error')
            return redirect(url_for('auth.cambiar_password'))
            
        if len(nueva) < 6:
            flash('La nueva contraseña debe tener al menos 6 caracteres', 'error')
            return redirect(url_for('auth.cambiar_password'))
            
        # Actualizar a hash
        usuario.password = generate_password_hash(nueva)
        db.session.commit()
        
        flash('Contraseña actualizada correctamente', 'success')
        if usuario.rol == 'admin':
            return redirect(url_for('admin.panel_admin'))
        elif usuario.rol == 'agente':
            return redirect(url_for('tickets.panel_agente'))
        else:
            return redirect(url_for('tickets.mis_tickets'))
            
    return render_template('cambiar_password.html')

