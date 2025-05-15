import telebot
from telebot import types
import re
import sys
import os
import time
import random
import logging
from datetime import datetime
from email.message import EmailMessage
import smtplib
from pathlib import Path

# Añadir directorio raíz al path para resolver importaciones
sys.path.append(str(Path(__file__).parent.parent))

# Añadir directorio padre al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importar módulos necesarios
from utils.excel_manager import buscar_usuario_por_email, cargar_excel, verificar_email_en_excel, importar_datos_por_email
import pandas as pd
from db.queries import (
    get_user_by_telegram_id, 
    create_user, 
    matricular_usuario,
    get_db_connection,
    update_user_telegram_id,
    update_user,
    get_o_crear_carrera,
    crear_matricula
)

# Añadir al inicio del archivo
from utils.state_manager import get_state, set_state, clear_state, user_data, user_states

# Referencias externas necesarias
user_states = {}
user_data = {}
estados_timestamp = {}

# Variables para seguridad de token
token_intentos_fallidos = {}  # {chat_id: número de intentos}
token_bloqueados = {}  # {chat_id: tiempo de desbloqueo}
token_usados = set()  # Conjunto de tokens ya utilizados

# Estados del proceso de registro
STATE_EMAIL = "registro_email"
STATE_VERIFY_TOKEN = "registro_verificacion"
STATE_CONFIRMAR_DATOS = "confirmando_datos_excel"

