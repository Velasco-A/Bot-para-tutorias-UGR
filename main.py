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
# Reemplaza todos los handlers universales por este ÚNICO handler al final
# Inicializar el bot de Telegram
bot = telebot.TeleBot(TOKEN) 

def escape_markdown(text):
    """Escapa caracteres especiales de Markdown"""
    if not text:
        return ""
    
    chars = ['_', '*', '`', '[', ']', '(', ')', '#', '+', '-', '.', '!']
    for char in chars:
        text = text.replace(char, '\\' + char)
    
    return text




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
    print(f"\n\n### INICIO VER_MISDATOS - Usuario: {message.from_user.id} ###")
    
    user = get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        print("⚠️ Usuario no encontrado en BD")
        bot.send_message(chat_id, "❌ No estás registrado. Usa /start para registrarte.")
        return
    
    print(f"✅ Usuario encontrado: {user['Nombre']} ({user['Tipo']})")
    
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
    if user['Tipo'] == 'profesor':
        if 'Horario' in user_dict and user_dict['Horario']:
            user_info += f"\n*Horario de tutorías:*\n{user_dict['Horario']}\n\n"
        
        # NUEVA SECCIÓN: Mostrar salas creadas por el profesor
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Consultar todas las salas creadas por este profesor
        cursor.execute("""
            SELECT g.Nombre_sala, g.Proposito_sala, g.Tipo_sala, g.Fecha_creacion, 
                   g.id_sala, g.Chat_id, a.Nombre as NombreAsignatura
            FROM Grupos_tutoria g
            LEFT JOIN Asignaturas a ON g.Id_asignatura = a.Id_asignatura
            WHERE g.Id_usuario = ?
            ORDER BY g.Fecha_creacion DESC
        """, (user['Id_usuario'],))
        
        salas = cursor.fetchall()
        conn.close()
        
        if salas and len(salas) > 0:
            user_info += "\n*🔵 Salas de tutoría creadas:*\n"
            
            # Diccionario para traducir los propósitos a texto más amigable
            propositos = {
                'individual': 'Tutorías individuales',
                'grupal': 'Tutorías grupales',
                'avisos': 'Canal de avisos'
            }
            
            for sala in salas:
                # Obtener propósito en formato legible
                proposito = propositos.get(sala['Proposito_sala'], sala['Proposito_sala'] or 'General')
                
                # Obtener asignatura o indicar que es general
                asignatura = sala['NombreAsignatura'] or 'General'
                
                # Formato de fecha más amigable
                fecha = sala['Fecha_creacion'].split(' ')[0] if sala['Fecha_creacion'] else 'Desconocida'
                
                user_info += f"• *{sala['Nombre_sala']}*\n"
                user_info += f"  📋 Propósito: {proposito}\n"
                user_info += f"  📚 Asignatura: {asignatura}\n"
                user_info += f"  📅 Creada: {fecha}\n\n"
        else:
            user_info += "\n*🔵 No has creado salas de tutoría todavía.*\n"
            user_info += "Usa /crear_grupo_tutoria para crear una nueva sala.\n"
    
    # Intentar enviar el mensaje con formato Markdown
    try:
        bot.send_message(chat_id, user_info, parse_mode="Markdown")
        
        # Si es profesor y tiene salas, mostrar botones para editar
        if user['Tipo'] == 'profesor' and salas and len(salas) > 0:
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            # Añadir SOLO botones para editar cada sala (quitar botones de eliminar)
            for sala in salas:
                sala_id = sala['id_sala']
                
                markup.add(types.InlineKeyboardButton(
                    f"✏️ Sala: {sala['Nombre_sala']}",
                    callback_data=f"edit_sala_{sala_id}"
                ))
            
            bot.send_message(
                chat_id,
                "Selecciona una sala para gestionar:",
                reply_markup=markup
            )
    except Exception as e:
        # Si falla por problemas de formato, enviar sin formato
        print(f"Error al enviar datos de usuario: {e}")
        bot.send_message(chat_id, user_info.replace('*', ''), parse_mode=None)

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


