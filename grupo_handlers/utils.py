"""
Utilidades y funciones auxiliares para el bot de grupos.
Estados, menús y funciones comunes.
"""
import time
import logging
import sys
import os
from pathlib import Path

root_path = str(Path(__file__).parent.parent.absolute())
if root_path not in sys.path:
    sys.path.insert(0, root_path)
# Ahora importamos con una ruta absoluta que evita la ambigüedad
import importlib.util

# Ruta absoluta al archivo state_manager.py
state_manager_path = Path(__file__).parent.parent / "utils" / "state_manager.py"

# Cargar el módulo directamente sin depender de imports relativos
spec = importlib.util.spec_from_file_location("state_manager", state_manager_path)
state_manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state_manager)

# Obtener las variables
user_states = state_manager.user_states
user_data = state_manager.user_data
estados_timestamp = state_manager.estados_timestamp

from telebot import types
# Importar funciones de la base de datos compartidas
from db.queries import (
    get_user_by_telegram_id, 
    get_db_connection,
    create_user,
    crear_grupo_tutoria,
    añadir_estudiante_grupo
)

# Variables globales para manejo de estados
# user_states = {}
# user_data = {}
# estados_timestamp = {}
MAX_ESTADO_DURACION = 3600  # 1 hora en segundos

def configurar_logger():
    """Configura y devuelve el logger"""
    logger = logging.getLogger("bot_grupo")
    
    if not logger.handlers:
        handler = logging.FileHandler("bot_grupos.log")
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
        logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.DEBUG)
    
    return logger

# Obtener logger
logger = configurar_logger()

def menu_profesor():
    """Crea un menú con botones específicos para profesores."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("👨‍🎓 Ver estudiantes"),
        types.KeyboardButton("📊 Ver Estadísticas")
    )
    markup.add(
        types.KeyboardButton("📝 Ver Valoraciones")
    )
    markup.add(types.KeyboardButton("Terminar Tutoria"))
    return markup

def menu_estudiante():
    """Crea un menú con botones específicos para estudiantes."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("Terminar Tutoria")
    )
    return markup

def es_profesor(user_id):
    """Verifica si el usuario es un profesor"""
    user = get_user_by_telegram_id(user_id)
    if user and user['Tipo'] == 'profesor':
        return True
    return False

def limpiar_estados_obsoletos():
    """Limpia estados de usuario obsoletos para evitar fugas de memoria."""
    tiempo_actual = time.time()
    usuarios_para_limpiar = []
    
    # Identificar estados obsoletos
    for user_id, timestamp in estados_timestamp.items():
        if tiempo_actual - timestamp > MAX_ESTADO_DURACION:
            usuarios_para_limpiar.append(user_id)
    
    # Eliminar estados obsoletos
    for user_id in usuarios_para_limpiar:
        if user_id in user_states:
            logger.info(f"Limpiando estado obsoleto para usuario {user_id}")
            del user_states[user_id]
        if user_id in estados_timestamp:
            del estados_timestamp[user_id]
    
    if usuarios_para_limpiar:
        logger.info(f"Limpiados {len(usuarios_para_limpiar)} estados obsoletos")

def inicializar_tablas_grupo():
    """Inicializa las tablas necesarias para grupos"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Crear tabla Usuario_Grupo
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Usuario_Grupo (...)
    """)
    
    # Verificar columna chat_id en Grupos_tutoria
    cursor.execute("PRAGMA table_info(Grupos_tutoria)")
    columnas = [info[1] for info in cursor.fetchall()]
    if "chat_id" not in columnas:
        cursor.execute("ALTER TABLE Grupos_tutoria ADD COLUMN chat_id INTEGER")
        logger.info("Añadida columna 'chat_id' a Grupos_tutoria")
    
    conn.commit()
    conn.close()

def guardar_usuario_en_grupo(user_id, username, chat_id):
    """Guarda un usuario en un grupo específico"""
    try:
        # Verificar si el usuario ya existe
        user = get_user_by_telegram_id(user_id)
        
        if not user:
            # Si no existe, crearlo como estudiante usando la función existente
            user_id_db = create_user(
                nombre=username, 
                tipo='estudiante',
                email=None,
                telegram_id=user_id
            )
            logger.info(f"Nuevo usuario {username} (ID: {user_id}) creado")
        else:
            user_id_db = user['Id_usuario']
        
        # Asegurar estructura de tabla (esto debería moverse a un script de inicialización)
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Usuario_Grupo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Id_usuario INTEGER,
                id_sala INTEGER,
                fecha_union TEXT,
                FOREIGN KEY (Id_usuario) REFERENCES Usuarios(Id_usuario),
                FOREIGN KEY (id_sala) REFERENCES Grupos_tutoria(id_sala),
                UNIQUE(Id_usuario, id_sala)
            )
        """)
        
        # Verifica/modifica el esquema (debería estar en un script de inicialización)
        cursor.execute("PRAGMA table_info(Grupos_tutoria)")
        columnas = [info[1] for info in cursor.fetchall()]
        if "chat_id" not in columnas:
            cursor.execute("ALTER TABLE Grupos_tutoria ADD COLUMN chat_id INTEGER")
            logger.info("Añadida columna 'chat_id' a Grupos_tutoria")
        
        # Buscar grupo por chat_id 
        cursor.execute("SELECT id_sala FROM Grupos_tutoria WHERE chat_id = ?", (chat_id,))
        grupo = cursor.fetchone()
        conn.close()
        
        if not grupo:
            # Usar función existente para crear grupo
            grupo_id = crear_grupo_tutoria(
                profesor_id=1,  # Usar un ID válido
                nombre_sala=f"Grupo {chat_id}",
                tipo_sala="publica",
                chat_id=chat_id,
                enlace=f"https://t.me/c/{chat_id}"
            )
            logger.info(f"Nuevo grupo creado para chat_id {chat_id}")
        else:
            grupo_id = grupo[0]
        
        # Usar función existente para añadir al estudiante
        añadir_estudiante_grupo(grupo_id, user_id_db)
        
        logger.info(f"Usuario {username} (ID: {user_id}) asociado al grupo {chat_id}")
        return True
    except Exception as e:
        logger.error(f"Error guardando usuario en grupo: {e}")
        return False