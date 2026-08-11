from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, g, send_file, Response, session
from datetime import datetime, timedelta, date
from extensions import db

from sqlalchemy.orm import joinedload
from models import *
from utils import login_required, requiere_permiso
import os
import json
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash


eventos_legacy_bp = Blueprint('eventos_legacy', __name__, template_folder='templates')

# ==================== MÓDULO HALLAZGOS ====================


if __name__ == '__main__':
    asegurar_base_de_datos()
    crear_datos_iniciales()
    scheduler = iniciar_scheduler()
    
    try:
        print("Iniciando Sistema de Tickets...")
        
        # Usamos el puerto 5500
        is_debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
        app.run(host='127.0.0.1', port=5500, debug=is_debug, use_reloader=False)
        
    finally:
        if scheduler:
            print("Apagando el scheduler...")
            scheduler.shutdown()

