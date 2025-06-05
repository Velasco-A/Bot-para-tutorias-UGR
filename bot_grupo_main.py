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
import sqlite3
from dotenv import load_dotenv

# Importar utilidades y handlers
from grupo_handlers.grupos import GestionGrupos
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

from telebot import apihelper
apihelper.ENABLE_MIDDLEWARE = True

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

# Reemplaza la función configurar_grupo actual con esta versión mejorada:

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

# Añadir este handler después de handle_new_chat_members
@bot.message_handler(content_types=['group_chat_created'])
def handle_group_created(message):
    """Maneja cuando el bot es añadida durante la creación de un grupo"""
    try:
        print("\n==================================================")
        print("⚠️⚠️⚠️ HANDLER ACTIVADO: GRUPO CREADO ⚠️⚠️⚠️")
        print(f"⚠️ Chat ID: {message.chat.id} | Tipo: {message.chat.type}")
        print(f"⚠️ De: {message.from_user.first_name} (ID: {message.from_user.id})")
        print("==================================================\n")
        
        chat_id = message.chat.id
        
        print(f"🤖 BOT AÑADIDO AL GRUPO RECIÉN CREADO {chat_id}")
        
        bot.send_message(
            chat_id,
            "¡Hola a todos!\n\n"
                "Soy el asistente para gestión de grupos de clase y tutorías. Es un placer "
                "estar aquí y ayudar a organizar este espacio educativo.\n\n"
                "Para poder configurar correctamente el grupo necesito ser administrador. "
                "Por favor, sigue estos pasos:\n\n"
                "1. Entra en la información del grupo\n"
                "2. Selecciona 'Administradores'\n"
                "3. Añádeme como administrador\n\n"
                "Una vez me hayas hecho administrador, podré configurar este grupo "
                "para tu clase o tutorías. ¡Gracias por tu confianza!"
        )
        
        print(f"✅ Mensaje de bienvenida enviado al grupo {chat_id}")
        
        # Registrar el grupo en la base de datos provisionalmente
        try:
            nombre_grupo = message.chat.title
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Verificar si el grupo ya existe
            cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
            grupo = cursor.fetchone()
            
            if not grupo:
                # Crear registro provisional
                cursor.execute(
                    """INSERT INTO Grupos_tutoria 
                    (Id_usuario, Nombre_sala, Tipo_sala, Chat_id, Proposito_sala) 
                    VALUES (?, ?, ?, ?, ?)""",
                    (message.from_user.id, nombre_grupo, 'pública', str(chat_id), 'pendiente')
                )
                conn.commit()
                print(f"✅ Grupo {nombre_grupo} (ID: {chat_id}) registrado como 'pendiente'")
            else:
                print(f"⚠️ El grupo {nombre_grupo} ya estaba registrado")
            
            conn.close()
        except Exception as e:
            print(f"❌ Error al registrar grupo: {e}")
            import traceback
            traceback.print_exc()
        
    except Exception as e:
        print(f"❌❌❌ ERROR EN HANDLER GROUP_CREATED: {e}")
        import traceback
        traceback.print_exc()
    
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
        # Usar la nueva función para operaciones de BD
        from grupo_handlers.utils import execute_db_operation
        
        # Función que encapsula toda la lógica de base de datos
        def configurar_grupo_db(conn, cursor):
            # Obtener nombre de la asignatura
            cursor.execute("SELECT Nombre FROM Asignaturas WHERE Id_asignatura = ?", (id_asignatura,))
            asignatura_nombre = cursor.fetchone()[0]
            
            # Obtener Id_usuario del profesor a partir de su TelegramID
            cursor.execute("SELECT Id_usuario FROM Usuarios WHERE TelegramID = ?", (str(user_id),))
            id_usuario_profesor = cursor.fetchone()[0]
            
            return asignatura_nombre, id_usuario_profesor
        
        # Ejecutar consultas de base de datos con manejo de bloqueos
        result = execute_db_operation(configurar_grupo_db)
        
        if not result:
            bot.send_message(chat_id, "❌ Error al acceder a la base de datos. Inténtalo de nuevo.")
            return
            
        asignatura_nombre, id_usuario_profesor = result
        
        # Crear enlace de invitación si es posible
        try:
            enlace_invitacion = bot.create_chat_invite_link(chat_id).invite_link
        except:
            enlace_invitacion = None
        
        # MODIFICACIÓN: En lugar de configurar directamente, preguntar el propósito
        # Guardar los datos en user_data
        user_data[user_id].update({
            "id_asignatura": id_asignatura,
            "asignatura_nombre": asignatura_nombre,
            "id_usuario_profesor": id_usuario_profesor,
            "enlace_invitacion": enlace_invitacion
        })
        
        # Cambiar el estado del usuario
        set_state(user_id, "esperando_proposito_sala")
        
        # Crear teclado con opciones de propósito
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                text="Sala de Avisos (pública)", 
                callback_data=f"proposito_avisos_{id_asignatura}"
            ),
            types.InlineKeyboardButton(
                text="Sala de Tutoría (privada)",
                callback_data="proposito_tutoria"
            ),
            types.InlineKeyboardButton(
                text="❌ Cancelar",
                callback_data="cancelar"
            )
        )
        
        # Editar el mensaje para mostrar las opciones
        bot.edit_message_text(
            f"🏫 *{asignatura_nombre}*\n\n"
            "¿Qué tipo de sala quieres configurar?\n\n"
            "📢 *Sala de Avisos*: Para enviar anuncios generales de la asignatura.\n"
            "👨‍🏫 *Sala de Tutoría*: Para tutorías privadas con estudiantes específicos.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=markup
        )
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error al configurar grupo: {str(e)}")
        logger.error(f"Error en la selección de asignatura {chat_id}: {e}")
        import traceback
        traceback.print_exc()
        
        # Limpiar estado en caso de error
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
            asignatura_id = "0"  # Indicando que no está vinculida a una asignatura específica
            
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
def handle_terminar_tutoria(message):
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        print(f"🔄 Botón 'Terminar Tutoria' pulsado por el usuario {user_id} en chat {chat_id}")
        
        # Verificamos que estamos en un grupo
        if message.chat.type not in ['group', 'supergroup']:
            bot.send_message(chat_id, "Este comando solo funciona en grupos de tutoría.")
            return
        
        # Obtener información del usuario que pulsó
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM Usuarios WHERE TelegramID = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            bot.send_message(chat_id, "❌ No estás registrado en el sistema.")
            conn.close()
            return
        
        # Obtener información de la sala
        cursor.execute("""
            SELECT * FROM Grupos_tutoria WHERE Chat_id = ?
        """, (str(chat_id),))
        
        sala = cursor.fetchone()
        
        if not sala:
            bot.send_message(chat_id, "❌ Este grupo no está configurado como sala de tutoría.")
            conn.close()
            return
            
        sala_id = sala['id_sala']
        
        # Comportamiento diferente según el tipo de usuario
        if user['Tipo'] == 'estudiante':
            # CASO 1: ESTUDIANTE - Banear al estudiante temporalmente
            nombre_completo = f"{user['Nombre']} {user['Apellidos'] or ''}".strip()
            
            # ELIMINAR de la tabla Miembros_Grupo
            cursor.execute("""
                DELETE FROM Miembros_Grupo 
                WHERE id_sala = ? AND Id_usuario = ?
            """, (sala_id, user['Id_usuario']))
            conn.commit()
            
            # Mensaje de despedida
            bot.send_message(
                chat_id, 
                f"👋 *Tutoría finalizada*\n\n"
                f"El estudiante {nombre_completo} ha finalizado su tutoría.\n"
                f"¡Gracias por utilizar el sistema de tutorías!",
                parse_mode="Markdown"
            )
            
            # Banear temporalmente al estudiante (1 minuto) - usar ban_chat_member con until_date
            try:
                # Calcular tiempo de expulsión (1 minuto desde ahora)
                import time
                tiempo_expulsion = int(time.time() + 60)  # 60 segundos
                
                # IMPORTANTE: Usar ban_chat_member con tiempo de expiración
                bot.ban_chat_member(chat_id, user_id, until_date=tiempo_expulsion)
                print(f"✅ Usuario {user_id} baneado temporalmente del grupo {chat_id} por 1 minuto")
                
                # Notificar al estudiante por mensaje privado
                try:
                    bot.send_message(
                        user_id,
                        "✅ *Tutoría finalizada correctamente*\n\n"
                        "Has sido expulsado temporalmente del grupo de tutoría.\n"
                        "Podrás volver a entrar utilizando el mismo enlace después de 1 minuto.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Error al enviar mensaje privado: {e}")
            except Exception as e:
                print(f"Error al banear usuario: {e}")
                bot.send_message(
                    chat_id,
                    "⚠️ No se pudo expulsar automáticamente al estudiante.\n"
                    "Por favor, verifica los permisos del bot en el grupo.",
                    parse_mode="Markdown"
                )
                
        elif user['Tipo'] == 'profesor':
            # CASO 2: PROFESOR - Mostrar lista de estudiantes para seleccionar
            print(f"Profesor {user_id} solicitó lista de estudiantes en sala {sala_id}")
            
            try:
                # Obtener todos los miembros del chat que son estudiantes
                # Primero verificamos que estudiantes están en la base de datos
                cursor.execute("""
                    SELECT u.Id_usuario, u.Nombre, u.Apellidos, u.TelegramID, m.id_miembro
                    FROM Usuarios u
                    LEFT JOIN Miembros_Grupo m ON u.Id_usuario = m.Id_usuario AND m.id_sala = ?
                    WHERE u.Tipo = 'estudiante'
                    AND u.TelegramID IS NOT NULL
                    ORDER BY u.Nombre
                """, (sala_id,))
                
                estudiantes = cursor.fetchall()
                
                # Verificar si hay estudiantes
                if not estudiantes or len(estudiantes) == 0:
                    bot.send_message(
                        chat_id, 
                        "📊 *No hay estudiantes registrados*\n\n"
                        "No hay estudiantes para expulsar en esta tutoría.",
                        parse_mode="Markdown"
                    )
                    conn.close()
                    return
                
                # Crear un mensaje con la lista de estudiantes para seleccionar
                mensaje = "👨‍🎓 *Selecciona el estudiante que ha terminado su tutoría:*\n\n"
                mensaje += "El estudiante será baneado temporalmente (1 minuto) del grupo.\n\n"
                
                # Crear botones inline con los estudiantes
                markup = types.InlineKeyboardMarkup(row_width=1)
                
                hay_estudiantes = False
                
                # Obtener los miembros actuales del chat
                chat_members = []
                try:
                    chat_members = bot.get_chat_members_count(chat_id)
                    print(f"Total miembros en el chat: {chat_members}")
                except Exception as e:
                    print(f"Error al obtener miembros del chat: {e}")
                
                # Solo mostrar estudiantes que están actualmente en el chat
                for estudiante in estudiantes:
                    nombre_completo = f"{estudiante['Nombre']} {estudiante['Apellidos'] or ''}".strip()
                    telegram_id = estudiante['TelegramID']
                    
                    if telegram_id:
                        try:
                            # Verificar si el estudiante está en el chat
                            miembro = bot.get_chat_member(chat_id, telegram_id)
                            if miembro.status not in ['left', 'kicked']:
                                # Estudiante presente en el chat
                                hay_estudiantes = True
                                callback_data = f"expulsar_{sala_id}_{estudiante['Id_usuario']}_{telegram_id}"
                                markup.add(types.InlineKeyboardButton(
                                    text=nombre_completo,
                                    callback_data=callback_data
                                ))
                                print(f"Añadido estudiante {nombre_completo} a la lista")
                        except Exception as e:
                            print(f"Error verificando miembro {telegram_id}: {e}")
                
                # Añadir botón para cancelar
                markup.add(types.InlineKeyboardButton(
                    text="❌ Cancelar",
                    callback_data="cancelar_expulsion"
                ))
                
                if not hay_estudiantes:
                    bot.send_message(
                        chat_id, 
                        "📊 *No hay estudiantes activos*\n\n"
                        "No hay estudiantes activos en el chat para expulsar.",
                        parse_mode="Markdown"
                    )
                else:
                    # Enviar mensaje con opciones
                    bot.send_message(
                        chat_id,
                        mensaje,
                        reply_markup=markup,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                print(f"Error procesando lista de estudiantes: {e}")
                import traceback
                traceback.print_exc()
                bot.send_message(
                    chat_id,
                    "❌ Error al obtener la lista de estudiantes.",
                    parse_mode="Markdown"
                )
            
        conn.close()
        
    except Exception as e:
        print(f"Error en handle_terminar_tutoria: {e}")
        import traceback
        traceback.print_exc()
        bot.send_message(chat_id, "❌ Ocurrió un error al procesar tu solicitud.")

# Handler para los botones de expulsión
@bot.callback_query_handler(func=lambda call: call.data.startswith("expulsar_"))
def handle_expulsar_estudiante(call):
    try:
        chat_id = call.message.chat.id
        datos = call.data.split('_')
        sala_id = int(datos[1])
        estudiante_id = int(datos[2])
        telegram_id = int(datos[3]) if datos[3] != '0' else None
        
        if not telegram_id:
            bot.answer_callback_query(call.id, "❌ No se puede expulsar a este usuario porque no tiene ID de Telegram registrado")
            return
        
        # Conectar a la base de datos
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Obtener información del estudiante
        cursor.execute("SELECT * FROM Usuarios WHERE Id_usuario = ?", (estudiante_id,))
        estudiante = cursor.fetchone()
        
        if not estudiante:
            bot.answer_callback_query(call.id, "❌ Estudiante no encontrado")
            conn.close()
            return
            
        nombre_completo = f"{estudiante['Nombre']} {estudiante['Apellidos'] or ''}".strip()
        
        # ELIMINAR registro de Miembros_Grupo
        cursor.execute("""
            DELETE FROM Miembros_Grupo 
            WHERE id_sala = ? AND Id_usuario = ?
        """, (sala_id, estudiante_id))
        conn.commit()
        conn.close()
        
        # Calcular tiempo de expulsión (1 minuto)
        import time
        tiempo_expulsion = int(time.time() + 60)  # 60 segundos
        
        # Banear al estudiante temporalmente
        try:
            # IMPORTANTE: Usar ban_chat_member con tiempo de expiración
            bot.ban_chat_member(chat_id, telegram_id, until_date=tiempo_expulsion)
            
            # Editar el mensaje para indicar que se ha expulsado al estudiante
            bot.edit_message_text(
                f"✅ *Estudiante baneado temporalmente*\n\n"
                f"El estudiante {nombre_completo} ha sido baneado temporalmente.\n"
                f"Podrá volver a unirse al grupo después de 1 minuto usando el mismo enlace.",
                chat_id=chat_id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
            
            # Notificar al estudiante por mensaje privado
            try:
                bot.send_message(
                    telegram_id,
                    "✅ *Tutoría finalizada por el profesor*\n\n"
                    "Has sido baneado temporalmente del grupo de tutoría.\n"
                    "Podrás volver a entrar utilizando el mismo enlace después de 1 minuto.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Error al enviar mensaje privado: {e}")
                
        except Exception as e:
            print(f"Error al banear estudiante: {e}")
            bot.edit_message_text(
                f"❌ *Error al banear estudiante*\n\n"
                f"No se pudo banear al estudiante {nombre_completo}.\n"
                f"Verifica que el bot tiene permisos de administrador en el grupo.",
                chat_id=chat_id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
            
    except Exception as e:
        print(f"Error en handle_expulsar_estudiante: {e}")
        import traceback
        traceback.print_exc()
        bot.answer_callback_query(call.id, "❌ Error al procesar la solicitud")
@bot.message_handler(content_types=['new_chat_members'])
def handle_new_chat_members(message):
    """Maneja cuando un nuevo miembro se une al grupo"""
    try:
        print("\n==================================================")
        print("⚠️⚠️⚠️ HANDLER ACTIVADO PARA NUEVOS MIEMBROS ⚠️⚠️⚠️")
        print(f"⚠️ Chat ID: {message.chat.id} | Tipo: {message.chat.type}")
        print(f"⚠️ De: {message.from_user.first_name} (ID: {message.from_user.id})")
        print(f"⚠️ Nuevos miembros: {[(m.first_name, m.id) for m in message.new_chat_members]}")
        print("==================================================\n")
        
        chat_id = message.chat.id
        bot_id = bot.get_me().id
        
        # Detectar si el bot fue añadida
        bot_added = False
        for member in message.new_chat_members:
            if member.id == bot_id:
                bot_added = True
                print(f"✓ BOT DETECTADO COMO NUEVO MIEMBRO: {bot_id}")
            else:
                print(f"→ OTRO USUARIO DETECTADO: {member.id}")
        
        # Caso 1: El BOT fue añadido al grupo
        if bot_added:
            print(f"🤖 BOT AÑADIDO AL GRUPO {chat_id}")
            
            # Mensaje personalizado cuando el bot es añadida
            bot.send_message(
                chat_id,
                "¡Hola a todos!\n\n"
                "Soy el asistente para gestión de grupos de clase y tutorías. Es un placer "
                "estar aquí y ayudar a organizar este espacio educativo.\n\n"
                "Para poder configurar correctamente el grupo necesito ser administrador. "
                "Por favor, sigue estos pasos:\n\n"
                "1. Entra en la información del grupo\n"
                "2. Selecciona 'Administradores'\n"
                "3. Añádeme como administrador\n\n"
                "Una vez me hayas hecho administrador, podré configurar este grupo "
                "para tu clase o tutorías. ¡Gracias por tu confianza!"
            )
            
            print(f"✅ Mensaje de bienvenida enviado al grupo {chat_id}")
            
            # Registrar el grupo en la base de datos provisionalmente
            try:
                nombre_grupo = message.chat.title
                
                conn = get_db_connection()
                cursor = conn.cursor()
                
                # Verificar si el grupo ya existe
                cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
                grupo = cursor.fetchone()
                
                if not grupo:
                    # Crear registro provisional
                    cursor.execute(
                        """INSERT INTO Grupos_tutoria 
                        (Id_usuario, Nombre_sala, Tipo_sala, Chat_id, Proposito_sala) 
                        VALUES (?, ?, ?, ?, ?)""",
                        (message.from_user.id, nombre_grupo, 'pública', str(chat_id), 'pendiente')
                    )
                    conn.commit()
                    print(f"✅ Grupo {nombre_grupo} (ID: {chat_id}) registrado como 'pendiente'")
                else:
                    print(f"⚠️ El grupo {nombre_grupo} ya estaba registrado")
                
                conn.close()
            except Exception as e:
                print(f"❌ Error al registrar grupo: {e}")
                import traceback
                traceback.print_exc()
        
        # Caso 2: Otros usuarios fueron añadidos
        else:
            for new_member in message.new_chat_members:
                print(f"👤 Procesando nuevo usuario: {new_member.first_name} (ID: {new_member.id})")
                # Resto del código para manejar nuevos miembros
    
    except Exception as e:
        print(f"❌❌❌ ERROR EN HANDLER NEW_CHAT_MEMBERS: {e}")
        import traceback
        traceback.print_exc()

@bot.middleware_handler(update_types=['message'])
def debug_all_messages(bot_instance, message):
    print("\n==================================================")
    print(f"🔍 MIDDLEWARE: Mensaje recibido - Tipo: {type(message).__name__}")
    if hasattr(message, 'content_type'):
        print(f"🔍 Tipo de contenido: {message.content_type}")
    
    print(f"🔍 De: {message.from_user.first_name} (ID: {message.from_user.id})")
    print(f"🔍 Chat: {message.chat.id} ({message.chat.type})")
    
    if hasattr(message, 'new_chat_members') and message.new_chat_members:
        print(f"🔍 ¡NUEVOS MIEMBROS DETECTADOS!: {[(m.first_name, m.id) for m in message.new_chat_members]}")
    
    print("==================================================\n")
    return message

# Añadir estos handlers ANTES del bloque if __name__ == "__main__":



# Luego viene el if __name__ == "__main__":
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
    
    # PRIMERO: Registra los handlers propios de bot_grupo_main.py
    # NO HAY CAMBIOS A ESTA PARTE - Tus handlers definidos directamente aquí serán registrados primero
    
    # SEGUNDO: Registra los handlers externos DESPUÉS, para que no sobreescriban 
    # Registrar handlers específicos
    from db.queries import DB_PATH
    gestion_grupos = GestionGrupos(str(DB_PATH))
    
    # IMPORTANTE: COMENTA ESTA LÍNEA
    # gestion_grupos.registrar_handlers(bot)
    
    # REGÍSTRALOS MANUALMENTE en su lugar:
    @bot.message_handler(commands=['finalizar'])
    def finalizar_handler(message):
        print("🔄 Comando finalizar recibido")
        gestion_grupos.finalizar_sesion(message)
    
    @bot.message_handler(commands=['eliminar_sala'])
    def eliminar_sala_handler(message):
        print("🔄 Comando eliminar_sala recibido")
        gestion_grupos.eliminar_sala(message)
    
    @bot.message_handler(commands=['cambiar_asignatura'])
    def cambiar_asignatura_handler(message):
        print("🔄 Comando cambiar_asignatura recibido")
        gestion_grupos.cambiar_asignatura_sala(message)
        
    # Registrar callbacks manualmente
    @bot.callback_query_handler(func=lambda call: call.data.startswith("eliminar_"))
    def ejecutar_eliminar_sala_handler(call):
        gestion_grupos.ejecutar_eliminar_sala(call)
    
    @bot.callback_query_handler(func=lambda call: call.data == "cancelar")
    def cancelar_handler(call):
        bot.answer_callback_query(call.id, "Operación cancelada")
    
    # Resto de callbacks...
    
    # Registrar otros handlers
    register_valoraciones_handlers(bot)
    
    # Iniciar hilo de limpieza
    threading.Thread(target=limpieza_periodica, daemon=True).start()
    
    
    print(f"🤖 Bot de Grupos iniciado con token: {BOT_TOKEN[:5]}...{BOT_TOKEN[-5:]}")
    logger.info("Bot de Grupos iniciado")
    
    # Reemplazar el bucle de polling al final
    # Polling con manejo de errores
    while True:
        try:
            print("\n==================================================")
            print("🟢🟢🟢 INICIANDO POLLING DEL BOT 🟢🟢🟢")
            print("==================================================\n")
            
            # Imprimir todos los handlers registrados para depurar
            all_handlers = bot.message_handlers
            print(f"Handlers registrados: {len(all_handlers)} handlers")
            for i, handler in enumerate(all_handlers):
                print(f"Handler #{i+1}: {handler}")
                
            # Verificar específicamente handlers de new_chat_members
            new_members_handlers = [h for h in all_handlers if 'filters' in h and 
                                   'content_types' in h['filters'] and
                                   'new_chat_members' in h['filters']['content_types']]
            print(f"\n🔍 Handlers específicos para new_chat_members: {len(new_members_handlers)}")
            for i, h in enumerate(new_members_handlers):
                print(f"  - Handler #{i+1}: {h}")
            
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except Exception as e:
            print(f"❌❌❌ ERROR EN POLLING: {e} ❌❌❌")
            logger.error(f"Error en polling: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)

@bot.message_handler(content_types=['migrate_to_chat_id', 'migrate_from_chat_id'])
def handle_upgrade_to_supergroup(message):
    """Maneja cuando un grupo se actualiza a supergrupo"""
    try:
        print("\n==================================================")
        print("⚠️⚠️⚠️ HANDLER ACTIVADO: MIGRACIÓN DE GRUPO ⚠️⚠️⚠️")
        print(f"⚠️ Chat ID: {message.chat.id}")
        print(f"⚠️ Contenido: {message.__dict__}")
        
        old_id = None
        new_id = None
        
        if hasattr(message, 'migrate_from_chat_id') and message.migrate_from_chat_id:
            old_id = message.migrate_from_chat_id
            new_id = message.chat.id
            print(f"⚠️ Migración DETECTADA - Viejo ID: {old_id}, Nuevo ID: {new_id}")
            
        elif hasattr(message, 'migrate_to_chat_id') and message.migrate_to_chat_id:
            old_id = message.chat.id
            new_id = message.migrate_to_chat_id
            print(f"⚠️ Migración DETECTADA - Viejo ID: {old_id}, Nuevo ID: {new_id}")
            
        if old_id and new_id:
            # Actualizar registro en la base de datos
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Comprobar si existe el grupo con el ID antiguo
            cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(old_id),))
            grupo = cursor.fetchone()
            
            if grupo:
                print(f"✓ Grupo encontrado con ID antiguo: {old_id}")
                
                # Comprobar que no exista otro grupo con el nuevo ID
                cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(new_id),))
                grupo_nuevo = cursor.fetchone()
                
                if not grupo_nuevo:
                    # Actualizar el ID del chat
                    cursor.execute(
                        "UPDATE Grupos_tutoria SET Chat_id = ? WHERE Chat_id = ?", 
                        (str(new_id), str(old_id))
                    )
                    conn.commit()
                    print(f"✅ ID de chat actualizado: {old_id} → {new_id}")
                    
                    # Enviar mensaje informativo en el nuevo supergrupo
                    try:
                        bot.send_message(
                            new_id,
                            "⚠️ Este grupo ha sido actualizado a supergrupo por Telegram.\n\n"
                            "He actualizado automáticamente la configuración. Todo debería seguir funcionando correctamente."
                        )
                    except Exception as e:
                        print(f"Error al enviar mensaje al nuevo supergrupo: {e}")
                else:
                    print(f"⚠️ Ya existe un grupo con el nuevo ID {new_id}")
            else:
                print(f"⚠️ No se encontró grupo con ID {old_id}")
                
            conn.close()
        else:
            print("⚠️ No se detectaron IDs de migración")
            
    except Exception as e:
        print(f"❌❌❌ ERROR EN HANDLER MIGRACIÓN: {e}")
        import traceback
        traceback.print_exc()

