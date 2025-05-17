import telebot
from telebot import types
import sys
import os
import time
import datetime
import logging
from grupo_handlers.utils import escape_markdown

# Comentar o eliminar esta línea:
# from utils.horarios_utils import formatear_horario
# En su lugar, definir la función localmente:
def formatear_horario(horario_texto):
    """Formatea un horario para mostrar"""
    if not horario_texto:
        return "No disponible"
    return horario_texto

# Arreglar la otra importación
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from grupo_handlers.valoraciones import iniciar_valoracion_profesor

from db.queries import (
    get_user_by_telegram_id, 
    get_db_connection,
    crear_grupo_tutoria,
    actualizar_grupo_tutoria,
    verificar_estudiante_matriculado,
    añadir_estudiante_grupo,
    get_user_by_id
)

# Variables para manejar estados de configuración
user_states = {}
user_data = {}

# Configurar logger
logger = logging.getLogger("grupos")
if not logger.handlers:
    handler = logging.FileHandler("grupos.log")
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def inicializar_tablas_grupo():
    """Verifica que las tablas necesarias existen sin intentar crearlas"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verificar que las tablas existen
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Grupos_tutoria'")
        if not cursor.fetchone():
            logger.error("La tabla Grupos_tutoria no existe en la base de datos")
            
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Miembros_Grupo'")
        if not cursor.fetchone():
            logger.error("La tabla Miembros_Grupo no existe en la base de datos")
            
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Valoraciones'")
        if not cursor.fetchone():
            logger.error("La tabla Valoraciones no existe en la base de datos")
            
        conn.close()
        logger.info("Verificación de tablas completada")
    except Exception as e:
        logger.error(f"Error al verificar tablas: {e}")

def register_handlers(bot):
    # Inicializar tablas
    inicializar_tablas_grupo()
    
    def reset_state(chat_id):
        """Elimina estados de usuario para evitar bloqueos"""
        if chat_id in user_states:
            del user_states[chat_id]
        if chat_id in user_data:
            del user_data[chat_id]
    
    @bot.my_chat_member_handler(func=lambda update: True)
    def handle_my_chat_member(update):
        """Detecta cuando el bot es añadido a un grupo o recibe permisos"""
        chat_id = update.chat.id
        new_status = update.new_chat_member.status
        old_status = update.old_chat_member.status
        user_id = update.from_user.id
        
        # Ignorar actualizaciones en chats privados
        if update.chat.type == 'private':
            return
            
        # Detectar si el bot fue añadido al grupo
        if old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
            # El bot fue añadido al grupo - mostrar mensaje inmediato y enviar mensaje privado
            bot.send_message(
                chat_id,
                "👋 *¡Gracias por añadirme al grupo!*\n\n"
                "Para funcionar correctamente, necesito ser administrador con permisos para:\n"
                "• Invitar usuarios mediante enlace\n"
                "• Eliminar y vetar usuarios\n\n"
                "Te enviaré instrucciones detalladas por mensaje privado.",
                parse_mode="Markdown"
            )
            
            # Intentar enviar mensaje privado al profesor con instrucciones
            try:
                user = get_user_by_telegram_id(user_id)
                if user and user['Tipo'] == 'profesor':
                    bot.send_message(
                        user_id,
                        "📝 *Configurar sala de tutoría*\n\n"
                        "Para configurar tu grupo, sigue estos pasos:\n\n"
                        "*1.* Abre el grupo de Telegram\n"
                        "*2.* Toca el nombre del grupo en la parte superior\n"
                        "*3.* Selecciona 'Administradores'\n"
                        "*4.* Toca 'Añadir administrador'\n"
                        "*5.* Busca y selecciona este bot\n"
                        "*6.* Activa los permisos:\n"
                        "   - ✅ Invitar usuarios mediante enlace\n"
                        "   - ✅ Eliminar y vetar usuarios\n"
                        "*7.* Guarda los cambios\n\n"
                        "Una vez hecho esto, podré registrar la sala automáticamente.",
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Error al enviar mensaje privado: {e}")
        
        # Detectar si el bot recibió permisos de administrador
        elif (old_status == 'member' and new_status == 'administrator') or (old_status == 'administrator' and new_status == 'administrator'):
            # El bot recibió permisos de administrador o se modificaron sus permisos
            try:
                # Verificar que el usuario es profesor
                user = get_user_by_telegram_id(user_id)
                if not user or user['Tipo'] != 'profesor':
                    return  # No es profesor, no hacemos nada
                
                # Verificar que el grupo no está ya registrado
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
                grupo_existente = cursor.fetchone()
                conn.close()
                
                if grupo_existente:
                    # El grupo ya está registrado
                    return
                
                # Verificar permisos necesarios
                admins = bot.get_chat_administrators(chat_id)
                bot_id = bot.get_me().id
                bot_is_admin = False
                bot_can_invite = False
                bot_can_ban = False
                
                for admin in admins:
                    if admin.user.id == bot_id:
                        bot_is_admin = True
                        bot_can_invite = admin.can_invite_users
                        bot_can_ban = admin.can_restrict_members
                        break
                
                if not (bot_is_admin and bot_can_invite and bot_can_ban):
                    # No tiene todos los permisos necesarios
                    bot.send_message(
                        chat_id,
                        "⚠️ *Necesito más permisos*\n\n"
                        "Para gestionar tutorías necesito:\n"
                        "• Invitar usuarios mediante enlace\n"
                        "• Eliminar y vetar usuarios",
                        parse_mode="Markdown"
                    )
                    return
                
                # Obtener información del grupo
                chat_info = bot.get_chat(chat_id)
                nombre_grupo = chat_info.title if hasattr(chat_info, 'title') and chat_info.title else None
                
                # Generar enlace de invitación
                enlace = None
                if hasattr(chat_info, 'invite_link') and chat_info.invite_link:
                    enlace = chat_info.invite_link
                else:
                    enlace = bot.create_chat_invite_link(chat_id).invite_link
                
                # Iniciar flujo de configuración si no se pudo obtener toda la información
                user_data[chat_id] = {
                    "profesor_id": user['Id_usuario'],
                    "chat_id": str(chat_id),
                    "enlace": enlace,
                    "nombre_grupo": nombre_grupo
                }
                
                # Si no se pudo obtener el nombre del grupo, preguntarlo
                if not nombre_grupo:
                    bot.send_message(
                        chat_id,
                        "📝 *Configuración de sala*\n\n"
                        "¿Qué nombre quieres darle a esta sala de tutoría?",
                        parse_mode="Markdown"
                    )
                    user_states[chat_id] = "espera_nombre_grupo"
                    return
                
                # Si tenemos el nombre, preguntar por la asignatura
                obtener_asignaturas_profesor(bot, chat_id, user['Id_usuario'])
                
            except Exception as e:
                logger.error(f"Error al verificar permisos: {e}")
                bot.send_message(
                    chat_id,
                    f"❌ Error al configurar el grupo: {str(e)}\n"
                    f"Por favor, verifica que tengo todos los permisos necesarios.",
                    parse_mode="Markdown"
                )
    
    def obtener_asignaturas_profesor(bot, chat_id, profesor_id):
        """Muestra las asignaturas del profesor para seleccionar"""
        try:
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
                # No tiene asignaturas asignadas, preguntar directamente por el propósito
                user_data[chat_id]["asignatura_id"] = None
                preguntar_proposito_grupo(bot, chat_id)
                return
            
            # Crear teclado con las asignaturas
            markup = types.InlineKeyboardMarkup(row_width=1)
            for asig in asignaturas:
                markup.add(types.InlineKeyboardButton(
                    asig['Nombre'],
                    callback_data=f"asig_{asig['Id_asignatura']}"
                ))
            
            # Añadir opción para no asociar a ninguna asignatura
            markup.add(types.InlineKeyboardButton(
                "No asociar a ninguna asignatura",
                callback_data="asig_none"
            ))
            
            # Enviar mensaje
            bot.send_message(
                chat_id,
                "📚 *Asignatura de la sala*\n\n"
                "Selecciona la asignatura a la que pertenece esta sala de tutoría:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
            
            user_states[chat_id] = "espera_asignatura"
            
        except Exception as e:
            logger.error(f"Error al obtener asignaturas: {e}")
            bot.send_message(
                chat_id, 
                "❌ Error al obtener asignaturas. Por favor, inténtalo de nuevo más tarde."
            )
    
    def preguntar_proposito_grupo(bot, chat_id):
        """Pregunta por el propósito del grupo"""
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📢 Comunicados y avisos", callback_data="prop_avisos"),
            types.InlineKeyboardButton("👨‍👨‍👦 Tutorías grupales", callback_data="prop_grupo"),
            types.InlineKeyboardButton("👤 Tutorías individuales", callback_data="prop_individual")
        )
        
        bot.send_message(
            chat_id,
            "🎯 *Propósito de la sala*\n\n"
            "¿Para qué utilizarás principalmente esta sala?",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        
        user_states[chat_id] = "espera_proposito"
    
    def guardar_grupo_en_db(chat_id):
        """Guarda la información del grupo en la base de datos"""
        try:
            data = user_data[chat_id]
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Determinar tipo según propósito - CORREGIR AQUÍ
            tipo_sala = 'privada'  # Valor predeterminado correcto
            if data.get('proposito_sala') == 'avisos':
                tipo_sala = 'pública'  # Con acento para cumplir con la restricción
            
            # Insertar grupo
            cursor.execute("""
                INSERT INTO Grupos_tutoria 
                (Id_usuario, Nombre_sala, Tipo_sala, Chat_id, Enlace_invitacion, Proposito_sala, Id_asignatura) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                data['profesor_id'], 
                data['nombre_grupo'], 
                tipo_sala,  # Ahora es 'privada' o 'pública' (con acento)
                data['chat_id'], 
                data['enlace'], 
                data.get('proposito_sala'),
                data.get('asignatura_id')
            ))
            
            grupo_id = cursor.lastrowid
            
            # Añadir al profesor como miembro
            cursor.execute("""
                INSERT OR IGNORE INTO Miembros_Grupo (id_sala, Id_usuario) 
                VALUES (?, ?)
            """, (grupo_id, data['profesor_id']))
            
            conn.commit()
            conn.close()
            
            # Preparar mensajes según el propósito
            proposito_textos = {
                'avisos': "Sala de comunicados y avisos",
                'grupo': "Sala de tutorías grupales",
                'individual': "Sala de tutorías individuales"
            }
            
            # Obtener nombre de asignatura si está asociada
            asignatura_texto = "No asociada a ninguna asignatura"
            if data.get('asignatura_id'):
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT Nombre FROM Asignaturas WHERE Id_asignatura = ?", (data['asignatura_id'],))
                asig = cursor.fetchone()
                conn.close()
                if asig:
                    asignatura_texto = asig['Nombre']
            
            # Mensaje de confirmación
            nombre_grupo_seguro = escape_markdown(data['nombre_grupo'])
            bot.send_message(
                chat_id,
                f"✅ *¡Sala configurada correctamente!*\n\n"
                f"*Nombre:* {nombre_grupo_seguro}\n"
                f"*Propósito:* {proposito_textos.get(data.get('proposito_sala'), 'General')}\n"
                f"*Asignatura:* {asignatura_texto}\n"
                f"*Enlace:* {data['enlace']}\n\n"
                f"Usa /ayuda para ver los comandos disponibles.",
                parse_mode="Markdown"
            )
            
            return True
        except Exception as e:
            logger.error(f"Error al guardar grupo: {e}")
            
            # Opción 1: Sin formato Markdown
            bot.send_message(
                chat_id,
                f"❌ Error al guardar la configuración.\nDetalles: {str(e)}",
                parse_mode=None
            )
            
            # O mejor, Opción 2: Escapar el mensaje de error
            # mensaje_error = escape_markdown(str(e))
            # bot.send_message(
            #     chat_id,
            #     f"❌ Error al guardar la configuración.\nDetalles: {mensaje_error}",
            #     parse_mode="Markdown"
            # )
            
            return False
    
    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "espera_nombre_grupo")
    def handle_nombre_grupo(message):
        """Procesa el nombre del grupo ingresado por el usuario"""
        chat_id = message.chat.id
        nombre = message.text.strip()
        
        # Caracteres problemáticos en Markdown
        caracteres_problematicos = ['_', '*', '`', '[', ']', '(', ')']
        
        # Verificar si hay caracteres problemáticos
        for char in caracteres_problematicos:
            if char in nombre:
                bot.send_message(
                    chat_id,
                    f"❌ El nombre contiene caracteres no permitidos ({', '.join(caracteres_problematicos)}).\n"
                    "Por favor, envía un nuevo nombre sin estos caracteres especiales.",
                    parse_mode=None
                )
                return
        
        # Guardar nombre y continuar
        user_data[chat_id]["nombre_grupo"] = nombre
        
        # Preguntar por la asignatura
        obtener_asignaturas_profesor(bot, chat_id, user_data[chat_id]["profesor_id"])
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "espera_asignatura" and call.data.startswith("asig_"))
    def handle_seleccion_asignatura(call):
        """Procesa la selección de asignatura"""
        chat_id = call.message.chat.id
        asignatura_data = call.data.replace("asig_", "")
        
        if asignatura_data == "none":
            user_data[chat_id]["asignatura_id"] = None
        else:
            user_data[chat_id]["asignatura_id"] = int(asignatura_data)
        
        # Preguntar por el propósito
        preguntar_proposito_grupo(bot, chat_id)
        
        # Editar mensaje original para quitar botones
        try:
            bot.edit_message_reply_markup(
                chat_id=chat_id, 
                message_id=call.message.message_id,
                reply_markup=None
            )
        except:
            pass
    
    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == "espera_proposito" and call.data.startswith("prop_"))
    def handle_seleccion_proposito(call):
        """Procesa la selección del propósito del grupo"""
        chat_id = call.message.chat.id
        proposito = call.data.replace("prop_", "")
        
        # Guardar propósito
        user_data[chat_id]["proposito_sala"] = proposito
        
        # Editar mensaje original para quitar botones
        try:
            bot.edit_message_reply_markup(
                chat_id=chat_id, 
                message_id=call.message.message_id,
                reply_markup=None
            )
        except:
            pass
        
        # Finalizar configuración
        if guardar_grupo_en_db(chat_id):
            reset_state(chat_id)
    
    @bot.message_handler(commands=['ayuda', 'help'])
    def handle_grupo_ayuda(message):
        """Muestra información de ayuda dentro de un grupo de tutoría"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar que sea un grupo
        if message.chat.type == 'private':
            bot.send_message(
                chat_id,
                "⚠️ Este bot se usa dentro de los grupos de tutoría.",
                parse_mode="Markdown"
            )
            return
        
        # Identificar al usuario
        user = get_user_by_telegram_id(user_id)
        if not user:
            bot.send_message(
                chat_id,
                "❌ No se pudo identificar al usuario.",
                parse_mode="Markdown"
            )
            return
        
        # Verificar que el grupo está registrado
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
        grupo = cursor.fetchone()
        conn.close()
        
        if not grupo:
            bot.send_message(
                chat_id,
                "❌ Este grupo no está registrado como sala de tutoría.",
                parse_mode="Markdown"
            )
            return
        
        # Mensaje para profesor propietario
        if user['Tipo'] == 'profesor' and user['Id_usuario'] == grupo['Id_usuario']:
            bot.send_message(
                chat_id,
                "🧑‍🏫 *Comandos para profesores:*\n\n"
                "• /finalizar_tutoria - Expulsa estudiantes y finaliza la sesión\n\n"
                "Como profesor, puedes expulsar estudiantes individualmente o finalizar la tutoría para todos de una vez.",
                parse_mode="Markdown"
            )
        # Mensaje para estudiantes
        elif user['Tipo'] == 'estudiante':
            bot.send_message(
                chat_id,
                "👨‍🎓 *Comandos para estudiantes:*\n\n"
                "• /finalizar_tutoria - Salir de la tutoría actual\n\n"
                "Al salir de la tutoría, se te pedirá que valores la sesión con el profesor.",
                parse_mode="Markdown"
            )
        # Otros profesores (no propietarios)
        else:
            bot.send_message(
                chat_id,
                "ℹ️ Este es un grupo de tutoría. Solo el profesor propietario puede gestionar la sala.",
                parse_mode="Markdown"
            )

    @bot.message_handler(commands=["finalizar_tutoria"])
    def handle_finalizar_tutoria(message):
        """Inicia el proceso de finalización de una tutoría"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar que estamos en un grupo
        if message.chat.type == 'private':
            bot.send_message(
                chat_id,
                "⚠️ Este comando solo puede usarse dentro de un grupo de tutoría.",
                parse_mode="Markdown"
            )
            return
        
        # Verificar que el grupo está registrado
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
        grupo = cursor.fetchone()
        
        if not grupo:
            bot.send_message(chat_id, "❌ Este grupo no está registrado como sala de tutoría.")
            return
        
        user = get_user_by_telegram_id(user_id)
        if not user:
            bot.send_message(chat_id, "❌ No se pudo identificar al usuario.")
            return
        
        # Diferentes opciones para profesor y estudiante
        if user['Tipo'] == 'profesor' and user['Id_usuario'] == grupo['Id_usuario']:
            # El profesor propietario puede seleccionar estudiantes o finalizar para todos
            # En tutorías grupales, mostrar lista de estudiantes
            cursor.execute("""
                SELECT u.* FROM Usuarios u
                JOIN Miembros_Grupo mg ON u.Id_usuario = mg.Id_usuario
                WHERE mg.id_sala = ? AND u.Tipo = 'estudiante'
                ORDER BY u.Nombre
            """, (grupo['id_sala'],))
            estudiantes = cursor.fetchall()
            
            if not estudiantes:
                bot.send_message(chat_id, "ℹ️ No hay estudiantes en esta tutoría.")
                return
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            for est in estudiantes:
                markup.add(types.InlineKeyboardButton(
                    f"{est['Nombre']} {est.get('Apellidos', '')}",
                    callback_data=f"fin_est_{est['Id_usuario']}"
                ))
                
            markup.add(types.InlineKeyboardButton(
                "🔴 Finalizar para todos", callback_data="fin_tutoria_todos"
            ))
            markup.add(types.InlineKeyboardButton(
                "❌ Cancelar", callback_data="fin_tutoria_cancel"
            ))
            
            bot.send_message(
                chat_id,
                "👨‍👨‍👦 *Finalizar Tutoría*\n\n"
                "Selecciona el estudiante que deseas expulsar o finaliza la tutoría para todos:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
    
        elif user['Tipo'] == 'estudiante':
            # Los estudiantes solo pueden salir ellos mismos
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Confirmar", callback_data="fin_est_self"),
                types.InlineKeyboardButton("❌ Cancelar", callback_data="fin_tutoria_cancel")
            )
            
            bot.send_message(
                chat_id,
                "🚪 *Salir de la tutoría*\n\n"
                "¿Confirmas que deseas salir de esta tutoría?\n"
                "No podrás volver a entrar durante 1 minuto.",
                reply_markup=markup,
                parse_mode="Markdown"
            )
    
        else:
            bot.send_message(
                chat_id,
                "⚠️ Solo los profesores propietarios y estudiantes pueden usar este comando."
            )
    
        conn.close()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("fin_"))
    def handle_finalizar_tutoria_callback(call):
        """Procesa las acciones de finalización de tutoría"""
        chat_id = call.message.chat.id
        mensaje_id = call.message.message_id
        user_id = call.from_user.id
        
        # Verificar usuario
        user = get_user_by_telegram_id(user_id)
        if not user:
            bot.answer_callback_query(call.id, "❌ No se pudo identificar al usuario.")
            return
        
        # Verificar grupo
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
        grupo = cursor.fetchone()
        
        if not grupo:
            bot.answer_callback_query(call.id, "❌ Este grupo no está registrado como sala de tutoría.")
            conn.close()
            return
        
        # Procesar según la acción
        accion = call.data
        
        if accion == "fin_tutoria_cancel":
            # Cancelar la acción
            bot.delete_message(chat_id, mensaje_id)
            bot.answer_callback_query(call.id, "Acción cancelada")
            
        elif accion == "fin_tutoria_todos" and user['Tipo'] == 'profesor' and user['Id_usuario'] == grupo['Id_usuario']:
            # Finalizar tutoría para todos los estudiantes
            try:
                # Encontrar a todos los estudiantes
                cursor.execute("""
                    SELECT u.* FROM Usuarios u
                    JOIN Miembros_Grupo mg ON u.Id_usuario = mg.Id_usuario
                    WHERE mg.id_sala = ? AND u.Tipo = 'estudiante'
                """, (grupo['id_sala'],))
                estudiantes = cursor.fetchall()
                
                expulsados = 0
                for est in estudiantes:
                    if est['TelegramID']:
                        try:
                            # Expulsar a cada estudiante
                            bot.ban_chat_member(
                                chat_id, 
                                est['TelegramID'],
                                until_date=int(time.time()) + 60  # Ban de 1 minuto
                            )
                            expulsados += 1
                            
                            # Iniciar valoración para cada estudiante
                            iniciar_valoracion_profesor(bot, user['Id_usuario'], est['Id_usuario'], grupo['id_sala'])
                        except:
                            # Continuar con el siguiente si hay error
                            pass
                
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=mensaje_id,
                    text=f"✅ *Tutoría finalizada para todos*\n\n"
                        f"Se han expulsado temporalmente a {expulsados} estudiantes.\n"
                        f"Se ha iniciado el proceso de valoración.",
                    parse_mode="Markdown"
                )
                
            except Exception as e:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=mensaje_id,
                    text=f"❌ Error al finalizar la tutoría: {str(e)}",
                    parse_mode="Markdown"
                )
                logger.error(f"Error al finalizar tutoría grupal: {e}")
        
        elif accion.startswith("fin_est_") and user['Tipo'] == 'profesor' and user['Id_usuario'] == grupo['Id_usuario']:
            # Expulsar a un estudiante específico
            try:
                estudiante_id = int(accion.replace("fin_est_", ""))
                
                # Obtener información del estudiante
                cursor.execute("SELECT * FROM Usuarios WHERE Id_usuario = ?", (estudiante_id,))
                estudiante = cursor.fetchone()
                
                if estudiante and estudiante['TelegramID']:
                    # Expulsar al estudiante
                    bot.ban_chat_member(
                        chat_id, 
                        estudiante['TelegramID'],
                        until_date=int(time.time()) + 60  # Ban de 1 minuto
                    )
                    
                    # Iniciar proceso de valoración
                    iniciar_valoracion_profesor(bot, user['Id_usuario'], estudiante_id, grupo['id_sala'])
                    
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=mensaje_id,
                        text=f"✅ *Estudiante expulsado*\n\n"
                            f"{estudiante['Nombre']} {estudiante.get('Apellidos', '')} ha sido expulsado temporalmente.\n"
                            f"Se ha iniciado el proceso de valoración.",
                        parse_mode="Markdown"
                    )
                else:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=mensaje_id,
                        text="⚠️ No se pudo encontrar al estudiante seleccionado.",
                        parse_mode="Markdown"
                    )
            except Exception as e:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=mensaje_id,
                    text=f"❌ Error al expulsar al estudiante: {str(e)}",
                    parse_mode="Markdown"
                )
                logger.error(f"Error al expulsar estudiante: {e}")
        
        elif accion == "fin_est_self" and user['Tipo'] == 'estudiante':
            # Estudiante sale voluntariamente - PRIMERO mostrar valoración
            try:
                # Buscar profesor para valoración
                profesor_id = grupo['Id_usuario']
                profesor = get_user_by_id(profesor_id)
                nombre_profesor = profesor['Nombre'] if profesor else "el profesor"
                
                # Mostrar opciones de valoración antes de expulsar
                markup = types.InlineKeyboardMarkup(row_width=5)
                # Añadir botones de estrellas
                buttons = []
                for i in range(1, 6):
                    stars = "⭐" * i
                    buttons.append(types.InlineKeyboardButton(stars, callback_data=f"val_{i}_{grupo['id_sala']}"))
                markup.add(*buttons)
                
                # Añadir opción para salir sin valorar
                markup.add(types.InlineKeyboardButton("Salir sin valorar", callback_data=f"exit_no_val"))
                
                # Editar mensaje con opciones de valoración
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=mensaje_id,
                    text=f"📊 *Valoración anónima*\n\n"
                        f"Antes de salir, ¿te gustaría valorar esta tutoría con {nombre_profesor}?\n\n"
                        f"Tu valoración será completamente anónima.",
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
                
            except Exception as e:
                # Si hay error, continuar con la expulsión
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=mensaje_id,
                    text=f"❌ Error al mostrar valoración: {str(e)}\n"
                        f"Procediendo a salir de la tutoría...",
                    parse_mode="Markdown"
                )
                # Expulsar al estudiante igualmente
                bot.ban_chat_member(
                    chat_id, 
                    user['TelegramID'],
                    until_date=int(time.time()) + 60  # Ban de 1 minuto
                )
                logger.error(f"Error al mostrar valoración: {e}")
        
        else:
            bot.answer_callback_query(call.id, "❌ No tienes permiso para realizar esta acción")
        
        conn.close()

    @bot.callback_query_handler(func=lambda call: call.data.startswith("val_"))
    def handle_valoracion_tutorias(call):
        """Procesa las valoraciones de tutorías"""
        chat_id = call.message.chat.id
        mensaje_id = call.message.message_id
        user_id = call.from_user.id
        
        # Verificar usuario
        user = get_user_by_telegram_id(user_id)
        if not user or user['Tipo'] != 'estudiante':
            bot.answer_callback_query(call.id, "❌ Solo los estudiantes pueden valorar tutorías.")
            return
        
        # Parsear datos de valoración
        partes = call.data.split('_')
        if len(partes) < 3:
            bot.answer_callback_query(call.id, "Datos de valoración incorrectos.")
            return
            
        puntuacion = int(partes[1])
        sala_id = int(partes[2])
        
        try:
            # Obtener información de la sala
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM Grupos_tutoria WHERE id_sala = ?", (sala_id,))
            sala = cursor.fetchone()
            
            if not sala:
                bot.answer_callback_query(call.id, "No se encontró la sala.")
                conn.close()
                return
            
            # Preparar para pedir comentario opcional
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✏️ Añadir comentario", callback_data=f"valc_{sala_id}"),
                types.InlineKeyboardButton("✅ Finalizar y salir", callback_data=f"vals_{puntuacion}_{sala_id}")
            )
            
            # Texto según puntuación
            if puntuacion >= 4:
                texto = "¡Gracias por tu excelente valoración!"
            elif puntuacion == 3:
                texto = "Gracias por tu valoración."
            else:
                texto = "Lamentamos que la experiencia no haya sido satisfactoria."
            
            # Mostrar mensaje de valoración
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=mensaje_id,
                text=f"⭐ *Valoración: {puntuacion}/5*\n\n"
                    f"{texto}\n\n"
                    f"¿Quieres añadir un comentario anónimo o finalizar?",
                reply_markup=markup,
                parse_mode="Markdown"
            )
            
            # Guardar temporalmente la valoración
            user_data[user_id] = {
                "valoracion_sala": sala_id,
                "valoracion_puntuacion": puntuacion,
                "valoracion_mensaje_id": mensaje_id,
                "valoracion_chat_id": chat_id
            }
            
            conn.close()
            
        except Exception as e:
            bot.answer_callback_query(call.id, f"Error al procesar valoración: {str(e)}")
            logger.error(f"Error al procesar valoración: {e}")
            
            # Expulsar al estudiante en caso de error
            try:
                bot.ban_chat_member(
                    chat_id, 
                    user['TelegramID'],
                    until_date=int(time.time()) + 60  # Ban de 1 minuto
                )
            except:
                pass

    @bot.callback_query_handler(func=lambda call: call.data.startswith("valc_"))
    def handle_valoracion_comentario(call):
        """Solicita un comentario para la valoración"""
        chat_id = call.message.chat.id
        mensaje_id = call.message.message_id
        user_id = call.from_user.id
        
        # Verificar usuario
        user = get_user_by_telegram_id(user_id)
        if not user or user['Tipo'] != 'estudiante':
            bot.answer_callback_query(call.id, "❌ Solo estudiantes pueden valorar tutorías.")
            return
        
        # Obtener ID de sala
        sala_id = int(call.data.replace("valc_", ""))
        
        # Actualizar estado
        user_states[user_id] = "esperando_comentario_valoracion"
        
        # Solicitar comentario
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=mensaje_id,
            text="✏️ *Añadir comentario*\n\n"
                "Por favor, escribe tu comentario sobre la tutoría (será anónimos).\n\n"
                "Cuando termines, envía el mensaje y serás expulsado automáticamente del grupo.",
            parse_mode="Markdown"
        )

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "esperando_comentario_valoracion")
    def handle_texto_comentario(message):
        """Procesa el comentario de valoración y expulsa al estudiante"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar usuario
        user = get_user_by_telegram_id(user_id)
        if not user or user['Tipo'] != 'estudiante':
            return
        
        # Obtener datos de valoración
        data = user_data.get(user_id, {})
        if not data or "valoracion_sala" not in data or "valoracion_puntuacion" not in data:
            bot.send_message(chat_id, "❌ Error: No se encontró información de valoración.")
            return
        
        # Guardar comentario
        comentario = message.text.strip()
        
        try:
            # Guardar valoración en la base de datos
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Obtener info de la sala para el profesor_id
            cursor.execute("SELECT * FROM Grupos_tutoria WHERE id_sala = ?", (data["valoracion_sala"],))
            sala = cursor.fetchone()
            
            if not sala:
                bot.send_message(chat_id, "❌ Error: No se encontró la sala.")
                conn.close()
                return
            
            # Insertar valoración anónima (guardamos id_estudiante solo para evitar duplicados)
            cursor.execute("""
                INSERT INTO Valoraciones 
                (id_sala, id_profesor, id_estudiante, puntuacion, comentario, anonima) 
                VALUES (?, ?, ?, ?, ?, 1)
            """, (
                data["valoracion_sala"],
                sala["Id_usuario"],
                user["Id_usuario"],
                data["valoracion_puntuacion"],
                comentario
            ))
            
            conn.commit()
            conn.close()
            
            # Agradecimiento final
            bot.send_message(
                chat_id,
                "✅ *¡Gracias por tu valoración!*\n\n"
                "Tu comentario ha sido registrado de forma anónima.\n"
                "Serás expulsado del grupo en 3 segundos...",
                parse_mode="Markdown"
            )
            
            # Esperar 3 segundos antes de expulsar
            time.sleep(3)
            
            # Expulsar al estudiante
            bot.ban_chat_member(
                chat_id, 
                user['TelegramID'],
                until_date=int(time.time()) + 60  # Ban de 1 minuto
            )
            
            # Limpiar estados
            if user_id in user_states:
                del user_states[user_id]
            if user_id in user_data:
                del user_data[user_id]
        
        except Exception as e:
            bot.send_message(
                chat_id,
                f"❌ Error al guardar valoración: {str(e)}\n"
                "Serás expulsado del grupo...",
                parse_mode="Markdown"
            )
            logger.error(f"Error al guardar valoración con comentario: {e}")
            
            # Expulsar al estudiante en caso de error
            try:
                bot.ban_chat_member(
                    chat_id, 
                    user['TelegramID'],
                    until_date=int(time.time()) + 60  # Ban de 1 minuto
                )
            except:
                pass

    @bot.callback_query_handler(func=lambda call: call.data.startswith("vals_"))
    def handle_valoracion_sin_comentario(call):
        """Guarda valoración sin comentario y expulsa al estudiante"""
        chat_id = call.message.chat.id
        mensaje_id = call.message.message_id
        user_id = call.from_user.id
        
        # Verificar usuario
        user = get_user_by_telegram_id(user_id)
        if not user or user['Tipo'] != 'estudiante':
            bot.answer_callback_query(call.id, "❌ Solo estudiantes pueden valorar tutorías.")
            return
        
        # Parsear datos
        partes = call.data.split("_")
        if len(partes) < 3:
            bot.answer_callback_query(call.id, "Datos de valoración incorrectos.")
            return
        
        puntuacion = int(partes[1])
        sala_id = int(partes[2])
        
        try:
            # Guardar valoración
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Obtener profesor
            cursor.execute("SELECT Id_usuario FROM Grupos_tutoria WHERE id_sala = ?", (sala_id,))
            sala = cursor.fetchone()
            
            if not sala:
                bot.answer_callback_query(call.id, "No se encontró la sala.")
                conn.close()
                return
            
            # Insertar valoración sin comentario
            cursor.execute("""
                INSERT INTO Valoraciones 
                (id_sala, id_profesor, id_estudiante, puntuacion, comentario, anonima) 
                VALUES (?, ?, ?, ?, '', 1)
            """, (
                sala_id,
                sala["Id_usuario"],
                user["Id_usuario"],
                puntuacion
            ))
            
            conn.commit()
            conn.close()
            
            # Mensaje de agradecimiento
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=mensaje_id,
                text="✅ *¡Gracias por tu valoración!*\n\n"
                    "Tu valoración ha sido registrada de forma anónima.\n"
                    "Serás expulsado del grupo en 3 segundos...",
                parse_mode="Markdown"
            )
            
            # Esperar 3 segundos antes de expulsar
            time.sleep(3)
            
            # Expulsar estudiante
            bot.ban_chat_member(
                chat_id, 
                user['TelegramID'],
                until_date=int(time.time()) + 60  # Ban de 1 minuto
            )
            
            # Limpiar datos
            if user_id in user_states:
                del user_states[user_id]
            if user_id in user_data:
                del user_data[user_id]
        
        except Exception as e:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=mensaje_id,
                text=f"❌ Error al guardar valoración: {str(e)}\n"
                    "Serás expulsado del grupo...",
                parse_mode="Markdown"
            )
            logger.error(f"Error al guardar valoración sin comentario: {e}")
            
            # Expulsar en caso de error
            try:
                bot.ban_chat_member(
                    chat_id, 
                    user['TelegramID'],
                    until_date=int(time.time()) + 60  # Ban de 1 minuto
                )
            except:
                pass

    @bot.callback_query_handler(func=lambda call: call.data == "exit_no_val")
    def handle_salir_sin_valorar(call):
        """Expulsa al estudiante sin valorar"""
        chat_id = call.message.chat.id
        mensaje_id = call.message.message_id
        user_id = call.from_user.id
        
        # Verificar usuario
        user = get_user_by_telegram_id(user_id)
        if not user or user['Tipo'] != 'estudiante':
            bot.answer_callback_query(call.id, "❌ Acción no permitida.")
            return
        
        try:
            # Mensaje final
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=mensaje_id,
                text="👋 *Saliendo de la tutoría*\n\n"
                    "Has elegido salir sin valorar.\n"
                    "Serás expulsado del grupo en 3 segundos...",
                parse_mode="Markdown"
            )
            
            # Esperar 3 segundos
            time.sleep(3)
            
            # Expulsar estudiante
            bot.ban_chat_member(
                chat_id, 
                user['TelegramID'],
                until_date=int(time.time()) + 60  # Ban de 1 minuto
            )
            
        except Exception as e:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=mensaje_id,
                text=f"❌ Error: {str(e)}\n"
                    "Serás expulsado del grupo...",
                parse_mode="Markdown"
            )
            logger.error(f"Error al expulsar sin valorar: {e}")
            
            # Intentar expulsar en caso de error
            try:
                bot.ban_chat_member(
                    chat_id, 
                    user['TelegramID'],
                    until_date=int(time.time()) + 60  # Ban de 1 minuto
                )
            except:
                pass



