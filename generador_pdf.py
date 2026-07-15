import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.units import cm

def crear_ficha_pdf(equipo, historial_reciente, ruta_salida):
    """
    Genera un PDF con el formato exacto de la Ficha de Mantención de Equipos.
    """
    doc = SimpleDocTemplate(
        ruta_salida, 
        pagesize=A4,
        rightMargin=1.5*cm,
        leftMargin=1.5*cm,
        topMargin=1.5*cm,
        bottomMargin=1.5*cm
    )
    
    elementos = []
    styles = getSampleStyleSheet()
    
    # Estilos de texto
    estilo_titulo = ParagraphStyle(
        'Titulo',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        alignment=1, # Center
    )
    estilo_seccion = ParagraphStyle(
        'Seccion',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor=colors.black,
    )
    estilo_normal = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
    )
    estilo_negrita = ParagraphStyle(
        'Negrita',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
    )
    
    # Helper para dibujar checkboxes (un simple cuadrado con o sin check)
    def checkbox(checked=False):
        # "[ x ]" o "[   ]" simulado
        return "[ X ]" if checked else "[   ]"

    # Datos
    h = historial_reciente
    
    # --- CABECERA ---
    fecha_registro = datetime.now().strftime('%d-%m-%Y')
    
    # Logo desde imagen
    ruta_logo = os.path.join(os.path.dirname(__file__), 'logo-238x85(2).png')
    if os.path.exists(ruta_logo):
        # Escalar imagen para que quepa en la celda (el original es 238x85)
        logo = Image(ruta_logo, width=3.5*cm, height=1.25*cm)
    else:
        # Fallback a texto si la imagen no se encuentra
        logo = Paragraph('<font color="#82C341" size="16"><b>Plan</b></font><font color="black" size="16"><b>infor</b></font>', styles['Normal'])
    
    cabecera_data = [
        [logo, Paragraph('<b>FICHA DE MANTENCIÓN DE EQUIPOS</b>', estilo_titulo), f"Fecha de registro:\n\n{fecha_registro}"]
    ]
    t_cabecera = Table(cabecera_data, colWidths=[4*cm, 9.5*cm, 4.5*cm], rowHeights=[2*cm])
    t_cabecera.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1.5, colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(t_cabecera)
    elementos.append(Spacer(1, 0.3*cm))
    
    # --- 1. INFORMACIÓN GENERAL ---
    t_seccion1 = Table([[Paragraph('<b>1. INFORMACIÓN GENERAL</b>', estilo_seccion)]], colWidths=[18*cm])
    t_seccion1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#e5e7eb')),
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    elementos.append(t_seccion1)
    
    info_gral_data = [
        ["ID del equipo:", equipo.codigo or ''],
        ["Nombre del equipo:", equipo.nombre or ''],
        ["Marca:", equipo.marca or ''],
        ["Modelo:", equipo.modelo or ''],
        ["Serie:", equipo.serie or ''],
        ["Área:", equipo.area or ''],
        ["Responsable:", equipo.responsable or ''],
        ["Última mantención:", equipo.ultima_mantencion or ''],
        ["Frecuencia de mantención:", equipo.frecuencia_mantencion or ''],
    ]
    t_info = Table(info_gral_data, colWidths=[6*cm, 12*cm])
    t_info.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica'),
        ('FONTNAME', (1,0), (1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
    ]))
    elementos.append(t_info)
    elementos.append(Spacer(1, 0.3*cm))
    
    # --- 2. DATOS DE LA MANTENCIÓN ---
    t_seccion2 = Table([[Paragraph('<b>2. DATOS DE LA MANTENCIÓN</b>', estilo_seccion)]], colWidths=[18*cm])
    t_seccion2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#e5e7eb')),
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    elementos.append(t_seccion2)
    
    es_preventiva = h and h.tipo == 'Preventiva'
    es_correctiva = h and h.tipo == 'Correctiva'
    
    datos_mant_data = [
        ["Fecha de mantención:", h.fecha_realizada.strftime('%d-%m-%Y') if h and h.fecha_realizada else ''],
        ["Tipo de mantención:", f"{checkbox(es_preventiva)} Preventiva", f"{checkbox(es_correctiva)} Correctiva"],
        ["Responsable de la mantención:", h.tecnico if h else '', ""],
        ["Condición del equipo:", equipo.estado or '', ""],
    ]
    t_mant = Table(datos_mant_data, colWidths=[6*cm, 6*cm, 6*cm])
    t_mant.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('SPAN', (1,2), (2,2)), # Span Responsable
        ('SPAN', (1,3), (2,3)), # Span Condicion
        ('SPAN', (1,0), (2,0)), # Span Fecha
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
    ]))
    elementos.append(t_mant)
    elementos.append(Spacer(1, 0.3*cm))
    
    # --- 3. ACTIVIDADES REALIZADAS ---
    t_seccion3 = Table([[Paragraph('<b>3. ACTIVIDADES REALIZADAS</b>', estilo_seccion)]], colWidths=[18*cm])
    t_seccion3.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#e5e7eb')),
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    elementos.append(t_seccion3)
    
    # Trataremos de poner las primeras lineas de observacion si parecen actividades
    # O simplemente dejaremos espacio
    obs_cruda = h.observaciones if h and h.observaciones else ''
    actividades = []
    obs_tecnicas = []
    resultados_pruebas = []
    obs_general = obs_cruda
    
    if "--- Detalles Adicionales ---" in obs_cruda:
        partes = obs_cruda.split("--- Detalles Adicionales ---")
        obs_general = partes[0].strip()
        detalles = partes[1].strip().split('\n')
        
        for d in detalles:
            d_clean = d.replace("•", "").replace("", "").strip()
            # No importa la categoría elegida, el usuario quiere que TODAS aparezcan 
            # en las filas N°1, N°2 y N°3 de ACTIVIDADES REALIZADAS.
            if ":" in d_clean:
                actividades.append(d_clean.split(":", 1)[1].strip())
            elif d_clean:
                actividades.append(d_clean)
                
    act1 = actividades[0] if len(actividades) > 0 else ''
    act2 = actividades[1] if len(actividades) > 1 else ''
    act3 = actividades[2] if len(actividades) > 2 else ''
    
    act_data = [
        ["N°1:", Paragraph(act1, estilo_normal)],
        ["N°2:", Paragraph(act2, estilo_normal)],
        ["N°3:", Paragraph(act3, estilo_normal)],
    ]
    t_act = Table(act_data, colWidths=[2*cm, 16*cm])
    t_act.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
    ]))
    elementos.append(t_act)
    elementos.append(Spacer(1, 0.3*cm))
    
    # --- 4. OBSERVACIONES TÉCNICAS ---
    t_seccion4 = Table([[Paragraph('<b>4. OBSERVACIONES TÉCNICAS</b>', estilo_seccion)]], colWidths=[18*cm])
    t_seccion4.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#e5e7eb')),
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    elementos.append(t_seccion4)
    
    obs_final = obs_general
    if obs_tecnicas:
        if obs_final:
            obs_final += "\n\n" + "\n".join(obs_tecnicas)
        else:
            obs_final = "\n".join(obs_tecnicas)
            
    # Reemplazar saltos de linea para que ReportLab los renderice correctamente
    obs_final_html = obs_final.replace('\n', '<br/>')
            
    t_obs = Table([[Paragraph(obs_final_html, estilo_normal)]], colWidths=[18*cm], rowHeights=[2.5*cm])
    t_obs.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
    ]))
    elementos.append(t_obs)
    elementos.append(Spacer(1, 0.3*cm))
    
    # --- 5. EVALUACIÓN DEL ESTADO FINAL ---
    t_seccion5 = Table([[Paragraph('<b>5. EVALUACIÓN DEL ESTADO FINAL</b>', estilo_seccion)]], colWidths=[18*cm])
    t_seccion5.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#e5e7eb')),
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    elementos.append(t_seccion5)
    
    res_final = "\n".join(resultados_pruebas) if resultados_pruebas else ""
    res_final_html = res_final.replace('\n', '<br/>')
    eval_data = [
        ["Prueba de funcionamiento:", f"{checkbox(True)} Realizada", f"{checkbox(False)} No realizada"],
        ["Resultados de pruebas:", Paragraph(res_final_html, estilo_normal), ""],
        ["Próxima mantención:", equipo.proxima_mantencion or '', ""],
    ]
    t_eval = Table(eval_data, colWidths=[6*cm, 6*cm, 6*cm])
    t_eval.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('SPAN', (1,1), (2,1)),
        ('SPAN', (1,2), (2,2)),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('ALIGN', (1,0), (2,0), 'CENTER'),
    ]))
    elementos.append(t_eval)
    elementos.append(Spacer(1, 0.3*cm))
    
    # --- 6. FIRMAS ---
    t_seccion6 = Table([[Paragraph('<b>6. FIRMAS</b>', estilo_seccion)]], colWidths=[18*cm])
    t_seccion6.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#e5e7eb')),
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
    ]))
    elementos.append(t_seccion6)
    
    firmas_data = [
        ["Nombre", "Cargo", "Fecha", "Firma"],
        [h.tecnico if h else '', "Soporte TI.", h.fecha_realizada.strftime('%d-%m-%Y') if h and h.fecha_realizada else '', ""],
    ]
    t_firmas = Table(firmas_data, colWidths=[6.5*cm, 4.5*cm, 3.5*cm, 3.5*cm], rowHeights=[0.8*cm, 1.5*cm])
    t_firmas.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(t_firmas)
    
    doc.build(elementos)
    return ruta_salida
