from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash, g, session
from functools import wraps
from datetime import datetime

hallazgos_bp = Blueprint('hallazgos', __name__, template_folder='templates')

def local_login_required(f):
    """Decorator local para rutas que requieren autenticación sin causar imports circulares"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario_id' not in session:
            flash('Debe iniciar sesión para acceder a esta página', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@hallazgos_bp.route('/calcular_recurrencia', methods=['GET'])
@local_login_required
def calcular_recurrencia():
    from models import HallazgoEvento
    from sqlalchemy.orm import joinedload
    from datetime import datetime, timedelta
    tipo_evento_id = request.args.get('tipo_evento_id', type=int)
    evento_id = request.args.get('evento_id', type=int)
    area_id = request.args.get('area_id', type=int)
    
    if not tipo_evento_id or not area_id:
        return jsonify({'recurrencia': 1, 'count_12m': 0, 'count_6m': 0, 'count_1m': 0})
        
    ahora = datetime.now()
    hace_1m = ahora - timedelta(days=30)
    hace_6m = ahora - timedelta(days=180)
    hace_12m = ahora - timedelta(days=365)
    
    query = HallazgoEvento.query.options(joinedload(HallazgoEvento.area), joinedload(HallazgoEvento.sistema_normativo), joinedload(HallazgoEvento.tipo_evento), joinedload(HallazgoEvento.responsable)).filter(HallazgoEvento.tipo_evento_id == tipo_evento_id, HallazgoEvento.area_id == area_id)
    if evento_id:
        query = query.filter(HallazgoEvento.id != evento_id)
        
    count_1m = query.filter(HallazgoEvento.fecha_registro >= hace_1m).count()
    count_6m = query.filter(HallazgoEvento.fecha_registro >= hace_6m).count()
    count_12m = query.filter(HallazgoEvento.fecha_registro >= hace_12m).count()
    
    if count_1m > 3:
        nivel = 5
    elif count_1m in [2, 3]:
        nivel = 4
    elif count_1m == 1:
        nivel = 3
    elif count_6m in [1, 2]:
        nivel = 2
    elif count_12m == 0:
        nivel = 1
    else:
        nivel = 2
        
    return jsonify({
        'recurrencia': nivel,
        'count_1m': count_1m,
        'count_6m': count_6m,
        'count_12m': count_12m
    })

@hallazgos_bp.route('/')
@local_login_required
def dashboard():
    from extensions import db
    from sqlalchemy.orm import joinedload
    from models import ( HallazgoEvento, HallazgoAccionCorrectiva, Area,
                     HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoACRIteracion)
    from sqlalchemy import func
    import json

    # --- Filtros ---
    mes = request.args.get('mes', type=int)
    anio = request.args.get('anio', type=int)
    area_id = request.args.get('area_id', type=int)

    ev_query = HallazgoEvento.query.options(
        joinedload(HallazgoEvento.area),
        joinedload(HallazgoEvento.tipo_evento),
        joinedload(HallazgoEvento.sistema_normativo),
        joinedload(HallazgoEvento.responsable)
    )
    ac_query = HallazgoAccionCorrectiva.query.options(
        joinedload(HallazgoAccionCorrectiva.area),
        joinedload(HallazgoAccionCorrectiva.responsable)
    )

    if mes:
        ev_query = ev_query.filter(func.extract('month', HallazgoEvento.fecha_registro) == mes)
        ac_query = ac_query.filter(func.extract('month', HallazgoAccionCorrectiva.fecha_registro) == mes)
    if anio:
        ev_query = ev_query.filter(func.extract('year', HallazgoEvento.fecha_registro) == anio)
        ac_query = ac_query.filter(func.extract('year', HallazgoAccionCorrectiva.fecha_registro) == anio)
    if area_id:
        ev_query = ev_query.filter(HallazgoEvento.area_id == area_id)
        ac_query = ac_query.filter(HallazgoAccionCorrectiva.area_id == area_id)

    eventos = ev_query.all()
    acciones = ac_query.all()

    # --- KPIs ---
    total_eventos = len(eventos)
    total_ac = len(acciones)
    ev_abiertos = sum(1 for e in eventos if e.estado == 'Abierto')
    ev_en_proceso = sum(1 for e in eventos if e.estado == 'En Proceso')
    ev_cerrados = sum(1 for e in eventos if e.estado == 'Cerrado')
    eventos_escalados = sum(1 for e in eventos if e.evaluacion == 'Escalado')
    tasa_escalamiento = round((eventos_escalados / total_eventos * 100) if total_eventos > 0 else 0, 1)

    tasa_cierre_eventos = round((ev_cerrados / total_eventos * 100) if total_eventos > 0 else 0, 1)

    ac_abiertas = sum(1 for a in acciones if a.estado == 'Abierto')
    ac_cerradas = sum(1 for a in acciones if a.estado == 'Cerrado')
    tasa_cierre_ac = round((ac_cerradas / total_ac * 100) if total_ac > 0 else 0, 1)
    hoy = datetime.now().date()
    ac_vencidas = sum(1 for a in acciones if a.fecha_plazo and a.estado == 'Abierto' and a.fecha_plazo < hoy)

    # Acciones correctivas pendientes (vencidas primero)
    ac_pendientes_atrasadas = []
    for a in acciones:
        if a.estado == 'Abierto':
            es_vencida = bool(a.fecha_plazo and a.fecha_plazo < hoy)
            ac_pendientes_atrasadas.append({
                'id': a.id,
                'codigo': a.codigo,
                'area': a.area.nombre if a.area else '--',
                'responsable': a.responsable.nombre if a.responsable else '--',
                'fecha_plazo': a.fecha_plazo.strftime('%d/%m/%Y') if a.fecha_plazo else '--',
                'estado_plazo': 'Vencido' if es_vencida else 'A tiempo',
                '_sort': 0 if es_vencida else 1
            })
    ac_pendientes_atrasadas.sort(key=lambda x: (x['_sort'], x['fecha_plazo']))
    ac_pendientes_atrasadas = ac_pendientes_atrasadas[:8]

    # Eventos que requieren atención
    atencion_eventos = []
    for e in eventos:
        if e.estado != 'Cerrado' and (e.estado in ('Abierto', 'En Proceso') or e.evaluacion == 'Escalado'):
            score = (e.impacto or 0) + (e.recurrencia or 0) + (e.potencialidad or 0)
            atencion_eventos.append(e)
    atencion_eventos = sorted(
        atencion_eventos,
        key=lambda e: (
            0 if e.evaluacion == 'Escalado' else 1,
            0 if e.estado == 'Abierto' else 1,
            -( (e.impacto or 0) + (e.recurrencia or 0) + (e.potencialidad or 0) )
        )
    )[:8]
    # --- Estado de Eventos (Donut) ---
    ev_estados = {}
    for e in eventos:
        st = e.estado
        ev_estados[st] = ev_estados.get(st, 0) + 1

    # --- Estado de AC (Donut) ---
    ac_estados = {}
    for a in acciones:
        ac_estados[a.estado] = ac_estados.get(a.estado, 0) + 1

    # --- Tipos de Evento (Donut) ---
    ev_tipos = {}
    for e in eventos:
        nombre = e.tipo_evento.nombre if e.tipo_evento else 'Sin Tipo'
        ev_tipos[nombre] = ev_tipos.get(nombre, 0) + 1

    # --- Eventos y AC por Área (Bar) ---
    areas_list = Area.query.filter_by(activa=True).all()
    area_labels = []
    ev_por_area = []
    ac_por_area = []
    for a in areas_list:
        ev_c = sum(1 for e in eventos if e.area_id == a.id)
        ac_c = sum(1 for ac in acciones if ac.area_id == a.id)
        if ev_c > 0 or ac_c > 0:
            area_labels.append(a.nombre)
            ev_por_area.append(ev_c)
            ac_por_area.append(ac_c)

    # --- Por Sistema Normativo (Bar) ---
    sistemas = HallazgoSistemaNormativo.query.filter_by(activo=True).all()
    sn_labels = []
    ev_por_sn = []
    ac_por_sn = []
    for s in sistemas:
        ev_c = sum(1 for e in eventos if e.sistema_normativo_id == s.id)
        ac_c = sum(1 for ac in acciones if ac.sistema_normativo_id == s.id)
        if ev_c > 0 or ac_c > 0:
            sn_labels.append(s.nombre)
            ev_por_sn.append(ev_c)
            ac_por_sn.append(ac_c)

    # --- Metodología ACR (Donut) ---
    metodo_counts = {}
    iteraciones = HallazgoACRIteracion.query.filter(HallazgoACRIteracion.metodologia.isnot(None)).all()
    for it in iteraciones:
        metodo_counts[it.metodologia] = metodo_counts.get(it.metodologia, 0) + 1

    # --- Nivel de Riesgo (Donut) ---
    riesgo = {'Alto (≥9)': 0, 'Medio (6-8)': 0, 'Bajo (3-5)': 0, 'Sin Evaluar': 0}
    for e in eventos:
        score = (e.impacto or 0) + (e.recurrencia or 0) + (e.potencialidad or 0)
        if score >= 9:
            riesgo['Alto (≥9)'] += 1
        elif score >= 6:
            riesgo['Medio (6-8)'] += 1
        elif score > 0:
            riesgo['Bajo (3-5)'] += 1
        else:
            riesgo['Sin Evaluar'] += 1

    # --- Tendencia mensual (Line chart) ---
    meses_data = {}
    for e in eventos:
        mes_key = e.fecha_registro.strftime('%Y-%m')
        meses_data.setdefault(mes_key, {'eventos': 0, 'ac': 0})
        meses_data[mes_key]['eventos'] += 1
    for a in acciones:
        mes_key = a.fecha_registro.strftime('%Y-%m')
        meses_data.setdefault(mes_key, {'eventos': 0, 'ac': 0})
        meses_data[mes_key]['ac'] += 1
    meses_sorted = sorted(meses_data.keys())
    tendencia_labels = meses_sorted
    tendencia_ev = [meses_data[m]['eventos'] for m in meses_sorted]
    tendencia_ac = [meses_data[m]['ac'] for m in meses_sorted]

    # --- Últimos 5 eventos ---
    default_years = [2024, 2025, 2026, 2027]
    ultimos_eventos = HallazgoEvento.query.options(joinedload(HallazgoEvento.area), joinedload(HallazgoEvento.sistema_normativo), joinedload(HallazgoEvento.tipo_evento), joinedload(HallazgoEvento.responsable)).order_by(HallazgoEvento.fecha_registro.desc()).limit(5).all()

    chart_data = {
        'ev_estados': ev_estados,
        'riesgo': riesgo,
        'area_labels': area_labels,
        'ev_por_area': ev_por_area,
        'tendencia_labels': tendencia_labels,
        'tendencia_ev': tendencia_ev,
        'tendencia_ac': tendencia_ac,
    }

    return render_template('hallazgos/dashboard.html',
                           total_eventos=total_eventos,
                           ev_abiertos=ev_abiertos,
                           ev_en_proceso=ev_en_proceso,
                           ev_cerrados=ev_cerrados,
                           acciones_correctivas=total_ac,
                           eventos_escalados=eventos_escalados,
                           tasa_escalamiento=tasa_escalamiento,
                           tasa_cierre_eventos=tasa_cierre_eventos,
                           tasa_cierre_ac=tasa_cierre_ac,
                           ac_abiertas=ac_abiertas,
                           ac_cerradas=ac_cerradas,
                           ac_vencidas=ac_vencidas,
                           chart_data=json.dumps(chart_data),
                           areas=areas_list,
                           filtro_mes=mes or '',
                           filtro_anio=anio or '',
                           filtro_area=area_id or '',
                           years=default_years,
                           ac_pendientes=ac_pendientes_atrasadas,
                           atencion_eventos=atencion_eventos,
                           ultimos_eventos=ultimos_eventos)

@hallazgos_bp.route('/lista')
@local_login_required
def lista():
    from models import HallazgoEvento, Area, HallazgoSistemaNormativo, HallazgoTipoEvento
    from sqlalchemy import func
    filtro = request.args.get('filtro')
    query = HallazgoEvento.query
    if filtro == 'Abiertos':
        query = query.filter_by(estado='Abierto')
    elif filtro == 'En Proceso':
        query = query.filter_by(estado='En Proceso')
    elif filtro == 'Cerrados':
        query = query.filter_by(estado='Cerrado')
    elif filtro == 'Escalados':
        query = query.filter_by(evaluacion='Escalado')
    elif filtro in ('RiesgoAlto', 'RiesgoMedio', 'RiesgoBajo', 'RiesgoSinEvaluar'):
        score = (
            func.coalesce(HallazgoEvento.impacto, 0)
            + func.coalesce(HallazgoEvento.recurrencia, 0)
            + func.coalesce(HallazgoEvento.potencialidad, 0)
        )
        if filtro == 'RiesgoAlto':
            query = query.filter(score >= 9)
        elif filtro == 'RiesgoMedio':
            query = query.filter(score >= 6, score < 9)
        elif filtro == 'RiesgoBajo':
            query = query.filter(score > 0, score < 6)
        else:
            query = query.filter(score == 0)
        
    eventos = query.order_by(HallazgoEvento.fecha_registro.desc()).all()
    
    # Conteos para el Resumen de Eventos
    abiertos = HallazgoEvento.query.filter_by(estado='Abierto').count()
    en_proceso = HallazgoEvento.query.filter_by(estado='En Proceso').count()
    cerrados = HallazgoEvento.query.filter_by(estado='Cerrado').count()
    escalados = HallazgoEvento.query.filter_by(evaluacion='Escalado').count()
    
    return render_template('hallazgos/lista.html', 
                           eventos=eventos,
                           abiertos=abiertos,
                           en_proceso=en_proceso,
                           cerrados=cerrados,
                           escalados=escalados)

@hallazgos_bp.route('/nuevo', methods=['GET', 'POST'])
@local_login_required
def nuevo():
    # Importaciones diferidas para evitar ciclo de dependencias con app.py
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import Area, Usuario, HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoEvento
    from datetime import datetime
    
    if request.method == 'POST':
        try:
            todos_eventos = HallazgoEvento.query.all()
            max_num = 0
            for e in todos_eventos:
                if e.codigo and e.codigo.startswith('EV-'):
                    try:
                        num = int(e.codigo.split('-')[1])
                        if num > max_num:
                            max_num = num
                    except:
                        pass
            nuevo_codigo = f"EV-{max_num + 1:03d}"
            
            # Procesar fecha personalizada
            fecha_reg = None
            if request.form.get('fecha_registro'):
                try:
                    fecha_reg = datetime.strptime(request.form.get('fecha_registro'), '%Y-%m-%d')
                except ValueError:
                    pass
            
            nuevo_hallazgo = HallazgoEvento(
                codigo=nuevo_codigo,
                fecha_registro=fecha_reg if fecha_reg else datetime.now(),
                area_id=request.form.get('area_id') or None,
                responsable_id=request.form.get('responsable_id') or None,
                sistema_normativo_id=request.form.get('sistema_normativo_id') or None,
                tipo_evento_id=request.form.get('tipo_evento_id') or None,
                descripcion=request.form.get('descripcion'),
                accion_contencion=request.form.get('accion_contencion'),
                impacto=request.form.get('impacto', type=int),
                recurrencia=request.form.get('recurrencia', type=int),
                potencialidad=request.form.get('potencialidad', type=int),
                firma_cierre=request.form.get('firma_cierre')
            )
            
            db.session.add(nuevo_hallazgo)
            db.session.flush()
            
            # Evaluación automática del riesgo para escalamiento
            if nuevo_hallazgo.impacto and nuevo_hallazgo.recurrencia and nuevo_hallazgo.potencialidad:
                score = nuevo_hallazgo.impacto + nuevo_hallazgo.recurrencia + nuevo_hallazgo.potencialidad
                es_critico = (nuevo_hallazgo.impacto == 5 or nuevo_hallazgo.recurrencia == 5 or nuevo_hallazgo.potencialidad == 5)
                if score >= 9 or es_critico:
                    nuevo_hallazgo.evaluacion = "Escalado"
                    nuevo_hallazgo.estado = "Cerrado"
                    
                    # Generar código AC basado en el código del evento
                    from models import HallazgoAccionCorrectiva
                    nuevo_codigo_ac = nuevo_hallazgo.codigo.replace('EV-', 'AC-') if 'EV-' in nuevo_hallazgo.codigo else f"AC-{nuevo_hallazgo.codigo}"
                    
                    nueva_ac = HallazgoAccionCorrectiva(
                        codigo=nuevo_codigo_ac,
                        evento_id=nuevo_hallazgo.id,
                        origen='Evaluación de Evento',
                        area_id=nuevo_hallazgo.area_id,
                        responsable_id=nuevo_hallazgo.responsable_id,
                        sistema_normativo_id=nuevo_hallazgo.sistema_normativo_id,
                        tipo_evento_id=nuevo_hallazgo.tipo_evento_id,
                        descripcion=nuevo_hallazgo.descripcion,
                        accion_contencion=nuevo_hallazgo.accion_contencion
                    )
                    db.session.add(nueva_ac)
                    db.session.flush()
                    nuevo_hallazgo.accion_correctiva_id = nueva_ac.id
                    
                    from models import HallazgoHistorialAC
                    hist_ac = HallazgoHistorialAC(
                        accion_id=nueva_ac.id,
                        accion='Creación Automática',
                        detalles='Acción Correctiva generada automáticamente por escalamiento del evento.',
                        usuario=session.get('user_name', 'Sistema')
                    )
                    db.session.add(hist_ac)

                    archivos = request.files.getlist('evidencias_nuevas')
                    tiene_archivos = any(f for f in archivos if f and f.filename)
                    
                    if nuevo_hallazgo.firma_cierre or tiene_archivos:
                        nuevo_hallazgo.estado = "Cerrado"
                        nuevo_hallazgo.estado_cierre = "Completado"
                        nuevo_hallazgo.fecha_cierre = datetime.now()
                    else:
                        nuevo_hallazgo.estado = "En Proceso"
                        nuevo_hallazgo.estado_cierre = "Pendiente"
                else:
                    nuevo_hallazgo.evaluacion = "Cierre Inmediato"
                    archivos = request.files.getlist('evidencias_nuevas')
                    tiene_archivos = any(f for f in archivos if f and f.filename)
                    
                    if nuevo_hallazgo.firma_cierre or tiene_archivos:
                        nuevo_hallazgo.estado = "Cerrado"
                        nuevo_hallazgo.estado_cierre = "Completado"
                        nuevo_hallazgo.fecha_cierre = datetime.now()
                    else:
                        nuevo_hallazgo.estado = "En Proceso"
                        nuevo_hallazgo.estado_cierre = "Pendiente"
            
            archivos = request.files.getlist('evidencias_nuevas')
            if archivos:
                from werkzeug.utils import secure_filename
                import os
                UPLOAD_FOLDER = os.path.join('static', 'uploads', 'hallazgos')
                if not os.path.exists(UPLOAD_FOLDER):
                    os.makedirs(UPLOAD_FOLDER)
                for file in archivos:
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        unique_name = f"ev_{nuevo_hallazgo.id}_{int(datetime.now().timestamp())}_{filename}"
                        filepath = os.path.join(UPLOAD_FOLDER, unique_name)
                        file.save(filepath)
                        from models import HallazgoArchivo
                        nuevo_archivo = HallazgoArchivo(
                            evento_id=nuevo_hallazgo.id,
                            nombre_original=filename,
                            nombre_almacenado=unique_name,
                            mime_type=file.content_type,
                            tamano=os.path.getsize(filepath),
                            subido_por=session.get('user_name', 'Sistema')
                        )
                        db.session.add(nuevo_archivo)
            
            from models import HallazgoHistorial
            hist = HallazgoHistorial(
                evento_id=nuevo_hallazgo.id,
                accion='Creación Inicial',
                detalles='Se registró el evento en el sistema.',
                usuario=session.get('user_name', 'Sistema')
            )
            db.session.add(hist)
            db.session.commit()
            flash('Evento registrado exitosamente', 'success')
            return redirect(url_for('hallazgos.dashboard'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar el evento: {str(e)}', 'error')
        
    areas = Area.query.filter_by(activa=True).all()
    sistemas_normativos = HallazgoSistemaNormativo.query.filter_by(activo=True).all()
    tipos_evento = HallazgoTipoEvento.query.filter_by(activo=True).all()
    usuarios = Usuario.query.filter_by(activo=True).all()
    
    return render_template('hallazgos/formulario.html', 
                           areas=areas, 
                           sistemas=sistemas_normativos, 
                           tipos=tipos_evento,
                           usuarios=usuarios,
                           evento=None)

@hallazgos_bp.route('/editar/<int:id>', methods=['GET', 'POST'])
@local_login_required
def editar(id):
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import Area, Usuario, HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoEvento, HallazgoAccionCorrectiva
    evento = HallazgoEvento.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Procesar fecha personalizada
            from datetime import datetime
            if request.form.get('fecha_registro'):
                try:
                    fecha_reg = datetime.strptime(request.form.get('fecha_registro'), '%Y-%m-%d')
                    evento.fecha_registro = fecha_reg
                except ValueError:
                    pass
                    
            evento.area_id = request.form.get('area_id') or None
            evento.responsable_id = request.form.get('responsable_id') or None
            evento.sistema_normativo_id = request.form.get('sistema_normativo_id') or None
            evento.tipo_evento_id = request.form.get('tipo_evento_id') or None
            evento.descripcion = request.form.get('descripcion')
            evento.accion_contencion = request.form.get('accion_contencion')
            
            # Solo actualizar puntajes si no estaban definidos (0 o None)
            if not evento.impacto and not evento.recurrencia and not evento.potencialidad:
                evento.impacto = request.form.get('impacto', type=int)
                evento.recurrencia = request.form.get('recurrencia', type=int)
                evento.potencialidad = request.form.get('potencialidad', type=int)
                
            evento.firma_cierre = request.form.get('firma_cierre')
            
            # Lógica para crear Acción Correctiva si el riesgo es alto (score >= 9)
            if evento.impacto and evento.recurrencia and evento.potencialidad:
                score = evento.impacto + evento.recurrencia + evento.potencialidad
                es_critico = (evento.impacto == 5 or evento.recurrencia == 5 or evento.potencialidad == 5)
                if score >= 9 or es_critico:
                    evento.evaluacion = "Escalado"
                    evento.estado = "Cerrado"
                    if not evento.accion_correctiva_id:
                        # Generar código AC basado en el código del evento
                        nuevo_codigo_ac = evento.codigo.replace('EV-', 'AC-') if 'EV-' in evento.codigo else f"AC-{evento.codigo}"
                        
                        nueva_ac = HallazgoAccionCorrectiva(
                            codigo=nuevo_codigo_ac,
                            evento_id=evento.id,
                            origen='Evaluación de Evento',
                            area_id=evento.area_id,
                            responsable_id=evento.responsable_id,
                            sistema_normativo_id=evento.sistema_normativo_id,
                            tipo_evento_id=evento.tipo_evento_id,
                            descripcion=evento.descripcion,
                            accion_contencion=evento.accion_contencion,
                            fecha_registro=evento.fecha_registro
                        )
                        db.session.add(nueva_ac)
                        db.session.flush() # Para obtener el ID
                        evento.accion_correctiva_id = nueva_ac.id
                        
                        from models import HallazgoHistorialAC
                        hist_ac = HallazgoHistorialAC(
                            accion_id=nueva_ac.id,
                            accion='Creación Automática',
                            detalles='Acción Correctiva generada automáticamente por escalamiento del evento.',
                            usuario=session.get('user_name', 'Sistema')
                        )
                        db.session.add(hist_ac)
                        
                    from models import HallazgoArchivo
                    tiene_archivos = HallazgoArchivo.query.filter_by(evento_id=evento.id).first() is not None
                    archivos = request.files.getlist('evidencias_nuevas')
                    if not tiene_archivos:
                        tiene_archivos = any(f for f in archivos if f and f.filename)
                        
                    if evento.firma_cierre or tiene_archivos:
                        evento.estado = "Cerrado"
                        evento.estado_cierre = "Completado"
                        evento.fecha_cierre = datetime.now()
                    else:
                        evento.estado = "En Proceso"
                        evento.estado_cierre = "Pendiente"
                else:
                    evento.evaluacion = "Cierre Inmediato"
                    
                    from models import HallazgoArchivo
                    tiene_archivos = HallazgoArchivo.query.filter_by(evento_id=evento.id).first() is not None
                    archivos = request.files.getlist('evidencias_nuevas')
                    if not tiene_archivos:
                        tiene_archivos = any(f for f in archivos if f and f.filename)
                        
                    if evento.firma_cierre or tiene_archivos:
                        evento.estado = "Cerrado"
                        evento.estado_cierre = "Completado"
                        evento.fecha_cierre = datetime.now()
                    else:
                        evento.estado = "En Proceso"
                        evento.estado_cierre = "Pendiente"
            
            # Generar detalles dinámicos para el historial
            cambios = []
            if request.form.get('descripcion'): cambios.append('Información Base')
            if request.form.get('val-impacto') and int(request.form.get('val-impacto')) > 0: cambios.append('Evaluación de Riesgo')
            if request.form.get('firma_cierre'): cambios.append('Firma de Cierre')
            
            if cambios:
                hist_detalles = f"Se actualizaron las secciones: {', '.join(cambios)}."
            else:
                hist_detalles = "Se actualizó la información general del evento."

            from models import HallazgoHistorial
            hist = HallazgoHistorial(
                evento_id=evento.id,
                accion='Actualización de Evento',
                detalles=hist_detalles,
                usuario=session.get('user_name', 'Sistema')
            )
            db.session.add(hist)
            db.session.commit()
            flash('Evento actualizado exitosamente', 'success')
            return redirect(url_for('hallazgos.lista'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar el evento: {str(e)}', 'error')
            
    areas = Area.query.filter((Area.activa == True) | (Area.id == evento.area_id)).all()
    sistemas_normativos = HallazgoSistemaNormativo.query.filter((HallazgoSistemaNormativo.activo == True) | (HallazgoSistemaNormativo.id == evento.sistema_normativo_id)).all()
    tipos_evento = HallazgoTipoEvento.query.filter((HallazgoTipoEvento.activo == True) | (HallazgoTipoEvento.id == evento.tipo_evento_id)).all()
    usuarios = Usuario.query.filter((Usuario.activo == True) | (Usuario.id == evento.responsable_id)).all()
    
    return render_template('hallazgos/formulario.html', 
                           areas=areas, 
                           sistemas=sistemas_normativos, 
                           tipos=tipos_evento, 
                           usuarios=usuarios,
                           evento=evento)

@hallazgos_bp.route('/eliminar/<int:id>', methods=['POST'])
@local_login_required
def eliminar(id):
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoEvento
    evento = HallazgoEvento.query.get_or_404(id)
    try:
        # Eliminar archivos asociados
        from models import HallazgoArchivo
        archivos = HallazgoArchivo.query.filter_by(evento_id=evento.id).all()
        for arch in archivos:
            db.session.delete(arch)
            
        # Si tiene acción correctiva y está vinculada exclusivamente a este evento, se podría desvincular o eliminar.
        # Por seguridad, desvinculamos o la eliminamos. En este caso eliminaremos la AC si fue generada por este evento.
        if evento.accion_correctiva_id:
            from models import HallazgoAccionCorrectiva, HallazgoACRIteracion
            ac = HallazgoAccionCorrectiva.query.get(evento.accion_correctiva_id)
            if ac:
                # Eliminar iteraciones de la AC
                iters = HallazgoACRIteracion.query.filter_by(accion_id=ac.id).all()
                for it in iters:
                    db.session.delete(it)
                # Eliminar archivos de la AC
                archs_ac = HallazgoArchivo.query.filter_by(accion_id=ac.id).all()
                for arch in archs_ac:
                    db.session.delete(arch)
                db.session.delete(ac)
        
        db.session.delete(evento)
        db.session.commit()
        flash('Evento eliminado exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar el evento: {str(e)}', 'error')
    return redirect(url_for('hallazgos.lista'))

@hallazgos_bp.route('/acciones_correctivas')
@local_login_required
def acciones_correctivas():
    from models import HallazgoAccionCorrectiva
    filtro = request.args.get('filtro')
    query = HallazgoAccionCorrectiva.query
    
    if filtro == 'Abiertos':
        query = query.filter_by(estado='Abierto')
    elif filtro == 'En Proceso':
        query = query.filter(HallazgoAccionCorrectiva.estado.in_(['En Proceso', 'En Revisión']), HallazgoAccionCorrectiva.estado_cierre != 'Parcial')
    elif filtro == 'Cerrado Parcial':
        query = query.filter_by(estado_cierre='Parcial')
    elif filtro == 'Cerrado (Eficaz)':
        query = query.filter_by(estado='Cerrado')
    elif filtro == 'Vencidas':
        hoy = datetime.now().date()
        query = query.filter(
            HallazgoAccionCorrectiva.estado.in_(['Abierto', 'En Proceso']),
            HallazgoAccionCorrectiva.fecha_plazo.isnot(None),
            HallazgoAccionCorrectiva.fecha_plazo < hoy
        )
        
    acciones = query.order_by(HallazgoAccionCorrectiva.fecha_registro.desc()).all()
    
    abiertos = HallazgoAccionCorrectiva.query.filter_by(estado='Abierto').count()
    en_proceso = HallazgoAccionCorrectiva.query.filter(HallazgoAccionCorrectiva.estado.in_(['En Proceso', 'En Revisión']), HallazgoAccionCorrectiva.estado_cierre != 'Parcial').count()
    cerrado_parcial = HallazgoAccionCorrectiva.query.filter_by(estado_cierre='Parcial').count()
    cerrado_eficaz = HallazgoAccionCorrectiva.query.filter_by(estado='Cerrado').count()
    
    return render_template('hallazgos/acciones_correctivas.html', acciones=acciones, abiertos=abiertos, en_proceso=en_proceso, cerrado_parcial=cerrado_parcial, cerrado_eficaz=cerrado_eficaz)

@hallazgos_bp.route('/acciones_correctivas/nuevo', methods=['GET', 'POST'])
@local_login_required
def acciones_correctivas_nuevo():
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoAccionCorrectiva, Area, Usuario, HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoClasificacion
    from datetime import datetime
    
    if request.method == 'POST':
        try:
            todas_ac = HallazgoAccionCorrectiva.query.all()
            max_num = 0
            for a in todas_ac:
                if a.codigo and a.codigo.startswith('AC-'):
                    try:
                        num = int(a.codigo.split('-')[1])
                        if num > max_num:
                            max_num = num
                    except:
                        pass
            nuevo_codigo_ac = f"AC-{max_num + 1:03d}"
            
            nueva_ac = HallazgoAccionCorrectiva(
                codigo=nuevo_codigo_ac,
                origen=request.form.get('origen') or 'Manual',
                area_id=request.form.get('area_id') or None,
                responsable_id=request.form.get('responsable_id') or None,
                sistema_normativo_id=request.form.get('sistema_normativo_id') or None,
                tipo_evento_id=request.form.get('tipo_evento_id') or None,
                clasificacion_id=request.form.get('clasificacion_id') or None,
                descripcion=request.form.get('descripcion'),
                accion_contencion=request.form.get('accion_contencion'),
                consulta_trabajador=request.form.get('consulta_trabajador'),
                estado='Abierto',
                estado_cierre='Pendiente'
            )
            
            if request.form.get('fecha_plazo'):
                nueva_ac.fecha_plazo = datetime.strptime(request.form.get('fecha_plazo'), '%Y-%m-%d')
                
            if request.form.get('fecha_registro'):
                try:
                    nueva_ac.fecha_registro = datetime.strptime(request.form.get('fecha_registro'), '%Y-%m-%d')
                except ValueError:
                    pass
            
            db.session.add(nueva_ac)
            db.session.flush()
            
            from models import HallazgoHistorialAC
            hist_ac = HallazgoHistorialAC(
                accion_id=nueva_ac.id,
                accion='Creación Inicial',
                detalles='Se registró la Acción Correctiva manualmente.',
                usuario=session.get('user_name', 'Sistema')
            )
            db.session.add(hist_ac)
            
            db.session.commit()
            
            archivos = request.files.getlist('evidencias_nuevas')
            if archivos:
                from werkzeug.utils import secure_filename
                import os
                UPLOAD_FOLDER = os.path.join('static', 'uploads', 'hallazgos')
                if not os.path.exists(UPLOAD_FOLDER):
                    os.makedirs(UPLOAD_FOLDER)
                for file in archivos:
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        unique_name = f"ac_{nueva_ac.id}_{int(datetime.now().timestamp())}_{filename}"
                        filepath = os.path.join(UPLOAD_FOLDER, unique_name)
                        file.save(filepath)
                        from models import HallazgoArchivo
                        nuevo_archivo = HallazgoArchivo(
                            accion_id=nueva_ac.id,
                            nombre_original=filename,
                            nombre_almacenado=unique_name,
                            mime_type=file.content_type,
                            tamano=os.path.getsize(filepath),
                            subido_por=session.get('user_name', 'Sistema')
                        )
                        db.session.add(nuevo_archivo)
                db.session.commit()
                
            flash('Acción Correctiva registrada exitosamente', 'success')
            return redirect(url_for('hallazgos.acciones_correctivas'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al registrar AC: {str(e)}', 'error')
            
    areas = Area.query.filter_by(activa=True).all()
    sistemas_normativos = HallazgoSistemaNormativo.query.filter_by(activo=True).all()
    tipos_evento = HallazgoTipoEvento.query.filter_by(activo=True).all()
    clasificaciones = HallazgoClasificacion.query.filter_by(activo=True).all()
    usuarios = Usuario.query.filter_by(activo=True).all()
    
    return render_template('hallazgos/formulario_ac.html', 
                           ac=None,
                           areas=areas, 
                           sistemas=sistemas_normativos, 
                           tipos=tipos_evento, 
                           clasificaciones=clasificaciones,
                           usuarios=usuarios)

@hallazgos_bp.route('/acciones_correctivas/eliminar/<int:id>', methods=['POST'])
@local_login_required
def eliminar_ac(id):
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoAccionCorrectiva
    ac = HallazgoAccionCorrectiva.query.get_or_404(id)
    try:
        from models import HallazgoACRIteracion, HallazgoArchivo
        # Eliminar iteraciones
        iters = HallazgoACRIteracion.query.filter_by(accion_id=ac.id).all()
        for it in iters:
            db.session.delete(it)
            
        # Eliminar archivos asociados
        archivos = HallazgoArchivo.query.filter_by(accion_id=ac.id).all()
        for arch in archivos:
            db.session.delete(arch)
            
        db.session.delete(ac)
        db.session.commit()
        flash('Acción Correctiva eliminada exitosamente.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar la Acción Correctiva: {str(e)}', 'error')
    return redirect(url_for('hallazgos.acciones_correctivas'))

@hallazgos_bp.route('/configuraciones')
@local_login_required
def configuraciones():
    from sqlalchemy.orm import joinedload
    from models import HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoClasificacion, HallazgoOrigenACR, Area, Usuario
    sistemas = HallazgoSistemaNormativo.query.all()
    tipos = HallazgoTipoEvento.query.all()
    clasificaciones = HallazgoClasificacion.query.all()
    origenes = HallazgoOrigenACR.query.all()
    areas = Area.query.options(joinedload(Area.jefe)).order_by(Area.nombre).all()
    usuarios = Usuario.query.all()
    return render_template('hallazgos/configuraciones.html', sistemas=sistemas, tipos=tipos, clasificaciones=clasificaciones, origenes=origenes, areas=areas, usuarios=usuarios)

@hallazgos_bp.route('/acciones_correctivas/editar/<int:id>', methods=['GET', 'POST'])
@local_login_required
def acciones_correctivas_editar(id):
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoAccionCorrectiva, Area, Usuario, HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoClasificacion, HallazgoACRIteracion
    from datetime import datetime
    
    ac = HallazgoAccionCorrectiva.query.get_or_404(id)
    
    if request.method == 'POST':
        if ac.estado == 'Cerrado':
            flash('La Acción Correctiva está cerrada y no puede ser modificada.', 'error')
            return redirect(url_for('hallazgos.acciones_correctivas_editar', id=ac.id))
            
        try:
            if request.form.get('origen'):
                ac.origen = request.form.get('origen')
            ac.area_id = request.form.get('area_id') or None
            ac.responsable_id = request.form.get('responsable_id') or None
            ac.sistema_normativo_id = request.form.get('sistema_normativo_id') or None
            ac.tipo_evento_id = request.form.get('tipo_evento_id') or None
            ac.clasificacion_id = request.form.get('clasificacion_id') or None
            ac.descripcion = request.form.get('descripcion')
            ac.accion_contencion = request.form.get('accion_contencion')
            ac.consulta_trabajador = request.form.get('consulta_trabajador')
            
            fecha_plazo_str = request.form.get('fecha_plazo')
            if fecha_plazo_str:
                try:
                    ac.fecha_plazo = datetime.strptime(fecha_plazo_str, '%Y-%m-%d').date()
                except ValueError:
                    try:
                        ac.fecha_plazo = datetime.strptime(fecha_plazo_str, '%d/%m/%Y').date()
                    except ValueError:
                        pass
                
            if request.form.get('fecha_registro'):
                try:
                    ac.fecha_registro = datetime.strptime(request.form.get('fecha_registro'), '%Y-%m-%d')
                except ValueError:
                    try:
                        ac.fecha_registro = datetime.strptime(request.form.get('fecha_registro'), '%d/%m/%Y')
                    except ValueError:
                        pass
            
            # --- Análisis de Causa Raíz ---
            metodologia = request.form.get('acr_metodologia')
            
            # Obtener iteración actual o crearla
            iteracion = HallazgoACRIteracion.query.filter_by(accion_id=ac.id).order_by(HallazgoACRIteracion.numero_iteracion.desc()).first()
            if not iteracion and (metodologia or request.form.get('verif_resultado')):
                iteracion = HallazgoACRIteracion(accion_id=ac.id, numero_iteracion=1)
                db.session.add(iteracion)

            if metodologia:
                iteracion.metodologia = metodologia
                iteracion.causa_raiz = request.form.get('acr_causa_raiz')
                iteracion.texto_accion_correctiva = request.form.get('acr_texto_accion')
                
                tiene_riesgos = request.form.get('acr_tiene_riesgos')
                if tiene_riesgos == 'No':
                    iteracion.evaluacion_nuevos_riesgos = 'No'
                else:
                    iteracion.evaluacion_nuevos_riesgos = request.form.get('acr_nuevos_riesgos')
                
                if metodologia == '5 Porqués':
                    import json
                    datos = {
                        'p1': request.form.get('acr_p1', ''),
                        'p2': request.form.get('acr_p2', ''),
                        'p3': request.form.get('acr_p3', ''),
                        'p4': request.form.get('acr_p4', ''),
                        'p5': request.form.get('acr_p5', '')
                    }
                    iteracion.datos_acr = datos
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(iteracion, "datos_acr")
                elif metodologia == 'Ishikawa':
                    import json
                    datos = {
                        'maquina': request.form.get('acr_maquina', ''),
                        'metodo': request.form.get('acr_metodo', ''),
                        'material': request.form.get('acr_material', ''),
                        'mano_obra': request.form.get('acr_mano_obra', ''),
                        'medio_ambiente': request.form.get('acr_medio_ambiente', ''),
                        'medicion': request.form.get('acr_medicion', '')
                    }
                    iteracion.datos_acr = datos
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(iteracion, "datos_acr")
            
            # --- Lógica Automática de Estado ---
            tiene_acr = bool(request.form.get('acr_metodologia') or request.form.get('acr_causa_raiz') or request.form.get('acr_texto_accion'))
            tiene_archivos = len(ac.archivos) > 0
            
            nuevo_estado = 'Abierto'
            if tiene_acr or tiene_archivos:
                nuevo_estado = 'En Proceso'

            # --- Verificación y Eficacia ---
            fecha_eval = request.form.get('verif_fecha')
            if fecha_eval and iteracion:
                try:
                    iteracion.fecha_evaluacion = datetime.strptime(fecha_eval, '%Y-%m-%d')
                    ac.fecha_verificacion = iteracion.fecha_evaluacion.date()
                except ValueError:
                    try:
                        iteracion.fecha_evaluacion = datetime.strptime(fecha_eval, '%d/%m/%Y')
                        ac.fecha_verificacion = iteracion.fecha_evaluacion.date()
                    except ValueError:
                        pass
                
            q1 = request.form.get('verif_q1') == 'true'
            q2 = request.form.get('verif_q2') == 'true'
            
            # Solo si se envía evaluación explícitamente desde la pestaña de Verificación
            btn_guardar = request.form.get('btn_guardar')
            if btn_guardar == 'verif' and iteracion and request.form.get('verif_evaluado_por'):
                today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
                
                iteracion.eficacia_q1 = q1
                iteracion.eficacia_q2 = q2
                iteracion.evaluado_por = request.form.get('verif_evaluado_por')
                iteracion.motivo_falla = request.form.get('verif_motivo')
                
                # Para ser Eficaz, AMBAS casillas deben estar marcadas
                es_eficaz = (q1 and q2)
                es_parcial = (q1 and not q2) or (not q1 and q2)
                
                if es_eficaz:
                    # Validar backend para que no cierre si no es la fecha (si es futura)
                    if iteracion.fecha_evaluacion and iteracion.fecha_evaluacion > today:
                        # Bloqueado, no puede ser eficaz aún
                        iteracion.resultado_eficacia = 'Pendiente'
                        ac.resultado_eficacia = 'Pendiente'
                    else:
                        iteracion.resultado_eficacia = 'Eficaz'
                        ac.resultado_eficacia = 'Eficaz'
                        nuevo_estado = 'Cerrado'
                        ac.estado_cierre = 'Eficaz'
                        if not ac.fecha_cierre:
                            ac.fecha_cierre = datetime.now()
                elif es_parcial:
                    iteracion.resultado_eficacia = 'Ineficaz'
                    ac.resultado_eficacia = 'Ineficaz'
                    ac.estado_cierre = 'Parcial'
                    nuevo_estado = 'En Proceso'
                    
                    existe_siguiente = HallazgoACRIteracion.query.filter_by(accion_id=ac.id, numero_iteracion=iteracion.numero_iteracion + 1).first()
                    if not existe_siguiente:
                        nueva_it = HallazgoACRIteracion(accion_id=ac.id, numero_iteracion=iteracion.numero_iteracion + 1)
                        db.session.add(nueva_it)
                        flash('Evaluación parcial (1 tick). La Acción Correctiva sigue En Proceso y se ha creado una nueva iteración de Análisis.', 'warning')
                        
                else:
                    # 0 ticks
                    iteracion.resultado_eficacia = 'Ineficaz'
                    ac.resultado_eficacia = 'Ineficaz'
                    ac.estado_cierre = 'Parcial'
                    nuevo_estado = 'En Proceso'
                    
                    existe_siguiente = HallazgoACRIteracion.query.filter_by(accion_id=ac.id, numero_iteracion=iteracion.numero_iteracion + 1).first()
                    if not existe_siguiente:
                        nueva_it = HallazgoACRIteracion(accion_id=ac.id, numero_iteracion=iteracion.numero_iteracion + 1)
                        db.session.add(nueva_it)
                        flash('Evaluación Ineficaz (0 ticks). La Acción Correctiva sigue En Proceso y se ha creado una nueva iteración de Análisis.', 'warning')
            
            ac.estado = nuevo_estado
            
            if btn_guardar == 'info':
                hist_accion = 'Actualización de Información General'
                hist_detalles = 'Se actualizaron los datos básicos, detalles o fechas de la Acción Correctiva.'
            elif btn_guardar == 'acr':
                hist_accion = f'Actualización de ACR (Iteración #{iteracion.numero_iteracion if iteracion else 1})'
                hist_detalles = 'Se modificó la metodología, causa raíz o plan de acción.'
            elif btn_guardar == 'verif':
                hist_accion = 'Registro de Verificación'
                hist_detalles = 'Se evaluó la eficacia de la implementación de la Acción Correctiva.'
            else:
                hist_accion = 'Actualización de Acción Correctiva'
                hist_detalles = 'Se actualizó la información general de la Acción Correctiva.'
                
            from models import HallazgoHistorialAC
            hist_ac = HallazgoHistorialAC(
                accion_id=ac.id,
                accion=hist_accion,
                detalles=hist_detalles,
                usuario=session.get('user_name', 'Sistema')
            )
            db.session.add(hist_ac)
            
            db.session.commit()
            flash('Acción Correctiva actualizada', 'success')
            return redirect(url_for('hallazgos.acciones_correctivas_editar', id=ac.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al editar iteración: {str(e)}', 'error')
            return redirect(url_for('hallazgos.acciones_correctivas_editar', id=ac.id))

    # GET request part of acciones_correctivas_editar
    areas = Area.query.filter_by(activa=True).all()
    sistemas = HallazgoSistemaNormativo.query.filter_by(activo=True).all()
    tipos = HallazgoTipoEvento.query.filter_by(activo=True).all()
    clasificaciones = HallazgoClasificacion.query.filter_by(activo=True).all()
    usuarios = Usuario.query.filter_by(activo=True).all()
    iteraciones = HallazgoACRIteracion.query.filter_by(accion_id=ac.id).order_by(HallazgoACRIteracion.numero_iteracion).all()
    
    return render_template('hallazgos/formulario_ac.html', 
                           ac=ac, areas=areas, sistemas=sistemas, 
                           tipos=tipos, clasificaciones=clasificaciones, 
                           usuarios=usuarios, iteraciones=iteraciones)

@hallazgos_bp.route('/acciones_correctivas/iteracion/<int:id>/eliminar', methods=['POST'])
@local_login_required
def eliminar_iteracion_acr(id):
    from extensions import db
    from models import HallazgoACRIteracion
    
    it = HallazgoACRIteracion.query.get_or_404(id)
    ac_id = it.accion_id
    
    try:
        count = HallazgoACRIteracion.query.filter_by(accion_id=ac_id).count()
        if count <= 1:
            flash('No se puede eliminar la única iteración existente.', 'error')
        else:
            db.session.delete(it)
            db.session.commit()
            
            remaining_its = HallazgoACRIteracion.query.filter_by(accion_id=ac_id).order_by(HallazgoACRIteracion.id).all()
            for idx, r_it in enumerate(remaining_its):
                r_it.numero_iteracion = idx + 1
            db.session.commit()
            flash('Iteración eliminada correctamente.', 'success')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar iteración: {str(e)}', 'error')
        
    return redirect(url_for('hallazgos.acciones_correctivas_editar', id=ac_id))


@hallazgos_bp.route('/acciones_correctivas/editar/<int:id>/nueva_iteracion', methods=['POST'])
@local_login_required
def nueva_iteracion_acr(id):
    from extensions import db
    from models import HallazgoAccionCorrectiva, HallazgoACRIteracion
    
    ac = HallazgoAccionCorrectiva.query.get_or_404(id)
    if ac.estado == 'Cerrado':
        flash('La Acción Correctiva está cerrada, no se pueden agregar nuevas iteraciones.', 'error')
        return redirect(url_for('hallazgos.acciones_correctivas_editar', id=ac.id))
        
    ultima = HallazgoACRIteracion.query.filter_by(accion_id=ac.id).order_by(HallazgoACRIteracion.numero_iteracion.desc()).first()
    num = (ultima.numero_iteracion + 1) if ultima else 1
    
    nueva = HallazgoACRIteracion(accion_id=ac.id, numero_iteracion=num)
    db.session.add(nueva)
    db.session.commit()
    
    flash(f'Se ha creado la Iteración #{num} para un nuevo análisis.', 'success')
    return redirect(url_for('hallazgos.acciones_correctivas_editar', id=ac.id) + '#tab-acr')

@hallazgos_bp.route('/acciones_correctivas/iteracion/<int:it_id>/editar', methods=['POST'])
@local_login_required
def editar_iteracion_acr(it_id):
    from extensions import db
    from models import HallazgoACRIteracion
    import json
    
    iteracion = HallazgoACRIteracion.query.get_or_404(it_id)
    if iteracion.accion.estado == 'Cerrado':
        flash('La Acción Correctiva está cerrada.', 'error')
        return redirect(url_for('hallazgos.acciones_correctivas_editar', id=iteracion.accion_id) + '#tab-acr')
        
    metodologia = request.form.get('edit_acr_metodologia')
    if metodologia:
        iteracion.metodologia = metodologia
        iteracion.causa_raiz = request.form.get('edit_acr_causa_raiz')
        iteracion.texto_accion_correctiva = request.form.get('edit_acr_texto_accion')
        
        if metodologia == '5 Porqués':
            datos = {
                'p1': request.form.get('edit_acr_p1', ''),
                'p2': request.form.get('edit_acr_p2', ''),
                'p3': request.form.get('edit_acr_p3', ''),
                'p4': request.form.get('edit_acr_p4', ''),
                'p5': request.form.get('edit_acr_p5', '')
            }
            iteracion.datos_acr = datos
        elif metodologia == 'Ishikawa':
            datos = {
                'maquina': request.form.get('edit_acr_maquina', ''),
                'metodo': request.form.get('edit_acr_metodo', ''),
                'material': request.form.get('edit_acr_material', ''),
                'mano_obra': request.form.get('edit_acr_mano_obra', ''),
                'medio_ambiente': request.form.get('edit_acr_medio_ambiente', ''),
                'medicion': request.form.get('edit_acr_medicion', '')
            }
            iteracion.datos_acr = datos
            
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(iteracion, "datos_acr")
        db.session.commit()
        flash(f'Iteración #{iteracion.numero_iteracion} actualizada correctamente.', 'success')
        
    return redirect(url_for('hallazgos.acciones_correctivas_editar', id=iteracion.accion_id) + '#tab-acr')


# --- API RUTAS PARA EVIDENCIAS ---
import os
from werkzeug.utils import secure_filename
from flask import jsonify

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'hallazgos')

@hallazgos_bp.route('/<int:id>/subir_evidencia', methods=['POST'])
@local_login_required
def subir_evidencia_evento(id):
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoEvento, HallazgoArchivo
    ev = HallazgoEvento.query.get_or_404(id)
    
    if 'file' not in request.files:
        return jsonify({'error': 'No se envió ningún archivo'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nombre de archivo vacío'}), 400
        
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        
    filename = secure_filename(file.filename)
    unique_name = f"ev_{ev.id}_{int(datetime.now().timestamp())}_{filename}"
    filepath = os.path.join(UPLOAD_FOLDER, unique_name)
    
    try:
        file.save(filepath)
        nuevo_archivo = HallazgoArchivo(
            evento_id=ev.id,
            nombre_original=filename,
            nombre_almacenado=unique_name,
            mime_type=file.content_type,
            tamano=os.path.getsize(filepath),
            subido_por=session.get('user_name', 'Sistema')
        )
        db.session.add(nuevo_archivo)
        db.session.commit()
        return jsonify({
            'success': True, 
            'file': {
                'id': nuevo_archivo.id,
                'nombre': filename,
                'url': url_for('static', filename=f'uploads/hallazgos/{unique_name}'),
                'tamano': nuevo_archivo.tamano,
                'fecha': nuevo_archivo.fecha_subida.strftime('%d/%m/%Y %H:%M')
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@hallazgos_bp.route('/acciones_correctivas/<int:id>/subir_evidencia', methods=['POST'])
@local_login_required
def subir_evidencia_ac(id):
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoAccionCorrectiva, HallazgoArchivo
    ac = HallazgoAccionCorrectiva.query.get_or_404(id)
    
    if 'file' not in request.files:
        return jsonify({'error': 'No se envió ningún archivo'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nombre de archivo vacío'}), 400
        
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        
    filename = secure_filename(file.filename)
    unique_name = f"ac_{ac.id}_{int(datetime.now().timestamp())}_{filename}"
    filepath = os.path.join(UPLOAD_FOLDER, unique_name)
    
    try:
        file.save(filepath)
        nuevo_archivo = HallazgoArchivo(
            accion_id=ac.id,
            nombre_original=filename,
            nombre_almacenado=unique_name,
            mime_type=file.content_type,
            tamano=os.path.getsize(filepath),
            subido_por=session.get('user_name', 'Sistema')
        )
        db.session.add(nuevo_archivo)
        
        from models import HallazgoHistorialAC
        hist_ac = HallazgoHistorialAC(
            accion_id=ac.id,
            accion='Evidencia Subida',
            detalles=f'Se subió el archivo {filename}',
            usuario=session.get('user_name', 'Sistema')
        )
        db.session.add(hist_ac)
        
        db.session.commit()
        return jsonify({
            'success': True, 
            'file': {
                'id': nuevo_archivo.id,
                'nombre': filename,
                'url': url_for('static', filename=f'uploads/hallazgos/{unique_name}'),
                'tamano': nuevo_archivo.tamano,
                'fecha': nuevo_archivo.fecha_subida.strftime('%d/%m/%Y %H:%M')
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@hallazgos_bp.route('/evidencias/<int:file_id>/eliminar', methods=['POST'])
@local_login_required
def eliminar_evidencia(file_id):
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoArchivo
    archivo = HallazgoArchivo.query.get_or_404(file_id)
    
    try:
        filepath = os.path.join(UPLOAD_FOLDER, archivo.nombre_almacenado)
        if os.path.exists(filepath):
            os.remove(filepath)
        
        accion_id_hist = archivo.accion_id
        
        db.session.delete(archivo)
        
        if accion_id_hist:
            from models import HallazgoHistorialAC
            hist_ac = HallazgoHistorialAC(
                accion_id=accion_id_hist,
                accion='Evidencia Eliminada',
                detalles=f'Se eliminó el archivo {archivo.nombre_original}',
                usuario=session.get('user_name', 'Sistema')
            )
            db.session.add(hist_ac)
            
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# --- API RUTAS PARA CONFIGURACIONES ---
@hallazgos_bp.route('/configuraciones/agregar', methods=['POST'])
@local_login_required
def configuraciones_agregar():
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoClasificacion, HallazgoOrigenACR
    tipo_catalogo = request.form.get('tipo_catalogo')
    nombre = request.form.get('nombre')
    
    if not tipo_catalogo or not nombre:
        return jsonify({'error': 'Faltan datos'}), 400
        
    try:
        nuevo_obj = None
        if tipo_catalogo == 'sistema':
            nuevo_obj = HallazgoSistemaNormativo(nombre=nombre, activo=True)
        elif tipo_catalogo == 'tipo_evento':
            nuevo_obj = HallazgoTipoEvento(nombre=nombre, activo=True)
        elif tipo_catalogo == 'clasificacion':
            nuevo_obj = HallazgoClasificacion(nombre=nombre, activo=True)
        elif tipo_catalogo == 'origen':
            nuevo_obj = HallazgoOrigenACR(nombre=nombre, activo=True)
        elif tipo_catalogo == 'area':
            from models import Area, Usuario
            jefe_id = request.form.get('jefe_id')
            nuevo_obj = Area(nombre=nombre, activa=True, jefe_id=jefe_id if jefe_id else None)
        else:
            return jsonify({'error': 'Tipo de catálogo inválido'}), 400
            
        db.session.add(nuevo_obj)
        db.session.flush()
        if tipo_catalogo == 'area' and nuevo_obj.jefe_id:
            from models import Usuario
            jefe = Usuario.query.get(nuevo_obj.jefe_id)
            if jefe and not jefe.area_id:
                jefe.area_id = nuevo_obj.id
        db.session.commit()
        return jsonify({'success': True, 'id': nuevo_obj.id, 'nombre': nuevo_obj.nombre})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@hallazgos_bp.route('/configuraciones/toggle', methods=['POST'])
@local_login_required
def configuraciones_toggle():
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoClasificacion, HallazgoOrigenACR
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    tipo_catalogo = data.get('tipo_catalogo')
    item_id = data.get('id')
    
    if not tipo_catalogo or not item_id:
        return jsonify({'error': 'Faltan datos'}), 400
        
    try:
        obj = None
        if tipo_catalogo == 'sistema':
            obj = HallazgoSistemaNormativo.query.get(item_id)
        elif tipo_catalogo == 'tipo_evento':
            obj = HallazgoTipoEvento.query.get(item_id)
        elif tipo_catalogo == 'clasificacion':
            obj = HallazgoClasificacion.query.get(item_id)
        elif tipo_catalogo == 'origen':
            obj = HallazgoOrigenACR.query.get(item_id)
        elif tipo_catalogo == 'area':
            from models import Area
            obj = Area.query.get(item_id)
            
        if not obj:
            return jsonify({'error': 'Registro no encontrado'}), 404
            
        if tipo_catalogo == 'area':
            obj.activa = not obj.activa
            nuevo_estado = obj.activa
        else:
            obj.activo = not obj.activo
            nuevo_estado = obj.activo
            
        db.session.commit()
        return jsonify({'success': True, 'nuevo_estado': nuevo_estado})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@hallazgos_bp.route('/configuraciones/editar', methods=['POST'])
@local_login_required
def configuraciones_editar():
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoClasificacion, HallazgoOrigenACR
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    tipo_catalogo = data.get('tipo_catalogo')
    item_id = data.get('id')
    nuevo_nombre = data.get('nombre')
    
    if not tipo_catalogo or not item_id or not nuevo_nombre:
        return jsonify({'error': 'Faltan datos'}), 400
        
    try:
        obj = None
        if tipo_catalogo == 'sistema':
            obj = HallazgoSistemaNormativo.query.get(item_id)
        elif tipo_catalogo == 'tipo_evento':
            obj = HallazgoTipoEvento.query.get(item_id)
        elif tipo_catalogo == 'clasificacion':
            obj = HallazgoClasificacion.query.get(item_id)
        elif tipo_catalogo == 'origen':
            obj = HallazgoOrigenACR.query.get(item_id)
        elif tipo_catalogo == 'area':
            from models import Area
            obj = Area.query.get(item_id)
            
        if not obj:
            return jsonify({'error': 'Registro no encontrado'}), 404
            
        obj.nombre = nuevo_nombre
        if tipo_catalogo == 'area':
            from models import Usuario
            jefe_id = data.get('jefe_id')
            obj.jefe_id = int(jefe_id) if jefe_id else None
            if obj.jefe_id:
                jefe = Usuario.query.get(obj.jefe_id)
                if jefe and not jefe.area_id:
                    jefe.area_id = obj.id

        db.session.commit()
        return jsonify({'success': True, 'nombre': obj.nombre})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@hallazgos_bp.route('/configuraciones/eliminar', methods=['POST'])
@local_login_required
def configuraciones_eliminar():
    from extensions import db

    from sqlalchemy.orm import joinedload
    from models import HallazgoSistemaNormativo, HallazgoTipoEvento, HallazgoClasificacion, HallazgoOrigenACR
    try:
        data = request.get_json()
        tipo_catalogo = data.get('tipo_catalogo')
        item_id = data.get('id')
        
        obj = None
        if tipo_catalogo == 'sistema':
            obj = HallazgoSistemaNormativo.query.get(item_id)
        elif tipo_catalogo == 'tipo_evento':
            obj = HallazgoTipoEvento.query.get(item_id)
        elif tipo_catalogo == 'clasificacion':
            obj = HallazgoClasificacion.query.get(item_id)
        elif tipo_catalogo == 'origen':
            obj = HallazgoOrigenACR.query.get(item_id)
        elif tipo_catalogo == 'area':
            from models import Area
            obj = Area.query.get(item_id)
            
        if not obj:
            return jsonify({'error': 'Registro no encontrado'}), 404
            
        db.session.delete(obj)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'No se pudo eliminar el registro. Es posible que esté en uso por otros elementos del sistema.'}), 500


