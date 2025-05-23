# filepath: C:\Users\Alberto\Desktop\TFG_V2\handlers\horarios.py
import telebot
from telebot import types
import re
import sys
import os
import time
import datetime
import logging

# Añadir directorio padre al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importaciones correctas desde módulos existentes
from db.queries import get_user_by_telegram_id, get_db_connection, update_user, get_horarios_profesor
from utils.horarios_utils import parsear_horario_string, convertir_horario_a_string
from utils.state_manager import user_states, user_data, set_state, clear_state

# Estados específicos para este módulo
estados_timestamp = {}

# Configurar logger
logger = logging.getLogger("horarios")
if not logger.handlers:
    handler = logging.FileHandler("horarios.log")
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def formatear_horario_bonito(horario_str):
    """Formatea el horario para mostrarlo de forma elegante"""
    print(f"DEBUG - formatear_horario_bonito - input: '{horario_str}'")
    
    if not horario_str or horario_str.strip() == "":
        return "No hay horario configurado"
    
    # Normalizar el formato del horario
    # Puede venir como "Lunes 09:00-11:00" o "Lunes: 09:00-11:00" o "Lunes, 09:00-11:00"
    horario_normalizado = horario_str.replace(": ", " ").replace(", ", " ")
    
    franjas = [f.strip() for f in horario_normalizado.split(',') if f.strip()]
    if not franjas:
        return "No hay horario configurado"
    
    dias = {"Lunes": [], "Martes": [], "Miércoles": [], "Jueves": [], "Viernes": []}
    
    for franja in franjas:
        print(f"DEBUG - Procesando franja: '{franja}'")
        partes = franja.split(" ", 1)  # Dividir solo en la primera ocurrencia
        
        if len(partes) >= 2:
            dia = partes[0]
            horas = partes[1]
            
            # Verificar que el día sea válido
            if dia in dias:
                dias[dia].append(horas)
                print(f"DEBUG - Añadida franja '{horas}' al día '{dia}'")
            else:
                print(f"DEBUG - Día no reconocido: '{dia}'")
        else:
            print(f"DEBUG - Formato incorrecto, no se puede dividir: '{franja}'")
    
    # Verificar si hay alguna franja válida
    franjas_validas = any(horas for horas in dias.values())
    if not franjas_validas:
        print("DEBUG - No se encontraron franjas válidas")
        return "No hay horario configurado correctamente"
    
    resultado = []
    for dia, horas in dias.items():
        if horas:
            lineas_hora = [f"• {hora}" for hora in horas]
            resultado.append(f"📅 *{dia}*:\n{chr(10).join(lineas_hora)}")
    
    return "\n\n".join(resultado) if resultado else "No hay horario configurado"

