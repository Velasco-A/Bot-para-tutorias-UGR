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
        
    # Obtener las asignaturas del profesor
    cursor.execute("""
        SELECT a.Id_asignatura, a.Nombre 
        FROM Asignaturas a 
        JOIN Matriculas m ON a.Id_asignatura = m.Id_asignatura
        JOIN Usuarios u ON m.Id_usuario = u.Id_usuario
        WHERE u.TelegramID = ? AND u.Tipo = 'profesor'
    """, (str(user_id),))
    
    asignaturas = cursor.fetchall()
    conn.close()
    
    if not asignaturas:
        bot.send_message(chat_id, "⚠️ No tienes asignaturas asignadas. Contacta con el administrador.")
        return
    
    # Crear teclado con las asignaturas
    markup = types.InlineKeyboardMarkup()
    for asig in asignaturas:
        callback_data = f"config_asig_{asig[0]}"  # Formato: config_asig_ID
        markup.add(types.InlineKeyboardButton(text=asig[1], callback_data=callback_data))
    
    # Añadir opción de tutoría privada
    markup.add(types.InlineKeyboardButton("Tutoría Privada", callback_data="config_tutoria_privada"))
    
    # Guardar estado para manejar la siguiente interacción
    set_state(user_id, "esperando_asignatura_grupo")
    user_data[user_id] = {"chat_id": chat_id}
    
    # Enviar mensaje con las opciones
    bot.send_message(
        chat_id,
        "🏫 *Configuración de sala de tutoría*\n\n"
        "Selecciona la asignatura para la que deseas configurar este grupo:",
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
        tipo_sala = "publica"
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
            tipo_sala=tipo_sala,
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
            reply_markup=menu_profesor()
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
            tipo_sala = "publica"
            sala_tipo_texto = "Avisos"
            nuevo_nombre = f"{asignatura_nombre} - Avisos"
            
            descripcion = "Esta es una sala para **avisos generales** de la asignatura donde los estudiantes pueden unirse mediante el enlace de invitación."
            
        else:  # tutoria_privada
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
            "• Si quieres cambiar el propósito, usa el menú principal.",
            parse_mode="Markdown",
            reply_markup=menu_profesor()
        )
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error al configurar grupo: {str(e)}")
        logger.error(f"Error configurando grupo {chat_id}: {e}")
    
    # Limpiar estado
    clear_state(user_id)    
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