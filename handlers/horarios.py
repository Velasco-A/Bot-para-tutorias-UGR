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
from db.queries import get_user_by_telegram_id, get_db_connection, update_horario_profesor, get_horarios_profesor
from utils.horarios_utils import parsear_horario_string, convertir_horario_a_string, formatear_horario
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

def register_handlers(bot):
    """Registra todos los handlers relacionados con horarios de tutorías"""
    
    def obtener_horario_actual(user_id):
        """Obtiene el horario actual del profesor desde la base de datos"""
        try:
            # Obtener datos del usuario
            usuario = get_user_by_telegram_id(user_id)
            if not usuario or usuario['Tipo'] != 'profesor':
                return None
            
            # Usar la función existente en queries.py
            horarios = get_horarios_profesor(usuario['Id_usuario'])
            if horarios and 'horario_formateado' in horarios[0]:
                return horarios[0]['horario_formateado']
            return ""
        except Exception as e:
            logger.error(f"Error al obtener horario: {e}")
            return None
    
    @bot.message_handler(commands=["configurar_horario"])
    def configurar_horario(message):
        """Función para configurar horarios de tutoría"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar si el usuario es profesor
        usuario = get_user_by_telegram_id(user_id)
        if not usuario or usuario['Tipo'] != 'profesor':
            bot.send_message(chat_id, "⚠️ Este comando es solo para profesores.")
            return
            
        # Inicializar datos si es necesario
        if chat_id not in user_data:
            user_data[chat_id] = {}
        
        # Obtener horario actual
        horario_actual = obtener_horario_actual(user_id)
        
        if horario_actual is not None:
            # Mostrar horario actual formateado
            if horario_actual:
                bot.send_message(
                    chat_id,
                    f"📅 *Tu horario actual:*\n\n{formatear_horario(horario_actual)}",
                    parse_mode="Markdown"
                )
        else:
            bot.send_message(
                chat_id,
                "❌ Error al recuperar tu horario. Por favor, inténtalo más tarde."
            )
            return
        
        # Mostrar selector de días
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        markup.add(*[telebot.types.KeyboardButton(dia) for dia in dias])
        markup.row(telebot.types.KeyboardButton("Ver horario completo"))
        markup.row(
            telebot.types.KeyboardButton("💾 Confirmar horario"), 
            telebot.types.KeyboardButton("❌ Cancelar")
        )
        
        bot.send_message(
            chat_id,
            "🕒 *Configuración de horario*\n\n"
            "Selecciona el día que deseas configurar o confirma el horario cuando hayas terminado:",
            parse_mode="Markdown",
            reply_markup=markup
        )
        
        # Parsear el horario existente para tenerlo disponible
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
        
        # Manejar confirmación del horario
        if seleccion == "💾 Confirmar horario":
            try:
                # Convertir el horario a formato de string
                horario_str = convertir_horario_a_string(user_data[chat_id]["horario"])
                
                # Obtener ID del usuario
                usuario = get_user_by_telegram_id(chat_id)
                
                # Guardar en la base de datos
                exito = update_horario_profesor(usuario['Id_usuario'], horario_str)
                
                if exito:
                    # Confirmar al usuario
                    bot.send_message(
                        chat_id,
                        "✅ *Horario guardado correctamente*\n\n"
                        "Tu horario de tutorías ha sido actualizado.",
                        parse_mode="Markdown",
                        reply_markup=telebot.types.ReplyKeyboardRemove()
                    )
                    
                    # Mostrar el horario guardado
                    bot.send_message(
                        chat_id,
                        f"📅 *Tu horario actualizado:*\n\n{formatear_horario(horario_str)}",
                        parse_mode="Markdown"
                    )
                else:
                    bot.send_message(
                        chat_id,
                        "❌ Error al guardar el horario en la base de datos.",
                        reply_markup=telebot.types.ReplyKeyboardRemove()
                    )
                
                clear_state(chat_id)
                return
                
            except Exception as e:
                bot.send_message(
                    chat_id,
                    f"❌ Error al guardar el horario: {str(e)}",
                    reply_markup=telebot.types.ReplyKeyboardRemove()
                )
                clear_state(chat_id)
                return
            
        # Ver horario completo
        if seleccion == "Ver horario completo":
            # Convertir el horario actual a string y mostrarlo
            horario_str = convertir_horario_a_string(user_data[chat_id]["horario"])
            if horario_str:
                bot.send_message(
                    chat_id,
                    f"📅 *Tu horario completo:*\n\n{formatear_horario(horario_str)}\n\n"
                    "Para modificarlo, selecciona un día específico.",
                    parse_mode="Markdown"
                )
            else:
                bot.send_message(chat_id, "No tienes horario configurado aún.")
                
            # Mantener en el mismo estado para seguir configurando
            return
            
        # Procesar selección de día
        if seleccion in dias_validos:
            # Guardar el día seleccionado
            user_data[chat_id]["dia_actual"] = seleccion
            
            # Mostrar franjas actuales para ese día si existen
            franjas_actuales = user_data[chat_id]["horario"].get(seleccion, [])
            
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
            
            if franjas_actuales:
                mensaje = f"🕒 *Franjas horarias para {seleccion}:*\n\n"
                for i, franja in enumerate(franjas_actuales, 1):
                    mensaje += f"{i}. {franja}\n"
                    
                # Opciones para modificar, añadir o eliminar
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
                mensaje = f"No hay franjas configuradas para {seleccion}."
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
            # Guardar cambios solo para este día
            try:
                # Convertir el horario a formato de string
                horario_str = convertir_horario_a_string(user_data[chat_id]["horario"])
                
                # Obtener ID del usuario
                usuario = get_user_by_telegram_id(chat_id)
                
                # Guardar en la base de datos
                exito = update_horario_profesor(usuario['Id_usuario'], horario_str)
                
                if exito:
                    # Confirmar al usuario
                    bot.send_message(
                        chat_id,
                        f"✅ *Cambios guardados*\n\n"
                        f"El horario para *{dia}* ha sido actualizado y guardado en la base de datos.",
                        parse_mode="Markdown"
                    )
                else:
                    bot.send_message(
                        chat_id,
                        "❌ Error al guardar el horario en la base de datos."
                    )
                
                # Mantener al usuario en la misma pantalla de gestión de franjas
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
                
            except Exception as e:
                bot.send_message(
                    chat_id,
                    f"❌ Error al guardar el horario: {str(e)}"
                )
        else:
            bot.send_message(chat_id, "Por favor, selecciona una opción válida.")

    # El resto de los handlers manteniendo la misma estructura pero usando set_state y clear_state
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
            
            # Añadir al horario
            if dia not in user_data[chat_id]["horario"]:
                user_data[chat_id]["horario"][dia] = []
                
            user_data[chat_id]["horario"][dia].append(franja_formateada)
            
            # Confirmar y añadir botones de acción específicos
            markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
            markup.add(
                telebot.types.KeyboardButton("➕ Añadir otra franja"),
                telebot.types.KeyboardButton("💾 Guardar cambios")
            )
            markup.add(telebot.types.KeyboardButton("🔙 Volver"))
            
            bot.send_message(
                chat_id,
                f"✅ Franja *{franja_formateada}* añadida a *{dia}*\n\n"
                "¿Qué deseas hacer ahora?",
                parse_mode="Markdown",
                reply_markup=markup
            )
            
            # Cambiar el estado para manejar la acción post-adición
            set_state(chat_id, "post_añadir_franja")
            estados_timestamp[chat_id] = time.time()
            
        except ValueError as e:
            bot.send_message(
                chat_id,
                f"⚠️ Error en el formato: {str(e)}\n"
                "Usa el formato HH:MM-HH:MM"
            )

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
                chat=message.chat,
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
                chat=message.chat,
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