def register_handlers(bot):
    def obtener_horario_actual(user_id):
        """Obtiene el horario actual del profesor desde la base de datos"""
        try:
            # Obtener datos del usuario
            usuario = get_user_by_telegram_id(user_id)
            print(f"DEBUG - obtener_horario_actual - usuario: {usuario}")
            
            if not usuario:
                print(f"DEBUG - obtener_horario_actual - Usuario no encontrado para ID: {user_id}")
                return ""
            
            # Convertir sqlite3.Row a diccionario para poder usar get()
            usuario_dict = dict(usuario)
            
            if usuario_dict['Tipo'] != 'profesor':
                print(f"DEBUG - obtener_horario_actual - Usuario no es profesor: {usuario_dict['Tipo']}")
                return ""
            
            horario = usuario_dict.get('Horario', '')
            print(f"DEBUG - obtener_horario_actual - horario recuperado: {horario}")
            return horario if horario else ""
            
        except Exception as e:
            print(f"ERROR - obtener_horario_actual: {e}")
            import traceback
            traceback.print_exc()
            return ""  # Devolver string vacío en caso de error
    
    @bot.message_handler(commands=["configurar_horario"])
    def configurar_horario(message):
        """Función para configurar horarios de tutoría"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar si el usuario es profesor
        usuario = get_user_by_telegram_id(user_id)
        print(f"DEBUG - Usuario recuperado: {usuario}")

        if not usuario:
            bot.send_message(chat_id, "⚠️ Usuario no encontrado en la base de datos.")
            return

        # Convertir sqlite3.Row a diccionario
        usuario_dict = dict(usuario)

        if usuario_dict['Tipo'] != 'profesor':
            bot.send_message(chat_id, f"⚠️ Tipo de usuario incorrecto: {usuario_dict['Tipo']}")
            return
    
        # Inicializar datos
        if chat_id not in user_data:
            user_data[chat_id] = {}

        # Obtener horario actual
        horario_actual = obtener_horario_actual(user_id)
        
        # Modificar esta parte para evitar el error
        if horario_actual is not None:
            # Mostrar horario actual formateado (incluso si está vacío)
            bot.send_message(
                chat_id,
                f"📅 *Tu horario actual:*\n\n{formatear_horario_bonito(horario_actual)}",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                chat_id,
                "❌ Error al recuperar tu horario. Por favor, inténtalo más tarde."
            )
            return

        # Mostrar selector de días - ELIMINAR BOTÓN DE CONFIRMAR HORARIO DEL MENÚ PRINCIPAL
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        markup.add(*[telebot.types.KeyboardButton(dia) for dia in dias])
        markup.row(telebot.types.KeyboardButton("Ver horario completo"))
        # Solo mantener el botón de cancelar en el menú inicial
        markup.row(telebot.types.KeyboardButton("❌ Cancelar"))
        
        bot.send_message(
            chat_id,
            "🕒 *Configuración de horario*\n\n"
            "Selecciona el día que deseas configurar:",
            parse_mode="Markdown",
            reply_markup=markup
        )
        
        # Parsear el horario existente
        user_data[chat_id]["horario"] = parsear_horario_string(horario_actual) if horario_actual else {}
        set_state(chat_id, "seleccion_dia_horario")
        estados_timestamp[chat_id] = time.time()

    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "seleccion_dia_horario")
    def handle_seleccion_dia(message):
        """Maneja la selección del día para configurar horario"""
        chat_id = message.chat.id
        seleccion = message.text.strip()
        
        dias_validos = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        
        if seleccion == "❌ Cancelar":
            bot.send_message(
                chat_id,
                "Configuración de horario cancelada.",
                reply_markup=telebot.types.ReplyKeyboardRemove()
            )
            clear_state(chat_id)
            return
    
        # Ver horario completo
        if seleccion == "Ver horario completo":
            horario_actual = obtener_horario_actual(message.from_user.id)
            print(f"DEBUG - Ver horario completo - horario recuperado: {horario_actual}")
            
            # IMPORTANTE: Se debe mostrar siempre algo, incluso si está vacío
            if horario_actual and horario_actual.strip():
                bot.send_message(
                    chat_id,
                    f"📅 *Tu horario completo:*\n\n{formatear_horario_bonito(horario_actual)}\n\n"
                    "Para modificarlo, selecciona un día específico.",
                    parse_mode="Markdown"
                )
            else:
                bot.send_message(
                    chat_id, 
                    "📝 Aún no has añadido franjas horarias. Selecciona un día para comenzar a configurar tu horario de tutorías."
                )
            return
            
        # Procesar selección de día
        if seleccion in dias_validos:
            # Guardar el día seleccionado
            user_data[chat_id]["dia_actual"] = seleccion
            
            # Obtener franjas ya existentes para este día
            franjas = user_data[chat_id]["horario"].get(seleccion, [])
                
            if franjas and len(franjas) > 0:
                # Hay franjas para este día
                mensaje = f"📅 *Franjas horarias para {seleccion}:*\n\n"
                
                for i, franja in enumerate(franjas, 1):
                    mensaje += f"{i}. De *{franja}*\n\n"
                
                mensaje += "Selecciona una opción:"
                
                # Opciones para modificar, añadir o eliminar
                markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
                markup.add(
                    telebot.types.KeyboardButton("➕ Añadir nueva franja"),
                    telebot.types.KeyboardButton("✏️ Modificar franja existente"),
                    telebot.types.KeyboardButton("➖ Eliminar franja"),
                    telebot.types.KeyboardButton("🔙 Volver"),
                    telebot.types.KeyboardButton("💾 Guardar cambios")
                )
                
                bot.send_message(
                    chat_id,
                    mensaje,
                    parse_mode="Markdown",
                    reply_markup=markup
                )
            else:
                # No hay franjas para este día
                mensaje = f"📅 *{seleccion}*\n\nNo tienes franjas horarias configuradas para este día."
                markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
                markup.add(
                    telebot.types.KeyboardButton("➕ Añadir franja horaria"),
                    telebot.types.KeyboardButton("🔙 Volver")
                )
                
                bot.send_message(
                    chat_id,
                    mensaje,
                    reply_markup=markup
                )
            
            set_state(chat_id, "gestion_franjas")
            estados_timestamp[chat_id] = time.time()
        else:
            bot.send_message(chat_id, "Por favor, selecciona un día válido.")

    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "gestion_franjas")
    def handle_gestion_franjas(message):
        """Maneja la gestión de franjas horarias para un día específico"""
        chat_id = message.chat.id
        accion = message.text.strip()
        dia = user_data[chat_id]["dia_actual"]
        
        if accion == "➕ Añadir franja horaria" or accion == "➕ Añadir nueva franja":
            # Sugerir franjas horarias comunes
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            franjas_comunes = [
                "09:00-11:00", "11:00-13:00", "13:00-15:00", 
                "15:00-17:00", "17:00-19:00", "19:00-21:00"
            ]
            markup.add(*[telebot.types.KeyboardButton(franja) for franja in franjas_comunes])
            markup.row(telebot.types.KeyboardButton("🔙 Cancelar"))
            
            bot.send_message(
                chat_id,
                "⌨️ *Introduce la franja horaria*\n\n"
                "Selecciona una opción predefinida o escribe tu propia franja en formato HH:MM-HH:MM\n"
                "Ejemplo: 09:00-11:30\n\n"
                "👉 Introduce una sola franja por vez",
                parse_mode="Markdown",
                reply_markup=markup
            )
            set_state(chat_id, "introducir_franja")
            estados_timestamp[chat_id] = time.time()
            
        elif accion == "✏️ Modificar franja existente":
            # Mostrar opciones de franjas a modificar
            franjas = user_data[chat_id]["horario"].get(dia, [])
            if not franjas:
                bot.send_message(chat_id, f"No hay franjas configuradas para {dia}.")
                return
                
            # Crear botones para cada franja
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
            for i, franja in enumerate(franjas, 1):
                markup.add(telebot.types.KeyboardButton(f"Modificar {i}: {franja}"))
            markup.add(telebot.types.KeyboardButton("🔙 Cancelar"))
            
            bot.send_message(
                chat_id,
                f"Selecciona la franja que deseas modificar para {dia}:",
                reply_markup=markup
            )
            set_state(chat_id, "seleccionar_franja_modificar")
            estados_timestamp[chat_id] = time.time()
            
        elif accion == "➖ Eliminar franja":
            # Mostrar opciones de franjas a eliminar
            franjas = user_data[chat_id]["horario"].get(dia, [])
            if not franjas:
                bot.send_message(chat_id, f"No hay franjas configuradas para {dia}.")
                return
                
            # Crear botones para cada franja
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
            for i, franja in enumerate(franjas, 1):
                markup.add(telebot.types.KeyboardButton(f"Eliminar {i}: {franja}"))
            markup.add(telebot.types.KeyboardButton("🔙 Cancelar"))
            
            bot.send_message(
                chat_id,
                f"Selecciona la franja que deseas eliminar para {dia}:",
                reply_markup=markup
            )
            set_state(chat_id, "seleccionar_franja_eliminar")
            estados_timestamp[chat_id] = time.time()
            
        elif accion == "🔙 Volver":
            # Volver a la selección de día
            configurar_horario(message)
            
        elif accion == "💾 Guardar cambios":
            try:
                # Convertir el horario a formato de string
                horario_str = convertir_horario_a_string(user_data[chat_id]["horario"])
                
                # Obtener ID del usuario
                usuario = get_user_by_telegram_id(message.from_user.id)
                
                # Guardar en la base de datos
                exito = update_user(usuario['Id_usuario'], Horario=horario_str)
                
                if exito:
                    # Confirmar al usuario
                    bot.send_message(
                        chat_id,
                        f"✅ *Cambios guardados*\n\n"
                        f"El horario para *{dia}* ha sido actualizado y guardado en la base de datos.",
                        parse_mode="Markdown"
                    )
                    
                    # Obtener y mostrar el horario actualizado
                    horario_actual = obtener_horario_actual(message.from_user.id)
                    horario_formateado = formatear_horario_bonito(horario_actual)
                    
                    bot.send_message(
                        chat_id,
                        f"📅 *Tu horario actualizado:*\n\n{horario_formateado}",
                        parse_mode="Markdown"
                    )
                    
                    # Cambiar el estado para manejar esta nueva opción
                    set_state(chat_id, "post_guardar_horario")
                    estados_timestamp[chat_id] = time.time()
                    return  # Importante: no seguir con el código que vuelve al menú de días
                    
                else:
                    bot.send_message(
                        chat_id,
                        "❌ Error al guardar el horario en la base de datos.",
                        parse_mode="Markdown"
                    )
    
            except Exception as e:
                bot.send_message(
                    chat_id,
                    f"❌ Error al guardar el horario: {str(e)}",
                    parse_mode="Markdown"
                )
                print(f"ERROR guardando horario: {e}")
        else:
            bot.send_message(chat_id, "Por favor, selecciona una opción válida.")

    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "introducir_franja")
    def handle_introducir_franja(message):
        """Procesa la introducción de una nueva franja horaria"""
        chat_id = message.chat.id
        texto = message.text.strip()
        dia = user_data[chat_id]["dia_actual"]
        
        if texto == "🔙 Cancelar":
            # Volver al menú de gestión de franjas
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=message.chat,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = dia
            handle_seleccion_dia(msg)
            return
            
        # Validar formato de la franja horaria
        if not re.match(r'^\d{1,2}:\d{2}-\d{1,2}:\d{2}$', texto):
            bot.send_message(
                chat_id,
                "⚠️ Formato incorrecto. Usa el formato HH:MM-HH:MM\n"
                "Ejemplo: 09:00-11:30"
            )
            return
            
        try:
            # Validar horas y minutos
            inicio, fin = texto.split("-")
            hora_inicio, min_inicio = map(int, inicio.split(":"))
            hora_fin, min_fin = map(int, fin.split(":"))
            
            if not (0 <= hora_inicio <= 23 and 0 <= min_inicio <= 59):
                bot.send_message(
                    chat_id,
                    "⚠️ Hora de inicio inválida. Debe estar entre 00:00 y 23:59."
                )
                return
                
            if not (0 <= hora_fin <= 23 and 0 <= min_fin <= 59):
                bot.send_message(
                    chat_id,
                    "⚠️ Hora de fin inválida. Debe estar entre 00:00 y 23:59."
                )
                return
                
            if (hora_inicio > hora_fin) or (hora_inicio == hora_fin and min_inicio >= min_fin):
                bot.send_message(
                    chat_id,
                    "⚠️ La hora de inicio debe ser anterior a la hora de fin."
                )
                return

            # Añadir la franja al día seleccionado
            if dia not in user_data[chat_id]["horario"]:
                user_data[chat_id]["horario"][dia] = []
                
            # NUEVA VALIDACIÓN: Comprobar si ya existe esta franja para este día
            if texto in user_data[chat_id]["horario"][dia]:
                bot.send_message(
                    chat_id,
                    f"⚠️ Ya tienes configurada la franja {texto} para {dia}.\n"
                    "Por favor, introduce una franja horaria diferente."
                )
                return
    
            # Añadir la franja al horario
            user_data[chat_id]["horario"][dia].append(texto)
            print(f"DEBUG - Franja añadida: {dia} {texto}")
            print(f"DEBUG - Horario actualizado: {user_data[chat_id]['horario']}")
            
            # Enviar confirmación y opciones
            bot.send_message(
                chat_id,
                f"✅ Franja {texto} añadida a {dia}",
                parse_mode="Markdown"
            )
            
            # Opciones post-añadir
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
            markup.add(
                telebot.types.KeyboardButton("➕ Añadir otra franja"),
                telebot.types.KeyboardButton("💾 Guardar cambios"),
                telebot.types.KeyboardButton("🔙 Volver")
            )
            
            bot.send_message(
                chat_id,
                "¿Qué deseas hacer ahora?",
                reply_markup=markup
            )
            
            set_state(chat_id, "post_añadir_franja")
            estados_timestamp[chat_id] = time.time()
            
        except ValueError as e:
            bot.send_message(
                chat_id,
                f"⚠️ Error en el formato de hora: {e}"
            )
            return

    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "post_añadir_franja")
    def handle_post_añadir_franja(message):
        """Maneja las acciones después de añadir una franja"""
        chat_id = message.chat.id
        accion = message.text.strip()
        
        if accion == "➕ Añadir otra franja":
            # Volver a añadir franja
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=message.chat,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = "➕ Añadir nueva franja"
            handle_gestion_franjas(msg)
        elif accion == "💾 Guardar cambios":
            # Guardar cambios
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=message.chat,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = "💾 Guardar cambios"
            handle_gestion_franjas(msg)
        elif accion == "🔙 Volver":
            # Volver al menú de gestión
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=message.chat,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = user_data[chat_id]["dia_actual"]
            handle_seleccion_dia(msg)

    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "seleccionar_franja_modificar")
    def handle_seleccionar_franja_modificar(message):
        """Procesa la selección de franja a modificar"""
        chat_id = message.chat.id
        seleccion = message.text.strip()
        dia = user_data[chat_id]["dia_actual"]
        
        if seleccion == "🔙 Cancelar":
            # Volver al menú de gestión de franjas
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=message.chat,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = dia
            handle_seleccion_dia(msg)
            return
            
        # Extraer el índice y la franja
        if not seleccion.startswith("Modificar "):
            bot.send_message(chat_id, "Por favor, selecciona una opción válida.")
            return
            
        try:
            # Extraer el índice (formato: "Modificar X: HH:MM-HH:MM")
            partes = seleccion.split(": ")
            indice_parte = partes[0].split(" ")[1]
            indice = int(indice_parte) - 1  # Convertir a base 0
            franja = user_data[chat_id]["horario"][dia][indice]
            
            # Guardar el índice para la modificación
            user_data[chat_id]["indice_modificar"] = indice
            
            # Sugerir franjas horarias comunes
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            franjas_comunes = [
                "09:00-11:00", "11:00-13:00", "13:00-15:00", 
                "15:00-17:00", "17:00-19:00", "19:00-21:00"
            ]
            markup.add(*[telebot.types.KeyboardButton(franja) for franja in franjas_comunes])
            markup.row(telebot.types.KeyboardButton("🔙 Cancelar"))
            
            bot.send_message(
                chat_id,
                f"Estás modificando la franja: *{franja}*\n\n"
                "Selecciona una opción predefinida o escribe la nueva franja horaria en formato HH:MM-HH:MM\n"
                "Ejemplo: 09:00-11:30",
                parse_mode="Markdown",
                reply_markup=markup
            )
            set_state(chat_id, "introducir_franja_modificada")
            estados_timestamp[chat_id] = time.time()
            
        except (ValueError, IndexError, KeyError) as e:
            bot.send_message(
                chat_id,
                f"❌ Error: {str(e)}\nPor favor, inténtalo de nuevo."
            )

    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "introducir_franja_modificada")
    def handle_introducir_franja_modificada(message):
        """Procesa la modificación de una franja horaria existente"""
        chat_id = message.chat.id
        texto = message.text.strip()
        dia = user_data[chat_id]["dia_actual"]
        indice = user_data[chat_id]["indice_modificar"]
        
        if texto == "🔙 Cancelar":
            # Volver al menú de gestión de franjas
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=message.chat,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = dia
            handle_seleccion_dia(msg)
            return

        # Validar formato de la franja horaria
        if not re.match(r'^\d{1,2}:\d{2}-\d{1,2}:\d{2}$', texto):
            bot.send_message(
                chat_id,
                "⚠️ Formato incorrecto. Usa el formato HH:MM-HH:MM\n"
                "Ejemplo: 09:00-11:30"
            )
            return
            
        try:
            # Validar horas y minutos
            inicio, fin = texto.split("-")
            hora_inicio, min_inicio = map(int, inicio.split(":"))
            hora_fin, min_fin = map(int, fin.split(":"))
            
            if not (0 <= hora_inicio <= 23 and 0 <= min_inicio <= 59):
                bot.send_message(chat_id, f"⚠️ Hora de inicio inválida: {inicio}")
                return
                
            if not (0 <= hora_fin <= 23 and 0 <= min_fin <= 59):
                bot.send_message(chat_id, f"⚠️ Hora de fin inválida: {fin}")
                return
                
            if (hora_inicio > hora_fin) or (hora_inicio == hora_fin and min_inicio >= min_fin):
                bot.send_message(chat_id, "⚠️ La hora de fin debe ser posterior a la hora de inicio")
                return
                
            # Formatear para guardar
            franja_formateada = f"{hora_inicio:02d}:{min_inicio:02d}-{hora_fin:02d}:{min_fin:02d}"
            franja_anterior = user_data[chat_id]["horario"][dia][indice]
            
            # Modificar el horario
            user_data[chat_id]["horario"][dia][indice] = franja_formateada
            
            # Confirmar y volver al menú de gestión
            bot.send_message(
                chat_id,
                f"✅ Franja modificada:\n"
                f"Anterior: {franja_anterior}\n"
                f"Nueva: {franja_formateada}"
            )
            
            # Simular la selección del día para mostrar el menú actualizado
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=message.chat,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = dia
            handle_seleccion_dia(msg)
            
        except ValueError as e:
            bot.send_message(
                chat_id,
                f"⚠️ Error en el formato: {str(e)}\n"
                "Usa el formato HH:MM-HH:MM"
            )

    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "seleccionar_franja_eliminar")
    def handle_seleccionar_franja_eliminar(message):
        """Procesa la selección de franja a eliminar"""
        chat_id = message.chat.id
        seleccion = message.text.strip()
        dia = user_data[chat_id]["dia_actual"]
        
        if seleccion == "🔙 Cancelar":
            # Volver al menú de gestión de franjas
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=chat_id,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = dia
            handle_seleccion_dia(msg)
            return
            
        # Extraer el índice y la franja
        if not seleccion.startswith("Eliminar "):
            bot.send_message(chat_id, "Por favor, selecciona una opción válida.")
            return
            
        try:
            # Extraer el índice (formato: "Eliminar X: HH:MM-HH:MM")
            partes = seleccion.split(": ")
            indice_parte = partes[0].split(" ")[1]
            indice = int(indice_parte) - 1  # Convertir a base 0
            franja = user_data[chat_id]["horario"][dia][indice]
            
            # Eliminar la franja
            user_data[chat_id]["horario"][dia].pop(indice)
            
            # Si era la última franja del día, eliminar el día completo
            if not user_data[chat_id]["horario"][dia]:
                del user_data[chat_id]["horario"][dia]
            
            # Confirmar eliminación
            bot.send_message(
                chat_id,
                f"✅ Franja {franja} eliminada de {dia}"
            )
            
            # Simular la selección del día para mostrar el menú actualizado
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=chat_id,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = dia
            handle_seleccion_dia(msg)
            
        except (ValueError, IndexError, KeyError) as e:
            bot.send_message(
                chat_id,
                f"❌ Error: {str(e)}\nPor favor, inténtalo de nuevo."
            )
    
    @bot.message_handler(commands=['configurar_horario'])
    def handle_configurar_horario(message):
        """Inicia el proceso de configuración de horario para profesores"""
        chat_id = message.chat.id
        user = get_user_by_telegram_id(message.from_user.id)
        
        if not user:
            bot.send_message(chat_id, "❌ No estás registrado. Usa /start para registrarte.")
            return
            
        if user['Tipo'] != 'profesor':
            bot.send_message(
                chat_id, 
                "⚠️ Solo los profesores pueden configurar horarios de tutoría."
            )
            return
        
        # Verificar si ya tiene horario configurado
        user_dict = dict(user)
        horario_actual = user_dict.get('Horario', '')
        
        # Crear menú principal con días directamente
        markup = types.InlineKeyboardMarkup(row_width=3)
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        
        buttons_dias = []
        for dia in dias:
            buttons_dias.append(types.InlineKeyboardButton(
                dia, callback_data=f"dia_{dia.lower()}"
            ))
        
        # Añadir botones en filas
        markup.add(*buttons_dias[:3])  # Primera fila: Lunes, Martes, Miércoles
        markup.add(*buttons_dias[3:])  # Segunda fila: Jueves, Viernes
        
        # Si ya tiene horario, añadir botón para modificar
        if horario_actual:
            markup.add(types.InlineKeyboardButton(
                "✏️ Modificar horario existente", callback_data="modificar_horario"
            ))
        
        # Añadir botón para confirmar
        markup.add(types.InlineKeyboardButton(
            "✅ Confirmar horario", callback_data="confirmar_horario"
        ))
        
        # Texto del mensaje
        if horario_actual:
            mensaje = f"🕒 *Configuración de horario*\n\n" \
                     f"Tu horario actual:\n{horario_actual}\n\n" \
                     f"Selecciona un día para añadir franjas o modifica tu horario existente:"
        else:
            mensaje = "🕒 *Configuración de horario*\n\n" \
                     "No tienes horario configurado. Selecciona un día para comenzar:"
        
        bot.send_message(
            chat_id,
            mensaje,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        
        user_states[chat_id] = "configurando_horario"
    
    @bot.callback_query_handler(func=lambda call: call.data == "add_franja")
    def handle_add_franja(call):
        """Inicia proceso para añadir una franja"""
        chat_id = call.message.chat.id
        
        # Mostrar días disponibles
        markup = types.InlineKeyboardMarkup(row_width=2)
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        for dia in dias:
            markup.add(types.InlineKeyboardButton(dia, callback_data=f"dia_{dia}"))
        
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="📅 Selecciona un día para la tutoría:",
                reply_markup=markup
            )
        except Exception as e:
            print(f"Error al editar mensaje: {e}")
            # Intentar enviar nuevo mensaje si editar falla
            bot.send_message(
                chat_id,
                "📅 Selecciona un día para la tutoría:",
                reply_markup=markup
            )
        
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("dia_"))
    def handle_dia_seleccionado(call):
        """Maneja la selección de día"""
        chat_id = call.message.chat.id
        dia = call.data.split("_")[1]
        
        # Guardar el día para uso posterior
        user_data[chat_id] = user_data.get(chat_id, {})
        user_data[chat_id]['dia'] = dia
        
        # Mostrar opciones de horario
        markup = types.InlineKeyboardMarkup(row_width=2)
        horarios = [
            ("09:00-11:00", "h_9_11"),
            ("11:00-13:00", "h_11_13"),
            ("13:00-15:00", "h_13_15"),
            ("15:00-17:00", "h_15_17"),
            ("17:00-19:00", "h_17_19")
        ]
        
        # Añadir botones de horario
        for texto, callback in horarios:
            markup.add(types.InlineKeyboardButton(texto, callback_data=callback))
        
        # Opción personalizada
        markup.add(types.InlineKeyboardButton("✏️ Personalizado", callback_data="h_custom"))
        
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"⏰ Selecciona un horario para el {dia}:",
                reply_markup=markup
            )
        except Exception as e:
            print(f"Error al editar mensaje: {e}")
            bot.send_message(
                chat_id,
                f"⏰ Selecciona un horario para el {dia}:",
                reply_markup=markup
            )
        
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("h_"))
    def handle_horario_seleccionado(call):
        """Procesa la selección de horario"""
        chat_id = call.message.chat.id
        user = get_user_by_telegram_id(call.from_user.id)
        dia = user_data[chat_id].get('dia', "")
        
        if call.data == "h_custom":
            # Manejo de horario personalizado
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"✏️ Introduce el horario para el {dia} en formato HH:MM-HH:MM\n"
                     f"Ejemplo: 10:30-12:45"
            )
            
            user_states[chat_id] = "esperando_hora_personalizada"
        else:
            # Horario predefinido
            partes = call.data.split("_")
            hora_inicio = partes[1]
            hora_fin = partes[2]
            
            # Crear franja completa
            franja = f"{dia} {hora_inicio}:00-{hora_fin}:00"
            franja_horas = f"{hora_inicio}:00-{hora_fin}:00"
            
            # Añadir a horario existente
            user_dict = dict(user)
            horario_actual = user_dict.get('Horario', '')
            
            # NUEVA VALIDACIÓN: Verificar si ya existe esta franja en el horario
            if horario_actual:
                # Verificar si ya existe esta franja
                franjas = [f.strip() for f in horario_actual.split(',')]
                for f in franjas:
                    if f.startswith(dia) and franja_horas in f:
                        bot.answer_callback_query(call.id, "⚠️ Esta franja ya existe para este día")
                        return
                        
                horario_nuevo = f"{horario_actual}, {franja}"
            else:
                horario_nuevo = franja
        
            # Guardar en la base de datos
            success = update_user(user['Id_usuario'], Horario=horario_nuevo)
            
            if success:
                # Mostrar confirmación
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("➕ Añadir más franjas", callback_data="add_franja"),
                    types.InlineKeyboardButton("🖊️ Modificar horario", callback_data="modificar_horario"),
                    types.InlineKeyboardButton("↩️ Volver", callback_data="volver_menu_principal")
                )
                
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=f"✅ *Franja añadida*\n\n"
                         f"Tu horario actualizado:\n{horario_nuevo}",
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
            else:
                bot.answer_callback_query(call.id, "❌ Error al guardar el horario")
    
        bot.answer_callback_query(call.id)
    
    @bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "esperando_hora_personalizada")
    def handle_hora_personalizada(message):
        """Procesa la entrada de horario personalizado"""
        chat_id = message.chat.id
        user = get_user_by_telegram_id(message.from_user.id)
        hora = message.text.strip()
        
        # Validar formato
        import re
        if not re.match(r'^\d{1,2}:\d{2}-\d{1,2}:\d{2}$', hora):
            bot.send_message(
                chat_id,
                "⚠️ Formato incorrecto. Debe ser HH:MM-HH:MM (ejemplo: 10:30-12:45)"
            )
            return
        
        dia = user_data[chat_id].get('dia', "")
        franja = f"{dia} {hora}"
        
        # Añadir a horario existente
        user_dict = dict(user)
        horario_actual = user_dict.get('Horario', '')
        
        if horario_actual:
            # Verificar si ya existe
            franjas = [f.strip() for f in horario_actual.split(',')]
            if franja in franjas:
                bot.send_message(
                    chat_id,
                    "⚠️ Esta franja ya existe en tu horario"
                )
                return
                
            horario_nuevo = f"{horario_actual}, {franja}"
        else:
            horario_nuevo = franja
        
        # Guardar en la base de datos
        success = update_user(user['Id_usuario'], Horario=horario_nuevo)
        
        if success:
            # Mostrar confirmación
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("➕ Añadir más franjas", callback_data="add_franja"),
                types.InlineKeyboardButton("🖊️ Modificar horario", callback_data="modificar_horario"),
                types.InlineKeyboardButton("↩️ Volver", callback_data="volver_menu_principal")
            )
            
            bot.send_message(
                chat_id,
                f"✅ *Franja añadida*\n\n"
                f"Tu horario actualizado:\n{horario_nuevo}",
                reply_markup=markup,
                parse_mode="Markdown"
            )
            
            # Limpiar estado
            user_states[chat_id] = None
        else:
            bot.send_message(chat_id, "❌ Error al guardar el horario")
    
    @bot.callback_query_handler(func=lambda call: call.data == "del_franja")
    def handle_del_franja(call):
        """Muestra las franjas para eliminar"""
        chat_id = call.message.chat.id
        user = get_user_by_telegram_id(call.from_user.id)
        
        # Verificar si tiene horario
        user_dict = dict(user)
        horario = user_dict.get('Horario', '')
        
        if not horario:
            bot.answer_callback_query(call.id, "No tienes franjas para eliminar")
            return
        
        # Parsear franjas existentes
        franjas = [f.strip() for f in horario.split(',')]
        
        # Crear botones para cada franja
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        for i, franja in enumerate(franjas):
            markup.add(types.InlineKeyboardButton(
                f"🗑️ {franja}", callback_data=f"eliminar_{i}"
            ))
        
        markup.add(types.InlineKeyboardButton(
            "↩️ Volver", callback_data="ver_horario"
        ))
        
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="🗑️ *Eliminar franjas*\n\nSelecciona la franja que deseas eliminar:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
            
            # Guardar las franjas para uso posterior
            user_data[chat_id] = user_data.get(chat_id, {})
            user_data[chat_id]['franjas'] = franjas
        except Exception as e:
            print(f"Error al editar mensaje: {e}")
            # Intentar enviar nuevo mensaje
            bot.send_message(
                chat_id,
                "🗑️ *Eliminar franjas*\n\nSelecciona la franja que deseas eliminar:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith("eliminar_"))
    def handle_eliminar_franja(call):
        """Elimina una franja específica del horario"""
        chat_id = call.message.chat.id
        user = get_user_by_telegram_id(call.from_user.id)
        
        if not user:
            bot.answer_callback_query(call.id, "⚠️ No estás registrado")
            return
        
        user_dict = dict(user)
        
        # Obtener índice de la franja a eliminar
        indice = int(call.data.split("_")[2])
        
        # Verificar que el chat_id existe en user_data
        if chat_id not in user_data:
            user_data[chat_id] = {}
        
        if 'franjas' not in user_data[chat_id]:
            user_data[chat_id]['franjas'] = []
        
        # Obtener franjas de manera segura, inicializando si no existe
        franjas = user_data[chat_id].get('franjas', [])
        
        if indice >= len(franjas):
            bot.answer_callback_query(call.id, "❌ Error: Franja no encontrada")
            return
        
        # Obtener la franja a eliminar
        franja_eliminada = franjas[indice]
        
        # Eliminar la franja
        del franjas[indice]
        
        # Crear el nuevo horario
        horario_actualizado = ", ".join(franjas) if franjas else ""
        
        # Guardar en la base de datos
        from db.queries import update_user
        success = update_user(user['Id_usuario'], Horario=horario_actualizado)
        
        if success:
            # Mostrar mensaje de confirmación
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            if franjas:  # Si aún quedan franjas
                markup.add(
                    types.InlineKeyboardButton("✏️ Modificar más franjas", callback_data="modificar_horario"),
                    types.InlineKeyboardButton("➕ Añadir franja", callback_data="add_franja"),
                    types.InlineKeyboardButton("↩️ Volver", callback_data="volver_menu_horario")
                )
                
                mensaje = (
                    f"✅ *Franja eliminada*\n\n"
                    f"*Franja eliminada:* {franja_eliminada}\n\n"
                    f"Tu horario actualizado:\n{horario_actualizado}"
                )
            else:
                markup.add(
                    types.InlineKeyboardButton("➕ Añadir franja", callback_data="add_franja"),
                    types.InlineKeyboardButton("↩️ Volver", callback_data="volver_menu_horario")
                )
                
                mensaje = (
                    "✅ *Franja eliminada*\n\n"
                    "Has eliminado todas tus franjas horarias."
                )
            
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    text=mensaje,
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Error al editar mensaje: {e}")
                bot.send_message(
                    chat_id,
                    mensaje,
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
        else:
            bot.answer_callback_query(call.id, "❌ Error al actualizar el horario")
    
    @bot.callback_query_handler(func=lambda call: call.data == "ver_horario")
    def handle_ver_horario(call):
        """Muestra el horario completo"""
        chat_id = call.message.chat.id
        user = get_user_by_telegram_id(call.from_user.id)
        
        # Verificar si tiene horario
        user_dict = dict(user)
        horario = user_dict.get('Horario', '')
        
        # Crear menú principal
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        if horario:
            markup.add(
                types.InlineKeyboardButton("➕ Añadir franja", callback_data="add_franja"),
                types.InlineKeyboardButton("🗑️ Eliminar franja", callback_data="del_franja")
            )
            
            texto = f"🕒 *Tu horario actual:*\n\n{horario}\n\n¿Qué deseas hacer?"
        else:
            markup.add(
                types.InlineKeyboardButton("➕ Configurar horario", callback_data="add_franja")
            )
            
            texto = "No tienes horario configurado. ¿Deseas configurar uno?"
        
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=texto,
                reply_markup=markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error al editar mensaje: {e}")
            bot.send_message(
                chat_id,
                texto,
                reply_markup=markup,
                parse_mode="Markdown"
            )
        
        bot.answer_callback_query(call.id)
    
    @bot.callback_query_handler(func=lambda call: call.data == "modificar_horario")
    def handle_modificar_horario(call):
        """Muestra las franjas horarias existentes para modificarlas o eliminarlas"""
        chat_id = call.message.chat.id
        user = get_user_by_telegram_id(call.from_user.id)
        
        if not user:
            bot.answer_callback_query(call.id, "⚠️ No estás registrado")
            return
        
        # Convertir a diccionario - CORRECCIÓN
        user_dict = dict(user)
        
        # Verificar si tiene horario configurado
        horario_actual = user_dict.get('Horario', '')
        
        if not horario_actual:
            bot.answer_callback_query(call.id, "❌ No hay horario para modificar")
            return
        
        # Separar las franjas del horario
        franjas = [f.strip() for f in horario_actual.split(',')]
        
        # Crear botones para cada franja - AHORA CON DOS BOTONES POR FRANJA
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        for i, franja in enumerate(franjas):
            # Crear una fila con dos botones para cada franja: editar y eliminar
            markup.add(
                types.InlineKeyboardButton(f"✏️ {franja}", callback_data=f"editar_franja_{i}"),
                types.InlineKeyboardButton(f"🗑️ Eliminar", callback_data=f"eliminar_franja_{i}")
            )
        
        # Botón para volver
        markup.add(types.InlineKeyboardButton(
            "↩️ Volver", callback_data="volver_menu_horario"
        ))
        
        # Mostrar las franjas
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="✏️ *Modificar o eliminar franjas*\n\n"
                     "Selecciona la acción que deseas realizar:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error al editar mensaje: {e}")
            bot.send_message(
                chat_id,
                "✏️ *Modificar o eliminar franjas*\n\n"
                "Selecciona la acción que deseas realizar:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        
        # Guardar franjas para uso posterior
        user_data[chat_id] = user_data.get(chat_id, {})
        user_data[chat_id]['franjas'] = franjas
        
        user_states[chat_id] = "seleccionando_franja_modificar"
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("editar_franja_"))
    def handle_editar_franja(call):
        """Permite modificar una franja específica"""
        chat_id = call.message.chat.id
        indice = int(call.data.split("_")[2])
        
        # Recuperar franjas guardadas
        franjas = user_data[chat_id].get('franjas', [])
        
        if indice >= len(franjas):
            bot.answer_callback_query(call.id, "❌ Error: Franja no encontrada")
            return
        
        franja_actual = franjas[indice]
        
        # Extraer día y horas de la franja actual
        partes = franja_actual.split()
        dia = partes[0]
        horas = partes[1] if len(partes) > 1 else ""
        
        # Crear teclado con opciones de día
        markup = types.InlineKeyboardMarkup(row_width=2)
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        for d in dias:
            text = f"✓ {d}" if d == dia else d
            markup.add(types.InlineKeyboardButton(text, callback_data=f"edit_dia_{indice}_{d}"))
        
        # Añadir campo para editar horas (se procesará en un estado separado)
        markup.add(types.InlineKeyboardButton(
            f"⏰ Horas: {horas}", callback_data=f"edit_horas_{indice}"
        ))
        
        # Botón para guardar cambios
        markup.add(types.InlineKeyboardButton(
            "💾 Guardar", callback_data=f"guardar_franja_{indice}"
        ))
        
        # Botón para cancelar
        markup.add(types.InlineKeyboardButton(
            "↩️ Cancelar", callback_data="modificar_horario"
        ))
        
        # Mostrar diálogo
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"✏️ *Modificar franja*\n\n"
                 f"Franja actual: *{franja_actual}*\n\n"
                 f"Selecciona el día y las horas para esta franja:",
            parse_mode="Markdown",
            reply_markup=markup
        )
        
        # Almacenar el índice para uso posterior
        user_data[chat_id]['indice_franja'] = indice
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_dia_"))
    def handle_edit_dia(call):
        """Maneja la edición del día de una franja"""
        chat_id = call.message.chat.id
        indice = int(call.data.split("_")[2])
        nuevo_dia = call.data.split("_")[3]
        
        # Recuperar franjas guardadas
        franjas = user_data[chat_id].get('franjas', [])
        
        if indice >= len(franjas):
            bot.answer_callback_query(call.id, "❌ Error: Franja no encontrada")
            return
        
        # Modificar el día de la franja
        franjas[indice] = f"{nuevo_dia} " + franjas[indice][len(franjas[indice].split()[0]):]
        
        # Guardar cambios temporales
        user_data[chat_id]['franjas'] = franjas
        
        # Confirmar y mostrar opciones de horario
        handle_editar_franja(call)
        bot.answer_callback_query(call.id, "✅ Día actualizado. Ahora selecciona las horas.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("edit_horas_"))
    def handle_edit_horas(call):
        """Maneja la edición de las horas de una franja"""
        chat_id = call.message.chat.id
        indice = int(call.data.split("_")[2])
        
        # Recuperar franjas guardadas
        franjas = user_data[chat_id].get('franjas', [])
        
        if indice >= len(franjas):
            bot.answer_callback_query(call.id, "❌ Error: Franja no encontrada")
            return
        
        franja_actual = franjas[indice]
        
        # Extraer día de la franja actual
        dia = franja_actual.split()[0]
        
        # Sugerir franjas horarias comunes
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        franjas_comunes = [
            "09:00-11:00", "11:00-13:00", "13:00-15:00", 
            "15:00-17:00", "17:00-19:00", "19:00-21:00"
        ]
        markup.add(*[telebot.types.KeyboardButton(franja) for franja in franjas_comunes])
        markup.row(telebot.types.KeyboardButton("🔙 Cancelar"))
        
        bot.send_message(
            chat_id,
            f"⏰ Estás editando las horas de la franja: *{franja_actual}*\n\n"
            "Selecciona una opción predefinida o escribe tu propia franja en formato HH:MM-HH:MM\n"
            "Ejemplo: 09:00-11:30\n\n"
            "👉 Introduce una sola franja por vez",
            parse_mode="Markdown",
            reply_markup=markup
        )
        
        set_state(chat_id, "introducir_horas_modificadas")
        estados_timestamp[chat_id] = time.time()
        
        bot.answer_callback_query(call.id)

    @bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "introducir_horas_modificadas")
    def handle_horas_modificadas(message):
        """Procesa la modificación de las horas de una franja"""
        chat_id = message.chat.id
        texto = message.text.strip()
        
        if texto == "🔙 Cancelar":
            # Volver al menú de modificación de franjas
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=message.chat,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = "modificar_horario"
            handle_modificar_horario(msg)
            return
        
        # Validar formato de la franja horaria
        if not re.match(r'^\d{1,2}:\d{2}-\d{1,2}:\d{2}$', texto):
            bot.send_message(
                chat_id,
                "⚠️ Formato incorrecto. Usa el formato HH:MM-HH:MM\n"
                "Ejemplo: 09:00-11:30"
            )
            return
            
        try:
            # Validar horas y minutos
            inicio, fin = texto.split("-")
            hora_inicio, min_inicio = map(int, inicio.split(":"))
            hora_fin, min_fin = map(int, fin.split(":"))
            
            if not (0 <= hora_inicio <= 23 and 0 <= min_inicio <= 59):
                bot.send_message(chat_id, f"⚠️ Hora de inicio inválida: {inicio}")
                return
                
            if not (0 <= hora_fin <= 23 and 0 <= min_fin <= 59):
                bot.send_message(chat_id, f"⚠️ Hora de fin inválida: {fin}")
                return
                
            if (hora_inicio > hora_fin) or (hora_inicio == hora_fin and min_inicio >= min_fin):
                bot.send_message(chat_id, "⚠️ La hora de fin debe ser posterior a la hora de inicio")
                return
                
            # Formatear para guardar
            franja_formateada = f"{hora_inicio:02d}:{min_inicio:02d}-{hora_fin:02d}:{min_fin:02d}"
        
            # Recuperar índice de la franja
            indice = user_data[chat_id].get('indice_franja')
        
            # Obtener información de la franja que se está modificando
            franjas = user_data[chat_id]["franjas"]
            dia = franjas[indice].split()[0]  # Obtener el día de la franja existente
        
            # NUEVA VALIDACIÓN: Comprobar si ya existe esta franja para este día
            # Pero excluir la franja actual que estamos editando
            franja_actual = franjas[indice]
            horas_actuales = franja_actual[len(dia)+1:] if len(franja_actual) > len(dia) else ""
        
            # Verificar si la franja ya existe en otro índice
            for i, fr in enumerate(franjas):
                if i != indice and fr.startswith(dia) and fr[len(dia)+1:] == franja_formateada:
                    bot.send_message(
                        chat_id,
                        f"⚠️ Ya tienes configurada la franja {franja_formateada} para {dia}.\n"
                        "Por favor, introduce una franja horaria diferente."
                    )
                    return
        
            # Si llegamos aquí, la franja no es duplicada o se está editando la misma
            # Actualizar la franja completa
            franjas[indice] = f"{dia} {franja_formateada}"
        
            # Guardar cambios
            user_data[chat_id]["franjas"] = franjas
        
            # Confirmar y volver al menú de gestión
            bot.send_message(
                chat_id,
                f"✅ Horas modificadas:\n"
                f"Nueva franja: {franja_formateada}"
            )
        
            # Simular la selección del día para mostrar el menú actualizado
            msg = types.Message(
                message_id=0,
                from_user=message.from_user,
                date=datetime.datetime.now(),
                chat=message.chat,
                content_type='text',
                options={},
                json_string="{}"
            )
            msg.text = dia
            handle_seleccion_dia(msg)
        
        except ValueError as e:
            bot.send_message(
                chat_id,
                f"⚠️ Error en el formato: {str(e)}\n"
                "Usa el formato HH:MM-HH:MM"
            )

    @bot.callback_query_handler(func=lambda call: call.data == "volver_menu_horario")
    def handle_volver_menu_horario(call):
        """Vuelve al menú principal de horarios"""
        chat_id = call.message.chat.id
        
        # Crear mensaje tipo para reutilizar el handler existente
        mensaje = types.Message(
            message_id=call.message.message_id,
            from_user=call.from_user,
            date=call.message.date,
            chat=call.message.chat,
            content_type="text",
            options={},
            json_string=""
        )
        mensaje.text = "/configurar_horario"
        
        # Llamar al handler de configuración de horario
        handle_configurar_horario(mensaje)
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == "volver_menu_principal")
    def handle_volver_menu_principal(call):
        """Vuelve al menú principal del bot"""
        chat_id = call.message.chat.id
        
        try:
            # Eliminar mensaje actual
            bot.delete_message(chat_id, call.message.message_id)
        except Exception as e:
            print(f"Error al eliminar mensaje: {e}")
        
        # Enviar mensaje de bienvenida
        bot.send_message(
            chat_id,
            "👋 *Bienvenido de nuevo al menú principal*\n\n"
            "Puedes usar los comandos del menú explicados en el comando /help.",
            parse_mode="Markdown"
        )
        
        # Limpiar estados y datos
        if chat_id in user_states:
            user_states.pop(chat_id)
            
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data == "confirmar_horario")
    def handle_confirmar_horario(call):
        """Confirma el horario configurado"""
        chat_id = call.message.chat.id
        user = get_user_by_telegram_id(call.from_user.id)
        
        if not user:
            bot.answer_callback_query(call.id, "❌ No estás registrado")
            return
        
        user_dict = dict(user)
        horario_actual = user_dict.get('Horario', '')
        
        if not horario_actual:
            bot.answer_callback_query(call.id, "⚠️ No hay horario para confirmar")
            return
        
        # Mostrar mensaje de confirmación
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("✏️ Modificar horario", callback_data="modificar_horario"),
            types.InlineKeyboardButton("↩️ Volver al menú", callback_data="volver_menu_principal")
        )
        
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"✅ *¡Horario confirmado correctamente!*\n\n"
                     f"Tu horario de tutorías:\n{horario_actual}\n\n"
                     f"Los estudiantes ya pueden ver este horario cuando soliciten tutorías.",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Error al editar mensaje: {e}")
            bot.send_message(
                chat_id,
                f"✅ *¡Horario confirmado correctamente!*\n\n"
                f"Tu horario de tutorías:\n{horario_actual}\n\n"
                f"Los estudiantes ya pueden ver este horario cuando soliciten tutorías.",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        
        # Limpiar estados de configuración
        if chat_id in user_states:
            user_states[chat_id] = "horario_confirmado"
    
        bot.answer_callback_query(call.id, "✅ Horario confirmado")

# Si esta función está en utils/horarios_utils.py, verificar que sea robusta
def parsear_horario_string(horario_str):
    """Parsea el string de horario a un diccionario estructurado"""
    print(f"DEBUG - parsear_horario_string - input: '{horario_str}'")
    resultado = {}
    
    if not horario_str or horario_str.strip() == "":
        return resultado
        
    # Dividir por comas y procesar cada franja
    franjas = [f.strip() for f in horario_str.split(',') if f.strip()]
    
    for franja in franjas:
        partes = franja.split(maxsplit=1)
        if len(partes) >= 2:
            dia = partes[0]
            horas = partes[1]
            
            if dia not in resultado:
                resultado[dia] = []
                
            resultado[dia].append(horas)
    
    print(f"DEBUG - parsear_horario_string - resultado: {resultado}")
    return resultado