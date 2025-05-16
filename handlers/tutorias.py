import telebot
from telebot import types
import sys
import os
import datetime
import time  # Faltaba esta importación
import logging  # Para usar logger

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

# Referencias externas necesarias
user_states = {}
user_data = {}
estados_timestamp = {}  

def register_handlers(bot):
    """Registra todos los handlers de tutorías"""
    
    @bot.message_handler(commands=['tutoria'])
    def handle_tutoria_command(message):
        """Maneja el comando /tutoria para buscar profesores de las mismas asignaturas"""
        chat_id = message.chat.id
        user = get_user_by_telegram_id(message.from_user.id)
        
        if not user:
            bot.send_message(
                chat_id,
                "❌ No estás registrado. Usa /start para registrarte."
            )
            return
        
        if user['Tipo'] != 'estudiante':
            bot.send_message(
                chat_id,
                "⚠️ Esta funcionalidad está disponible solo para estudiantes."
            )
            return
        
        # Obtener las asignaturas en las que está matriculado el estudiante
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT a.Id_asignatura, a.Nombre as Asignatura, c.Nombre_carrera as Carrera  
            FROM Matriculas m
            JOIN Asignaturas a ON m.Id_asignatura = a.Id_asignatura
            LEFT JOIN Carreras c ON a.Id_carrera = c.id_carrera
            WHERE m.Id_usuario = ?
        """, (user['Id_usuario'],))
        
        asignaturas = cursor.fetchall()
        
        if not asignaturas:
            bot.send_message(
                chat_id,
                "❌ No estás matriculado en ninguna asignatura.\n"
                "Usa /registrar_otra_carrera para matricularte en alguna asignatura."
            )
            return
        
        # Obtener los profesores que imparten esas mismas asignaturas
        asignaturas_ids = [a['Id_asignatura'] for a in asignaturas]
        placeholders = ','.join(['?'] * len(asignaturas_ids))
        
        cursor.execute(f"""
            SELECT DISTINCT u.Id_usuario, u.Nombre, u.Email_UGR, u.horario, 
                   GROUP_CONCAT(DISTINCT a.Nombre) as Asignaturas
            FROM Usuarios u
            JOIN Matriculas m ON u.Id_usuario = m.Id_usuario
            JOIN Asignaturas a ON m.Id_asignatura = a.Id_asignatura
            WHERE u.Tipo = 'profesor' AND m.Id_asignatura IN ({placeholders})
            GROUP BY u.Id_usuario
            ORDER BY u.Nombre
        """, asignaturas_ids)
        
        profesores = cursor.fetchall()
        conn.close()
        
        if not profesores:
            bot.send_message(
                chat_id,
                "❌ No se encontraron profesores para tus asignaturas matriculadas.\n"
                "Consulta con tu coordinador de curso."
            )
            return
        
        # Mostrar lista de profesores con sus asignaturas
        mensaje = "👨‍🏫 *Profesores disponibles para tus asignaturas:*\n\n"
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        for i, prof in enumerate(profesores, 1):
            horario = prof['horario'] if prof['horario'] else "No especificado"
            mensaje += (
                f"{i}. *{prof['Nombre']}*\n"
                f"   📧 Email: {prof['Email_UGR']}\n"
                f"   📚 Asignaturas: {prof['Asignaturas']}\n"
                f"   🕗 Horario: {horario}\n\n"
            )
            
            # Añadir botón para contactar con este profesor
            markup.add(types.InlineKeyboardButton(
                f"Contactar a {prof['Nombre'][:15]}...",
                callback_data=f"contactar_prof_{prof['Id_usuario']}"
            ))
        
        bot.send_message(
            chat_id,
            mensaje,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        user_states[chat_id] = "seleccionando_profesor_tutoria"
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "seleccionando_area_tutoria" and call.data.startswith("tutoria_area_"))
    def handle_area_tutoria(call):
        chat_id = call.message.chat.id
        area_id = int(call.data.split("_")[2])
        
        user_data[chat_id] = {"area_id": area_id}
        
        # Mostrar carreras del área seleccionada
        carreras = get_carreras_by_area(area_id)
        markup = types.InlineKeyboardMarkup()
        
        for carrera in carreras:
            markup.add(types.InlineKeyboardButton(
                text=carrera['Nombre_carrera'],
                callback_data=f"tutoria_carrera_{carrera['id_carrera']}"
            ))
        
        bot.send_message(
            chat_id,
            "✅ Área seleccionada.\n\n"
            "Ahora, selecciona la carrera:",
            reply_markup=markup
        )
        user_states[chat_id] = "seleccionando_carrera_tutoria"
        
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "seleccionando_carrera_tutoria" and call.data.startswith("tutoria_carrera_"))
    def handle_carrera_tutoria(call):
        chat_id = call.message.chat.id
        carrera_id = int(call.data.split("_")[2])
        
        user_data[chat_id]["carrera_id"] = carrera_id
        
        # Buscar profesores de esta carrera
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query para buscar profesores que dan clase en esta carrera
        cursor.execute("""
            SELECT DISTINCT u.Id_usuario, u.Nombre, u.Email_UGR, u.horario
            FROM Usuarios u
            JOIN Matriculas m ON u.Id_usuario = m.Id_usuario
            JOIN Asignaturas a ON m.Id_asignatura = a.Id_asignatura
            WHERE u.Tipo = 'profesor' AND a.Id_carrera = ?
            ORDER BY u.Nombre
        """, (carrera_id,))
        
        profesores = cursor.fetchall()
        conn.close()
        
        if not profesores:
            bot.send_message(
                chat_id,
                "❌ No se encontraron profesores para esta carrera.\n"
                "Intenta con otra carrera o área académica."
            )
            user_states.pop(chat_id, None)
            user_data.pop(chat_id, None)
            bot.answer_callback_query(call.id)
            return
        
        # Mostrar lista de profesores
        mensaje = "👨‍🏫 *Profesores disponibles:*\n\n"
        
        for i, prof in enumerate(profesores, 1):
            horario = prof['horario'] if prof['horario'] else "No especificado"
            mensaje += (
                f"{i}. *{prof['Nombre']}*\n"
                f"   📧 Email: {prof['Email_UGR']}\n"
                f"   🕗 Horario: {horario}\n\n"
            )
            
            # Crear botones para solicitar tutorías
            if i == 1:
                markup = types.InlineKeyboardMarkup(row_width=2)
                for p in profesores:
                    markup.add(types.InlineKeyboardButton(
                        f"Contactar a {p['Nombre'][:15]}...",
                        callback_data=f"contactar_prof_{p['Id_usuario']}"
                    ))
        
        bot.send_message(
            chat_id,
            mensaje,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        user_states[chat_id] = "seleccionando_profesor_tutoria"
        
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "seleccionando_profesor_tutoria" and call.data.startswith("contactar_prof_"))
    def handle_contactar_profesor(call):
        chat_id = call.message.chat.id
        profesor_id = int(call.data.split("_")[2])
        
        user_data[chat_id] = user_data.get(chat_id, {})
        user_data[chat_id]["profesor_id"] = profesor_id
        
        # Obtener información del profesor
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Usuarios WHERE Id_usuario = ?", (profesor_id,))
        profesor = cursor.fetchone()
        
        # Buscar grupos de tutoría de este profesor
        cursor.execute("""
            SELECT * FROM Grupos_tutoria 
            WHERE Id_usuario = ? AND Tipo_sala = 'publica'
        """, (profesor_id,))
        grupos = cursor.fetchall()
        conn.close()
        
        if grupos:
            # Si hay grupos disponibles, mostrar enlaces
            mensaje = (
                f"✅ El profesor *{profesor['Nombre']}* tiene grupos de tutoría disponibles:\n\n"
            )
            
            for grupo in grupos:
                message_text = f"• [Grupo de tutoría]({grupo['group_link']})"
                mensaje += message_text + "\n"
            
            mensaje += "\nPuedes unirte a un grupo para consultar tus dudas."
            
            bot.send_message(
                chat_id,
                mensaje,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        else:
            # Si no hay grupos, ofrecer solicitar una tutoría por email
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "📝 Solicitar tutoría por email",
                callback_data=f"solicitar_email_{profesor_id}"
            ))
            
            bot.send_message(
                chat_id,
                f"⚠️ El profesor *{profesor['Nombre']}* no tiene grupos de tutoría configurados.\n\n"
                f"Puedes solicitar una tutoría por email.",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        
        # Limpiar estados
        user_states.pop(chat_id, None)
        
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("solicitar_email_"))
    def handle_solicitar_email(call):
        chat_id = call.message.chat.id
        profesor_id = int(call.data.split("_")[2])
        
        # Obtener información del profesor y del estudiante
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM Usuarios WHERE Id_usuario = ?", (profesor_id,))
        profesor = cursor.fetchone()
        
        estudiante = get_user_by_telegram_id(call.from_user.id)
        conn.close()
        
        if profesor and estudiante:
            # Preparar plantilla de correo
            now = datetime.datetime.now()
            fecha_hora = now.strftime("%d/%m/%Y %H:%M")
            
            template = (
                f"Asunto: Solicitud de Tutoría - {estudiante['Nombre']}\n\n"
                f"Estimado/a {profesor['Nombre']},\n\n"
                f"Me dirijo a usted para solicitar una tutoría. Soy {estudiante['Nombre']}, "
                f"estudiante registrado en el sistema de tutorías de la UGR.\n\n"
                f"Me gustaría concertar una tutoría en su horario disponible para resolver algunas dudas.\n\n"
                f"Quedo a la espera de su respuesta.\n\n"
                f"Atentamente,\n{estudiante['Nombre']}\n"
                f"{estudiante['Email_UGR']}\n\n"
                f"Mensaje generado automáticamente desde el Bot de Tutorías UGR el {fecha_hora}"
            )
            
            # Mostrar la plantilla al estudiante
            bot.send_message(
                chat_id,
                f"📧 *Plantilla de correo para solicitar tutoría:*\n\n"
                f"```\n{template}\n```\n\n"
                f"Puedes copiar este mensaje y enviarlo a: {profesor['Email_UGR']}",
                parse_mode="Markdown"
            )
        
        bot.answer_callback_query(call.id)
    
    def solicitar_valoracion(user_id):
        markup = types.ReplyKeyboardMarkup(row_width=5, resize_keyboard=True)
    
        markup.add(
            types.KeyboardButton("1"),
            types.KeyboardButton("2"),
            types.KeyboardButton("3"),
            types.KeyboardButton("4"),
            types.KeyboardButton("5")
        )
        
        bot.send_message(
            user_id,
            "🌟 *Valora tu experiencia*\n\n"
            "Del 1 al 5, siendo 5 la mejor puntuación, "
            "¿cómo valorarías la tutoría recibida?",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    
    @bot.message_handler(commands=['crear_grupo_tutoria'])
    def handle_crear_grupo_tutoria(message):
        """Guía simple para crear un grupo de tutoría en Telegram"""
        chat_id = message.chat.id
        user = get_user_by_telegram_id(message.from_user.id)
        
        # Verificar si el usuario es profesor
        if not user:
            bot.send_message(
                chat_id,
                "❌ No estás registrado. Usa /start para registrarte."
            )
            return
        
        if user['Tipo'] != 'profesor':
            bot.send_message(
                chat_id,
                "⚠️ Lo siento, la creación de grupos de tutoría es una función exclusiva para profesores."
            )
            return
        
        # Instrucciones simples para crear un grupo
        texto_guia = (
            "📝 *GUÍA RÁPIDA: CREAR GRUPO DE TUTORÍA*\n\n"
            
            "1️⃣ *Crear grupo en Telegram*\n"
            "• Pulsa el icono de lápiz o '+' en Telegram\n"
            "• Selecciona 'Nuevo grupo'\n"
            "• Dale un nombre descriptivo (ej: 'Tutorías Programación')\n\n"
            
            "2️⃣ *Añadir el bot*\n"
            "• En el grupo, pulsa '+' o 'Añadir miembro'\n"
            "• Busca y añade @UGRTutoriasBot\n\n"
            
            "3️⃣ *Hacer administrador al bot*\n"
            "• Pulsa el nombre del grupo en la parte superior\n"
            "• Selecciona 'Administradores'\n" 
            "• Añade al bot como administrador\n"
            "• Activa TODOS los permisos\n\n"
            
            "👉 Ya puedes usar el bot en el grupo para gestionar tutorías"
        )
        
        # Enviar guía
        bot.send_message(
            chat_id,
            texto_guia,
            parse_mode="Markdown"
        )
    
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id, {}).get("estado") == "confirmando_valoracion")
    def procesar_confirmacion_valoracion(message):
        """Procesa la decisión del usuario sobre si desea valorar o no."""
        user_id = message.from_user.id
        opcion = message.text.strip()
        
        # Recuperar el estado actual
        estado = user_states.get(user_id, {})
        chat_pendiente = estado.get("chat_pendiente_expulsion")
        contraparte_id = estado.get("contraparte_id")
        
        if opcion == "✅ Valorar tutoría":
            # Actualizar estado para solicitar puntuación
            user_states[user_id]["estado"] = "valorando_tutoria"
            
            # Enviar mensaje con botones de valoración
            solicitar_valoracion(user_id)
        else:
            # El usuario decidió no valorar
            bot.send_message(
                user_id,
                "✓ Gracias por usar el sistema de tutorías.",
                reply_markup=types.ReplyKeyboardRemove()
            )
            
            # Si hay expulsión pendiente, realizarla ahora
            if chat_pendiente:
                try:
                    bot.send_message(
                        chat_pendiente,
                        f"El estudiante ha finalizado la tutoría."
                    )
                    bot.ban_chat_member(chat_pendiente, user_id, until_date=int(time.time() + 60))
                except Exception as e:
                    logger.error(f"Error expulsando al estudiante: {e}")
            
            # Limpiar estado
            if user_id in user_states:
                del user_states[user_id]
            if user_id in estados_timestamp:
                del estados_timestamp[user_id]