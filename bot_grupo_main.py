"""
Archivo principal del bot de grupos de tutorías.
Inicialización, configuración y handlers básicos.
"""
import telebot
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
    configurar_logger
)
# Importar estados desde el manejador central
from utils.state_manager import user_states, user_data, estados_timestamp

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

# Importar funciones de la base de datos compartidas
from db.queries import get_db_connection, get_user_by_telegram_id

# Configurar comandos personalizados
def configurar_comandos_por_rol():
    """Configura diferentes comandos visibles para profesores y estudiantes."""
    # Comandos para profesores
    comandos_profesor = [
        telebot.types.BotCommand('/start', 'Iniciar el bot'),
        telebot.types.BotCommand('/ayuda', 'Mostrar ayuda del bot'),
        telebot.types.BotCommand('/estudiantes', 'Ver lista de estudiantes'),
        telebot.types.BotCommand('/estadisticas', 'Ver estadísticas de tutorías'),
        telebot.types.BotCommand('/test_simple', 'Probar funcionamiento del bot'),
    ]
    
    # Comandos para estudiantes
    comandos_estudiante = [
        telebot.types.BotCommand('/start', 'Iniciar el bot'),
        telebot.types.BotCommand('/ayuda', 'Mostrar ayuda del bot'),
    ]
    
    # Establecer comandos generales para todos los usuarios
    bot.set_my_commands([
        telebot.types.BotCommand('/start', 'Iniciar el bot'),
        telebot.types.BotCommand('/ayuda', 'Mostrar ayuda')
    ])
    
    return comandos_profesor, comandos_estudiante


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
    
    # Actualizar interfaz según rol
    if user['Tipo'] == 'profesor':
        bot.send_message(
            chat_id,
            "¡Bienvenido, Profesor! Usa los botones para gestionar tu tutoría.",
            reply_markup=menu_profesor()
        )
    else:
        # Es estudiante
        bot.send_message(
            chat_id,
            "¡Hola! Chatea con tu tutor. Cuando finalices, usa el botón 'Terminar Tutoria'.",
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
        "✅ Pulsa el botón 'Terminar Tutoria' para finalizar tu consulta o expulsar a un estudiante (solo para profesores).\n"
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

# Registrar handlers específicos
register_grupo_handlers(bot)
register_valoraciones_handlers(bot)

if __name__ == "__main__":
    # Verificar que existe la base de datos
    if not os.path.exists(os.path.join(base_dir, "tutoria_ugr.db")):
        logger.error("Base de datos no encontrada")
        print("Error: Base de datos no encontrada. Primero ejecuta python -m db.models")
        sys.exit(1)
    
    # Configurar comandos por rol
    configurar_comandos_por_rol()
    
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