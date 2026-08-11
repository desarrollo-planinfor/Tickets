from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
from extensions import db
from models import *
from flask import current_app, jsonify
import os
from modulos.rutas_equipos import cron_alertas_mantenciones, cron_alertas_licencias

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
        from app import app
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
        from app import app
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
        from app import app
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
        from app import app
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
        from app import app
        with app.app_context():
            notificaciones = Notificacion.query.filter_by(estado='pendiente', tipo='email').all()
            
            if not notificaciones:
                return
                
            enviados = 0
            try:
                # Si las credenciales no están configuradas, solo simular
                if SMTP_USER == "tu_correo@planinfor.cl":
                    print(f"[!] SMTP no configurado. Simulando envío de {len(notificaciones)} correos...")
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
                print(f"[OK] Se enviaron {enviados} correos exitosamente.")
                return
                
                
            except Exception as e:
                print(f"[ERROR] Error enviando correo: {str(e)}")
                
    except Exception as e:
        print(f"[ERROR] Error general en cron de correos: {str(e)}")

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






