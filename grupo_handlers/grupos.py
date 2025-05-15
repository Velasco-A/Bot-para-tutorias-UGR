import telebot
from telebot import types
import re
import sys
import os
import time
import datetime
import logging
from utils.horarios_utils import formatear_horario

# Añadir directorio padre al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from grupo_handlers.valoraciones import iniciar_valoracion_profesor

from db.queries import (
    get_user_by_telegram_id, 
    get_db_connection,
    crear_grupo_tutoria,
    actualizar_grupo_tutoria,
    obtener_grupos_profesor,
    obtener_grupo_por_id,
    verificar_estudiante_matriculado,
    añadir_estudiante_grupo,
    get_user_by_id,
    get_asignaturas_by_carrera,
    get_matriculas_by_user,
    obtener_profesores_por_asignaturas,
    obtener_grupos_por_asignaturas,
    obtener_grupos_profesor_por_asignatura
)

# Referencias externas necesarias
user_states = {}
user_data = {}
estados_timestamp = {}

# Configurar logger
logger = logging.getLogger("grupos")
if not logger.handlers:
    handler = logging.FileHandler("grupos.log")
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def register_handlers(bot):
    # Inicializar tablas
    inicializar_tablas_grupo()
    
    """Registra los handlers para gestionar grupos de tutoría"""
    
    def reset_user(chat_id):
        """Reinicia el estado del usuario"""
        if chat_id in user_states:
            del user_states[chat_id]
        if chat_id in user_data:
            del user_data[chat_id]
        if chat_id in estados_timestamp:
            del estados_timestamp[chat_id]
    
    @bot.message_handler(commands=["crear_grupo"])
    def handle_crear_grupo(message):
        """Inicia el proceso de creación de un grupo"""
        chat_id = message.chat.id
        user = get_user_by_telegram_id(message.from_user.id)
        
        # Verificar que sea profesor
        if not user or user['Tipo'] != 'profesor':
            bot.send_message(chat_id, "⚠️ Solo los profesores pueden crear grupos de tutoría.")
            return
        
        # Iniciar proceso
        bot.send_message(
            chat_id,
            "🏫 *Crear Grupo de Tutoría*\n\n"
            "Para crear un grupo necesito algunos datos.\n\n"
            "Primero, ¿qué *nombre* quieres darle al grupo?\n"
            "Ejemplo: 'Tutorías Sistemas Operativos' o 'Avisos Matemáticas II'",
            parse_mode="Markdown"
        )
        
        # Guardar estado
        user_states[chat_id] = "crear_grupo_nombre"
        user_data[chat_id] = {"profesor_id": user['Id_usuario']}
        estados_timestamp[chat_id] = time.time()
    
    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "crear_grupo_nombre")
    def handle_grupo_nombre(message):
        """Procesa el nombre del grupo"""
        chat_id = message.chat.id
        nombre = message.text.strip()
        
        if len(nombre) < 3:
            bot.send_message(chat_id, "❌ El nombre debe tener al menos 3 caracteres.")
            return
        
        user_data[chat_id]["nombre_grupo"] = nombre
        
        # Solicitar tipo de grupo
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔒 Privada (tú controlas quién accede)", callback_data="grupo_tipo_privada"),
            types.InlineKeyboardButton("🔓 Pública (acceso automático para estudiantes matriculados)", callback_data="grupo_tipo_publica")
        )
        
        bot.send_message(
            chat_id,
            "🔐 *Tipo de Sala*\n\n"
            "¿Qué tipo de sala quieres crear?",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        user_states[chat_id] = "crear_grupo_tipo"
        estados_timestamp[chat_id] = time.time()
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "crear_grupo_tipo" and call.data.startswith("grupo_tipo_"))
    def handle_grupo_tipo(call):
        """Procesa el tipo de grupo seleccionado"""
        chat_id = call.message.chat.id
        tipo = call.data.replace("grupo_tipo_", "")
        
        user_data[chat_id]["tipo_grupo"] = tipo
        
        # Solicitar asignatura asociada
        profesor_id = user_data[chat_id]["profesor_id"]
        
        # Obtener asignaturas del profesor
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT a.* 
            FROM Asignaturas a
            JOIN Matriculas m ON a.Id_asignatura = m.Id_asignatura
            WHERE m.Id_usuario = ?
        """, (profesor_id,))
        asignaturas = cursor.fetchall()
        conn.close()
        
        if not asignaturas:
            bot.send_message(
                chat_id,
                "❌ No tienes asignaturas asignadas. Contacta con el administrador."
            )
            reset_user(chat_id)
            return
        
        # Crear botones para cada asignatura
        markup = types.InlineKeyboardMarkup(row_width=1)
        for asig in asignaturas:
            markup.add(types.InlineKeyboardButton(
                text=asig['Nombre'],
                callback_data=f"grupo_asig_{asig['Id_asignatura']}"
            ))
        
        # Opción para no asociar a ninguna asignatura
        markup.add(types.InlineKeyboardButton("No asociar a ninguna asignatura", callback_data="grupo_asig_none"))
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="📚 *Asignatura Asociada*\n\n"
                "Selecciona la asignatura a la que pertenece este grupo:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        user_states[chat_id] = "crear_grupo_asignatura"
        estados_timestamp[chat_id] = time.time()
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "crear_grupo_asignatura" and call.data.startswith("grupo_asig_"))
    def handle_grupo_asignatura(call):
        """Procesa la asignatura seleccionada"""
        chat_id = call.message.chat.id
        asignatura_data = call.data.replace("grupo_asig_", "")
        
        if asignatura_data != "none":
            user_data[chat_id]["asignatura_id"] = int(asignatura_data)
        else:
            user_data[chat_id]["asignatura_id"] = None
        
        # Confirmar la creación del grupo
        tipo_texto = "privada (control manual)" if user_data[chat_id]["tipo_grupo"] == "privada" else "pública (control automático)"
        
        asignatura_texto = "No asociada a ninguna asignatura"
        if user_data[chat_id]["asignatura_id"]:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT Nombre FROM Asignaturas WHERE Id_asignatura = ?", (user_data[chat_id]["asignatura_id"],))
            asig = cursor.fetchone()
            conn.close()
            if asig:
                asignatura_texto = asig['Nombre']
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Confirmar", callback_data="grupo_confirmar"),
            types.InlineKeyboardButton("❌ Cancelar", callback_data="grupo_cancelar")
        )
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"📋 *Resumen del Grupo*\n\n"
                f"*Nombre:* {user_data[chat_id]['nombre_grupo']}\n"
                f"*Tipo:* {tipo_texto}\n"
                f"*Asignatura:* {asignatura_texto}\n\n"
                f"¿Confirmas la creación del grupo?",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        user_states[chat_id] = "crear_grupo_confirmar"
        estados_timestamp[chat_id] = time.time()
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "crear_grupo_confirmar")
    def handle_grupo_confirmar(call):
        """Procesa la confirmación de creación de grupo"""
        chat_id = call.message.chat.id
        accion = call.data
        
        if accion == "grupo_cancelar":
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="❌ Creación de grupo cancelada.",
                parse_mode="Markdown"
            )
            reset_user(chat_id)
            return
        
        if accion == "grupo_confirmar":
            try:
                # Crear el grupo en la base de datos
                grupo_id = crear_grupo_tutoria(
                    profesor_id=user_data[chat_id]["profesor_id"],
                    nombre_sala=user_data[chat_id]["nombre_grupo"],
                    tipo_sala=user_data[chat_id]["tipo_grupo"],
                    asignatura_id=user_data[chat_id]["asignatura_id"]
                )
                
                # Mensaje de éxito con instrucciones
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"✅ *¡Grupo creado correctamente!*\n\n"
                        f"Tu grupo '{user_data[chat_id]['nombre_grupo']}' ha sido creado.\n\n"
                        f"Para gestionarlo, sigue estos pasos:\n"
                        f"1. Crea un nuevo grupo en Telegram\n"
                        f"2. Añade este bot como administrador\n"
                        f"3. Usa el comando /vincular_grupo para asociarlo con el grupo que acabas de crear",
                    parse_mode="Markdown"
                )
                
                logger.info(f"Grupo creado: {user_data[chat_id]['nombre_grupo']} por profesor {user_data[chat_id]['profesor_id']}")
                
            except Exception as e:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"❌ Error al crear el grupo: {str(e)}",
                    parse_mode="Markdown"
                )
                logger.error(f"Error al crear grupo: {e}")
            
            reset_user(chat_id)
    
    @bot.message_handler(commands=["vincular_grupo"])
    def handle_vincular_grupo(message):
        """Proporciona instrucciones para vincular un grupo"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar que el usuario sea profesor
        user = get_user_by_telegram_id(user_id)
        if not user or user['Tipo'] != 'profesor':
            bot.send_message(chat_id, "⚠️ Solo los profesores pueden vincular grupos.")
            return
            
        # Diferentes instrucciones según si está en chat privado o grupo
        if message.chat.type == 'private':
            # Instrucciones detalladas para crear un grupo desde cero
            bot.send_message(
                chat_id,
                "🔄 *Cómo Vincular un Grupo de Tutoría*\n\n"
                "*Paso 1:* Crea un nuevo grupo en Telegram\n"
                "• Pulsa en el botón de crear nuevo chat\n"
                "• Selecciona 'Nuevo grupo'\n"
                "• Dale un nombre provisional al grupo\n"
                "• Añade a este bot (@TuBotUsername) como miembro\n\n"
                "*Paso 2:* Haz administrador al bot\n"
                "• En el grupo, pulsa en el nombre del grupo en la parte superior\n"
                "• Selecciona 'Administradores'\n"
                "• Pulsa en 'Añadir administrador'\n"
                "• Selecciona este bot\n"
                "• Asegúrate de activar el permiso 'Invitar usuarios mediante enlace'\n\n"
                "*Paso 3:* Completa la vinculación\n"
                "• Una vez hecho esto, el bot detectará los permisos y continuará automáticamente\n"
                "• Si no recibe notificación, escribe /vincular_grupo dentro del grupo\n\n"
                "⚠️ _Recuerda que el bot debe ser administrador para poder generar enlaces de invitación_",
                parse_mode="Markdown"
            )
        else:
            # Ya estamos en un grupo, verificar si el bot es administrador
            try:
                admins = bot.get_chat_administrators(chat_id)
                bot_is_admin = False
                bot_id = bot.get_me().id
                
                for admin in admins:
                    if admin.user.id == bot_id:
                        if admin.can_invite_users:
                            bot_is_admin = True
                        break
                
                if bot_is_admin:
                    # El bot ya es admin, continuar con la vinculación
                    iniciar_configuracion_grupo(chat_id, user_id)
                else:
                    # El bot está en el grupo pero no es admin o no tiene los permisos necesarios
                    bot.send_message(
                        chat_id,
                        "⚠️ *Necesito ser administrador*\n\n"
                        "Por favor, hazme administrador del grupo y dame permiso para invitar usuarios:\n\n"
                        "1. Pulsa en el nombre del grupo arriba\n"
                        "2. Selecciona 'Administradores'\n"
                        "3. Pulsa en 'Añadir administrador'\n"
                        "4. Seleccióname de la lista\n"
                        "5. Activa el permiso 'Invitar usuarios mediante enlace'\n"
                        "6. Guarda los cambios\n\n"
                        "Cuando hayas completado estos pasos, escribe /vincular_grupo de nuevo.",
                        parse_mode="Markdown"
                    )
            except Exception as e:
                bot.send_message(
                    chat_id,
                    f"❌ Error al verificar permisos: {str(e)}\n\n"
                    "Por favor, asegúrate de que soy miembro del grupo y prueba de nuevo."
                )
    
    def iniciar_configuracion_grupo(chat_id, user_id):
        """Inicia la configuración del grupo cuando el bot ya es administrador"""
        # Verificar si el grupo ya está configurado
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
        grupo_existente = cursor.fetchone()
        conn.close()
        
        if grupo_existente:
            bot.send_message(
                chat_id, 
                "ℹ️ Este grupo ya está vinculado a un grupo de tutoría con el nombre: "
                f"*{grupo_existente['Nombre_sala']}*",
                parse_mode="Markdown"
            )
            return
        
        # Generar el enlace de invitación
        enlace_invitacion = None
        try:
            chat_info = bot.get_chat(chat_id)
            if hasattr(chat_info, 'invite_link') and chat_info.invite_link:
                enlace_invitacion = chat_info.invite_link
            else:
                # Intentar crear el enlace
                enlace_invitacion = bot.create_chat_invite_link(chat_id).invite_link
            
            # Almacenar el enlace temporalmente
            user = get_user_by_telegram_id(user_id)
            user_data[chat_id] = {
                "profesor_id": user['Id_usuario'], 
                "enlace_invitacion": enlace_invitacion
            }
            
            # Confirmación de enlace generado
            bot.send_message(
                chat_id,
                f"✅ *¡Enlace de grupo generado correctamente!*\n\n"
                f"Enlace: {enlace_invitacion}\n\n"
                f"Ahora, por favor, indica el nombre que quieres darle a este grupo de tutoría.\n\n"
                f"*Ejemplos:*\n"
                f"• Tutorías Programación I\n"
                f"• Dudas Matemáticas\n"
                f"• Grupo General Física",
                parse_mode="Markdown"
            )
            
            # Cambiar el estado para esperar el nombre
            user_states[chat_id] = "grupo_espera_nombre"
            estados_timestamp[chat_id] = time.time()
            
        except Exception as e:
            bot.send_message(
                chat_id,
                f"❌ Error al generar el enlace: {str(e)}\n\n"
                "Asegúrate de que tengo los permisos correctos (Administrador con permiso para invitar usuarios)"
            )
    
    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "grupo_espera_nombre")
    def handle_grupo_nombre(message):
        """Procesa el nombre del grupo proporcionado por el profesor"""
        chat_id = message.chat.id
        nombre = message.text.strip()
        
        if len(nombre) < 3:
            bot.send_message(chat_id, "❌ El nombre debe tener al menos 3 caracteres.")
            return
        
        user_data[chat_id]["nombre_grupo"] = nombre
        
        # Solicitar tipo de grupo
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔒 Privada (tú controlas quién accede)", callback_data="grupo_tipo_privada"),
            types.InlineKeyboardButton("🔓 Pública (acceso automático para matriculados)", callback_data="grupo_tipo_publica")
        )
        
        bot.send_message(
            chat_id,
            "🔐 *Tipo de Sala*\n\n"
            "¿Qué tipo de sala quieres crear?",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        user_states[chat_id] = "grupo_tipo"
        estados_timestamp[chat_id] = time.time()
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "grupo_tipo" and call.data.startswith("grupo_tipo_"))
    def handle_grupo_tipo(call):
        """Procesa el tipo de grupo seleccionado"""
        chat_id = call.message.chat.id
        tipo = call.data.replace("grupo_tipo_", "")
        
        user_data[chat_id]["tipo_grupo"] = tipo
        
        # Solicitar asignatura asociada
        profesor_id = user_data[chat_id]["profesor_id"]
        
        # Obtener asignaturas del profesor
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT a.* 
            FROM Asignaturas a
            JOIN Matriculas m ON a.Id_asignatura = m.Id_asignatura
            WHERE m.Id_usuario = ?
        """, (profesor_id,))
        asignaturas = cursor.fetchall()
        conn.close()
        
        if not asignaturas:
            bot.send_message(
                chat_id,
                "❌ No tienes asignaturas asignadas. Contacta con el administrador."
            )
            reset_user(chat_id)
            return
        
        # Crear botones para cada asignatura
        markup = types.InlineKeyboardMarkup(row_width=1)
        for asig in asignaturas:
            markup.add(types.InlineKeyboardButton(
                text=asig['Nombre'],
                callback_data=f"grupo_asig_{asig['Id_asignatura']}"
            ))
        
        # Opción para no asociar a ninguna asignatura
        markup.add(types.InlineKeyboardButton("No asociar a ninguna asignatura", callback_data="grupo_asig_none"))
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="📚 *Asignatura Asociada*\n\n"
                "Selecciona la asignatura a la que pertenece este grupo:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        user_states[chat_id] = "grupo_asignatura"
        estados_timestamp[chat_id] = time.time()
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "grupo_asignatura" and call.data.startswith("grupo_asig_"))
    def handle_grupo_asignatura(call):
        """Procesa la asignatura seleccionada y finaliza la configuración"""
        chat_id = call.message.chat.id
        asignatura_data = call.data.replace("grupo_asig_", "")
        
        if asignatura_data != "none":
            user_data[chat_id]["asignatura_id"] = int(asignatura_data)
        else:
            user_data[chat_id]["asignatura_id"] = None
        
        try:
            # Crear el grupo en la base de datos con el enlace ya generado
            grupo_id = crear_grupo_tutoria(
                profesor_id=user_data[chat_id]["profesor_id"],
                nombre_sala=user_data[chat_id]["nombre_grupo"],
                tipo_sala=user_data[chat_id]["tipo_grupo"],
                asignatura_id=user_data[chat_id].get("asignatura_id"),
                chat_id=str(chat_id),
                enlace=user_data[chat_id].get("enlace_invitacion")
            )
            
            # Mensaje de éxito
            tipo_texto = "privada (acceso controlado)" if user_data[chat_id]["tipo_grupo"] == "privada" else "pública (acceso automático)"
            
            asignatura_texto = "No asociada a ninguna asignatura"
            if user_data[chat_id].get("asignatura_id"):
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT Nombre FROM Asignaturas WHERE Id_asignatura = ?", (user_data[chat_id]["asignatura_id"],))
                asig = cursor.fetchone()
                conn.close()
                if asig:
                    asignatura_texto = asig['Nombre']
            
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"✅ *¡Grupo configurado correctamente!*\n\n"
                    f"*Nombre:* {user_data[chat_id]['nombre_grupo']}\n"
                    f"*Tipo:* {tipo_texto}\n"
                    f"*Asignatura:* {asignatura_texto}\n\n"
                    f"Los estudiantes pueden unirse:\n"
                    f"• A través del enlace: {user_data[chat_id]['enlace_invitacion']}\n"
                    f"• Usando /unirse_grupo dentro de este chat\n\n"
                    f"{'⚠️ Las solicitudes de acceso necesitarán tu aprobación.' if user_data[chat_id]['tipo_grupo'] == 'privada' else '✅ El acceso será automático para estudiantes matriculados.'}",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            
            logger.info(f"Grupo vinculado: {chat_id} con nombre {user_data[chat_id]['nombre_grupo']} por profesor {user_data[chat_id]['profesor_id']}")
            
        except Exception as e:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"❌ Error al configurar el grupo: {str(e)}",
                parse_mode="Markdown"
            )
            logger.error(f"Error al configurar grupo: {e}")
        
        reset_user(chat_id)
    
    # Detector de cuando el bot es añadido a un grupo
    @bot.my_chat_member_handler(func=lambda update: True)
    def handle_my_chat_member(update):
        """Detecta cuando el bot es añadido a un grupo o recibe permisos de administrador"""
        chat_id = update.chat.id
        new_status = update.new_chat_member.status
        old_status = update.old_chat_member.status
        user_id = update.from_user.id
        
        # Ignorar actualizaciones en chats privados
        if update.chat.type == 'private':
            return
            
        # Detectar si el bot fue añadido al grupo
        if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
            # El bot fue añadido al grupo
            bot.send_message(
                chat_id,
                "👋 *¡Gracias por añadirme al grupo!*\n\n"
                "Para vincular este grupo como un grupo de tutoría, necesito ser *administrador* con permisos para invitar usuarios.\n\n"
                "*Pasos:*\n"
                "1. Pulsa en el nombre del grupo arriba\n"
                "2. Selecciona 'Administradores'\n"
                "3. Pulsa en 'Añadir administrador' o edita mis permisos\n"
                "4. Activa el permiso 'Invitar usuarios mediante enlace'\n"
                "5. Guarda los cambios\n\n"
                "Cuando termine, escribe /vincular_grupo para continuar.",
                parse_mode="Markdown"
            )
        
        # Detectar si el bot recibió permisos de administrador
        elif old_status in ['member'] and new_status == 'administrator':
            # El bot recibió permisos de administrador
            user = get_user_by_telegram_id(user_id)
            if user and user['Tipo'] == 'profesor':
                bot.send_message(
                    chat_id,
                    "✅ *¡Gracias por darme permisos de administrador!*\n\n"
                    "Ahora podemos vincular este grupo como un grupo de tutoría.\n\n"
                    "Escribe /vincular_grupo para continuar con la configuración.",
                    parse_mode="Markdown"
                )
    
    @bot.message_handler(commands=["unirse_grupo"])
    def handle_unirse_grupo(message):
        """Permite a un estudiante unirse a un grupo"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar que sea un grupo
        if message.chat.type not in ['group', 'supergroup']:
            bot.send_message(chat_id, "⚠️ Este comando solo puede usarse en grupos.")
            return
        
        # Verificar que el usuario esté registrado
        user = get_user_by_telegram_id(user_id)
        if not user:
            bot.send_message(
                chat_id, 
                "⚠️ Debes estar registrado para unirte a grupos. Usa /start para registrarte."
            )
            return
        
        # Obtener información del grupo
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.*, a.Nombre as Asignatura, a.Id_asignatura
            FROM Grupos_tutoria g
            LEFT JOIN Asignaturas a ON g.Id_asignatura = a.Id_asignatura
            WHERE g.Chat_id = ?
        """, (str(chat_id),))
        grupo = cursor.fetchone()
        conn.close()
        
        if not grupo:
            bot.send_message(
                chat_id, 
                "❌ Este grupo de Telegram no está vinculado a ningún grupo de tutoría."
            )
            return
        
        # Verificar según el tipo de grupo
        if grupo['Tipo_sala'] == 'pública':
            # Verificar matrícula si hay asignatura asociada
            if grupo['Id_asignatura']:
                esta_matriculado = verificar_estudiante_matriculado(
                    user['Id_usuario'], 
                    grupo['Id_asignatura']
                )
                
                if not esta_matriculado and user['Tipo'] != 'profesor':
                    bot.send_message(
                        chat_id,
                        f"⚠️ Para unirte a este grupo necesitas estar matriculado en {grupo['Asignatura']}."
                    )
                    return
            
            # Añadir al estudiante (o profesor) al grupo
            exito = añadir_estudiante_grupo(grupo['id_sala'], user['Id_usuario'])
            if exito:
                bot.send_message(
                    chat_id,
                    f"✅ ¡Te has unido al grupo {grupo['Nombre_sala']} correctamente!"
                )
            else:
                bot.send_message(
                    chat_id,
                    "❌ Error al unirte al grupo. Inténtalo de nuevo más tarde."
                )
        
        elif grupo['Tipo_sala'] == 'privada':
            # Para grupos privados, notificar al profesor
            profesor = get_user_by_id(grupo['Id_usuario'])
            if not profesor:
                bot.send_message(chat_id, "❌ Error: No se encontró al profesor del grupo.")
                return
            
            # Si el usuario es el profesor, permitir acceso directo
            if user['Id_usuario'] == profesor['Id_usuario']:
                exito = añadir_estudiante_grupo(grupo['id_sala'], user['Id_usuario'])
                if exito:
                    bot.send_message(
                        chat_id,
                        f"✅ Como creador del grupo, has sido añadido a {grupo['Nombre_sala']}."
                    )
                return
            
            # Enviar solicitud al profesor
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Aceptar", callback_data=f"solicitud_aceptar_{grupo['id_sala']}_{user['Id_usuario']}"),
                types.InlineKeyboardButton("❌ Rechazar", callback_data=f"solicitud_rechazar_{grupo['id_sala']}_{user['Id_usuario']}")
            )
            
            try:
                bot.send_message(
                    profesor['TelegramID'],
                    f"🔔 *Solicitud de acceso*\n\n"
                    f"El estudiante *{user['Nombre']} {user['Apellidos'] or ''}* solicita unirse al grupo *{grupo['Nombre_sala']}*.\n\n"
                    f"¿Quieres permitir su acceso?",
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
                
                bot.send_message(
                    chat_id,
                    f"📩 Tu solicitud ha sido enviada al profesor. Te notificaremos cuando sea respondida."
                )
            except Exception as e:
                bot.send_message(
                    chat_id,
                    f"❌ Error al enviar solicitud: {str(e)}"
                )
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("solicitud_"))
    def handle_solicitud_acceso(call):
        """Procesa las solicitudes de acceso a grupos privados"""
        partes = call.data.split("_")
        accion = partes[1]
        grupo_id = int(partes[2])
        estudiante_id = int(partes[3])
        
        profesor_id = call.from_user.id
        
        # Verificar que sea el profesor del grupo
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Grupos_tutoria WHERE id_sala = ?", (grupo_id,))
        grupo = cursor.fetchone()
        
        profesor = get_user_by_telegram_id(profesor_id)
        if not grupo or not profesor or grupo['Id_usuario'] != profesor['Id_usuario']:
            bot.answer_callback_query(call.id, "⚠️ No tienes permisos para gestionar este grupo.")
            conn.close()
            return
        
        # Obtener datos del estudiante
        estudiante = get_user_by_id(estudiante_id)
        if not estudiante:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="❌ Error: Estudiante no encontrado."
            )
            conn.close()
            return
        
        if accion == "aceptar":
            # Añadir al estudiante al grupo
            exito = añadir_estudiante_grupo(grupo_id, estudiante_id)
            
            if exito:
                # Notificar al profesor
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"✅ Has aceptado a *{estudiante['Nombre']}* en el grupo *{grupo['Nombre_sala']}*.",
                    parse_mode="Markdown"
                )
                
                # Notificar al estudiante
                try:
                    bot.send_message(
                        estudiante['TelegramID'],
                        f"✅ Tu solicitud para unirte al grupo *{grupo['Nombre_sala']}* ha sido *ACEPTADA*.\n\n"
                        f"Ya puedes participar en el grupo.",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            else:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"❌ Error al añadir al estudiante al grupo."
                )
        
        elif accion == "rechazar":
            # Notificar al profesor
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"❌ Has rechazado a *{estudiante['Nombre']}* del grupo *{grupo['Nombre_sala']}*.",
                parse_mode="Markdown"
            )
            
            # Notificar al estudiante
            try:
                bot.send_message(
                    estudiante['TelegramID'],
                    f"❌ Tu solicitud para unirte al grupo *{grupo['Nombre_sala']}* ha sido *RECHAZADA*.",
                    parse_mode="Markdown"
                )
            except:
                    pass
        
        conn.close()

    # NUEVO: Comando para ver profesores y sus grupos
    @bot.message_handler(commands=["mis_tutorias"])
    def handle_mis_tutorias(message):
        """Muestra los profesores y grupos disponibles para el estudiante"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar que el usuario esté registrado
        user = get_user_by_telegram_id(user_id)
        if not user:
            bot.send_message(
                chat_id,
                "⚠️ Debes estar registrado para usar este comando. Usa /start para registrarte."
            )
            return
        
        # Solo para estudiantes
        if user['Tipo'] != 'estudiante':
            bot.send_message(
                chat_id,
                "ℹ️ Este comando está pensado para estudiantes. Usa /mis_grupos para ver los grupos que has creado."
            )
            return
        
        # Obtener asignaturas matriculadas
        matriculas = get_matriculas_by_user(user['Id_usuario'])
        if not matriculas:
            bot.send_message(
                chat_id,
                "ℹ️ No estás matriculado en ninguna asignatura. Contacta con el administrador."
            )
            return
        
        # Obtener IDs de asignaturas
        asignaturas_ids = [m['Id_asignatura'] for m in matriculas]
        
        # Obtener profesores de esas asignaturas
        profesores = obtener_profesores_por_asignaturas(asignaturas_ids)
        if not profesores:
            bot.send_message(
                chat_id,
                "ℹ️ No hay profesores asignados a tus asignaturas."
            )
            return
        
        # Obtener grupos de tutoría disponibles
        grupos = obtener_grupos_por_asignaturas(asignaturas_ids)
        
        # Crear mensaje con los profesores y sus grupos
        mensaje = "👨‍🏫 *PROFESORES Y GRUPOS DISPONIBLES*\n\n"
        
        for profesor in profesores:
            # Información del profesor
            mensaje += f"*{profesor['Nombre']} {profesor['Apellidos'] or ''}*\n"
            mensaje += f"📧 {profesor['Email_UGR'] or 'Sin correo'}\n"
            
            # Horario del profesor
            if profesor.get('Horario'):
                mensaje += f"🕒 *Horario de tutorías:*\n{formatear_horario(profesor['Horario'])}\n"
            else:
                mensaje += "🕒 No hay horario de tutorías disponible\n"
            
            # Grupos del profesor
            grupos_profesor = [g for g in grupos if g['Id_usuario'] == profesor['Id_usuario']]
            if grupos_profesor:
                mensaje += "\n*Grupos de tutoría:*\n"
                for grupo in grupos_profesor:
                    tipo_emoji = "🔒" if grupo['Tipo_sala'] == 'privada' else "🔓"
                    mensaje += f"{tipo_emoji} {grupo['Nombre_sala']} - {grupo['Asignatura']}\n"
                    if grupo['Enlace_invitacion']:
                        mensaje += f"[Unirse al grupo]({grupo['Enlace_invitacion']})\n"
                    else:
                        mensaje += "Usa /unirse_grupo en el grupo correspondiente\n"
            else:
                mensaje += "\nNo hay grupos de tutoría disponibles de este profesor\n"
            
            mensaje += "\n---\n\n"
        
        # Enviar mensaje
        try:
            bot.send_message(
                chat_id,
                mensaje,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception as e:
            # Si el mensaje es muy largo, dividirlo
            if "message is too long" in str(e).lower():
                partes = []
                max_chars = 4000
                
                # Dividir el mensaje en partes
                for profesor in profesores:
                    parte = f"👨‍🏫 *{profesor['Nombre']} {profesor['Apellidos'] or ''}*\n"
                    parte += f"📧 {profesor['Email_UGR'] or 'Sin correo'}\n"
                    
                    if profesor.get('Horario'):
                        parte += f"🕒 *Horario de tutorías:*\n{formatear_horario(profesor['Horario'])}\n"
                    else:
                        parte += "🕒 No hay horario de tutorías disponible\n"
                    
                    grupos_profesor = [g for g in grupos if g['Id_usuario'] == profesor['Id_usuario']]
                    if grupos_profesor:
                        parte += "\n*Grupos de tutoría:*\n"
                        for grupo in grupos_profesor:
                            tipo_emoji = "🔒" if grupo['Tipo_sala'] == 'privada' else "🔓"
                            parte += f"{tipo_emoji} {grupo['Nombre_sala']} - {grupo['Asignatura']}\n"
                            if grupo['Enlace_invitacion']:
                                parte += f"[Unirse al grupo]({grupo['Enlace_invitacion']})\n"
                            else:
                                parte += "Usa /unirse_grupo en el grupo correspondiente\n"
                    else:
                        parte += "\nNo hay grupos de tutoría disponibles de este profesor\n"
                    
                    partes.append(parte)
                
                # Enviar cada parte
                for parte in partes:
                    bot.send_message(
                        chat_id,
                        parte,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
            else:
                bot.send_message(
                    chat_id,
                    f"❌ Error al mostrar tutorías: {str(e)}\n\n"
                    "Por favor, inténtalo de nuevo más tarde."
                )
    
    @bot.message_handler(commands=["mis_grupos"])
    def handle_mis_grupos(message):
        """Muestra los grupos creados por el profesor"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar que el usuario esté registrado
        user = get_user_by_telegram_id(user_id)
        if not user:
            bot.send_message(
                chat_id,
                "⚠️ Debes estar registrado para usar este comando. Usa /start para registrarte."
            )
            return
        
        # Solo para profesores
        if user['Tipo'] != 'profesor':
            bot.send_message(
                chat_id,
                "ℹ️ Este comando es solo para profesores. Usa /mis_tutorias para ver los grupos disponibles."
            )
            return
        
        # Obtener grupos del profesor
        grupos = obtener_grupos_profesor(user['Id_usuario'])
        if not grupos:
            bot.send_message(
                chat_id,
                "ℹ️ No has creado ningún grupo todavía. Usa /crear_grupo para crear uno."
            )
            return
        
        # Crear mensaje con los grupos
        mensaje = "🏫 *MIS GRUPOS DE TUTORÍA*\n\n"
        
        grupos_vinculados = [g for g in grupos if g.get('Chat_id')]
        grupos_no_vinculados = [g for g in grupos if not g.get('Chat_id')]
        
        if grupos_vinculados:
            mensaje += "*Grupos vinculados:*\n"
            for grupo in grupos_vinculados:
                tipo_emoji = "🔒" if grupo['Tipo_sala'] == 'privada' else "🔓"
                asignatura = f" - {grupo['Asignatura']}" if grupo.get('Asignatura') else ""
                mensaje += f"{tipo_emoji} {grupo['Nombre_sala']}{asignatura}\n"
                if grupo['Enlace_invitacion']:
                    mensaje += f"[Enlace del grupo]({grupo['Enlace_invitacion']})\n"
                mensaje += "\n"
        
        if grupos_no_vinculados:
            mensaje += "\n*Grupos pendientes de vincular:*\n"
            for grupo in grupos_no_vinculados:
                tipo_emoji = "🔒" if grupo['Tipo_sala'] == 'privada' else "🔓"
                asignatura = f" - {grupo['Asignatura']}" if grupo.get('Asignatura') else ""
                mensaje += f"{tipo_emoji} {grupo['Nombre_sala']}{asignatura}\n"
            
            mensaje += "\nPara vincular un grupo, crea un grupo en Telegram, añade al bot como administrador y usa /vincular_grupo dentro del grupo."
        
        # Enviar mensaje
        bot.send_message(
            chat_id,
            mensaje,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    
    @bot.message_handler(commands=["terminar_tutoria"])
    def handle_terminar_tutoria(message):
        """Termina una tutoría, expulsando temporalmente a los usuarios para vaciar la sala"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar que sea un grupo
        if message.chat.type not in ['group', 'supergroup']:
            bot.send_message(chat_id, "⚠️ Este comando solo puede usarse en grupos de tutoría.")
            return
        
        # Verificar que el usuario esté registrado
        user = get_user_by_telegram_id(user_id)
        if not user:
            bot.send_message(chat_id, "⚠️ Debes estar registrado para usar esta función.")
            return
        
        # Verificar que el grupo sea de tutorías
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT g.*, u.TelegramID as Profesor_TelegramID
            FROM Grupos_tutoria g
            JOIN Usuarios u ON g.Id_usuario = u.Id_usuario
            WHERE g.Chat_id = ?
        """, (str(chat_id),))
        grupo = cursor.fetchone()
        conn.close()
        
        if not grupo:
            bot.send_message(chat_id, "❌ Este grupo no está registrado como grupo de tutoría.")
            return
        
        # Verificar que sea el profesor o un estudiante miembro del grupo
        es_profesor = user['Id_usuario'] == grupo['Id_usuario']
        es_estudiante = False
        
        if not es_profesor:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM Miembros_Grupo
                WHERE id_sala = ? AND Id_usuario = ?
            """, (grupo['id_sala'], user['Id_usuario']))
            es_estudiante = cursor.fetchone()['count'] > 0
            conn.close()
        
        if not (es_profesor or es_estudiante):
            bot.send_message(chat_id, "⚠️ Solo el profesor o los estudiantes de esta tutoría pueden terminarla.")
            return
        
        # Preguntar confirmación
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Sí, terminar", callback_data="terminar_tutoria_confirmar"),
            types.InlineKeyboardButton("❌ No, cancelar", callback_data="terminar_tutoria_cancelar")
        )
        
        bot.send_message(
            chat_id,
            "⚠️ *¿Estás seguro de que quieres terminar esta tutoría?*\n\n"
            "Esto expulsará temporalmente a todos los participantes (excepto al profesor) "
            "durante 1 minuto para vaciar la sala.\n\n"
            "El enlace seguirá funcionando para futuras tutorías.",
            reply_markup=markup,
            parse_mode="Markdown"
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("terminar_tutoria_"))
    def handle_terminar_tutoria_callback(call):
        """Maneja la confirmación para terminar la tutoría"""
        chat_id = call.message.chat.id
        accion = call.data.replace("terminar_tutoria_", "")
        user_id = call.from_user.id
        
        if accion == "cancelar":
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="✅ Se ha cancelado la terminación de la tutoría."
            )
            return
        
        if accion == "confirmar":
            # Verificar permisos del bot
            try:
                bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
                if not bot_member.can_restrict_members:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        text="❌ No tengo permisos para restringir miembros en este grupo. "
                             "Necesito ser administrador con permisos para banear usuarios."
                    )
                    return
            except Exception as e:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"❌ Error al verificar permisos: {str(e)}"
                )
                return
            
            # Obtener información del grupo
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT g.*, u.TelegramID as Profesor_TelegramID
                FROM Grupos_tutoria g
                JOIN Usuarios u ON g.Id_usuario = u.Id_usuario
                WHERE g.Chat_id = ?
            """, (str(chat_id),))
            grupo = cursor.fetchone()
            conn.close()
            
            if not grupo:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text="❌ No se encontró información del grupo."
                )
                return
            
            # Obtener miembros del grupo
            try:
                miembros = bot.get_chat_administrators(chat_id)
                
                # Enviar mensaje de aviso
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text="🔄 *Terminando tutoría...*\n\n"
                         "Todos los participantes serán expulsados temporalmente.\n"
                         "El enlace seguirá activo para futuras tutorías.",
                    parse_mode="Markdown"
                )
                
                # Mensaje a enviar a cada estudiante
                mensaje_expulsion = (
                    f"🏁 *La tutoría en {grupo['Nombre_sala']} ha terminado*\n\n"
                    f"Has sido expulsado temporalmente del grupo para finalizar la sesión.\n"
                    f"Podrás volver a unirte después usando el mismo enlace "
                    f"o el comando /unirse_grupo dentro del grupo."
                )
                
                # Obtener ID del profesor y del bot para no expulsarlos
                profesor_id = int(grupo['Profesor_TelegramID'])
                bot_id = bot.get_me().id
                
                # Banear temporalmente a cada miembro excepto al profesor y al bot
                usuarios_expulsados = 0
                estudiantes_expulsados = []
                
                # Obtener todos los miembros del chat
                all_members = []
                try:
                    # Este método no está disponible en todos los chats, así que usamos los administradores como referencia
                    for admin in miembros:
                        if admin.user.id != profesor_id and admin.user.id != bot_id:
                            all_members.append(admin.user)
                            
                    # Ahora expulsamos a cada miembro que no sea el profesor o el bot
                    for member in all_members:
                        try:
                            # Mensaje de expulsión con botón de valoración
                            markup = types.InlineKeyboardMarkup(row_width=1)
                            markup.add(
                                types.InlineKeyboardButton("⭐ Valorar esta tutoría", 
                                    callback_data=f"valorar_tutoria_{grupo['Profesor_Id']}")
                            )
                            
                            # Enviar mensaje con botón de valoración
                            bot.send_message(
                                member.id,
                                mensaje_expulsion,
                                parse_mode="Markdown",
                                reply_markup=markup
                            )
                            estudiantes_expulsados.append(member.id)
                            
                            # Ban temporal (60 segundos = 1 minuto)
                            bot.ban_chat_member(chat_id, member.id, until_date=int(time.time()) + 60)
                            usuarios_expulsados += 1
                        except Exception as ex:
                            logger.error(f"No se pudo enviar mensaje a {member.id}: {ex}")
                except Exception as e:
                    logger.error(f"Error al obtener miembros del chat: {e}")
                
                # Mensaje final
                try:
                    bot.send_message(
                        chat_id,
                        f"✅ *Tutoría finalizada*\n\n"
                        f"{usuarios_expulsados} participantes han sido expulsados temporalmente.\n"
                        f"El enlace de la sala sigue activo para futuras tutorías.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Error al enviar mensaje final: {e}")
            
            except Exception as e:
                bot.send_message(
                    chat_id,
                    f"❌ Error al terminar la tutoría: {str(e)}\n"
                    f"Asegúrate de que tengo todos los permisos necesarios.",
                    parse_mode="Markdown"
                )
                
        
        
    # Añadir este handler justo después de handle_terminar_tutoria_callback en grupos.py
    @bot.callback_query_handler(func=lambda call: call.data.startswith("valorar_tutoria_"))
    def handle_valorar_tutoria_callback(call):
            """Redirige al sistema de valoraciones existente"""
            chat_id = call.message.chat.id
            profesor_id = int(call.data.replace("valorar_tutoria_", ""))
            
            # Redirigir al flujo de valoraciones usando la función importada
            iniciar_valoracion_profesor(bot, chat_id, profesor_id, call.message.message_id)
    
    @bot.message_handler(commands=["expulsar_estudiante"])
    def handle_expulsar_estudiante(message):
        """Permite al profesor expulsar a un estudiante específico"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar que sea un grupo
        if message.chat.type not in ["group", "supergroup"]:
            bot.reply_to(message, "❌ Este comando solo funciona en grupos.")
            return
        
        # Verificar que el usuario sea profesor
        user = get_user_by_telegram_id(user_id)
        if not user or user['Tipo'] != 'profesor':
            bot.reply_to(message, "❌ Solo los profesores pueden expulsar estudiantes.")
            return
        
        # Obtener lista de estudiantes del grupo
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT g.* FROM Grupos_tutoria g
            WHERE g.Chat_id = ?
        """, (str(chat_id),))
        
        grupo = cursor.fetchone()
        if not grupo:
            bot.reply_to(message, "❌ Este grupo no está registrado como grupo de tutoría.")
            conn.close()
            return
        
        # Obtener estudiantes del grupo
        cursor.execute("""
            SELECT u.* FROM Miembros_Grupo mg
            JOIN Usuarios u ON mg.Id_usuario = u.Id_usuario
            WHERE mg.id_sala = ? AND u.Tipo = 'estudiante'
        """, (grupo['id_sala'],))
        
        estudiantes = cursor.fetchall()
        conn.close()
        
        if not estudiantes:
            bot.reply_to(message, "❌ No hay estudiantes registrados en este grupo.")
            return
        
        # Crear teclado con estudiantes
        markup = types.InlineKeyboardMarkup(row_width=1)
        for estudiante in estudiantes:
            nombre_completo = f"{estudiante['Nombre']} {estudiante['Apellidos'] or ''}"
            callback_data = f"expulsar_{estudiante['TelegramID']}"
            markup.add(types.InlineKeyboardButton(nombre_completo, callback_data=callback_data))
        
        bot.send_message(
            chat_id,
            "🔄 *Expulsión Individual*\n\n"
            "Selecciona el estudiante que deseas expulsar:",
            reply_markup=markup,
            parse_mode="Markdown"
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("expulsar_"))
    def handle_expulsar_callback(call):
        """Procesa la selección de estudiante a expulsar"""
        chat_id = call.message.chat.id
        user_id = call.from_user.id
        
        # Verificar que sea profesor
        user = get_user_by_telegram_id(user_id)
        if not user or user['Tipo'] != 'profesor':
            bot.answer_callback_query(call.id, "❌ Solo los profesores pueden expulsar estudiantes.")
            return
        
        # Obtener ID del estudiante a expulsar
        estudiante_id = int(call.data.replace("expulsar_", ""))
        
        # Confirmar expulsión
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Confirmar", callback_data=f"confirm_expulsar_{estudiante_id}"),
            types.InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_expulsion")
        )
        
        bot.edit_message_text(
            "⚠️ *Confirmación de Expulsión*\n\n"
            "¿Estás seguro de que deseas expulsar a este estudiante?",
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode="Markdown"
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_expulsar_"))
    def handle_confirmar_expulsion(call):
        """Confirma y procesa la expulsión de un estudiante"""
        chat_id = call.message.chat.id
        user_id = call.from_user.id
        estudiante_id = int(call.data.replace("confirm_expulsar_", ""))
        
        # Verificar permisos del bot
        try:
            bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
            if not bot_member.can_restrict_members:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text="❌ No tengo permisos para restringir miembros."
                )
                return
        except Exception as e:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"❌ Error al verificar permisos: {e}"
            )
            return
        
        # Obtener datos del estudiante
        estudiante = get_user_by_telegram_id(estudiante_id)
        if not estudiante:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="❌ No se pudo encontrar al estudiante."
            )
            return
        
        # Obtener datos del grupo
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT g.*, u.TelegramID as Profesor_TelegramID, u.Nombre as Profesor_Nombre,
                   u.Apellidos as Profesor_Apellidos, u.Id_usuario as Profesor_Id
            FROM Grupos_tutoria g
            JOIN Usuarios u ON g.Id_usuario = u.Id_usuario
            WHERE g.Chat_id = ?
        """, (str(chat_id),))
        
        grupo = cursor.fetchone()
        conn.close()
        
        if not grupo:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="❌ No se encontró información del grupo."
            )
            return
        
        # Expulsar al estudiante
        try:
            # Mensaje para el estudiante expulsado
            mensaje_expulsion = (
                f"🏁 *Tu tutoría en {grupo['Nombre_sala']} ha sido finalizada por el profesor*\n\n"
                f"Has sido expulsado temporalmente del grupo.\n"
                f"Podrás volver a unirte después usando el mismo enlace."
            )
            
            # Añadir botón de valoración
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("⭐ Valorar esta tutoría", 
                    callback_data=f"valorar_tutoria_{grupo['Profesor_Id']}")
            )
            
            # Enviar mensaje con botón de valoración
            try:
                bot.send_message(
                    estudiante_id,
                    mensaje_expulsion,
                    parse_mode="Markdown",
                    reply_markup=markup
                )
            except Exception as ex:
                logger.error(f"No se pudo enviar mensaje a {estudiante_id}: {ex}")
            
            # Ban temporal (60 segundos)
            bot.ban_chat_member(chat_id, estudiante_id, until_date=int(time.time()) + 60)
            
            # Mensaje de confirmación
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"✅ Estudiante *{estudiante['Nombre']}* expulsado correctamente.\n\n"
                     f"Se le ha enviado un mensaje para valorar la tutoría.",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"❌ Error al expulsar al estudiante: {e}"
            )

    @bot.callback_query_handler(func=lambda call: call.data == "cancelar_expulsion")
    def handle_cancelar_expulsion(call):
        """Cancela la expulsión del estudiante"""
        bot.edit_message_text(
            "🔄 Expulsión cancelada.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )