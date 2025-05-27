"""
Archivo principal del bot de grupos de tutorías.
Inicialización, configuración y handlers básicos.
"""
import telebot
from telebot import types
import threading
import time
import os
import sys
import logging
from dotenv import load_dotenv

# Importar utilidades y handlers
from grupo_handlers.grupos import register_handlers as register_grupo_handlers
from grupo_handlers.valoraciones import register_handlers as register_valoraciones_handlers
from grupo_handlers.utils import (
    limpiar_estados_obsoletos, es_profesor, menu_profesor, menu_estudiante, 
    configurar_logger, configurar_comandos_por_rol
)
# Importar estados desde el manejador central
from utils.state_manager import user_states, user_data, estados_timestamp, set_state, get_state, clear_state

# Configuración de logging
logger = configurar_logger()

# Cargar token del bot de grupos
base_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(base_dir, "datos.env.txt")

if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
    logger.info(f"Cargando variables desde {env_path}")
else:
    load_dotenv()
    logger.warning("No se encontró archivo de variables específico")

# Estandarizar el nombre del token
BOT_TOKEN = os.getenv("TOKEN_GRUPO")
if not BOT_TOKEN:
    logger.warning("TOKEN_GRUPO no encontrado, buscando TOKEN_1 como alternativa")
    BOT_TOKEN = os.getenv("TOKEN_1")
    
if not BOT_TOKEN:
    logger.critical("Token del bot de grupos no encontrado")
    print("El token del bot de grupos no está configurado. Añade TOKEN_GRUPO en datos.env.txt")
    sys.exit(1)

# Inicializar el bot
bot = telebot.TeleBot(BOT_TOKEN)

# Mecanismo para prevenir instancias duplicadas del bot
import socket
import sys
import atexit

def prevent_duplicate_instances(port=12345):
    """Evita que se ejecuten múltiples instancias del bot usando un socket de bloqueo"""
    global lock_socket
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        lock_socket.bind(('localhost', port))
        print(f"🔒 Instancia única asegurada en el puerto {port}")
    except socket.error:
        print("⚠️ ADVERTENCIA: Otra instancia del bot ya está en ejecución.")
        print("⚠️ Cierra todas las demás instancias antes de ejecutar este script.")
        sys.exit(1)

    # Asegurar que el socket se cierra al salir
    def cleanup():
        lock_socket.close()
    atexit.register(cleanup)

# Prevenir múltiples instancias
prevent_duplicate_instances()

# Crear una función wrapper que maneje errores de Markdown
def safe_send_message(chat_id, text, parse_mode=None, **kwargs):
    if parse_mode == "Markdown":
        try:
            return bot.send_message(chat_id, text, parse_mode=parse_mode, **kwargs)
        except Exception as e:
            logger.warning(f"Error con Markdown, reintentando sin formato: {e}")
            return bot.send_message(chat_id, text, parse_mode=None, **kwargs)
    else:
        return bot.send_message(chat_id, text, parse_mode=parse_mode, **kwargs)

# Importar funciones de la base de datos compartidas
from db.queries import get_db_connection, get_user_by_telegram_id, crear_grupo_tutoria

# Handlers básicos
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    user = get_user_by_telegram_id(user_id)
    
    if not user:
        bot.send_message(
            chat_id,
            "👋 Bienvenido al sistema de tutorías en grupos.\n\n"
            "No te encuentro registrado en el sistema. Por favor, primero regístrate con el bot principal."
        )
        return
    
    # Actualizar interfaz según rol y tipo de chat
    if message.chat.type in ['group', 'supergroup']:
        # Estamos en un grupo
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
        grupo = cursor.fetchone()
        conn.close()
        
        if grupo:
            # Es un grupo de tutoría registrado
            if user['Tipo'] == 'profesor':
                bot.send_message(
                    chat_id,
                    "👨‍🏫 *Bot de tutoría activo*\n\n"
                    "Este grupo está configurado como sala de tutoría. Usa los botones para gestionarla.",
                    reply_markup=menu_profesor(),
                    parse_mode="Markdown"
                )
            else:
                # Es estudiante
                bot.send_message(
                    chat_id,
                    "👨‍🎓 *Bot de tutoría activo*\n\n"
                    "Cuando termines tu consulta, usa el botón para finalizar la tutoría.",
                    reply_markup=menu_estudiante(),
                    parse_mode="Markdown"
                )
        else:
            # No es un grupo registrado
            if user['Tipo'] == 'profesor':
                bot.send_message(
                    chat_id,
                    "Este grupo no está configurado como sala de tutoría. Usa /configurar_grupo para configurarlo."
                )
    else:
        # Es un chat privado
        if user['Tipo'] == 'profesor':
            bot.send_message(
                chat_id,
                "¡Bienvenido, Profesor! Usa los botones para gestionar tus tutorías.",
                reply_markup=menu_profesor()
            )
        else:
            # Es estudiante
            bot.send_message(
                chat_id,
                "¡Hola! Para unirte a una tutoría, necesitas el enlace de invitación de tu profesor.",
                reply_markup=menu_estudiante()
            )
    
    logger.info(f"Usuario {user_id} ({user['Nombre']}) ha iniciado el bot en chat {chat_id}")
    actualizar_interfaz_usuario(user_id, chat_id)

@bot.message_handler(commands=['ayuda'])
def ayuda_comando(message):
    chat_id = message.chat.id
    bot.send_message(
        chat_id,
        "ℹ️ *Ayuda del Bot*\n\n"
        "🔹 Usa los siguientes comandos para interactuar con el bot:\n"
        "✅ /ayuda - Muestra este mensaje de ayuda.\n"
        "✅ Pulsa el botón '❌ Terminar Tutoria' para finalizar tu consulta o expulsar a un estudiante (solo para profesores).\n"
        "✅ /start - Almacena tus datos y te da la bienvenida si eres estudiante.",
        parse_mode="Markdown"
    )
    logger.info(f"Mensaje de ayuda enviado a {chat_id}")

def actualizar_interfaz_usuario(user_id, chat_id=None):
    """Actualiza la interfaz completa según el rol del usuario."""
    comandos_profesor, comandos_estudiante = configurar_comandos_por_rol()
    try:
        if es_profesor(user_id):
            # Actualizar comandos visibles
            scope = telebot.types.BotCommandScopeChat(user_id)
            bot.set_my_commands(comandos_profesor, scope)
            
            # Si hay un chat_id, enviar menú de profesor
            if chat_id:
                bot.send_message(
                    chat_id,
                    "🔄 Interfaz actualizada para profesor",
                    reply_markup=menu_profesor()
                )
            logger.info(f"Interfaz de profesor configurada para usuario {user_id}")
        else:
            # Actualizar comandos visibles
            scope = telebot.types.BotCommandScopeChat(user_id)
            bot.set_my_commands(comandos_estudiante, scope)
            
            # Si hay un chat_id, enviar menú de estudiante
            if chat_id:
                bot.send_message(
                    chat_id,
                    "🔄 Interfaz actualizada para estudiante",
                    reply_markup=menu_estudiante()
                )
            logger.info(f"Interfaz de estudiante configurada para usuario {user_id}")
    except Exception as e:
        logger.error(f"Error configurando interfaz para usuario {user_id}: {e}")

# Iniciar hilo de limpieza periódica
def limpieza_periodica():
    while True:
        time.sleep(1800)  # 30 minutos
        try:
            limpiar_estados_obsoletos()
        except Exception as e:
            logger.error(f"Error en limpieza periódica: {e}")

@bot.message_handler(commands=['configurar_grupo'])
def configurar_grupo(message):
    """
    Inicia el proceso de configuración de un grupo como sala de tutoría
    """
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Verificar que estamos en un grupo
    if message.chat.type not in ['group', 'supergroup']:
        bot.send_message(chat_id, "⚠️ Este comando solo funciona en grupos.")
        return
        
    # Verificar que el usuario es profesor
    if not es_profesor(user_id):
        bot.send_message(chat_id, "⚠️ Solo los profesores pueden configurar grupos.")
        return
        
    # Verificar que el bot tiene permisos de administrador
    bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
    if bot_member.status != 'administrator':
        bot.send_message(
            chat_id,
            "⚠️ Para configurar este grupo necesito ser administrador con permisos para:\n"
            "- Invitar usuarios mediante enlaces\n"
            "- Eliminar mensajes\n"
            "- Restringir usuarios"
        )
        return
    
    # Verificar si el grupo ya está configurado
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
    grupo = cursor.fetchone()
    
    if grupo:
        bot.send_message(chat_id, "ℹ️ Este grupo ya está configurado como sala de tutoría.")
        conn.close()
        return
    
    # Obtener ID del usuario profesor
    cursor.execute("SELECT Id_usuario FROM Usuarios WHERE TelegramID = ? AND Tipo = 'profesor'", (str(user_id),))
    profesor_row = cursor.fetchone()
    
    if not profesor_row:
        bot.send_message(chat_id, "⚠️ Solo los profesores registrados pueden configurar grupos.")
        conn.close()
        return
        
    profesor_id = profesor_row['Id_usuario']
    
    # CONSULTA MEJORADA: Obtener SOLO asignaturas sin sala de avisos asociada
    cursor.execute("""
        SELECT a.Id_asignatura, a.Nombre 
        FROM Asignaturas a 
        JOIN Matriculas m ON a.Id_asignatura = m.Id_asignatura
        WHERE m.Id_usuario = ? 
        AND NOT EXISTS (
            SELECT 1 
            FROM Grupos_tutoria g 
            WHERE g.Id_asignatura = a.Id_asignatura 
            AND g.Id_usuario = ?
        )
    """, (profesor_id, profesor_id))
    
    asignaturas_disponibles = cursor.fetchall()
    
    # Verificar si ya tiene sala de tutoría privada
    cursor.execute("""
        SELECT COUNT(*) as total
        FROM Grupos_tutoria g
        WHERE g.Id_usuario = ? AND g.Tipo_sala = 'privada'
    """, (profesor_id,))
    
    tiene_privada = cursor.fetchone()['total'] > 0
    
    # Depuración - Mostrar salas actuales
    cursor.execute("""
        SELECT g.id_sala, g.Nombre_sala, g.Id_asignatura, a.Nombre as Asignatura
        FROM Grupos_tutoria g
        LEFT JOIN Asignaturas a ON g.Id_asignatura = a.Id_asignatura
        WHERE g.Id_usuario = ?
    """, (profesor_id,))

    salas_actuales = cursor.fetchall()
    print(f"\n--- SALAS ACTUALES PARA PROFESOR ID {profesor_id} ---")
    for sala in salas_actuales:
        # Usar operador ternario para manejar valores nulos
        nombre_asignatura = sala['Asignatura'] if sala['Asignatura'] is not None else 'N/A'
        print(f"Sala ID: {sala['id_sala']}, Nombre: {sala['Nombre_sala']}, " + 
              f"Asignatura ID: {sala['Id_asignatura']}, Asignatura: {nombre_asignatura}")
    print("--- FIN SALAS ACTUALES ---\n")
    
    conn.close()
    
    # Verificar si hay asignaturas disponibles
    if not asignaturas_disponibles and not (not tiene_privada):
        mensaje = "⚠️ No hay más asignaturas disponibles para configurar."
        if tiene_privada:
            mensaje += "\n\nYa tienes una sala configurada para cada asignatura y una sala de tutoría privada."
        bot.send_message(chat_id, mensaje)
        return
    
    # Crear teclado con las asignaturas disponibles que no tienen sala
    markup = types.InlineKeyboardMarkup()
    
    if asignaturas_disponibles:
        for asig in asignaturas_disponibles:
            callback_data = f"config_asig_{asig[0]}"
            markup.add(types.InlineKeyboardButton(text=asig[1], callback_data=callback_data))
    
    # Añadir opción de tutoría privada SOLO si no tiene una ya
    if not tiene_privada:
        markup.add(types.InlineKeyboardButton("Tutoría Privada", callback_data="config_tutoria_privada"))
        print(f"✅ Usuario {user_id} NO tiene sala privada - Mostrando opción")
    else:
        print(f"⚠️ Usuario {user_id} YA tiene sala privada - Ocultando opción")
    
    # Comprobar si no hay opciones disponibles
    if not asignaturas_disponibles and tiene_privada:
        bot.send_message(
            chat_id,
            "⚠️ No puedes configurar más salas. Ya tienes una sala para cada asignatura y una sala privada."
        )
        return
    
    # Guardar estado para manejar la siguiente interacción
    set_state(user_id, "esperando_asignatura_grupo")
    user_data[user_id] = {"chat_id": chat_id}
    
    # Enviar mensaje con las opciones
    mensaje = "🏫 *Configuración de sala de tutoría*\n\n"
    
    if asignaturas_disponibles:
        mensaje += "Selecciona la asignatura para la que deseas configurar este grupo:"
    else:
        mensaje += "Ya has configurado salas para todas tus asignaturas."
    
    # Si ya tiene sala privada, informarle
    if tiene_privada:
        mensaje += "\n\n*Nota:* Ya tienes una sala de tutoría privada configurada, por lo que esa opción no está disponible."
    
    bot.send_message(
        chat_id,
        mensaje,
        reply_markup=markup,
        parse_mode="Markdown"
    )