# Handlers para cambio de propósito de salas de tutoría
@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_sala_"))
def handle_edit_sala(call):
    """Muestra opciones para editar una sala"""
    chat_id = call.message.chat.id
    print(f"\n\n### INICIO EDIT_SALA - Callback: {call.data} ###")
    
    try:
        sala_id = int(call.data.split("_")[2])
        print(f"🔍 Sala ID a editar: {sala_id}")
        
        # Verificar que el usuario es el propietario de la sala
        user = get_user_by_telegram_id(call.from_user.id)
        print(f"👤 Usuario: {user['Nombre'] if user else 'No encontrado'}")
        
        if not user or user['Tipo'] != 'profesor':
            print("⚠️ Usuario no es profesor o no existe")
            bot.answer_callback_query(call.id, "⚠️ Solo los profesores propietarios pueden editar salas")
            return
        
        # Obtener datos actuales de la sala
        conn = get_db_connection()
        cursor = conn.cursor()
        print(f"🔍 Consultando detalles de sala ID {sala_id}")
        cursor.execute(
            """
            SELECT g.*, a.Nombre as NombreAsignatura
            FROM Grupos_tutoria g
            LEFT JOIN Asignaturas a ON g.Id_asignatura = a.Id_asignatura
            WHERE g.id_sala = ? AND g.Id_usuario = ?  
            """, 
            (sala_id, user['Id_usuario'])
        )
        sala = cursor.fetchone()
        conn.close()
        
        if not sala:
            print(f"❌ Sala no encontrada o no pertenece al usuario")
            bot.answer_callback_query(call.id, "❌ No se encontró la sala o no tienes permisos")
            return
        
        print(f"✅ Sala encontrada: {sala['Nombre_sala']} (Chat ID: {sala['Chat_id']})")
        
        # Mostrar opciones de edición
        print("🔘 Generando botones de opciones...")
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Diccionario de propósitos con emojis
        propositos = {
            'individual': '👨‍🏫 Tutorías individuales',
            'grupal': '👥 Tutorías grupales',
            'avisos': '📢 Canal de avisos'
        }
        
        # Crear botones para cada propósito posible
        for key, value in propositos.items():
            # Marcar el propósito actual
            if sala['Proposito_sala'] == key:
                text = f"✅ {value} (actual)"
            else:
                text = value
            
            markup.add(types.InlineKeyboardButton(
                text,
                callback_data=f"cambiar_proposito_{sala_id}_{key}"
            ))
            print(f"  ✓ Botón propósito: {key} con callback: cambiar_proposito_{sala_id}_{key}")
        
        # Añadir opción para eliminar la sala
        markup.add(types.InlineKeyboardButton(
            "🗑️ Eliminar sala",
            callback_data=f"eliminarsala_{sala_id}"
        ))
        print(f"  ✓ Botón eliminar con callback: eliminarsala_{sala_id}")
        
        # Botón para cancelar
        markup.add(types.InlineKeyboardButton(
            "❌ Cancelar",
            callback_data=f"cancelar_edicion_{sala_id}"
        ))
        
        print(f"📤 Enviando mensaje de edición con {len(markup.keyboard)} botones")
        bot.edit_message_text(
            f"🔄 *Editar propósito de sala*\n\n"
            f"*Sala:* {escape_markdown(sala['Nombre_sala'])}\n"
            f"*Propósito actual:* {escape_markdown(propositos.get(sala['Proposito_sala'], 'General'))}\n"
            f"*Asignatura:* {escape_markdown(sala['NombreAsignatura'] or 'General')}\n\n"
            f"Selecciona el nuevo propósito para esta sala:",
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        print("✅ Mensaje de opciones enviado")
    
    except Exception as e:
        print(f"❌ ERROR en handle_edit_sala: {e}")
        import traceback
        print(traceback.format_exc())
    
    print(f"### FIN EDIT_SALA ###\n")
    bot.answer_callback_query(call.id)
    print("✅ Respuesta de callback enviada")
    # imprimir call.id
    print(f"### FIN EDIT_SALA - Callback: {call.data} ###\n")

@bot.callback_query_handler(func=lambda call: call.data.startswith("cambiar_proposito_"))
def handle_cambiar_proposito(call):
    """Muestra opciones para gestionar miembros al cambiar el propósito de la sala"""
    chat_id = call.message.chat.id
    data = call.data.split("_")
    sala_id = int(data[2])
    nuevo_proposito = data[3]
    
    # Verificar usuario
    user = get_user_by_telegram_id(call.from_user.id)
    if not user or user['Tipo'] != 'profesor':
        bot.answer_callback_query(call.id, "⚠️ No tienes permisos para esta acción")
        return
    
    # Obtener datos de la sala
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT g.*, a.Nombre as NombreAsignatura
        FROM Grupos_tutoria g
        LEFT JOIN Asignaturas a ON g.Id_asignatura = a.Id_asignatura
        WHERE g.id_sala = ? AND g.Id_usuario = ?  
        """, 
        (sala_id, user['Id_usuario'])
    )
    sala = cursor.fetchone()
    
    # Contar miembros actuales
    cursor.execute(
        "SELECT COUNT(*) as total FROM Miembros_Grupo WHERE id_sala = ? AND Estado = 'activo'",  # cambiar chat_id por id_sala
        (sala_id,)
    )
    miembros = cursor.fetchone()
    conn.close()
    
    total_miembros = miembros['total'] if miembros else 0
    
    # Si no hay miembros, cambiar directamente
    if total_miembros == 0:
        realizar_cambio_proposito(chat_id, call.message.message_id, sala_id, nuevo_proposito, user['Id_usuario'])
        bot.answer_callback_query(call.id)
        return
    
    # Textos descriptivos según el tipo de cambio
    propositos = {
        'individual': 'Tutorías individuales (requiere aprobación)',
        'grupal': 'Tutorías grupales',
        'avisos': 'Canal de avisos (acceso público)'
    }
    
    # Escapar todos los textos dinámicos
    nombre_sala = escape_markdown(sala['Nombre_sala'])
    nombre_asignatura = escape_markdown(sala['NombreAsignatura'] or 'General')
    prop_actual = escape_markdown(propositos.get(sala['Proposito_sala'], 'General'))
    prop_nueva = escape_markdown(propositos.get(nuevo_proposito, 'General'))
    
    # Determinar qué tipo de cambio es
    cambio_tipo = f"{sala['Proposito_sala']}_{nuevo_proposito}"
    titulo_decision = ""
    
    if cambio_tipo == "avisos_individual":
        titulo_decision = (
            f"🔄 Estás cambiando de *canal de avisos* a *tutorías individuales*.\n"
            f"Esto hará que los nuevos accesos requieran tu aprobación."
        )
    elif cambio_tipo == "individual_avisos":
        titulo_decision = (
            f"🔄 Estás cambiando de *tutorías individuales* a *canal de avisos*.\n"
            f"Esto permitirá que cualquier estudiante matriculado acceda directamente."
        )
    else:
        titulo_decision = f"🔄 Estás cambiando el propósito de la sala de *{prop_actual}* a *{prop_nueva}*."
    
    # Mostrar opciones para gestionar miembros
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    markup.add(types.InlineKeyboardButton(
        f"✅ Mantener a los {total_miembros} miembros actuales",
        callback_data=f"confirmar_cambio_{sala_id}_{nuevo_proposito}_mantener"
    ))
    
    markup.add(types.InlineKeyboardButton(
        "❌ Eliminar a todos los miembros actuales",
        callback_data=f"confirmar_cambio_{sala_id}_{nuevo_proposito}_eliminar"
    ))
    
    markup.add(types.InlineKeyboardButton(
        "🔍 Ver lista de miembros antes de decidir",
        callback_data=f"ver_miembros_{sala_id}_{nuevo_proposito}"
    ))
    
    markup.add(types.InlineKeyboardButton(
        "↩️ Cancelar cambio",
        callback_data=f"cancelar_edicion_{sala_id}"
    ))
    
    # Enviar mensaje con opciones
    bot.edit_message_text(
        f"{titulo_decision}\n\n"
        f"*Sala:* {nombre_sala}\n"
        f"*Miembros actuales:* {total_miembros}\n"
        f"*Asignatura:* {nombre_asignatura}\n\n"
        f"¿Qué deseas hacer con los miembros actuales?",
        chat_id=chat_id,
        message_id=call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirmar_cambio_"))
def handle_confirmar_cambio(call):
    """Confirma el cambio de propósito con la decisión sobre los miembros"""
    chat_id = call.message.chat.id
    data = call.data.split("_")
    sala_id = int(data[2])
    nuevo_proposito = data[3]
    decision_miembros = data[4]  # "mantener" o "eliminar"
    
    # Verificar usuario
    user = get_user_by_telegram_id(call.from_user.id)
    if not user or user['Tipo'] != 'profesor':
        bot.answer_callback_query(call.id, "⚠️ No tienes permisos para esta acción")
        return
    
    # Realizar el cambio de propósito
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Actualizar el propósito de la sala
        cursor.execute(
            "UPDATE Grupos_tutoria SET Proposito_sala = ? WHERE id_sala = ? AND Id_usuario = ?",  # cambiar chat_id por id_sala
            (nuevo_proposito, sala_id, user['Id_usuario'])
        )
        
        # 2. Actualizar el tipo de sala según el propósito
        tipo_sala = 'pública' if nuevo_proposito == 'avisos' else 'privada'
        cursor.execute(
            "UPDATE Grupos_tutoria SET Tipo_sala = ? WHERE id_sala = ?",  # cambiar chat_id por id_sala
            (tipo_sala, sala_id)
        )
        
        # 3. Gestionar miembros según la decisión
        if decision_miembros == "eliminar":
            # Eliminar todos los miembros excepto el profesor creador
            cursor.execute(
                """
                DELETE FROM Miembros_Grupo 
                WHERE id_sala = ? AND Id_usuario != (
                    SELECT Id_usuario FROM Grupos_tutoria WHERE id_sala = ?
                )
                """,
                (sala_id, sala_id)
            )
        
        conn.commit()
        
        # Obtener información actualizada de la sala
        cursor.execute(
            """
            SELECT g.*, a.Nombre as NombreAsignatura
            FROM Grupos_tutoria g
            LEFT JOIN Asignaturas a ON g.Id_asignatura = a.Id_asignatura
            WHERE g.id_sala = ?
            """, 
            (sala_id,)
        )
        sala = cursor.fetchone()
        
        # Contar miembros restantes
        cursor.execute(
            "SELECT COUNT(*) as total FROM Miembros_Grupo WHERE id_sala = ? AND Estado = 'activo'",
            (sala_id,)
        )
        miembros = cursor.fetchone()
        total_miembros = miembros['total'] if miembros else 0
        
        # Textos para los propósitos
        propositos = {
            'individual': 'Tutorías individuales',
            'grupal': 'Tutorías grupales',
            'avisos': 'Canal de avisos'
        }
        
        # Escapar textos que pueden contener caracteres Markdown
        nombre_sala = escape_markdown(sala['Nombre_sala'])
        nombre_asignatura = escape_markdown(sala['NombreAsignatura'] or 'General')
        prop_nueva = escape_markdown(propositos.get(nuevo_proposito, 'General'))
        
        # Mensaje de éxito
        mensaje_exito = (
            f"✅ *¡Propósito actualizado correctamente!*\n\n"
            f"*Sala:* {nombre_sala}\n"
            f"*Nuevo propósito:* {prop_nueva}\n"
            f"*Asignatura:* {nombre_asignatura}\n"
            f"*Miembros actuales:* {total_miembros}\n\n"
        )
        
        # Agregar mensaje según la decisión tomada
        if decision_miembros == "eliminar":
            mensaje_exito += (
                "🧹 Se han eliminado todos los miembros anteriores.\n"
                "La sala está lista para su nuevo propósito."
            )
        else:
            mensaje_exito += (
                "👥 Se han mantenido todos los miembros anteriores.\n"
                "Se ha notificado a los miembros del cambio de propósito."
            )
            # Notificar a los miembros del cambio
            notificar_cambio_sala(sala_id, nuevo_proposito)
        
        # Editar mensaje con confirmación
        try:
            bot.edit_message_text(
                mensaje_exito,
                chat_id=chat_id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                pass  # Ignorar este error específico
            else:
                # Manejar otros errores
                print(f"Error al editar mensaje de confirmación: {e}")
                bot.send_message(chat_id, mensaje_exito, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error al actualizar sala: {e}")
        bot.answer_callback_query(call.id, "❌ Error al actualizar la sala")
    finally:
        conn.close()
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ver_miembros_"))
def handle_ver_miembros(call):
    """Muestra la lista de miembros de la sala antes de decidir"""
    chat_id = call.message.chat.id
    data = call.data.split("_")
    sala_id = int(data[2])
    nuevo_proposito = data[3]
    
    # Verificar usuario
    user = get_user_by_telegram_id(call.from_user.id)
    if not user or user['Tipo'] != 'profesor':
        bot.answer_callback_query(call.id, "⚠️ No tienes permisos para esta acción")
        return
    
    # Obtener lista de miembros
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        """
        SELECT u.Nombre, u.Apellidos, u.Email_UGR, mg.Fecha_union, mg.Estado
        FROM Miembros_Grupo mg
        JOIN Usuarios u ON mg.Id_usuario = u.Id_usuario
        WHERE mg.id_sala = ? AND mg.Estado = 'activo'
        ORDER BY mg.Fecha_union DESC
        """,
        (sala_id,)
    )
    
    miembros = cursor.fetchall()
    
    # Obtener información de la sala
    cursor.execute(
        "SELECT Nombre_sala FROM Grupos_tutoria WHERE id_sala = ?",
        (sala_id,)
    )
    sala = cursor.fetchone()
    conn.close()
    
    if not miembros:
        # No hay miembros, cambiar directamente
        bot.answer_callback_query(call.id, "No hay miembros en esta sala")
        realizar_cambio_proposito(chat_id, call.message.message_id, sala_id, nuevo_proposito, user['Id_usuario'])
        return
    
    # Crear mensaje con lista de miembros
    mensaje = f"👥 *Miembros de la sala \"{sala['Nombre_sala']}\":*\n\n"
    
    for i, m in enumerate(miembros, 1):
        nombre_completo = f"{m['Nombre']} {m['Apellidos'] or ''}"
        fecha = m['Fecha_union'].split(' ')[0] if m['Fecha_union'] else 'Desconocida'
        mensaje += f"{i}. *{nombre_completo}*\n   📧 {m['Email_UGR']}\n   📅 Unido: {fecha}\n\n"
    
    # Botones para continuar
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    markup.add(types.InlineKeyboardButton(
        f"✅ Mantener a los {len(miembros)} miembros",
        callback_data=f"confirmar_cambio_{sala_id}_{nuevo_proposito}_mantener"
    ))
    
    markup.add(types.InlineKeyboardButton(
        "❌ Eliminar a todos los miembros",
        callback_data=f"confirmar_cambio_{sala_id}_{nuevo_proposito}_eliminar"
    ))
    
    markup.add(types.InlineKeyboardButton(
        "↩️ Cancelar cambio",
        callback_data=f"cancelar_edicion_{sala_id}"
    ))
    
    # Enviar mensaje con lista y opciones
    bot.edit_message_text(
        mensaje,
        chat_id=chat_id,
        message_id=call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )
    
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cancelar_edicion_"))
def handle_cancelar_edicion(call):
    """Cancela la edición de la sala"""
    bot.edit_message_text(
        "❌ Edición cancelada. No se realizaron cambios.",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )
    bot.answer_callback_query(call.id)

def notificar_cambio_sala(sala_id, nuevo_proposito):
    """Notifica a los miembros de la sala sobre el cambio de propósito"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Obtener datos de la sala
    cursor.execute(
        """
        SELECT g.*, u.Nombre as NombreProfesor, a.Nombre as NombreAsignatura
        FROM Grupos_tutoria g
        JOIN Usuarios u ON g.Id_usuario = u.Id_usuario
        LEFT JOIN Asignaturas a ON g.Id_asignatura = a.Id_asignatura
        WHERE g.id_sala = ?  
        """, 
        (sala_id,)
    )
    sala = cursor.fetchone()
    
    if not sala:
        conn.close()
        return
    
    # Obtener miembros de la sala
    cursor.execute(
        """
        SELECT u.*
        FROM Miembros_Grupo mg
        JOIN Usuarios u ON mg.Id_usuario = u.Id_usuario
        WHERE mg.id_sala = ? AND u.Tipo = 'estudiante' AND mg.Estado = 'activo'  
        """, 
        (sala_id,)
    )
    miembros = cursor.fetchall()
    conn.close()
    
    # Textos para los propósitos
    propositos = {
        'individual': 'Tutorías individuales',
        'grupal': 'Tutorías grupales',
        'avisos': 'Canal de avisos'
    }
    
    # Textos explicativos según el nuevo propósito
    explicaciones = {
        'individual': (
            "Ahora la sala requiere aprobación del profesor para cada solicitud "
            "y solo está disponible durante su horario de tutorías."
        ),
        'grupal': (
            "Ahora la sala está diseñada para sesiones grupales donde "
            "varios estudiantes pueden participar simultáneamente."
        ),
        'avisos': (
            "Ahora la sala funciona como canal informativo donde "
            "el profesor comparte anuncios importantes para todos los estudiantes."
        )
    }
    
    # Notificar a cada miembro
    for miembro in miembros:
        if miembro['TelegramID']:
            try:
                bot.send_message(
                    miembro['TelegramID'],
                    f"ℹ️ *Cambio en sala de tutoría*\n\n"
                    f"El profesor *{sala['NombreProfesor']}* ha modificado el propósito "
                    f"de la sala *{sala['Nombre_sala']}*.\n\n"
                    f"*Nuevo propósito:* {propositos.get(nuevo_proposito, 'General')}\n"
                    f"*Asignatura:* {sala['NombreAsignatura'] or 'General'}\n\n"
                    f"{explicaciones.get(nuevo_proposito, '')}\n\n"
                    f"Tu acceso a la sala se mantiene, pero la forma de interactuar "
                    f"podría cambiar según el nuevo propósito.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Error al notificar a usuario {miembro['Id_usuario']}: {e}")

def realizar_cambio_proposito(chat_id, message_id, sala_id, nuevo_proposito, user_id):
    """Realiza el cambio de propósito cuando no hay miembros que gestionar"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Actualizar propósito
        cursor.execute(
            "UPDATE Grupos_tutoria SET Proposito_sala = ? WHERE id_sala = ? AND Id_usuario = ?",  # cambiar chat_id por id_sala
            (nuevo_proposito, sala_id, user_id)
        )
        
        # Actualizar tipo
        tipo_sala = 'pública' if nuevo_proposito == 'avisos' else 'privada'
        cursor.execute(
            "UPDATE Grupos_tutoria SET Tipo_sala = ? WHERE id_sala = ?",  # cambiar chat_id por id_sala
            (tipo_sala, sala_id)
        )
        
        conn.commit()
        
        # Obtener info actualizada
        cursor.execute(
            """
            SELECT g.*, a.Nombre as NombreAsignatura
            FROM Grupos_tutoria g
            LEFT JOIN Asignaturas a ON g.Id_asignatura = a.Id_asignatura
            WHERE g.id_sala = ?
            """, 
            (sala_id,)
        )
        sala = cursor.fetchone()
        
        # Textos para los propósitos
        propositos = {
            'individual': 'Tutorías individuales',
            'grupal': 'Tutorías grupales',
            'avisos': 'Canal de avisos'
        }
        
        # Enviar confirmación
        bot.edit_message_text(
            f"✅ *¡Propósito actualizado correctamente!*\n\n"
            f"*Sala:* {sala['Nombre_sala']}\n"
            f"*Nuevo propósito:* {propositos.get(nuevo_proposito, 'General')}\n"
            f"*Asignatura:* {sala['NombreAsignatura'] or 'General'}\n\n"
            f"La sala está lista para su nuevo propósito.",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode="Markdown"
        )
        
    except Exception as e:
        print(f"Error al actualizar sala: {e}")
        bot.send_message(chat_id, "❌ Error al actualizar la sala")
    finally:
        conn.close()
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("eliminarsala_"))
def handle_eliminar_sala(call):
    """Solicita confirmación para eliminar una sala"""
    chat_id = call.message.chat.id
    print(f"\n\n### INICIO ELIMINAR_SALA - Callback: {call.data} ###")
    print(f"👤 Usuario: {call.from_user.id}, Chat ID: {chat_id}")
    print(f"📤 Mensaje ID: {call.message.message_id}")
    
    # Responder al callback inmediatamente
    bot.answer_callback_query(call.id)
    
    try:
        partes = call.data.split("_")
        print(f"🔍 Partes del callback: {partes}")
        
        if len(partes) < 2:
            print("❌ Callback con formato incorrecto")
            bot.answer_callback_query(call.id, "❌ Error: formato de callback incorrecto")
            return
            
        sala_id = int(partes[1])
        print(f"🔍 Sala ID a eliminar: {sala_id}")
        
        # Verificar usuario
        user = get_user_by_telegram_id(call.from_user.id)
        print(f"👤 Usuario: {user['Nombre'] if user else 'No encontrado'} (ID: {call.from_user.id})")
        
        if not user or user['Tipo'] != 'profesor':
            print("⚠️ Usuario no es profesor o no existe")
            bot.answer_callback_query(call.id, "⚠️ No tienes permisos para esta acción")
            return
        
        # Obtener datos de la sala
        print(f"🔍 Consultando detalles de sala ID {sala_id}")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT g.*, a.Nombre as NombreAsignatura
            FROM Grupos_tutoria g
            LEFT JOIN Asignaturas a ON g.Id_asignatura = a.Id_asignatura
            WHERE g.id_sala = ? AND g.Id_usuario = ?
            """, 
            (sala_id, user['Id_usuario'])
        )
        sala = cursor.fetchone()
        
        if not sala:
            print(f"❌ Sala no encontrada o no pertenece al usuario")
            bot.answer_callback_query(call.id, "❌ No se encontró la sala o no tienes permisos")
            conn.close()
            return
            
        print(f"✅ Sala encontrada: {sala['Nombre_sala']} (ID: {sala_id}, Chat ID: {sala['Chat_id']})")
        
        # Contar miembros
        print(f"🔍 Contando miembros de la sala")
        cursor.execute(
            "SELECT COUNT(*) as total FROM Miembros_Grupo WHERE id_sala = ? AND Estado = 'activo'",
            (sala_id,)
        )
        miembros = cursor.fetchone()
        total_miembros = miembros['total'] if miembros else 0
        print(f"👥 Total miembros: {total_miembros}")
        conn.close()
        
        # Almacenar Chat_id para usarlo en la eliminación
        telegram_chat_id = sala['Chat_id']
        
        # Crear mensaje de confirmación
        print("📝 Creando mensaje de confirmación")
        mensaje = (
            f"⚠️ *¿Estás seguro de eliminar esta sala?*\n\n"
            f"*Sala:* {escape_markdown(sala['Nombre_sala'])}\n"
            f"*ID sala:* `{sala_id}`\n"
            f"*Chat ID Telegram:* `{telegram_chat_id}`\n"
            f"*Asignatura:* {escape_markdown(sala['NombreAsignatura'] or 'General')}\n"
            f"*Miembros actuales:* {total_miembros}\n\n"
            f"Esta acción *no se puede deshacer* y eliminará la sala junto con todos sus miembros "
            f"y configuraciones."
        )
        
        # Crear botones de confirmación, pasando también el Chat_id
        print("🔘 Creando botones de confirmación")
        markup = types.InlineKeyboardMarkup(row_width=2)
        callback_data = f"confirmar_eliminar_{sala_id}_{telegram_chat_id}"
        print(f"  → Callback de confirmación: {callback_data}")
        
        markup.add(
            types.InlineKeyboardButton(
                "✅ Sí, eliminar",
                callback_data=callback_data
            ),
            types.InlineKeyboardButton(
                "❌ No, cancelar",
                callback_data=f"cancelar_edicion_{sala_id}"
            )
        )
        
        # Enviar mensaje de confirmación
        print("📤 Enviando mensaje de confirmación")
        try:
            bot.edit_message_text(
                mensaje,
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )
            print("✅ Mensaje de confirmación enviado correctamente")
        except telebot.apihelper.ApiTelegramException as e:
            print(f"⚠️ Error al editar mensaje: {e}")
            if "message is not modified" in str(e):
                print("  → Ignorando error de mensaje no modificado")
            else:
                print("  → Intentando enviar mensaje nuevo")
                bot.send_message(
                    chat_id,
                    mensaje,
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
                print("  ✅ Nuevo mensaje enviado correctamente")
        
    except Exception as e:
        print(f"❌ ERROR GENERAL en handle_eliminar_sala: {e}")
        import traceback
        print(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ Error al procesar la solicitud de eliminación. Inténtalo de nuevo."
        )
    
    print(f"### FIN ELIMINAR_SALA ###\n")
    

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirmar_eliminar_"))
def handle_confirmar_eliminar(call):
    """Elimina definitivamente la sala después de la confirmación"""
    chat_id = call.message.chat.id
    print(f"\n\nDEBUG CONFIRMAR: Entrando en handle_confirmar_eliminar con data: {call.data}")
    print(f"👤 Usuario: {call.from_user.id}, Chat ID: {chat_id}")
    bot.answer_callback_query(call.id)
    try:
        # Extraer IDs de la cadena de callback
        data = call.data.split("_")
        print(f"DEBUG CONFIRMAR: Partes del callback: {data}")
        
        if len(data) < 4:  # Verificar que tenemos suficientes partes
            print(f"DEBUG CONFIRMAR: Formato de datos incorrecto, partes: {len(data)}")
            bot.send_message(chat_id, "❌ Error: formato de datos incorrecto")
            return
            
        sala_id = int(data[2])
        telegram_chat_id = data[3]  # Obtener el Chat_id de Telegram
        
        print(f"DEBUG CONFIRMAR: Procesando eliminación de sala_id={sala_id}, Chat_id={telegram_chat_id}")
        
        # Verificar usuario
        user = get_user_by_telegram_id(call.from_user.id)
        if not user or user['Tipo'] != 'profesor':
            print(f"DEBUG CONFIRMAR: Usuario no autorizado: {call.from_user.id}")
            bot.answer_callback_query(call.id, "⚠️ No tienes permisos para esta acción")
            return
            
        print(f"DEBUG CONFIRMAR: Usuario autorizado: {user['Nombre']}")
        
        # Eliminar miembros de la sala
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Eliminar primero los miembros
        cursor.execute("DELETE FROM Miembros_Grupo WHERE id_sala = ?", (sala_id,))
        
        # Obtener el nombre de la sala antes de eliminarla
        cursor.execute("SELECT Nombre_sala FROM Grupos_tutoria WHERE id_sala = ?", (sala_id,))
        sala_info = cursor.fetchone()
        nombre_sala = sala_info['Nombre_sala'] if sala_info else "desconocida"
        
        # Eliminar la sala
        cursor.execute("DELETE FROM Grupos_tutoria WHERE (id_sala = ? OR Chat_id = ?) AND Id_usuario = ?", 
                      (sala_id, telegram_chat_id, user['Id_usuario']))
        
        conn.commit()
        conn.close()
        
        # Notificar éxito
        bot.send_message(
            chat_id, 
            f"✅ La sala *{escape_markdown(nombre_sala)}* con ID *{sala_id}* ha sido eliminada correctamente.",
            parse_mode="Markdown"
        )
        
    except Exception as e:
        print(f"DEBUG CONFIRMAR: Error general: {e}")
        print(f"DEBUG CONFIRMAR: Traza completa:")
        import traceback
        traceback.print_exc()
        try:
            bot.send_message(
                chat_id,
                f"❌ Error al eliminar la sala: {str(e)}"
            )
        except:
            print("No se pudo enviar mensaje de error")
    
    print(f"### FIN CONFIRMAR_ELIMINAR ###\n")


@bot.message_handler(commands=['debug_sala'])
def handle_debug_sala(message):
    """Comando de depuración para examinar una sala por ID"""
    chat_id = message.chat.id
    
    try:
        # Verificar que se proporcionó un ID
        args = message.text.split()
        if len(args) < 2:
            bot.send_message(chat_id, "Uso: /debug_sala ID_SALA")
            return
            
        sala_id = int(args[1])
        
        # Verificar usuario
        user = get_user_by_telegram_id(message.from_user.id)
        if not user or user['Tipo'] != 'profesor':
            bot.send_message(chat_id, "⚠️ Solo los profesores pueden usar este comando")
            return
        
        # Obtener detalles de la sala
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM Grupos_tutoria WHERE id_sala = ?
            """, 
            (sala_id,)
        )
        sala = cursor.fetchone()
        
        if not sala:
            bot.send_message(chat_id, f"❌ No se encontró ninguna sala con ID {sala_id}")
            conn.close()
            return
            
        # Mostrar información detallada
        info = f"🔍 *Datos internos de sala ID {sala_id}*\n\n"
        for key in sala.keys():
            info += f"*{key}:* `{sala[key]}`\n"
            
        # Contar miembros
        cursor.execute("SELECT COUNT(*) as total FROM Miembros_Grupo WHERE id_sala = ?", (sala_id,))
        miembros = cursor.fetchone()
        info += f"\n*Total miembros:* {miembros['total']}\n"
        
        conn.close()
        
        bot.send_message(chat_id, info, parse_mode="Markdown")
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error: {str(e)}")

@bot.callback_query_handler(func=lambda call: True)
def debug_callback_universal(call):
    """Registra el callback y permite que otros handlers lo procesen"""
    print(f"🔍 DEBUG: Callback recibido: {call.data}")
    # NO llamar a bot.answer_callback_query() aquí
    return False  # Crucial: permite que otros handlers lo procesen
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
    
    # Iniciar el polling con manejo de errores más robusto
    while True:
        try:
            # Polling con parámetros para mejorar la estabilidad
            bot.polling(none_stop=True, interval=2, timeout=30)
        except Exception as e:
            print(f"❌ Error en el polling: {e}")
            # Información detallada del error
            import traceback
            traceback.print_exc()
            # Esperar antes de reconectar
            time.sleep(15)

