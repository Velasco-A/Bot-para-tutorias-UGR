import telebot
import time
import threading
from telebot import types
import os
import sys
from config import TOKEN, DB_PATH,EXCEL_PATH

# Importar funciones para manejar estados
from utils.state_manager import get_state, set_state, clear_state, user_states, user_data

# Importar funciones para manejar el Excel
from utils.excel_manager import cargar_excel, importar_datos_desde_excel
from db.queries import get_db_connection

# Inicializar el bot de Telegram
bot = telebot.TeleBot(TOKEN)

def setup_commands():
    """Configura los comandos que aparecen en el menú del bot"""
    try:
        bot.set_my_commands([
            telebot.types.BotCommand("/start", "Inicia el bot y el registro"),
            telebot.types.BotCommand("/help", "Muestra la ayuda del bot"),
            telebot.types.BotCommand("/tutoria", "Ver profesores disponibles para tutoría"),
            telebot.types.BotCommand("/crear_grupo_tutoria", "Crea un grupo de tutoría"),
            telebot.types.BotCommand("/configurar_horario", "Configura tu horario de tutorías"),
            telebot.types.BotCommand("/ver_misdatos", "Ver tus datos registrados")
        ])
        print("✅ Comandos del bot configurados correctamente")
        return True
    except Exception as e:
        print(f"❌ Error al configurar los comandos del bot: {e}")
        return False

# Importar funciones básicas de consulta a la BD
from db.queries import get_user_by_telegram_id

@bot.message_handler(commands=['help'])
def handle_help(message):
    """Muestra la ayuda del bot"""
    chat_id = message.chat.id
    user = get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        bot.send_message(
            chat_id,
            "❌ No estás registrado. Usa /start para registrarte."
        )
        return
    
    help_text = (
        "🤖 *Comandos disponibles:*\n\n"
        "/start - Inicia el bot y el proceso de registro\n"
        "/help - Muestra este mensaje de ayuda\n"
        "/tutoria - Ver profesores disponibles para tutoría\n"
        "/ver\\_misdatos - Ver tus datos registrados\n"
    )
    
    if user['Tipo'] == 'profesor':
        help_text += (
            "/configurar\\_horario - Configura tu horario de tutorías\n"
            "/crear\\_grupo\\_tutoria - Crea un grupo de tutoría\n"
        )
    
    # Escapar los guiones bajos para evitar problemas de formato
    help_text = help_text.replace("_", "\\_")
    
    try:
        bot.send_message(chat_id, help_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Error al enviar mensaje de ayuda: {e}")
        # Si falla, envía sin formato
        bot.send_message(chat_id, help_text.replace('*', ''), parse_mode=None)

@bot.message_handler(commands=['ver_misdatos'])
def handle_ver_misdatos(message):
    chat_id = message.chat.id
    user = get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        bot.send_message(chat_id, "❌ No estás registrado. Usa /start para registrarte.")
        return
    
    # Convertir el objeto sqlite3.Row a diccionario
    user_dict = dict(user)
    
    # Obtener matrículas del usuario
    from db.queries import get_matriculas_usuario
    matriculas = get_matriculas_usuario(user['Id_usuario'])
    
    user_info = (
        f"👤 *Datos de usuario:*\n\n"
        f"*Nombre:* {user['Nombre']}\n"
        f"*Correo:* {user['Email_UGR'] or 'No registrado'}\n"
        f"*Tipo:* {user['Tipo'].capitalize()}\n"
    )
    
    # Añadir la carrera desde la tabla Usuarios
    if 'Carrera' in user_dict and user_dict['Carrera']:
        user_info += f"*Carrera:* {user_dict['Carrera']}\n\n"
    else:
        user_info += "*Carrera:* No registrada\n\n"
    
    # Añadir información de matrículas
    if matriculas and len(matriculas) > 0:
        user_info += "*Asignaturas matriculadas:*\n"
        
        # Agrupar asignaturas por carrera
        for m in matriculas:
            # Convertir cada matrícula a diccionario si es necesario
            m_dict = dict(m) if hasattr(m, 'keys') else m
            asignatura = m_dict.get('Asignatura', 'Desconocida')
            user_info += f"- {asignatura}\n"
    else:
        user_info += "No tienes asignaturas matriculadas.\n"
    
    # Añadir horario si es profesor
    if user['Tipo'] == 'profesor' and 'Horario' in user_dict and user_dict['Horario']:
        user_info += f"\n*Horario de tutorías:*\n{user_dict['Horario']}"
    
    bot.send_message(chat_id, user_info, parse_mode="Markdown")

# Importar y configurar los handlers desde los módulos
from handlers.registro import register_handlers as register_registro_handlers
from handlers.tutorias import register_handlers as register_tutorias_handlers
from handlers.horarios import register_handlers as register_horarios_handlers
from utils.excel_manager import verificar_excel_disponible

# Verificar si es la primera ejecución
MARKER_FILE = os.path.join(os.path.dirname(DB_PATH), ".initialized")
primera_ejecucion = not os.path.exists(MARKER_FILE)

# Verificar que el Excel existe pero no cargar datos
print("📊 Cargando datos académicos...")
if verificar_excel_disponible():
    print("✅ Excel encontrado")
    # Primera vez - importar todo
    if primera_ejecucion:  # Usa alguna forma de detectar primer inicio
        importar_datos_desde_excel(solo_nuevos=False)
        # Crear archivo marcador para futuras ejecuciones
        with open(MARKER_FILE, 'w') as f:
            f.write("Initialized")
    else:
        # Ejecuciones posteriores - solo nuevos datos
        importar_datos_desde_excel(solo_nuevos=True)
else:
    print("⚠️ Excel no encontrado")

# Registrar todos los handlers
register_registro_handlers(bot)
register_tutorias_handlers(bot)
register_horarios_handlers(bot)

# Inicializar y ejecutar el bot
if __name__ == "__main__":
    # Verificar que existe la base de datos
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: Base de datos no encontrada en {DB_PATH}")
        print("Primero debes crear la base de datos con db/models.py")
        sys.exit(1)
    
    # Configurar los comandos del bot
    threading.Thread(target=setup_commands).start()
    
    print(f"🤖 Bot iniciado - Base de datos: {DB_PATH}")
    print("Presiona Ctrl+C para detener.")
    
    # Iniciar el polling con manejo de errores
    while True:
        try:
            bot.polling(none_stop=True, interval=0)
        except Exception as e:
            print(f"❌ Error en el polling: {e}")
            time.sleep(10)