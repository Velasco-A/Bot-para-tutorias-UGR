import telebot
from telebot import types
import sys
import os
import datetime
import time  # Faltaba esta importación
import logging  # Para usar logger

# Importar esta función al principio del archivo
from grupo_handlers.utils import escape_markdown

# Configurar logger
logger = logging.getLogger(__name__)

# Añadir directorio padre al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.queries import (
    get_user_by_telegram_id,
    get_carreras_by_area,
    get_matriculas_by_user,
    get_db_connection
)

# Añadir la función directamente en este archivo
def escape_markdown(text: str) -> str:
    """Escapa caracteres especiales de Markdown para evitar errores de formato"""
    if not text:
        return ""
        
    # Caracteres que necesitan escape en Markdown
    markdown_chars = ['_', '*', '`', '[', ']', '(', ')', '#', '+', '-', '.', '!']
    
    # Reemplazar cada caracter especial con su versión escapada
    result = text
    for char in markdown_chars:
        result = result.replace(char, '\\' + char)
        
    return result






# Referencias externas necesarias
user_states = {}
user_data = {}
estados_timestamp = {}  

def register_handlers(bot):
    """Registra todos los handlers de tutorías"""
    
    @bot.message_handler(commands=['tutoria'])
    def handle_tutoria_command(message):
        """Muestra profesores y salas disponibles para las asignaturas del estudiante"""
        chat_id = message.chat.id
        user = get_user_by_telegram_id(message.from_user.id)
        
        if not user:
            bot.send_message(chat_id, "❌ No estás registrado. Usa /start para registrarte.")
            return
        
        if user['Tipo'] != 'estudiante':
            bot.send_message(chat_id, "⚠️ Esta funcionalidad está disponible solo para estudiantes.")
            return
        
        # Obtener las asignaturas del estudiante
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT a.Id_asignatura, a.Nombre as Asignatura
            FROM Matriculas m
            JOIN Asignaturas a ON m.Id_asignatura = a.Id_asignatura
            WHERE m.Id_usuario = ?
        """, (user['Id_usuario'],))
        
        asignaturas = cursor.fetchall()
        
        if not asignaturas:
            bot.send_message(chat_id, "❌ No estás matriculado en ninguna asignatura.")
            conn.close()
            return
        
        # Obtener profesores y salas para asignaturas del estudiante
        asignaturas_ids = [a['Id_asignatura'] for a in asignaturas]
        placeholders = ','.join(['?'] * len(asignaturas_ids))
        
        cursor.execute(f"""
            SELECT 
                u.Id_usuario, 
                u.Nombre, 
                u.Apellidos,
                u.Email_UGR, 
                u.horario, 
                a.Id_asignatura,
                a.Nombre as NombreAsignatura,
                g.id_sala,
                g.Nombre_sala,
                g.Proposito_sala,
                g.Enlace_invitacion,
                g.Tipo_sala
            FROM Usuarios u
            JOIN Matriculas m ON u.Id_usuario = m.Id_usuario
            JOIN Asignaturas a ON m.Id_asignatura = a.Id_asignatura
            LEFT JOIN Grupos_tutoria g ON (u.Id_usuario = g.Id_usuario AND (g.Id_asignatura = a.Id_asignatura OR g.Id_asignatura IS NULL))
            WHERE u.Tipo = 'profesor' AND m.Id_asignatura IN ({placeholders})
            ORDER BY u.Nombre, a.Nombre
        """, asignaturas_ids)
        
        resultados = cursor.fetchall()
        conn.close()
        
        if not resultados:
            bot.send_message(chat_id, "❌ No se encontraron profesores para tus asignaturas.")
            return
        
        # Organizar resultados por profesor > asignatura > salas
        profesores = {}
        
        for r in resultados:
            profesor_id = r['Id_usuario']
            
            if profesor_id not in profesores:
                profesores[profesor_id] = {
                    'nombre': f"{r['Nombre']} {r['Apellidos'] or ''}",
                    'email': r['Email_UGR'],
                    'horario': r['horario'] or "No especificado",
                    'asignaturas': {}
                }
            
            asig_id = r['Id_asignatura']
            if asig_id not in profesores[profesor_id]['asignaturas']:
                profesores[profesor_id]['asignaturas'][asig_id] = {
                    'nombre': r['NombreAsignatura'],
                    'salas': []
                }
            
            if r['id_sala']:
                # Evitar duplicados
                sala_existente = False
                for sala in profesores[profesor_id]['asignaturas'][asig_id]['salas']:
                    if sala['id'] == r['id_sala']:
                        sala_existente = True
                        break
                
                if not sala_existente:
                    proposito = r['Proposito_sala'] or "General"
                    proposito_texto = {
                        'individual': "Tutorías individuales",
                        'grupal': "Tutorías grupales",
                        'avisos': "Canal de avisos"
                    }.get(proposito, proposito)
                    
                    profesores[profesor_id]['asignaturas'][asig_id]['salas'].append({
                        'id': r['id_sala'],
                        'nombre': r['Nombre_sala'],
                        'proposito': proposito_texto,
                        'proposito_original': proposito,
                        'enlace': r['Enlace_invitacion'],
                        'tipo': r['Tipo_sala']
                    })
        
        # Generar mensaje
        mensaje = "👨‍🏫 *Profesores y salas disponibles:*\n\n"
        
        # Inicializar botones
        markup = types.InlineKeyboardMarkup(row_width=1)
        botones_salas = []
        
        for profesor_id, prof_info in profesores.items():
            mensaje += f"*{escape_markdown(prof_info['nombre'])}*\n"
            mensaje += f"📧 Email: {escape_markdown(prof_info['email'])}\n"
            mensaje += f"🕗 Horario: {escape_markdown(prof_info['horario'])}\n\n"
            
            for asig_id, asig_info in prof_info['asignaturas'].items():
                mensaje += f"📚 *{escape_markdown(asig_info['nombre'])}*\n"
                
                if asig_info['salas']:
                    for sala in asig_info['salas']:
                        mensaje += f"   • *{escape_markdown(sala['nombre'])}*: {sala['proposito']}\n"
                        
                        # Añadir botón según tipo de sala
                        if sala['proposito_original'] == 'avisos':
                            # Para salas de avisos: enlace directo
                            if sala['enlace']:
                                botones_salas.append({
                                    'texto': f"📢 Unirse a canal: {sala['nombre']}",
                                    'url': sala['enlace'],
                                    'callback': None
                                })
                        else:
                            # Para tutorías individuales: verificación previa
                            botones_salas.append({
                                'texto': f"👨‍🏫 Solicitar tutoría: {sala['nombre']}",
                                'url': None,
                                'callback': f"solicitar_sala_{sala['id']}_{profesor_id}"
                            })
                else:
                    mensaje += f"   • No hay salas disponibles para esta asignatura\n"
                
                mensaje += "\n"
        
        # Crear botones
        for boton in botones_salas:
            if boton['url']:
                markup.add(types.InlineKeyboardButton(
                    text=boton['texto'],
                    url=boton['url']
                ))
            else:
                markup.add(types.InlineKeyboardButton(
                    text=boton['texto'],
                    callback_data=boton['callback']
                ))
        
        # Enviar mensaje
        bot.send_message(
            chat_id, 
            mensaje, 
            reply_markup=markup,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("solicitar_sala_"))
    def handle_solicitar_sala(call):
        """Gestiona la solicitud de acceso a una sala de tutoría individual"""
        chat_id = call.message.chat.id
        data = call.data.split("_")
        sala_id = int(data[2])
        profesor_id = int(data[3])
        
        # Obtener datos del estudiante
        estudiante = get_user_by_telegram_id(call.from_user.id)
        
        if not estudiante:
            bot.send_message(chat_id, "❌ Error: No se encontró tu registro de usuario.")
            bot.answer_callback_query(call.id)
            return
        
        # Obtener datos de la sala y profesor
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT g.*, u.Nombre as NombreProfesor, u.TelegramID, u.horario
            FROM Grupos_tutoria g
            JOIN Usuarios u ON g.Id_usuario = u.Id_usuario
            WHERE g.id_sala = ? AND g.Id_usuario = ?
        """, (sala_id, profesor_id))
        
        sala = cursor.fetchone()
        conn.close()
        
        if not sala:
            bot.send_message(chat_id, "❌ La sala solicitada no está disponible.")
            bot.answer_callback_query(call.id)
            return
        
        # Verificar si es una sala de tutorías individuales
        if sala['Proposito_sala'] != 'individual':
            # Si no es tutoría individual, proporcionar enlace directo
            if sala['Enlace_invitacion']:
                bot.send_message(
                    chat_id,
                    f"✅ Puedes unirte directamente a la sala *{escape_markdown(sala['Nombre_sala'])}*:",
                    parse_mode="Markdown"
                )
                bot.send_message(
                    chat_id,
                    f"[Unirse a la sala]({sala['Enlace_invitacion']})",
                    parse_mode="Markdown",
                    disable_web_page_preview=False
                )
            else:
                bot.send_message(chat_id, "❌ El enlace de esta sala no está disponible.")
            
            bot.answer_callback_query(call.id)
            return
        
        # Para tutorías individuales, verificar el horario del profesor
        hora_actual = datetime.datetime.now().time()
        dia_actual = datetime.datetime.now().strftime('%A').lower()  # día en inglés, minúsculas
        
        # Traducción de días
        traduccion_dias = {
            'monday': 'lunes',
            'tuesday': 'martes',
            'wednesday': 'miércoles',
            'thursday': 'jueves',
            'friday': 'viernes',
            'saturday': 'sábado',
            'sunday': 'domingo'
        }
        
        dia_actual_es = traduccion_dias.get(dia_actual, dia_actual)
        
        # Verificar si estamos en horario de tutoría
        en_horario = False
        horario_texto = sala['horario'] or ""
        
        # Formato esperado: "lunes 10:00-12:00, miércoles 16:00-18:00"
        if horario_texto:
            bloques = horario_texto.split(',')
            for bloque in bloques:
                bloque = bloque.strip()
                if not bloque:
                    continue
                
                partes = bloque.split(' ')
                if len(partes) >= 2:
                    dia = partes[0].lower()
                    rango = partes[1]
                    
                    if dia == dia_actual_es and '-' in rango:
                        horas = rango.split('-')
                        if len(horas) == 2:
                            hora_inicio = datetime.datetime.strptime(horas[0], "%H:%M").time()
                            hora_fin = datetime.datetime.strptime(horas[1], "%H:%M").time()
                            
                            if hora_inicio <= hora_actual <= hora_fin:
                                en_horario = True
                                break
        
        if not en_horario:
            bot.send_message(
                chat_id,
                f"⚠️ Lo siento, el profesor *{escape_markdown(sala['NombreProfesor'])}* "
                f"no está en horario de tutorías ahora mismo.\n\n"
                f"Horario disponible: *{escape_markdown(horario_texto)}*\n\n"
                f"Por favor, intenta acceder durante el horario establecido.",
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)
            return
        
        # Estamos en horario, enviar solicitud al profesor
        if not sala['TelegramID']:
            bot.send_message(
                chat_id,
                "❌ No se puede contactar con el profesor. Por favor, usa el email."
            )
            bot.answer_callback_query(call.id)
            return
        
        # Notificar al estudiante
        bot.send_message(
            chat_id,
            f"✅ Solicitud enviada al profesor *{escape_markdown(sala['NombreProfesor'])}*.\n\n"
            f"Espera mientras se procesa tu solicitud. Recibirás una notificación cuando "
            f"el profesor responda.",
            parse_mode="Markdown"
        )
        
        # Enviar solicitud al profesor
        markup = types.InlineKeyboardMarkup(row_width=3)
        markup.add(
            types.InlineKeyboardButton("✅ Aceptar", callback_data=f"aprobar_tut_{estudiante['Id_usuario']}_{sala_id}"),
            types.InlineKeyboardButton("⏳ En espera", callback_data=f"espera_tut_{estudiante['Id_usuario']}_{sala_id}"),
            types.InlineKeyboardButton("❌ Rechazar", callback_data=f"rechazar_tut_{estudiante['Id_usuario']}_{sala_id}")
        )
        
        bot.send_message(
            sala['TelegramID'],
            f"🔔 *Solicitud de tutoría*\n\n"
            f"El estudiante *{escape_markdown(estudiante['Nombre'])} {escape_markdown(estudiante['Apellidos'] or '')}* "
            f"solicita acceso a tu sala de tutorías *{escape_markdown(sala['Nombre_sala'])}*.\n\n"
            f"¿Deseas permitir el acceso?",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        
        bot.answer_callback_query(call.id)
    
    # Handlers para respuestas del profesor
    @bot.callback_query_handler(func=lambda call: call.data.startswith(("aprobar_tut_", "espera_tut_", "rechazar_tut_")))
    def handle_respuesta_profesor(call):
        """Procesa la respuesta del profesor a una solicitud de tutoría"""
        chat_id = call.message.chat.id
        action = call.data.split("_")[0]
        estudiante_id = int(call.data.split("_")[2])
        sala_id = int(call.data.split("_")[3])
        
        # Obtener datos de la sala y del estudiante
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM Grupos_tutoria WHERE id_sala = ?", (sala_id,))
        sala = cursor.fetchone()
        
        cursor.execute("SELECT * FROM Usuarios WHERE Id_usuario = ?", (estudiante_id,))
        estudiante = cursor.fetchone()
        
        conn.close()
        
        if not sala or not estudiante or not estudiante['TelegramID']:
            bot.send_message(chat_id, "❌ No se pudo procesar la solicitud.")
            bot.answer_callback_query(call.id)
            return
        
        respuesta = ""
        
        if action == "aprobar":
            # Proporcionar enlace al estudiante
            respuesta = (
                f"✅ El profesor ha *aprobado* tu solicitud de tutoría.\n\n"
                f"Puedes unirte a la sala ahora: [Acceder a la tutoría]({sala['Enlace_invitacion']})"
            )
            
            # Confirmar al profesor
            bot.edit_message_text(
                "✅ Has aceptado la solicitud. Se ha notificado al estudiante.",
                chat_id=chat_id,
                message_id=call.message.message_id
            )
            
        elif action == "espera":
            # Notificar al estudiante que debe esperar
            respuesta = (
                f"⏳ Tu solicitud está *en espera*.\n\n"
                f"El profesor te atenderá cuando termine con las tutorías en curso."
                f"Recibirás otra notificación cuando sea tu turno."
            )
            
            # Actualizar mensaje del profesor
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Aceptar ahora", callback_data=f"aprobar_tut_{estudiante_id}_{sala_id}"),
                types.InlineKeyboardButton("❌ Rechazar", callback_data=f"rechazar_tut_{estudiante_id}_{sala_id}")
            )
            
            bot.edit_message_text(
                f"⏳ Has puesto en espera la solicitud de *{escape_markdown(estudiante['Nombre'])}*.\n"
                f"Utiliza los botones cuando estés listo para atenderle.",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )
            
        elif action == "rechazar":
            # Notificar al estudiante del rechazo
            respuesta = (
                f"❌ Tu solicitud de tutoría ha sido *rechazada*.\n\n"
                f"El profesor no puede atenderte en este momento. "
                f"Por favor, intenta de nuevo más tarde o contacta por email."
            )
            
            # Confirmar al profesor
            bot.edit_message_text(
                "❌ Has rechazado la solicitud. Se ha notificado al estudiante.",
                chat_id=chat_id,
                message_id=call.message.message_id
            )
        
        # Enviar respuesta al estudiante
        bot.send_message(
            estudiante['TelegramID'],
            respuesta,
            parse_mode="Markdown",
            disable_web_page_preview=False
        )
        
        bot.answer_callback_query(call.id)