# Añadir este callback handler a archivo grupo_handlers/grupos.py
@bot.callback_query_handler(func=lambda call: call.data.startswith('config_asig_'))
def handle_configuracion_asignatura(call):
    user_id = call.from_user.id
    id_asignatura = call.data.split('_')[2]  # Extraer ID de la asignatura
    
    # Verificar estado
    if get_state(user_id) != "esperando_asignatura_grupo":
        bot.answer_callback_query(call.id, "Esta opción ya no está disponible")
        return
        
    # Obtener datos guardados
    if user_id not in user_data or "chat_id" not in user_data[user_id]:
        bot.answer_callback_query(call.id, "Error: Datos no encontrados")
        clear_state(user_id)
        return
        
    chat_id = user_data[user_id]["chat_id"]
    
    try:
        # Registrar el grupo en la base de datos
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Obtener nombre de la asignatura
        cursor.execute("SELECT Nombre FROM Asignaturas WHERE Id_asignatura = ?", (id_asignatura,))
        asignatura_nombre = cursor.fetchone()[0]
        
        # Obtener Id_usuario del profesor a partir de su TelegramID
        cursor.execute("SELECT Id_usuario FROM Usuarios WHERE TelegramID = ?", (str(user_id),))
        id_usuario_profesor = cursor.fetchone()[0]

        # Cerrar la conexión temporal
        conn.close()

        # Crear enlace de invitación si es posible
        try:
            enlace_invitacion = bot.create_chat_invite_link(chat_id).invite_link
        except:
            enlace_invitacion = None
        
        # Configurar directamente como sala de avisos (pública)
        # CORRECCIÓN: Usar "pública" con tilde para cumplir con el constraint
        tipo_sala = "pública"  # Cambiado de "publica" a "pública"
        sala_tipo_texto = "Avisos"
        nuevo_nombre = f"{asignatura_nombre} - Avisos"
        
        # Cambiar el nombre del grupo
        try:
            bot.set_chat_title(chat_id, nuevo_nombre)
        except Exception as e:
            logger.warning(f"No se pudo cambiar el nombre del grupo: {e}")
        
        # Crear el grupo en la base de datos
        from db.queries import crear_grupo_tutoria
        crear_grupo_tutoria(
            profesor_id=id_usuario_profesor,
            nombre_sala=nuevo_nombre,
            tipo_sala=tipo_sala,  # Ahora con el valor correcto "pública"
            asignatura_id=id_asignatura,
            chat_id=str(chat_id),
            enlace=enlace_invitacion
        )
        
        # Mensaje de éxito
        bot.edit_message_text(
            f"✅ Grupo configurado exitosamente como sala de avisos para *{asignatura_nombre}*",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Enviar mensaje informativo
        descripcion = "Esta es una sala para **avisos generales** de la asignatura donde los estudiantes pueden unirse mediante el enlace de invitación."
        
        bot.send_message(
            chat_id,
            f"🎓 *Sala configurada*\n\n"
            f"Esta sala está ahora configurada como: *Sala de Avisos*\n\n"
            f"{descripcion}\n\n"
            "Como profesor puedes:\n"
            "• Gestionar el grupo según el propósito configurado\n"
            "• Compartir el enlace de invitación con tus estudiantes",
            parse_mode="Markdown",
            reply_markup=menu_profesor()  # Esto ahora devuelve un ReplyKeyboardMarkup
        )
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error al configurar grupo: {str(e)}")
        logger.error(f"Error en la selección de asignatura {chat_id}: {e}")
    
    # Limpiar estado
    clear_state(user_id)

@bot.callback_query_handler(func=lambda call: call.data == 'config_tutoria_privada')
def handle_configuracion_tutoria_privada(call):
    user_id = call.from_user.id
    
    # Verificar estado
    if get_state(user_id) != "esperando_asignatura_grupo":
        bot.answer_callback_query(call.id, "Esta opción ya no está disponible")
        return
        
    # Obtener datos guardados
    if user_id not in user_data or "chat_id" not in user_data[user_id]:
        bot.answer_callback_query(call.id, "Error: Datos no encontrados")
        clear_state(user_id)
        return
        
    chat_id = user_data[user_id]["chat_id"]
    
    try:
        # Registrar el grupo en la base de datos
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Obtener Id_usuario y nombre del profesor a partir de su TelegramID
        cursor.execute("SELECT Id_usuario, Nombre FROM Usuarios WHERE TelegramID = ?", (str(user_id),))
        profesor = cursor.fetchone()
        id_usuario_profesor = profesor[0]
        nombre_profesor = profesor[1]

        # Cerrar la conexión temporal
        conn.close()

        # Crear enlace de invitación si es posible
        try:
            enlace_invitacion = bot.create_chat_invite_link(chat_id).invite_link
        except:
            enlace_invitacion = None
        
        # Configurar como sala de tutorías privadas
        tipo_sala = "privada"
        sala_tipo_texto = "Tutoría Privada"
        nuevo_nombre = f"Tutoría Privada - Prof. {nombre_profesor}"
        
        # Cambiar el nombre del grupo
        try:
            bot.set_chat_title(chat_id, nuevo_nombre)
        except Exception as e:
            logger.warning(f"No se pudo cambiar el nombre del grupo: {e}")
        
        # Crear el grupo en la base de datos
        from db.queries import crear_grupo_tutoria
        crear_grupo_tutoria(
            profesor_id=id_usuario_profesor,
            nombre_sala=nuevo_nombre,
            tipo_sala=tipo_sala,
            asignatura_id="0",  # 0 indica que no está vinculado a una asignatura específica
            chat_id=str(chat_id),
            enlace=enlace_invitacion
        )
        
        # Mensaje de éxito
        bot.edit_message_text(
            f"✅ Grupo configurado exitosamente como sala de tutorías privadas",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Enviar mensaje informativo
        descripcion = "Esta es tu sala de **tutorías privadas** donde solo pueden entrar estudiantes que invites específicamente."
        
        bot.send_message(
            chat_id,
            f"🎓 *Sala configurada*\n\n"
            f"Esta sala está ahora configurada como: *Sala de Tutorías Privadas*\n\n"
            f"{descripcion}\n\n"
            "Como profesor puedes:\n"
            "• Invitar a estudiantes específicos para tutorías\n"
            "• Expulsar estudiantes cuando finalice la consulta",
            parse_mode="Markdown",
            reply_markup=menu_profesor()
        )
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error al configurar grupo: {str(e)}")
        logger.error(f"Error en la configuración de tutoría privada {chat_id}: {e}")
    
    # Limpiar estado
    clear_state(user_id)
    
@bot.callback_query_handler(func=lambda call: call.data.startswith('proposito_'))
def handle_proposito_sala(call):
    user_id = call.from_user.id
    
    # Verificar estado
    if get_state(user_id) != "esperando_proposito_sala":
        bot.answer_callback_query(call.id, "Esta opción ya no está disponible")
        return
    
    # Extraer información
    proposito = call.data.split('_')[1]  # avisos o tutoria
    
    # Obtener datos guardados
    if user_id not in user_data:
        bot.answer_callback_query(call.id, "Error: Datos no encontrados")
        clear_state(user_id)
        return
    
    data = user_data[user_id]
    chat_id = data["chat_id"]
    asignatura_nombre = data["asignatura_nombre"]
    asignatura_id = data["asignatura_id"]
    enlace_invitacion = data["enlace_invitacion"]
    id_usuario_profesor = data["id_usuario_profesor"]
    
    try:
        if proposito == "avisos":
            # Es una sala de avisos para la asignatura (pública)
            id_asignatura = call.data.split('_')[2]
            tipo_sala = "pública"  # Cambiado de "publica" a "pública"
            sala_tipo_texto = "Avisos"
            nuevo_nombre = f"{asignatura_nombre} - Avisos"
            
            descripcion = "Esta es una sala para **avisos generales** de la asignatura donde los estudiantes pueden unirse mediante el enlace de invitación."
            
        else:
            # Es una sala de tutorías privada (independiente de asignaturas)
            tipo_sala = "privada"
            sala_tipo_texto = "Tutoría Privada"
            nuevo_nombre = f"Tutoría Privada - Prof. {data['id_usuario_profesor']}"
            asignatura_id = "0"  # Indicando que no está vinculada a una asignatura específica
            
            descripcion = "Esta es tu sala de **tutorías privadas** donde solo pueden entrar estudiantes que invites específicamente."
        
        # Cambiar nombre del grupo
        try:
            bot.set_chat_title(chat_id, nuevo_nombre)
        except Exception as e:
            logger.warning(f"No se pudo cambiar el nombre del grupo: {e}")
        
        # Crear el grupo en la base de datos
        from db.queries import crear_grupo_tutoria
        crear_grupo_tutoria(
            profesor_id=id_usuario_profesor,
            nombre_sala=nuevo_nombre,
            tipo_sala=tipo_sala,
            asignatura_id=asignatura_id,
            chat_id=str(chat_id),
            enlace=enlace_invitacion
        )
        
        # Mensaje de éxito
        bot.edit_message_text(
            f"✅ Grupo configurado exitosamente como sala de {sala_tipo_texto.lower()}",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown"
        )
        
        # Enviar mensaje informativo
        bot.send_message(
            chat_id,
            f"🎓 *Sala configurada*\n\n"
            f"Esta sala está ahora configurada como: *{sala_tipo_texto}*\n\n"
            f"{descripcion}\n\n"
            "Como profesor puedes:\n"
            "• Gestionar el grupo según el propósito configurado\n"
            "• Compartir el enlace de invitación con tus estudiantes",
            parse_mode="Markdown",
            reply_markup=menu_profesor()  # Esto ahora devuelve un ReplyKeyboardMarkup
        )
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error al configurar grupo: {str(e)}")
        logger.error(f"Error configurando grupo {chat_id}: {e}")
    
    # Limpiar estado
    clear_state(user_id)    
@bot.message_handler(func=lambda message: message.text == "👨‍🎓 Ver estudiantes")
def handle_ver_estudiantes_cmd(message):
    """Maneja el comando de ver estudiantes desde el teclado personalizado"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Verificar que el usuario es profesor
    user = get_user_by_telegram_id(user_id)
    if not user or user['Tipo'] != 'profesor':
        bot.send_message(chat_id, "⚠️ Solo los profesores pueden ver la lista de estudiantes")
        return
        
    # Aquí va el código para mostrar la lista de estudiantes
    # (el mismo que tenías en tu handler de callback)
    try:
        # Obtener grupo y estudiantes
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verificar que este chat es un grupo registrado
        cursor.execute(
            "SELECT id_sala FROM Grupos_tutoria WHERE Chat_id = ?", 
            (str(chat_id),)
        )
        sala = cursor.fetchone()
        
        if not sala:
            bot.send_message(chat_id, "⚠️ Este grupo no está configurado como sala de tutoría")
            conn.close()
            return
            
        sala_id = sala['id_sala']
        
        # Obtener lista de estudiantes
        cursor.execute("""
            SELECT u.Nombre, u.Apellidos, u.TelegramID, m.Fecha_incorporacion, m.Estado
            FROM Miembros_Grupo m
            JOIN Usuarios u ON m.Id_usuario = u.Id_usuario
            WHERE m.id_sala = ? AND u.Tipo = 'alumno'
            ORDER BY m.Fecha_incorporacion DESC
        """, (sala_id,))
        
        estudiantes = cursor.fetchall()
        conn.close()
        
        if not estudiantes:
            bot.send_message(
                chat_id, 
                "📊 *No hay estudiantes*\n\nAún no hay estudiantes en este grupo.",
                parse_mode="Markdown"
            )
            return
            
        # Crear mensaje con lista de estudiantes
        mensaje = "👨‍🎓 *Lista de estudiantes*\n\n"
        
        for i, est in enumerate(estudiantes, 1):
            nombre_completo = f"{est['Nombre']} {est['Apellidos'] or ''}"
            fecha = est['Fecha_incorporacion'].split()[0]  # Solo la fecha, no la hora
            estado = "✅ Activo" if est['Estado'] == 'activo' else "❌ Inactivo"
            
            mensaje += f"{i}. *{nombre_completo}*\n"
            mensaje += f"   • Desde: {fecha}\n"
            mensaje += f"   • Estado: {estado}\n\n"
        
        bot.send_message(chat_id, mensaje, parse_mode="Markdown")
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error al recuperar estudiantes: {str(e)}")
        logger.error(f"Error recuperando estudiantes del grupo {chat_id}: {e}")

@bot.message_handler(func=lambda message: message.text == "❌ Terminar Tutoria")
def handle_terminar_tutoria_cmd(message):
    """Maneja el comando de terminar tutoría desde el teclado personalizado"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    # Verificar que el usuario es profesor
    user = get_user_by_telegram_id(user_id)
    if not user or user['Tipo'] != 'profesor':
        bot.send_message(chat_id, "⚠️ Solo los profesores pueden terminar la tutoría")
        return
    
    # Obtener datos de la sala y sus miembros (estudiantes)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verificar que este chat es un grupo registrado
        cursor.execute(
            "SELECT id_sala, Tipo_sala FROM Grupos_tutoria WHERE Chat_id = ?", 
            (str(chat_id),)
        )
        sala = cursor.fetchone()
        
        if not sala:
            bot.send_message(chat_id, "⚠️ Este grupo no está configurado como sala de tutoría")
            conn.close()
            return
            
        sala_id = sala['id_sala']
        tipo_sala = sala['Tipo_sala']
        
        # Obtener lista de estudiantes activos en el grupo
        cursor.execute("""
            SELECT u.Id_usuario, u.Nombre, u.Apellidos, u.TelegramID
            FROM Miembros_Grupo m
            JOIN Usuarios u ON m.Id_usuario = u.Id_usuario
            WHERE m.id_sala = ? AND u.Tipo = 'alumno' AND m.Estado = 'activo'
            ORDER BY u.Nombre
        """, (sala_id,))
        
        estudiantes = cursor.fetchall()
        conn.close()
        
        if not estudiantes:
            bot.send_message(
                chat_id, 
                "📊 *No hay estudiantes*\n\nNo hay estudiantes activos en esta tutoría para expulsar.",
                parse_mode="Markdown"
            )
            return
        
        # Crear un mensaje con la lista de estudiantes para seleccionar
        mensaje = "👨‍🎓 *Selecciona el estudiante que ha terminado su tutoría:*\n\n"
        mensaje += "El estudiante será expulsado temporalmente (1 minuto) del grupo y podrá volver a entrar cuando necesite otra tutoría.\n\n"
        
        # Crear botones inline con los estudiantes
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        for estudiante in estudiantes:
            nombre_completo = f"{estudiante['Nombre']} {estudiante['Apellidos'] or ''}".strip()
            # Incluir ID de usuario y TelegramID en el callback_data
            callback_data = f"expulsar_{sala_id}_{estudiante['Id_usuario']}_{estudiante['TelegramID'] or '0'}"
            
            markup.add(types.InlineKeyboardButton(
                f"👤 {nombre_completo}",
                callback_data=callback_data
            ))
        
        # Botón para cancelar
        markup.add(types.InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_expulsion"))
        
        # Enviar mensaje con las opciones
        bot.send_message(
            chat_id,
            mensaje,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error al procesar la solicitud: {str(e)}")
        import traceback
        print(f"Error en terminar tutoría: {e}")
        print(traceback.format_exc())


@bot.callback_query_handler(func=lambda call: call.data.startswith("expulsar_"))
def handle_expulsar_estudiante(call):
    """Maneja la expulsión temporal de un estudiante del grupo"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    # Parsear datos del callback
    partes = call.data.split("_")
    sala_id = int(partes[1])
    estudiante_id = int(partes[2])
    estudiante_telegram_id = partes[3]
    
    # Prevenir errores si el ID de Telegram es '0' (nulo)
    if estudiante_telegram_id == '0':
        estudiante_telegram_id = None
    
    # Verificar que el usuario es profesor
    user = get_user_by_telegram_id(call.from_user.id)
    if not user or user['Tipo'] != 'profesor':
        bot.answer_callback_query(call.id, "⚠️ No tienes permisos para esta acción")
        return
    
    try:
        # Obtener información del estudiante y la sala
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Obtener datos del estudiante
        cursor.execute(
            "SELECT Nombre, Apellidos FROM Usuarios WHERE Id_usuario = ?", 
            (estudiante_id,)
        )
        estudiante = cursor.fetchone()
        
        if not estudiante:
            bot.answer_callback_query(call.id, "⚠️ No se encontró el estudiante")
            conn.close()
            return
            
        nombre_completo = f"{estudiante['Nombre']} {estudiante['Apellidos'] or ''}".strip()
        
        # Actualizar la tabla Miembros_Grupo para cambiar el estado del estudiante
        cursor.execute(
            "UPDATE Miembros_Grupo SET Estado = 'pausado' WHERE id_sala = ? AND Id_usuario = ?",
            (sala_id, estudiante_id)
        )
        conn.commit()
        conn.close()
        
        # Función auxiliar para escapar caracteres markdown
        def escape_markdown(text):
            if not text:
                return ""
            chars = ['_', '*', '`', '[', ']', '(', ')', '#', '+', '-', '.', '!']
            for char in chars:
                text = text.replace(char, '\\' + char)
            return text
        
        # Intentar expulsar al estudiante del grupo de Telegram con ban de 1 minuto (60 segundos)
        if estudiante_telegram_id:
            try:
                import time
                tiempo_ban = 60  # Ban de 1 minuto (60 segundos)
                bot.ban_chat_member(chat_id, estudiante_telegram_id, until_date=int(time.time() + tiempo_ban))
                print(f"✅ Estudiante {estudiante_telegram_id} expulsado temporalmente del grupo {chat_id}")
                
                # Enviar mensaje de confirmación
                bot.edit_message_text(
                    f"✅ *Tutoría finalizada*\n\n"
                    f"El estudiante *{escape_markdown(nombre_completo)}* ha sido expulsado temporalmente del grupo.\n"
                    f"Podrá volver a unirse después de 1 minuto.",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode="Markdown"
                )
                
                # Enviar mensaje al estudiante si es posible
                try:
                    bot.send_message(
                        estudiante_telegram_id,
                        f"ℹ️ *Tutoría finalizada*\n\n"
                        f"Tu tutoría ha concluido y has sido temporalmente removido del grupo.\n"
                        f"Podrás volver a unirte después de 1 minuto si necesitas otra consulta.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Error al enviar mensaje al estudiante: {e}")
            except Exception as e:
                print(f"Error al expulsar estudiante: {e}")
                bot.edit_message_text(
                    f"⚠️ *No se pudo expulsar al estudiante*\n\n"
                    f"La tutoría con *{escape_markdown(nombre_completo)}* ha sido registrada como finalizada,\n"
                    f"pero no se pudo expulsar al estudiante del grupo automáticamente.",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode="Markdown"
                )
        else:
            # No tenemos ID de Telegram del estudiante
            bot.edit_message_text(
                f"⚠️ *No se pudo expulsar al estudiante*\n\n"
                f"No se encontró el ID de Telegram para *{escape_markdown(nombre_completo)}*.\n"
                f"La tutoría ha sido registrada como finalizada, pero deberás expulsar al estudiante manualmente.",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="Markdown"
            )
        
    except Exception as e:
        bot.edit_message_text(
            f"❌ Error al expulsar estudiante: {str(e)}",
            chat_id=chat_id,
            message_id=message_id
        )
        import traceback
        print(f"Error al expulsar estudiante: {e}")
        print(traceback.format_exc())
    
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "cancelar_expulsion")
def handle_cancelar_expulsion(call):
    """Cancela la operación de expulsión"""
    bot.edit_message_text(
        "❌ Operación cancelada. No se ha expulsado a ningún estudiante.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    bot.answer_callback_query(call.id)
    
if __name__ == "__main__":
    # Verificar que existe la base de datos
    if not os.path.exists(os.path.join(base_dir, "tutoria_ugr.db")):
        logger.error("Base de datos no encontrada")
        print("Error: Base de datos no encontrada. Primero ejecuta python -m db.models")
        sys.exit(1)
    
    # Establecer comandos generales para todos los usuarios
    bot.set_my_commands([
        telebot.types.BotCommand('/start', 'Iniciar el bot'),
        telebot.types.BotCommand('/ayuda', 'Mostrar ayuda')
    ])
    
    # Añadir comandos específicos para grupos
    commands_grupos = bot.set_my_commands([
        telebot.types.BotCommand('/start', 'Iniciar el bot'),
        telebot.types.BotCommand('/ayuda', 'Mostrar ayuda'),
        telebot.types.BotCommand('/configurar_grupo', 'Configurar este grupo como sala')
    ], scope=telebot.types.BotCommandScopeAllGroupChats())
    
    # Registrar handlers específicos
    register_grupo_handlers(bot)
    register_valoraciones_handlers(bot)
    
    # Iniciar hilo de limpieza
    threading.Thread(target=limpieza_periodica, daemon=True).start()
    
    print(f"🤖 Bot de Grupos iniciado con token: {BOT_TOKEN[:5]}...{BOT_TOKEN[-5:]}")
    logger.info("Bot de Grupos iniciado")
    
    # Polling con manejo de errores
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            logger.error(f"Error en polling: {e}")
            time.sleep(10)