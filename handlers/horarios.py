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
    # Esta función ya está definida anteriormente
    
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
                exito = update_user(usuario['Id_usuario'], Horario=horario_str)
                
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
            # Obtener usuario directamente de la BD
            conn = get_db_connection()
            cursor = conn.cursor()
    
            cursor.execute(
                "SELECT Horario FROM Usuarios WHERE TelegramID = ?",
                (message.from_user.id,)
            )
    
            resultado = cursor.fetchone()
            conn.close()
    
            if resultado and resultado['Horario']:
                # El horario existe en la BD
                horario_guardado = resultado['Horario']
                bot.send_message(
                    chat_id,
                    f"📅 *Tu horario completo:*\n\n{horario_guardado}\n\n"
                    "Para modificarlo, selecciona un día específico.",
                    parse_mode="Markdown"
                )
            else:
                # No hay horario guardado
                bot.send_message(
                    chat_id, 
                    "❓ No tienes horario configurado aún. Selecciona un día para comenzar a añadir franjas."
                )
    
            # Mantener en el mismo estado para seguir configurando
            return
            
        # Procesar selección de día
        if seleccion in dias_validos:
            # Guardar el día seleccionado
            user_data[chat_id]["dia_actual"] = seleccion
            
            # Obtener usuario actual
            user = get_user_by_telegram_id(message.from_user.id)
            
            # Obtener franjas ya existentes para este día
            conn = get_db_connection()
            cursor = conn.cursor()

            # Obtener el horario desde la tabla Usuarios
            cursor.execute(
                "SELECT Horario FROM Usuarios WHERE Id_usuario = ?", 
                (user['Id_usuario'],)
            )
            resultado = cursor.fetchone()

            # Procesar el horario almacenado como texto
            horario_texto = resultado['Horario'] if resultado and resultado['Horario'] else ""
            franjas_existentes = []

            # Si hay horario, buscar las franjas del día seleccionado
            if horario_texto:
                # Suponiendo que el formato es "Lunes: 10:00-12:00, Martes: 16:00-18:00"
                import re
                
                # Buscar el patrón del día seleccionado - MÁS ROBUSTO
                patron = re.compile(f"{seleccion.lower()} (\\d+:\\d+-\\d+:\\d+)")
                coincidencia = patron.search(horario_texto)
                
                if coincidencia:
                    franjas_dia = coincidencia.group(1).strip()
                    for franja in franjas_dia.split(";"):
                        if "-" in franja:
                            inicio, fin = franja.split("-")
                            franjas_existentes.append({
                                'dia': seleccion,
                                'hora_inicio': inicio.strip(),
                                'hora_fin': fin.strip(),
                                'lugar': "No especificado"
                            })
            
            conn.close()

            if franjas_existentes and len(franjas_existentes) > 0:
                # Hay franjas para este día
                mensaje = f"📅 *Franjas horarias para {seleccion}:*\n\n"
                
                for i, franja in enumerate(franjas_existentes, 1):
                    # Formatear la hora para mejor visualización
                    inicio = franja['hora_inicio']
                    fin = franja['hora_fin']
                    lugar = franja['lugar'] or "No especificado"
                    
                    mensaje += f"{i}. De *{inicio}* a *{fin}*\n   📍 {lugar}\n\n"
                
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
            # Guardar cambios solo para este día
            try:
                # Convertir el horario a formato de string
                horario_str = convertir_horario_a_string(user_data[chat_id]["horario"])
                
                # Obtener ID del usuario
                usuario = get_user_by_telegram_id(chat_id)
                
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
            
            # Añadir a horario existente
            horario_actual = get_user_property(user, 'Horario', '')
            
            if horario_actual:
                # Verificar si ya existe esta franja
                franjas = [f.strip() for f in horario_actual.split(',')]
                if franja in franjas:
                    bot.answer_callback_query(call.id, "⚠️ Esta franja ya existe en tu horario")
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
        horario_actual = get_user_property(user, 'Horario', '')
        
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
        horario = get_user_property(user, 'Horario', '')
        
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
        horario = get_user_property(user, 'Horario', '')
        
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
        
        # Convertir a diccionario
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
        
        # Guardar índice para uso posterior
        user_data[chat_id]['indice_franja'] = indice
        
        # Mostrar diálogo para editar
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=f"✏️ *Modificar franja*\n\n"
                 f"Franja actual: *{franja_actual}*\n\n"
                 f"Introduce la nueva franja en formato:\n"
                 f"Día HH:MM-HH:MM\n\n"
                 f"Ejemplo: Lunes 10:30-12:45",
            parse_mode="Markdown"
        )
        
        user_states[chat_id] = "introduciendo_franja_modificada"
        bot.answer_callback_query(call.id)

    @bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "introduciendo_franja_modificada")
    def handle_franja_modificada(message):
        """Procesa la modificación de una franja"""
        chat_id = message.chat.id
        user = get_user_by_telegram_id(message.from_user.id)
        nueva_franja = message.text.strip()
        
        # Validar formato
        import re
        if not re.match(r'^[A-Za-záéíóúÁÉÍÓÚ]+ \d{1,2}:\d{2}-\d{1,2}:\d{2}$', nueva_franja):
            bot.send_message(
                chat_id,
                "⚠️ Formato incorrecto. Debe ser: Día HH:MM-HH:MM\n"
                "Por ejemplo: Lunes 10:30-12:45\n\n"
                "Inténtalo de nuevo:"
            )
            return
        
        # Recuperar datos
        franjas = user_data[chat_id].get('franjas', [])
        indice = user_data[chat_id].get('indice_franja')
        
        if indice is None or indice >= len(franjas):
            bot.send_message(chat_id, "❌ Error al modificar la franja. Inténtalo de nuevo.")
            user_states[chat_id] = None
            return
        
        # Verificar si ya existe esta franja (excepto la que estamos modificando)
        franja_duplicada = False
        for i, f in enumerate(franjas):
            if i != indice and f.lower() == nueva_franja.lower():
                franja_duplicada = True
                break
        
        if franja_duplicada:
            bot.send_message(
                chat_id,
                "⚠️ Esta franja ya existe en tu horario. Por favor, introduce una franja diferente:"
            )
            return
        
        # Actualizar la franja
        antigua_franja = franjas[indice]
        franjas[indice] = nueva_franja
        
        # Guardar en la base de datos
        horario_actualizado = ", ".join(franjas)
        success = update_user(user['Id_usuario'], Horario=horario_actualizado)
        
        if success:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("✏️ Modificar otra franja", callback_data="modificar_horario"),
                types.InlineKeyboardButton("📋 Ver mi horario", callback_data="volver_menu_horario")
            )
            
            bot.send_message(
                chat_id,
                f"✅ *¡Franja modificada!*\n\n"
                f"Antigua: {antigua_franja}\n"
                f"Nueva: {nueva_franja}\n\n"
                f"Tu horario actualizado:\n{horario_actualizado}",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                chat_id,
                "❌ Error al guardar los cambios. Inténtalo de nuevo."
            )
        
        # Limpiar estado
        user_states[chat_id] = None

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

def get_user_property(user, property_name, default=None):
    """Obtiene una propiedad de un usuario de forma segura"""
    if user is None:
        return default
    
    # Convertir a diccionario si es necesario
    user_dict = dict(user) if hasattr(user, 'keys') else user
    
    # Obtener la propiedad
    return user_dict.get(property_name, default)