# Configurar logger
logger = logging.getLogger("registro")
if not logger.handlers:
    handler = logging.FileHandler("registro.log")
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def register_handlers(bot):
    """Registra todos los handlers del proceso de registro"""
    
    def get_state(chat_id):
        """Obtiene el estado actual del usuario de forma segura"""
        return user_states.get(chat_id, 'INICIO')  # 'INICIO' es el estado predeterminado
    
    def set_state(chat_id, state):
        """Establece el estado del usuario y actualiza el timestamp"""
        user_states[chat_id] = state
        estados_timestamp[chat_id] = time.time()
    
    def reset_user(chat_id):
        """Reinicia el estado y datos del usuario"""
        if chat_id in user_states:
            del user_states[chat_id]
        if chat_id in user_data:
            del user_data[chat_id]
        if chat_id in estados_timestamp:
            del estados_timestamp[chat_id]
    
    def is_user_registered(chat_id):
        """Verifica si el usuario ya está registrado"""
        user = get_user_by_telegram_id(chat_id)
        return user is not None
    
    def send_verification_email(email, token):
        """Envía un correo electrónico con el token de verificación"""
        # Cargar credenciales sin valores predeterminados para datos sensibles
        smtp_server = os.getenv("SMTP_SERVER")
        sender_email = os.getenv("SMTP_EMAIL")
        password = os.getenv("SMTP_PASSWORD")
        
        # Verificar todas las credenciales necesarias
        if not all([smtp_server, sender_email, password]):
            missing = []
            if not smtp_server: missing.append("SMTP_SERVER")
            if not sender_email: missing.append("SMTP_EMAIL")  
            if not password: missing.append("SMTP_PASSWORD")
            logger.error(f"Faltan credenciales en datos.env.txt: {', '.join(missing)}")
            return False
        
        msg = EmailMessage()
        msg["From"] = sender_email
        msg["To"] = email
        msg["Subject"] = "Token tutorChatBot"
        
        # Create a more attractive HTML email
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #0066cc; color: white; padding: 15px; text-align: center; border-radius: 5px 5px 0 0;">
                <h2>Verificación de Asistente de Tutorías</h2>
            </div>
            <div style="padding: 20px; border: 1px solid #ddd; border-top: none; border-radius: 0 0 5px 5px;">
                <p>Hola,</p>
                <p>Gracias por registrarte en el <strong>Asistente de Tutorías</strong>. Para completar tu registro, utiliza el siguiente código de verificación:</p>
                <div style="background-color: #f5f5f5; padding: 15px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 5px; margin: 20px 0; border-radius: 5px;">
                    {token}
                </div>
                <p>Este código es válido durante <strong>3 minutos</strong>. Si no has solicitado este código, puedes ignorar este correo.</p>
                <p>Saludos,<br>El equipo del Asistente de Tutorías</p>
            </div>
            <div style="text-align: center; font-size: 12px; color: #777; margin-top: 20px;">
                <p>Este es un correo automático, por favor no respondas a este mensaje.</p>
            </div>
        </body>
        </html>
        """
        msg.set_content("Tu código de verificación es: " + token)
        msg.add_alternative(html_content, subtype='html')

        try:
            with smtplib.SMTP(str(smtp_server), 587) as server:
                server.ehlo()
                server.starttls()
                # Add explicit type assertion since we've already validated these aren't None
                server.login(str(sender_email), str(password))
                server.send_message(msg)
            
            # También registramos el token en el log/consola para desarrollo
            logger.info(f"TOKEN DE VERIFICACIÓN enviado a {email}: {token}")
            print(f"TOKEN DE VERIFICACIÓN enviado a {email}: {token}")
            return True
        except Exception as e:
            logger.error(f"Error en el envío del correo a {email}: {e}")
            print(f"Error en el envío del correo: {e}")
            return False

    def is_valid_email(email):
        """Verifica si el correo es válido (institucional UGR)"""
        return re.match(r'.+@(correo\.)?ugr\.es$', email) is not None
    
    def is_email_registered(email):
        """Verifica si el correo ya está registrado en la base de datos"""
        # Implementar según tu estructura de base de datos
        # Por ahora siempre devuelve False
        return False
    
    def completar_registro(chat_id):
        """Completa el registro del usuario"""
        try:
            # Crear usuario
            user_id = create_user(
                nombre=user_data[chat_id]['nombre'],
                apellidos=user_data[chat_id]['apellidos'],
                tipo=user_data[chat_id]['tipo'],
                email=user_data[chat_id]['email'],
                telegram_id=chat_id,
                dni=user_data[chat_id].get('dni', '')
            )
            
            # Actualizar el campo carrera en la tabla usuarios
            update_user(user_id, Carrera=user_data[chat_id].get('carrera', ''))
            
            # Obtener o crear la carrera en la tabla Carreras
            carrera_id = get_o_crear_carrera(user_data[chat_id].get('carrera', 'General'))
            
            # Para estudiantes, crear matrículas
            if user_data[chat_id]['tipo'] == 'estudiante':
                for asignatura_id in user_data[chat_id].get('asignaturas_seleccionadas', []):
                    crear_matricula(user_id, asignatura_id)
                    # Asegurarse de que la asignatura esté asociada a la carrera
                    cursor = get_db_connection().cursor()
                    cursor.execute("UPDATE Asignaturas SET Id_carrera = ? WHERE Id_asignatura = ? AND Id_carrera IS NULL", 
                                  (carrera_id, asignatura_id))
                    cursor.connection.commit()
                    cursor.connection.close()
                    
            # Para profesores, crear asignaturas impartidas
            elif user_data[chat_id]['tipo'] == 'profesor':
                for asignatura_id in user_data[chat_id].get('asignaturas_seleccionadas', []):
                    crear_matricula(user_id, asignatura_id, 'profesor')
                    # Asegurarse de que la asignatura esté asociada a la carrera
                    cursor = get_db_connection().cursor()
                    cursor.execute("UPDATE Asignaturas SET Id_carrera = ? WHERE Id_asignatura = ? AND Id_carrera IS NULL", 
                                  (carrera_id, asignatura_id))
                    cursor.connection.commit()
                    cursor.connection.close()
                    
            # Resto del código de completar_registro...
        except Exception as e:
            logger.error(f"Error al completar registro: {e}")
            bot.send_message(chat_id, "❌ Error al completar el registro. Por favor, intenta de nuevo con /start.")
            return False

    def solicitar_carrera(chat_id):
        """Solicita al estudiante que seleccione su carrera"""
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        # Agregar carreras comunes como opciones rápidas
        markup.add("Ingeniería Informática", "Matemáticas")
        markup.add("Física", "Química")
        markup.add("Medicina", "Enfermería")
        markup.add("Derecho", "Economía")
        markup.add("Otra")
        
        bot.send_message(
            chat_id,
            "📚 Por favor, indica la carrera que estás cursando:",
            reply_markup=markup
        )
        
        # Establecer el estado para manejar la respuesta
        user_states[chat_id] = "esperando_carrera"
        estados_timestamp[chat_id] = time.time()
    
    @bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "esperando_carrera")
    def handle_carrera(message):
        """Procesa la selección de carrera del estudiante"""
        chat_id = message.chat.id
        carrera = message.text.strip()
        
        # Guardar la carrera seleccionada
        user_data[chat_id]['carrera'] = carrera
        
        bot.send_message(
            chat_id,
            f"✅ Has seleccionado: {carrera}\n\nCompletando registro...",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        
        # Continuar con el proceso de registro
        completar_registro(chat_id)
        
    @bot.message_handler(commands=["start"])
    def handle_start(message):
        """Inicia el proceso de registro simplificado"""
        chat_id = message.chat.id

        # Verifica si el usuario ya está registrado
        if is_user_registered(chat_id):
            bot.send_message(chat_id, "Ya estás registrado. Puedes usar las funcionalidades disponibles.")
            reset_user(chat_id)
            return

        # Inicia el proceso simplificado pidiendo solo el correo
        bot.send_message(
            chat_id, 
            "🤖 *¡Bienvenido al Asistente de Tutorías UGR!* 🎓\n\n"
            "Este bot te permite acceder a tutorías académicas con profesores y estudiantes "
            "de forma sencilla y organizada.\n\n"
            "Para comenzar, necesito verificar tu cuenta institucional.\n\n"
            "Por favor, introduce tu correo electrónico de la UGR:\n"
            "• Estudiantes: usuario@correo.ugr.es\n"
            "• Profesores: usuario@ugr.es",
            parse_mode="Markdown"
        )
        user_states[chat_id] = STATE_EMAIL
        user_data[chat_id] = {}  # Reinicia los datos del usuario
        estados_timestamp[chat_id] = time.time()

    @bot.message_handler(func=lambda message: user_states.get(message.chat.id) == STATE_EMAIL)
    def handle_email(message):
        """Procesa el correo electrónico y envía código de verificación"""
        chat_id = message.chat.id
        text = message.text.strip()
        
        # Comprobar si está bloqueado
        if chat_id in token_bloqueados:
            if time.time() < token_bloqueados[chat_id]:
                tiempo_restante = int((token_bloqueados[chat_id] - time.time()) / 60)
                bot.send_message(
                    chat_id,
                    f"⛔ Tu cuenta está bloqueada temporalmente.\n"
                    f"Debes esperar {tiempo_restante} minutos antes de intentarlo de nuevo.",
                    reply_markup=telebot.types.ReplyKeyboardRemove()
                )
                return
            else:
                # Ya pasó el tiempo de bloqueo
                del token_bloqueados[chat_id]
                if chat_id in token_intentos_fallidos:
                    del token_intentos_fallidos[chat_id]
        
        # Validar el email
        email = text.lower()
        
        if not is_valid_email(email):
            bot.send_message(
                chat_id, 
                "⚠️ El correo debe ser institucional (@ugr.es o @correo.ugr.es).\n"
                "Por favor, introduce un correo válido:"
            )
            return
        
        if is_email_registered(email):
            bot.send_message(
                chat_id, 
                "⚠️ Este correo ya está registrado. Si ya tienes cuenta, usa los comandos disponibles.\n"
                "Si necesitas ayuda, contacta con soporte."
            )
            reset_user(chat_id)
            return
        
        # Guardar el email
        user_data[chat_id]["email"] = email
        
        # Generar token seguro de 6 dígitos
        token = str(random.randint(100000, 999999))
        user_data[chat_id]["token"] = token
        user_data[chat_id]["token_expiry"] = time.time() + 180  # Token válido por 3 minutos
        
        # Determinar tipo de usuario por el correo
        es_estudiante = email.endswith("@correo.ugr.es")
        user_data[chat_id]["tipo"] = "estudiante" if es_estudiante else "profesor"
        
        # Simular envío de token
        if send_verification_email(email, token):
            # Botón para cancelar
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("❌ Cancelar", callback_data="cancelar_registro"))
            
            bot.send_message(
                chat_id, 
                "🔑 *Verificación de Cuenta*\n\n"
                "Se ha enviado un código de 6 dígitos a tu correo.\n"
                "Por favor, introduce el código que has recibido.\n\n"
                "⏱️ *El código expirará en 3 minutos*\n\n"
                "_Si no lo recibes, verifica tu carpeta de spam._",
                parse_mode="Markdown",
                reply_markup=markup
            )
            user_states[chat_id] = STATE_VERIFY_TOKEN
            estados_timestamp[chat_id] = time.time()
        else:
            bot.send_message(
                chat_id, 
                "❌ *Error al enviar el código de verificación*\n\n"
                "No ha sido posible enviar el email con tu código.\n"
                "Por favor, intenta nuevamente más tarde o contacta con soporte.\n\n"
                "_Para desarrollo: revisa los logs y la configuración SMTP._",
                parse_mode="Markdown"
            )
            reset_user(chat_id)

    @bot.callback_query_handler(func=lambda call: call.data == "cancelar_registro")
    def handle_cancelar_registro(call):
        """Cancela el proceso de registro"""
        chat_id = call.message.chat.id
        
        bot.send_message(
            chat_id, 
            "Registro cancelado. Puedes iniciarlo nuevamente con /start cuando lo desees.",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        reset_user(chat_id)
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: user_states.get(call.message.chat.id) == STATE_CONFIRMAR_DATOS and call.data == "confirmar_datos_excel")
    def handle_confirmar_datos_excel(call):
        """Completa el registro con los datos del Excel"""
        chat_id = call.message.chat.id
        telegram_id = call.from_user.id
        
        try:
            completar_registro(chat_id)
            
            # Mensaje final según tipo de usuario
            tipo_usuario = "estudiante" if user_data[chat_id]["tipo"] == "estudiante" else "profesor"
            nombre = f"{user_data[chat_id]['nombre']} {user_data[chat_id]['apellidos']}"
            asignaturas = ", ".join(user_data[chat_id]["asignaturas"])
            
            bot.send_message(
                chat_id,
                f"✅ *¡Registro completado correctamente!*\n\n"
                f"Te has registrado como {tipo_usuario}.\n\n"
                f"*Nombre:* {nombre}\n"
                f"*Email:* {user_data[chat_id]['email']}\n"
                f"*Asignaturas:* {asignaturas}",
                parse_mode="Markdown"
            )
            
            if user_data[chat_id]["tipo"] == "estudiante":
                mensaje = (
                    f"📚 *Comandos disponibles:*\n"
                    f"• /help - Ver todos los comandos disponibles\n"
                    f"• /profesores - Ver profesores de tus asignaturas\n"
                    f"• /horarios - Ver horarios de tutorías"
                )
            else:  # Si es profesor
                mensaje = (
                    f"🔔 *Tu próximo paso:*\n"
                    f"Debes crear un grupo de tutoría para cada asignatura que impartes.\n"
                    f"Utiliza el comando /crear_grupo para configurar tus grupos.\n\n"
                    f"📚 *Otros comandos disponibles:*\n"
                    f"• /help - Ver todos los comandos disponibles\n"
                    f"• /configurar_horario - Modificar tu horario de tutorías\n"
                    f"• /mis_tutorias - Ver tus grupos de tutoría activos"
                )
            
            bot.send_message(
                chat_id,
                mensaje,
                parse_mode="Markdown",
                reply_markup=telebot.types.ReplyKeyboardRemove()
            )
            
            # Limpiar estados
            reset_user(chat_id)
            logger.info(f"Usuario registrado desde Excel: {user_data[chat_id]['nombre']} {user_data[chat_id]['apellidos']} ({telegram_id})")
            
        except Exception as e:
            logger.error(f"Error al registrar usuario desde Excel: {str(e)}")
            
            bot.send_message(
                chat_id,
                f"❌ Error al completar el registro: {str(e)}\n"
                f"Por favor, contacta con soporte.",
                parse_mode="Markdown"
            )
            reset_user(chat_id)
        
        bot.answer_callback_query(call.id)

    # Comando para recargar datos del Excel (solo para administradores)
    @bot.message_handler(commands=["reload_excel"])
    def handle_reload_excel(message):
        """Recarga los datos del Excel (solo para admins)"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Lista de administradores (puedes moverla a una configuración)
        admin_ids = [123456789]  # Reemplaza con tu ID de Telegram
        
        if user_id not in admin_ids:
            bot.reply_to(message, "❌ No tienes permisos para ejecutar este comando.")
            return
        
        # Intentar recargar el Excel
        success = cargar_excel()
        
        if success:
            bot.reply_to(message, "✅ Datos de Excel recargados correctamente.")
        else:
            bot.reply_to(message, "❌ Error al recargar los datos del Excel. Revisa los logs.")

    # Manejador para cancelar registro con comando
    @bot.message_handler(commands=["cancelar"])
    def handle_cancelar_command(message):
        """Cancela el registro en curso"""
        chat_id = message.chat.id
        
        if chat_id in user_states:
            bot.send_message(
                chat_id, 
                "Registro cancelado. Puedes iniciarlo nuevamente con /start cuando lo desees.",
                reply_markup=telebot.types.ReplyKeyboardRemove()
            )
            reset_user(chat_id)
        else:
            bot.send_message(chat_id, "No hay ningún registro en curso para cancelar.")