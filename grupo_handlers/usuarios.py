"""
Manejadores específicos para la detección de estudiantes nuevos en grupos.
Este módulo se encarga exclusivamente de dar la bienvenida a estudiantes
cuando entran a un grupo donde está el bot.
"""
import telebot
from telebot import types
import traceback
import logging
import sqlite3
import os
import sys
from pathlib import Path

# Configuración de ruta para importar correctamente
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Ahora puedes importar desde db
from db.queries import get_db_connection

# Configurar logging
logger = logging.getLogger(__name__)

def register_student_handlers(bot):
    """
    Registra los handlers para gestionar nuevos estudiantes.
    """
    print("\n==================================================")
    print("👨‍🎓👨‍🎓👨‍🎓 REGISTRANDO HANDLER DE NUEVOS ESTUDIANTES 👨‍🎓👨‍🎓👨‍🎓")
    print("==================================================\n")

    # ID del bot para comparaciones
    BOT_ID = None
    try:
        BOT_ID = bot.get_me().id
        print(f"👾 ID del bot: {BOT_ID}")
    except Exception as e:
        print(f"No se pudo obtener ID del bot: {e}")

    # Middleware para logging (opcional - puedes dejarlo)
    @bot.middleware_handler(update_types=['message'])
    def log_new_members(bot_instance, update):
        """Middleware para registrar todos los eventos new_chat_members"""
        if hasattr(update, 'message') and hasattr(update.message, 'content_type') and update.message.content_type == 'new_chat_members':
            print(f"\n🔍 MIDDLEWARE: DETECTADO new_chat_members en chat {update.message.chat.id}")
            for member in update.message.new_chat_members:
                print(f"➡️ Nuevo miembro: {member.first_name} (ID: {member.id}, is_bot: {getattr(member, 'is_bot', 'N/A')})")

    # MANTÉN SOLO UNO DE LOS DOS HANDLERS:
    # Handler principal para new_chat_members
    @bot.message_handler(content_types=['new_chat_members'])
    def handle_new_student_in_group(message):
        """Handler principal para gestionar nuevos miembros en grupos"""
        try:
            chat_id = message.chat.id
            print(f"\n🎓 NUEVO MIEMBRO DETECTADO EN CHAT {chat_id}")
            
            for new_member in message.new_chat_members:
                user_id = new_member.id
                print(f"👤 Procesando: {new_member.first_name} (ID: {user_id})")
                
                # Ignorar si es el propio bot
                if user_id == BOT_ID:
                    print(f"🤖 Es el propio bot, ignorando")
                    continue

                # Obtener información del grupo
                conn = get_db_connection()
                cursor = conn.cursor()
                
                # Verificar si el grupo es un grupo de tutorías
                cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
                grupo = cursor.fetchone()

                if not grupo:
                    # No es un grupo registrado - no hacer nada especial
                    print(f"ℹ️ Grupo {chat_id} no es una sala de tutoría")
                    conn.close()
                    continue

                # Verificar si el usuario está registrado
                cursor.execute("SELECT * FROM Usuarios WHERE TelegramID = ?", (user_id,))
                usuario = cursor.fetchone()

                if not usuario:
                    # Usuario no registrado - enviar mensaje informativo
                    print(f"⚠️ Usuario {user_id} no registrado en el sistema")
                    bot.send_message(
                        chat_id, 
                        f"👋 Bienvenido/a {new_member.first_name}.\n\n"
                        f"Para poder participar completamente en este grupo, primero debes registrarte "
                        f"con el bot principal.",
                        parse_mode="Markdown"
                    )
                    conn.close()
                    continue

                # Verificar si es estudiante
                if usuario['Tipo'] != 'estudiante':
                    print(f"ℹ️ Usuario {user_id} no es estudiante, es {usuario['Tipo']}")
                    conn.close()
                    continue
                    
                # Es un estudiante registrado - procesar correctamente
                nombre_completo = f"{usuario['Nombre']} {usuario['Apellidos'] or ''}".strip()
                print(f"✅ Nuevo estudiante en grupo {chat_id}: {nombre_completo}")
                
                # Mensaje de bienvenida personalizado para estudiantes
                mensaje = (
                    f"👋 ¡Bienvenido/a *{nombre_completo}*!\n\n"
                    f"Te has unido a una sala de tutoría. Cuando finalices tu consulta, "
                    f"pulsa el botón '❌ Terminar Tutoria' para salir."
                )

                # Registrar al estudiante en la base de datos si es sala individual
                if grupo['Proposito_sala'] == 'individual':
                    try:
                        cursor.execute("""
                            INSERT INTO Miembros_Grupo (id_sala, Id_usuario, Fecha_union, Estado)
                            VALUES (?, ?, CURRENT_TIMESTAMP, 'activo')
                        """, (grupo['id_sala'], usuario['Id_usuario']))
                        conn.commit()
                        print(f"✅ Estudiante {nombre_completo} registrado en sala {grupo['id_sala']}")
                    except Exception as e:
                        print(f"❌ Error al registrar estudiante en grupo: {e}")
                
                # Crear un teclado personalizado con el botón de finalizar tutoría
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
                terminar_btn = types.KeyboardButton('❌ Terminar Tutoria')
                markup.add(terminar_btn)

                # Enviar mensaje de bienvenida con teclado
                bot.send_message(
                    chat_id, 
                    mensaje,
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
                print(f"✅ Mensaje de bienvenida enviado a {nombre_completo}")

                conn.close()

        except Exception as e:
            print(f"❌ ERROR EN HANDLER NEW_CHAT_MEMBERS: {e}")
            traceback.print_exc()

    print("✅ Handler de nuevos estudiantes registrado correctamente")
    return True