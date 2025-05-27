import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import logging
import time

# Estados para el flujo de conversación
ELEGIR_TIPO = 1
BUSCAR_ALUMNO = 2
SELECCIONAR_ALUMNO = 3
CONFIRMAR_EXPULSION = 4
SELECCIONAR_SALA = 5
CONFIRMAR_ELIMINAR_SALA = 6
SELECCIONAR_ASIGNATURA = 7
CONFIRMAR_CAMBIO = 8
CONFIRMAR_ELIMINAR_SALA_FINAL = 9

# Registro para evitar mensajes duplicados
ultimos_mensajes_bienvenida = {}
ultimas_acciones_admin = {}  # Para eventos de promoción a administrador

class GestionGrupos:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
    
    def obtener_asignaturas_profesor(self, id_profesor: int):
        """Obtiene las asignaturas que imparte un profesor"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT a.id, a.nombre
            FROM asignaturas a
            JOIN profesor_asignatura pa ON a.id = pa.id_asignatura
            WHERE pa.id_profesor = ?
        ''', (id_profesor,))
        
        asignaturas = cursor.fetchall()
        conn.close()
        return asignaturas
    
    def guardar_grupo(self, nombre_grupo: str, enlace_grupo: str, id_profesor: int, 
                      id_asignatura: int = None, es_tutoria: bool = False):
        """Guarda la información del grupo en la base de datos"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Determinar el tipo de sala según es_tutoria
            tipo_sala = 'privada' if es_tutoria else 'pública'
            
            # Extraer el chat_id del enlace o usar un valor único
            chat_id = enlace_grupo.split('/')[-1] if '/' in enlace_grupo else enlace_grupo
            
            cursor.execute('''
                INSERT INTO Grupos_tutoria (
                    Id_usuario, Nombre_sala, Tipo_sala, Id_asignatura, 
                    Chat_id, Enlace_invitacion
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (id_profesor, nombre_grupo, tipo_sala, id_asignatura, chat_id, enlace_grupo))
            
            inserted_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            self.logger.info(f"Grupo guardado exitosamente: ID={inserted_id}, Nombre='{nombre_grupo}', " 
                             f"Profesor ID={id_profesor}, Asignatura ID={id_asignatura}, Es tutoria={es_tutoria}")
            
            return True
        except Exception as e:
            self.logger.error(f"Error al guardar grupo '{nombre_grupo}': {e}")
            return False
    
    def verificar_salas_existentes(self, id_profesor):
        """
        Verifica qué salas ya tiene creadas el profesor
        Devuelve un diccionario con:
        - Lista de IDs de asignaturas con sala ya creada
        - Booleano indicando si ya tiene sala de tutorías
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Verificar salas por asignatura
        cursor.execute('''
            SELECT Id_asignatura 
            FROM Grupos_tutoria 
            WHERE Id_usuario = ? AND Tipo_sala = 'pública' AND Id_asignatura IS NOT NULL
        ''', (id_profesor,))
        
        asignaturas_con_sala = [row[0] for row in cursor.fetchall()]
        
        # Verificar si tiene sala de tutorías
        cursor.execute('''
            SELECT COUNT(*) 
            FROM Grupos_tutoria 
            WHERE Id_usuario = ? AND Tipo_sala = 'privada'
        ''', (id_profesor,))
        
        tiene_sala_tutoria = cursor.fetchone()[0] > 0
        
        conn.close()
        
        return {
            'asignaturas_con_sala': asignaturas_con_sala,
            'tiene_sala_tutoria': tiene_sala_tutoria
        }
    
    def procesar_nuevo_grupo(self, update: Update, context: CallbackContext) -> int:
        """Inicia el proceso cuando el bot es añadido a un grupo"""
        chat = update.effective_chat
        
        # Verificar si el chat es un grupo o supergrupo
        if chat.type not in ['group', 'supergroup']:
            return ConversationHandler.END
        
        # Verificar si el bot fue añadido al grupo
        if update.message and update.message.new_chat_members:
            bot_added = any(member.id == context.bot.id for member in update.message.new_chat_members)
            if not bot_added:
                return ConversationHandler.END
        
        # Enviar instrucciones iniciales al grupo con un saludo cordial
        update.message.reply_text(
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
        
        # Obtener información básica del chat
        nombre_grupo = chat.title
        
        # Intentar obtener el enlace de invitación existente
        try:
            chat_info = context.bot.get_chat(chat.id)
            enlace_grupo = chat_info.invite_link
            
            # Si el enlace no existe, verificamos si podemos acceder a él (somos admin)
            if not enlace_grupo:
                # Verificamos si somos administradores
                bot_member = context.bot.get_chat_member(chat.id, context.bot.id)
                if bot_member.status in ['administrator', 'creator']:
                    # No generamos un nuevo enlace, solo informamos que no hay uno disponible
                    update.message.reply_text(
                        "Ahora soy administrador, pero este grupo no tiene un enlace de invitación activo. "
                        "Puedes crear uno manualmente desde la configuración del grupo."
                    )
                    return ConversationHandler.END
                else:
                    # No somos administradores todavía
                    self.logger.info("El bot aún no es administrador")
                    return ConversationHandler.END
            
            # Si llegamos aquí, tenemos el enlace y somos administradores
            # Almacenar datos del grupo en el contexto
            context.user_data['grupo_nombre'] = nombre_grupo
            context.user_data['grupo_enlace'] = enlace_grupo
            
            # Obtener el usuario que añadió al bot (asumimos que es el profesor)
            if update.message and update.message.from_user:
                id_profesor = update.message.from_user.id
                context.user_data['id_profesor'] = id_profesor
                
                # Verificar las salas que ya tiene creadas el profesor
                salas_existentes = self.verificar_salas_existentes(id_profesor)
                
                # Obtener asignaturas del profesor
                asignaturas = self.obtener_asignaturas_profesor(id_profesor)
                
                if not asignaturas:
                    update.message.reply_text("No tienes asignaturas asociadas en el sistema.")
                    return ConversationHandler.END
                
                # Crear teclado inline con opciones (solo para asignaturas sin sala)
                keyboard = []
                asignaturas_disponibles = False
                
                for id_asig, nombre_asig in asignaturas:
                    if id_asig not in salas_existentes['asignaturas_con_sala']:
                        keyboard.append([InlineKeyboardButton(nombre_asig, callback_data=f"asig_{id_asig}")])
                        asignaturas_disponibles = True
                
                # Añadir opción para tutorías (solo si no tiene ya una sala de tutorías)
                if not salas_existentes['tiene_sala_tutoria']:
                    keyboard.append([InlineKeyboardButton("Sala de Tutorías Individuales", callback_data="tutoria")])
                
                # Si no hay opciones disponibles, informar al profesor
                if not asignaturas_disponibles and salas_existentes['tiene_sala_tutoria']:
                    update.message.reply_text(
                        "Ya tienes salas creadas para todas tus asignaturas y una sala de tutorías. "
                        "No puedes crear más salas. Si necesitas reconfigurar una sala, "
                        "contacta con el administrador del sistema."
                    )
                    return ConversationHandler.END
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                # Enviar mensaje al chat privado con el profesor
                context.bot.send_message(
                    chat_id=id_profesor,
                    text=f"¡Ya puedo configurar el grupo '{nombre_grupo}'! "
                         f"¿A qué asignatura quieres asociar este grupo?",
                    reply_markup=reply_markup
                )
                
                # También confirmar en el grupo
                update.message.reply_text(
                    "¡Genial! Ya tengo los permisos necesarios.\n"
                    "He enviado un mensaje privado al profesor para completar la configuración."
                )
                
                return ELEGIR_TIPO
                
        except Exception as e:
            # Error al acceder a la información del chat
            self.logger.error(f"Error al acceder a la información del chat: {e}")
            # No hacemos nada más, esperamos a que el profesor haga admin al bot
            
        return ConversationHandler.END
    
    def procesar_eleccion(self, update: Update, context: CallbackContext) -> int:
        """Procesa la elección del profesor sobre el tipo de sala"""
        query = update.callback_query
        query.answer()
        
        eleccion = query.data
        id_profesor = context.user_data.get('id_profesor')
        nombre_grupo = context.user_data.get('grupo_nombre')
        enlace_grupo = context.user_data.get('grupo_enlace')
        
        if not all([id_profesor, nombre_grupo, enlace_grupo]):
            query.edit_message_text("Ocurrió un error al procesar la información del grupo.")
            return ConversationHandler.END
        
        if eleccion == "tutoria":
            # Es una sala de tutorías
            self.guardar_grupo(nombre_grupo, enlace_grupo, id_profesor, None, True)
            query.edit_message_text(f"El grupo '{nombre_grupo}' ha sido configurado como tu sala de tutorías individuales.")
        else:
            # Es una sala de asignatura
            id_asignatura = int(eleccion.split('_')[1])
            self.guardar_grupo(nombre_grupo, enlace_grupo, id_profesor, id_asignatura, False)
            
            # Obtener nombre de la asignatura
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT nombre FROM asignaturas WHERE id = ?", (id_asignatura,))
            nombre_asignatura = cursor.fetchone()[0]
            conn.close()
            
            query.edit_message_text(
                f"El grupo '{nombre_grupo}' ha sido asociado a la asignatura '{nombre_asignatura}'.\n\n"
                "Si en el futuro necesitas cambiar la asignatura asociada, puedes usar el comando /cambiar_asignatura"
            )
        
        return ConversationHandler.END
    
    def es_sala_tutoria(self, chat_id):
        """Verifica si un chat es una sala de tutoría"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT Tipo_sala FROM Grupos_tutoria
            WHERE Chat_id LIKE ?
        ''', (f"%{chat_id}%",))
        
        result = cursor.fetchone()
        conn.close()
        
        return result and result[0] == 'privada'
    
    def es_profesor(self, user_id):
        """Verifica si un usuario es profesor"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Cambiado de 'rol' a 'Tipo' para ser consistente con el resto del código
        cursor.execute('SELECT Tipo FROM Usuarios WHERE Telegram_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        
        return result and result[0] == 'profesor'
    
    def finalizar_sesion(self, update: Update, context: CallbackContext) -> int:
        """Gestiona el comando /finalizar tanto para profesores como para alumnos"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        # Verificar que sea una sala de tutoría
        if not self.es_sala_tutoria(chat_id):
            update.message.reply_text("Esta función solo está disponible en salas de tutoría individuales.")
            return ConversationHandler.END
        
        # Comportamiento diferente según el rol
        if self.es_profesor(user_id):
            # Es profesor: mostrar lista de alumnos para expulsar
            return self.iniciar_expulsion_por_profesor(update, context)
        else:
            # Es alumno: autoexpulsión
            return self.autoexpulsion_alumno(update, context)
    
    def autoexpulsión_alumno(self, update: Update, context: CallbackContext) -> int:
        """Permite a un alumno salir del grupo voluntariamente"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        try:
            # Obtener el nombre del alumno
            nombre = update.effective_user.first_name
            if update.effective_user.last_name:
                nombre += f" {update.effective_user.last_name}"
            
            # Expulsar al usuario que solicitó salir (ban temporal de 1 minuto)
            until_date = int(time.time()) + 60
            context.bot.ban_chat_member(chat_id, user_id, until_date=until_date)
            
            # Enviar mensaje privado al usuario
            context.bot.send_message(
                chat_id=user_id, 
                text="Has finalizado tu sesión de tutoría. Gracias por participar."
            )
            
            # Informar al grupo
            update.message.reply_text(
                f"{nombre} ha finalizado su sesión de tutoría."
            )
            
        except Exception as e:
            self.logger.error(f"Error en autoexpulsión: {e}")
            update.message.reply_text("No pude procesar tu solicitud para finalizar la sesión.")
        
        return ConversationHandler.END
    
    def iniciar_expulsion_por_profesor(self, update: Update, context: CallbackContext) -> int:
        """Inicia el proceso para que un profesor expulse a un alumno"""
        chat_id = update.effective_chat.id
        
        # Guardar el chat_id en el contexto para usarlo más tarde
        context.user_data['chat_id'] = chat_id
        
        try:
            # Obtener lista de miembros del chat
            chat_members = context.bot.get_chat_administrators(chat_id)
            admin_ids = [member.user.id for member in chat_members]
            
            # Intentar obtener todos los miembros (esto podría ser limitado por la API)
            all_members = []
            for member in context.bot.get_chat_members(chat_id):
                if member.user.id not in admin_ids:
                    all_members.append(member)
            
            if not all_members:
                update.message.reply_text("No hay alumnos en este grupo.")
                return ConversationHandler.END
            
            # Preguntar si quiere buscar por nombre o ver la lista completa
            keyboard = [
                [InlineKeyboardButton("Buscar por nombre", callback_data="buscar")],
                [InlineKeyboardButton("Ver lista completa", callback_data="lista")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text(
                "¿Cómo quieres seleccionar al alumno cuya sesión deseas finalizar?", 
                reply_markup=reply_markup
            )
            
            # Guardar la lista de miembros en el contexto
            context.user_data['miembros'] = all_members
            return BUSCAR_ALUMNO
            
        except Exception as e:
            self.logger.error(f"Error al obtener miembros: {e}")
            update.message.reply_text(
                "No pude obtener la lista de miembros del grupo. "
                "Asegúrate de que tengo los permisos necesarios."
            )
            return ConversationHandler.END
    
    def procesar_opcion_busqueda(self, update: Update, context: CallbackContext) -> int:
        """Procesa la elección del método de búsqueda"""
        query = update.callback_query
        query.answer()
        
        if query.data == "buscar":
            query.edit_message_text("Por favor, envía el nombre o parte del nombre del alumno a buscar:")
            return SELECCIONAR_ALUMNO
        else:
            # Mostrar lista completa de alumnos
            miembros = context.user_data.get('miembros', [])
            keyboard = []
            
            for i, miembro in enumerate(miembros):
                nombre = miembro.user.first_name
                if miembro.user.last_name:
                    nombre += f" {miembro.user.last_name}"
                keyboard.append([InlineKeyboardButton(nombre, callback_data=f"user_{miembro.user.id}")])
            
            # Añadir botón de cancelar
            keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text("Selecciona el alumno cuya sesión deseas finalizar:", reply_markup=reply_markup)
            
            return CONFIRMAR_EXPULSION
    
    def buscar_alumno(self, update: Update, context: CallbackContext) -> int:
        """Busca alumnos por nombre"""
        texto_busqueda = update.message.text.lower()
        miembros = context.user_data.get('miembros', [])
        
        # Filtrar miembros por nombre
        miembros_filtrados = []
        for miembro in miembros:
            nombre = miembro.user.first_name.lower()
            if miembro.user.last_name:
                nombre += f" {miembro.user.last_name.lower()}"
            
            if texto_busqueda in nombre:
                miembros_filtrados.append(miembro)
        
        if not miembros_filtrados:
            update.message.reply_text("No se encontraron alumnos con ese nombre. Intenta con otro término.")
            return SELECCIONAR_ALUMNO
        
        # Mostrar resultados
        keyboard = []
        for miembro in miembros_filtrados:
            nombre = miembro.user.first_name
            if miembro.user.last_name:
                nombre += f" {miembro.user.last_name}"
            keyboard.append([InlineKeyboardButton(nombre, callback_data=f"user_{miembro.user.id}")])
        
        # Añadir botón de cancelar
        keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("Selecciona el alumno cuya sesión deseas finalizar:", reply_markup=reply_markup)
        
        return CONFIRMAR_EXPULSION
    
    def confirmar_expulsion(self, update: Update, context: CallbackContext) -> int:
        """Confirma la expulsión de un alumno"""
        query = update.callback_query
        query.answer()
        
        if query.data == "cancelar":
            query.edit_message_text("Operación cancelada.")
            return ConversationHandler.END
        
        user_id = int(query.data.split("_")[1])
        chat_id = context.user_data.get('chat_id')
        
        try:
            # Obtener información del usuario
            miembro = next((m for m in context.user_data.get('miembros', []) 
                         if m.user.id == user_id), None)
            
            if not miembro:
                query.edit_message_text("No pude encontrar al usuario seleccionado.")
                return ConversationHandler.END
                
            nombre = miembro.user.first_name
            if miembro.user.last_name:
                nombre += f" {miembro.user.last_name}"
                
            # Guardar datos para la expulsión
            context.user_data['expulsar_id'] = user_id
            context.user_data['expulsar_nombre'] = nombre
            
            # Pedir confirmación
            keyboard = [
                [InlineKeyboardButton("Confirmar", callback_data="confirm")],
                [InlineKeyboardButton("Cancelar", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(
                f"¿Estás seguro de finalizar la sesión de {nombre}?",
                reply_markup=reply_markup
            )
            
            return CONFIRMAR_EXPULSION
            
        except Exception as e:
            self.logger.error(f"Error al preparar expulsión: {e}")
            query.edit_message_text("Ocurrió un error al procesar la solicitud.")
            return ConversationHandler.END
    
    def ejecutar_expulsion(self, update: Update, context: CallbackContext) -> int:
        """Ejecuta la expulsión del alumno"""
        query = update.callback_query
        query.answer()
        
        if query.data == "cancel":
            query.edit_message_text("Operación cancelada.")
            return ConversationHandler.END
        
        chat_id = context.user_data.get('chat_id')
        user_id = context.user_data.get('expulsar_id')
        nombre = context.user_data.get('expulsar_nombre')
        
        try:
            # Expulsar al usuario por 1 minuto (60 segundos)
            until_date = int(time.time()) + 60
            context.bot.ban_chat_member(chat_id, user_id, until_date=until_date)
            
            # Informar al profesor que la expulsión fue exitosa
            query.edit_message_text(f"Has finalizado la sesión de tutoría con {nombre}.")
            
            # Informar en el grupo 
            context.bot.send_message(
                chat_id=chat_id,
                text=f"El profesor ha finalizado la sesión de tutoría con {nombre}."
            )
            
            # Intentar enviar mensaje privado al alumno
            try:
                context.bot.send_message(
                    chat_id=user_id,
                    text="El profesor ha finalizado tu sesión de tutoría. Gracias por participar."
                )
            except:
                # Si no podemos enviar mensaje al alumno, lo ignoramos
                pass
            
            return ConversationHandler.END
            
        except Exception as e:
            self.logger.error(f"Error al expulsar: {e}")
            query.edit_message_text("No pude finalizar la sesión. Asegúrate de que soy administrador con permisos suficientes.")
            return ConversationHandler.END
    
    def cambiar_asignatura_sala(self, update: Update, context: CallbackContext) -> int:
        """Permite al profesor cambiar la asignatura asociada a una sala"""
        user_id = update.effective_user.id
        
        # Verificar que sea profesor
        if not self.es_profesor(user_id):
            update.message.reply_text("Solo los profesores pueden usar esta función.")
            return ConversationHandler.END
        
        # Obtener salas del profesor
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT g.id_sala, g.Nombre_sala, a.nombre, g.Id_asignatura
            FROM Grupos_tutoria g
            LEFT JOIN asignaturas a ON g.Id_asignatura = a.id
            WHERE g.Id_usuario = ? AND g.Tipo_sala = 'pública'
        ''', (user_id,))
        
        salas = cursor.fetchall()
        conn.close()
        
        if not salas:
            update.message.reply_text("No tienes salas de asignatura configuradas.")
            return ConversationHandler.END
        
        # Mostrar lista de salas para seleccionar
        keyboard = []
        for sala_id, nombre_sala, nombre_asig, _ in salas:
            keyboard.append([
                InlineKeyboardButton(
                    f"{nombre_sala} - {nombre_asig or 'Sin asignatura'}", 
                    callback_data=f"sala_{sala_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            "Selecciona la sala a la que quieres cambiar la asignatura:",
            reply_markup=reply_markup
        )
        
        # Guardar salas en contexto
        context.user_data['salas'] = {sala[0]: sala for sala in salas}
        
        return SELECCIONAR_SALA
    
    def eliminar_sala(self, update: Update, context: CallbackContext) -> int:
        """Permite al profesor eliminar una sala de la base de datos"""
        user_id = update.effective_user.id
        
        # Verificar que sea profesor
        if not self.es_profesor(user_id):
            update.message.reply_text("Solo los profesores pueden usar esta función.")
            return ConversationHandler.END
        
        # Obtener salas del profesor
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT g.id_sala, g.Nombre_sala, 
                   CASE 
                       WHEN g.Tipo_sala = 'privada' THEN 'Sala de Tutorías'
                       ELSE a.nombre 
                   END as tipo_o_asignatura
            FROM Grupos_tutoria g
            LEFT JOIN asignaturas a ON g.Id_asignatura = a.id
            WHERE g.Id_usuario = ?
        ''', (user_id,))
        
        salas = cursor.fetchall()
        conn.close()
        
        if not salas:
            update.message.reply_text("No tienes salas configuradas.")
            return ConversationHandler.END
        
        # Mostrar lista de salas para eliminar
        keyboard = []
        for sala_id, nombre_sala, tipo_o_asig in salas:
            keyboard.append([
                InlineKeyboardButton(
                    f"{nombre_sala} - {tipo_o_asig}", 
                    callback_data=f"eliminar_{sala_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            "⚠️ ATENCIÓN: Al eliminar una sala, se perderá su configuración en el sistema.\n"
            "Esto NO eliminará el grupo de Telegram, solo su vinculación con tus asignaturas.\n\n"
            "Selecciona la sala que quieres eliminar:",
            reply_markup=reply_markup
        )
        
        return CONFIRMAR_ELIMINAR_SALA
    
    def procesar_cambio_asignatura(self, update: Update, context: CallbackContext) -> int:
        """Procesa la selección de sala para cambiar su asignatura"""
        query = update.callback_query
        query.answer()
        
        if query.data == "cancelar":
            query.edit_message_text("Operación cancelada.")
            return ConversationHandler.END
        
        # Obtener ID de la sala seleccionada
        sala_id = int(query.data.split('_')[1])
        sala_info = context.user_data.get('salas', {}).get(sala_id)
        
        if not sala_info:
            query.edit_message_text("No se encontró información sobre la sala seleccionada.")
            return ConversationHandler.END
        
        # Guardar información de la sala en el contexto
        context.user_data['sala_actual'] = {
            'id': sala_id,
            'nombre': sala_info[1],  # nombre_sala
            'asignatura_actual': sala_info[3]  # id_asignatura
        }
        
        # Obtener asignaturas disponibles para el profesor
        user_id = update.effective_user.id
        asignaturas = self.obtener_asignaturas_profesor(user_id)
        
        # Crear teclado con opciones de asignaturas
        keyboard = []
        for id_asig, nombre_asig in asignaturas:
            if id_asig != sala_info[3]:  # No mostrar la asignatura actual
                keyboard.append([InlineKeyboardButton(nombre_asig, callback_data=f"asignar_{id_asig}")])
        
        keyboard.append([InlineKeyboardButton("Cancelar", callback_data="cancelar")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Mostrar opciones
        query.edit_message_text(
            f"Selecciona la nueva asignatura para la sala '{sala_info[1]}':",
            reply_markup=reply_markup
        )
        
        # Añadir un estado adicional para seleccionar la nueva asignatura
        return SELECCIONAR_ASIGNATURA

    def confirmar_cambio_asignatura(self, update: Update, context: CallbackContext) -> int:
        """Confirma el cambio de asignatura y pregunta si expulsar a los miembros"""
        query = update.callback_query
        query.answer()
        
        if query.data == "cancelar":
            query.edit_message_text("Operación cancelada.")
            return ConversationHandler.END
        
        # Obtener la nueva asignatura seleccionada
        nueva_asignatura_id = int(query.data.split('_')[1])
        
        # Obtener nombre de la asignatura
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT nombre FROM asignaturas WHERE id = ?", (nueva_asignatura_id,))
        nombre_asignatura = cursor.fetchone()[0]
        conn.close()
        
        # Guardar en el contexto
        context.user_data['nueva_asignatura'] = {
            'id': nueva_asignatura_id,
            'nombre': nombre_asignatura
        }
        
        # Confirmar y preguntar sobre expulsión de miembros
        sala_nombre = context.user_data['sala_actual']['nombre']
        keyboard = [
            [InlineKeyboardButton("Cambiar y mantener miembros", callback_data="cambiar_mantener")],
            [InlineKeyboardButton("Cambiar y expulsar miembros", callback_data="cambiar_expulsar")],
            [InlineKeyboardButton("Cancelar", callback_data="cancelar")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(
            f"¿Confirmas cambiar la sala '{sala_nombre}' a la asignatura '{nombre_asignatura}'?\n\n"
            "¿Qué deseas hacer con los miembros actuales del grupo?",
            reply_markup=reply_markup
        )
        
        return CONFIRMAR_CAMBIO

    def ejecutar_cambio_asignatura(self, update: Update, context: CallbackContext) -> int:
        """Ejecuta el cambio de asignatura y expulsa miembros si es necesario"""
        query = update.callback_query
        query.answer()
        
        expulsar_miembros = (query.data == "cambiar_expulsar")
        sala_id = context.user_data['sala_actual']['id']
        nueva_asignatura_id = context.user_data['nueva_asignatura']['id']
        sala_nombre = context.user_data['sala_actual']['nombre']
        nueva_asignatura_nombre = context.user_data['nueva_asignatura']['nombre']
        
        # Actualizar la asignatura en la base de datos
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Obtener el chat_id de la sala
            cursor.execute("SELECT Chat_id FROM Grupos_tutoria WHERE id_sala = ?", (sala_id,))
            chat_id_result = cursor.fetchone()
            
            if not chat_id_result:
                query.edit_message_text("No se encontró la sala en la base de datos.")
                conn.close()
                return ConversationHandler.END
                
            chat_id = chat_id_result[0]
            
            # Actualizar la asignatura
            cursor.execute(
                "UPDATE Grupos_tutoria SET Id_asignatura = ? WHERE id_sala = ?", 
                (nueva_asignatura_id, sala_id)
            )
            conn.commit()
            conn.close()
            
            # Si se solicitó expulsar miembros, hacerlo
            if expulsar_miembros:
                self.expulsar_todos_miembros(context.bot, chat_id, exclude_admins=True)
                mensaje_resultado = (
                    f"La sala '{sala_nombre}' ha sido asignada a la asignatura '{nueva_asignatura_nombre}'.\n"
                    "Todos los miembros han sido expulsados del grupo."
                )
            else:
                mensaje_resultado = (
                    f"La sala '{sala_nombre}' ha sido asignada a la asignatura '{nueva_asignatura_nombre}'.\n"
                    "Los miembros actuales se han mantenido en el grupo."
                )
            
            query.edit_message_text(mensaje_resultado)
            
        except Exception as e:
            self.logger.error(f"Error al cambiar asignatura: {e}")
            query.edit_message_text("Ocurrió un error al cambiar la asignatura de la sala.")
            if 'conn' in locals() and conn:
                conn.close()
    
        return ConversationHandler.END

    def expulsar_todos_miembros(self, bot, chat_id, exclude_admins=True):
        """Expulsa a todos los miembros de un grupo excepto administradores"""
        try:
            # Obtener lista de administradores
            admins = []
            if exclude_admins:
                admins = [member.user.id for member in bot.get_chat_administrators(chat_id)]
            
            # Añadir el ID del bot para no auto-expulsarse
            bot_id = bot.get_me().id
            if bot_id not in admins:
                admins.append(bot_id)
            
            # Obtener todos los miembros y expulsar a los que no son admin
            chat_members = bot.get_chat_members(chat_id)
            expulsados = 0
            
            for member in chat_members:
                if member.user.id not in admins:
                    # Ban temporal (1 minuto)
                    until_date = int(time.time()) + 60
                    bot.ban_chat_member(chat_id, member.user.id, until_date=until_date)
                    expulsados += 1
                    
                    # Intentar enviar mensaje al usuario expulsado
                    try:
                        bot.send_message(
                            chat_id=member.user.id,
                            text="Has sido expulsado del grupo porque la configuración del mismo ha cambiado."
                        )
                    except:
                        # Si no podemos enviar mensaje al usuario, lo ignoramos
                        pass
            
            # Enviar mensaje al grupo
            if expulsados > 0:
                bot.send_message(
                    chat_id=chat_id,
                    text=f"La configuración de este grupo ha cambiado. Se han expulsado {expulsados} miembros."
                )
                
            return expulsados
        
        except Exception as e:
            self.logger.error(f"Error al expulsar miembros: {e}")
            return 0

    def ejecutar_eliminar_sala(self, update: Update, context: CallbackContext) -> int:
        """Elimina una sala y opcionalmente expulsa a sus miembros"""
        query = update.callback_query
        query.answer()
        
        if query.data == "cancelar":
            query.edit_message_text("Operación cancelada.")
            return ConversationHandler.END
        
        # Obtener ID de la sala
        sala_id = int(query.data.split('_')[1])
        
        # Obtener información de la sala
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT g.Nombre_sala, g.Chat_id,
                       CASE 
                           WHEN g.Tipo_sala = 'privada' THEN 'Sala de Tutorías'
                           ELSE a.nombre 
                       END as tipo_o_asignatura
                FROM Grupos_tutoria g
                LEFT JOIN asignaturas a ON g.Id_asignatura = a.id
                WHERE g.id_sala = ?
            ''', (sala_id,))
            
            sala_info = cursor.fetchone()
            
            if not sala_info:
                query.edit_message_text("No se encontró información sobre la sala seleccionada.")
                conn.close()
                return ConversationHandler.END
            
            nombre_sala, chat_id, tipo_sala = sala_info
            
            # Preguntar si quiere expulsar a todos los miembros
            keyboard = [
                [InlineKeyboardButton("Eliminar y expulsar miembros", callback_data=f"expulsar_{sala_id}")],
                [InlineKeyboardButton("Solo eliminar configuración", callback_data=f"soloeliminar_{sala_id}")],
                [InlineKeyboardButton("Cancelar", callback_data="cancelar")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            query.edit_message_text(
                f"¿Confirmas eliminar la sala '{nombre_sala}' ({tipo_sala})?\n\n"
                "¿Qué deseas hacer con los miembros actuales del grupo?",
                reply_markup=reply_markup
            )
            
            # Guardar información para el siguiente paso
            context.user_data['sala_eliminar'] = {
                'id': sala_id,
                'nombre': nombre_sala,
                'tipo': tipo_sala,
                'chat_id': chat_id
            }
            
            return CONFIRMAR_ELIMINAR_SALA_FINAL
            
        except Exception as e:
            self.logger.error(f"Error al preparar eliminación de sala: {e}")
            query.edit_message_text("Ocurrió un error al procesar la solicitud.")
            if 'conn' in locals() and conn:
                conn.close()
            return ConversationHandler.END

    
    
    def confirmar_eliminar_sala_final(self, update: Update, context: CallbackContext) -> int:
        """Confirmación final y ejecución de la eliminación de sala"""
        query = update.callback_query
        query.answer()
        
        if query.data == "cancelar":
            query.edit_message_text("Operación cancelada.")
            return ConversationHandler.END
        
        accion, sala_id = query.data.split('_')
        sala_id = int(sala_id)
        
        # Verificar que coincida con la sala almacenada
        if context.user_data.get('sala_eliminar', {}).get('id') != sala_id:
            query.edit_message_text("Error de validación. Inténtalo de nuevo.")
            return ConversationHandler.END
        
        sala_info = context.user_data['sala_eliminar']
        expulsar_miembros = (accion == "expulsar")
        
        # Eliminar sala de la base de datos
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Eliminar de la BD
            cursor.execute("DELETE FROM Grupos_tutoria WHERE id_sala = ?", (sala_id,))
            conn.commit()
            conn.close()
            
            # Si se solicitó expulsar miembros, hacerlo
            if expulsar_miembros and sala_info['chat_id']:
                expulsados = self.expulsar_todos_miembros(context.bot, sala_info['chat_id'])
                mensaje_resultado = (
                    f"La sala '{sala_info['nombre']}' ({sala_info['tipo']}) ha sido eliminada del sistema.\n"
                    f"Se han expulsado {expulsados} miembros del grupo."
                )
            else:
                mensaje_resultado = (
                    f"La sala '{sala_info['nombre']}' ({sala_info['tipo']}) ha sido eliminada del sistema.\n"
                    "No se ha expulsado a ningún miembro del grupo."
                )
            
            query.edit_message_text(mensaje_resultado)
            
        except Exception as e:
            self.logger.error(f"Error al eliminar sala: {e}")
            query.edit_message_text("Ocurrió un error al eliminar la sala.")
            if 'conn' in locals() and conn:
                conn.close()
        
        return ConversationHandler.END

    def registrar_handlers(self, dp):
        """Registra los handlers necesarios para la gestión de grupos"""
        # Handler para cuando el bot es añadida al grupo
        conv_handler = ConversationHandler(
            entry_points=[
                MessageHandler(
                    filters.StatusUpdate.NEW_CHAT_MEMBERS, 
                    self.procesar_nuevo_grupo
                )
            ],
            states={
                ELEGIR_TIPO: [CallbackQueryHandler(self.procesar_eleccion)],
            },
            fallbacks=[]
        )
        dp.add_handler(conv_handler)
        
        # Handler para el comando /finalizar (usado tanto por profesores como por alumnos)
        finalizar_handler = ConversationHandler(
            entry_points=[CommandHandler('finalizar', self.finalizar_sesion)],
            states={
                BUSCAR_ALUMNO: [CallbackQueryHandler(self.procesar_opcion_busqueda)],
                SELECCIONAR_ALUMNO: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.buscar_alumno)],
                CONFIRMAR_EXPULSION: [
                    CallbackQueryHandler(self.confirmar_expulsion, pattern=r"^user_"),
                    CallbackQueryHandler(self.ejecutar_expulsion, pattern=r"^confirm|cancel$"),
                    CallbackQueryHandler(lambda u, c: ConversationHandler.END, pattern=r"^cancelar$")
                ],
            },
            fallbacks=[CommandHandler('cancelar', lambda u, c: ConversationHandler.END)]
        )
        dp.add_handler(finalizar_handler)
        
        # Handler para cambiar asignatura de sala
        cambiar_asignatura_handler = ConversationHandler(
            entry_points=[CommandHandler('cambiar_asignatura', self.cambiar_asignatura_sala)],
            states={
                SELECCIONAR_SALA: [CallbackQueryHandler(lambda u, c: self.procesar_cambio_asignatura(u, c) 
                                                 if not u.callback_query.data == "cancelar" 
                                                 else ConversationHandler.END)],
                SELECCIONAR_ASIGNATURA: [CallbackQueryHandler(self.confirmar_cambio_asignatura)],
                CONFIRMAR_CAMBIO: [CallbackQueryHandler(self.ejecutar_cambio_asignatura)],
            },
            fallbacks=[CommandHandler('cancelar', lambda u, c: ConversationHandler.END)]
        )
        dp.add_handler(cambiar_asignatura_handler)
        
        # Handler para eliminar sala
        eliminar_sala_handler = ConversationHandler(
            entry_points=[CommandHandler('eliminar_sala', self.eliminar_sala)],
            states={
                CONFIRMAR_ELIMINAR_SALA: [
                    CallbackQueryHandler(self.ejecutar_eliminar_sala, pattern=r"^eliminar_"),
                    CallbackQueryHandler(lambda u, c: ConversationHandler.END, pattern=r"^cancelar$")
                ],
                CONFIRMAR_ELIMINAR_SALA_FINAL: [
                    CallbackQueryHandler(self.confirmar_eliminar_sala_final)
                ],
            },
            fallbacks=[CommandHandler('cancelar', lambda u, c: ConversationHandler.END)]
        )
        dp.add_handler(eliminar_sala_handler)

def register_handlers(bot):
    """Registra los handlers para integrarse con el sistema principal"""
    # Enfoque simplificado para obtener la ruta de la base de datos
    import os
    from pathlib import Path
    
    # Buscar el archivo de base de datos en ubicaciones comunes
    base_dir = Path(__file__).parent.parent.absolute()
    posibles_rutas = [
        os.path.join(base_dir, "tutoria_ugr.db"),  # raíz del proyecto
        os.path.join(base_dir, "db", "tutoria_ugr.db"),  # carpeta db
        "tutoria_ugr.db"  # relativa al directorio actual
    ]
    
    db_path = None
    for ruta in posibles_rutas:
        if os.path.exists(ruta):
            db_path = ruta
            break
            
    if db_path is None:
        # Si no encontramos la BD, usar ruta por defecto y advertir
        db_path = os.path.join(base_dir, "tutoria_ugr.db")
        print(f"⚠️ ADVERTENCIA: No se pudo encontrar la base de datos. Usando: {db_path}")
    
    # Importar las dependencias necesarias para el manejo de grupos
    from telebot import types
    import time
    import sqlite3
    import logging
    
    # Configurar logger
    logger = logging.getLogger(__name__)
    
    # Importar funciones comunes
    from db.queries import get_db_connection, get_user_by_telegram_id
    from utils.state_manager import user_states, user_data, set_state, get_state, clear_state
    
    # Crear instancia de GestionGrupos
    gestor = GestionGrupos(db_path)
    
    # Manejador para el botón de finalizar tutoría
    @bot.message_handler(func=lambda message: message.text == "❌ Terminar Tutoria")
    def handle_keyboard_finalizar(message):
        """Maneja el botón de finalizar tutoría del teclado"""
        chat_id = message.chat.id
        user_id = message.from_user.id
        
        # Verificar que estamos en un grupo
        if message.chat.type not in ['group', 'supergroup']:
            bot.reply_to(message, "Este comando solo funciona en grupos de tutoría.")
            return
        
        # Verificar que el grupo es una sala de tutoría
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Grupos_tutoria WHERE Chat_id = ?", (str(chat_id),))
        grupo = cursor.fetchone()
        conn.close()
        
        if not grupo:
            bot.reply_to(message, "Este grupo no está registrado como sala de tutoría.")
            return
        
        # Verificar tipo de usuario
        user = get_user_by_telegram_id(user_id)
        if not user:
            bot.reply_to(message, "No se pudo identificar al usuario.")
            return
        
        # Dirigir al comando /finalizar para ambos tipos de usuario
        message.text = "/finalizar"
        bot.process_new_messages([message])
    
    # Registrar handler de finalización
    @bot.message_handler(commands=['finalizar'])
    def finalizar_command(message):
        # Crear un objeto Update para simular el comportamiento de python-telegram-bot
        from collections import namedtuple
        EffectiveUser = namedtuple('EffectiveUser', ['id', 'first_name', 'last_name'])
        EffectiveChat = namedtuple('EffectiveChat', ['id'])
        EffectiveMessage = namedtuple('EffectiveMessage', ['reply_text'])
        Context = namedtuple('Context', ['bot'])
        Update = namedtuple('Update', ['effective_chat', 'effective_user', 'message'])
        
        # Envolver los datos en estructura similar a python-telegram-bot
        update = Update(
            effective_chat=EffectiveChat(id=message.chat.id),
            effective_user=EffectiveUser(
                id=message.from_user.id, 
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name if hasattr(message.from_user, 'last_name') else None
            ),
            message=EffectiveMessage(reply_text=lambda text: bot.send_message(message.chat.id, text))
        )
        context = Context(bot=bot)
        
        # Llamar a la implementación existente
        gestor.finalizar_sesion(update, context)
    
    # Handler para configurar grupos
    @bot.message_handler(commands=['configurar_grupo'])
    def configurar_grupo_comando(message):
        """Inicia la configuración de un grupo manualmente"""
        # Solo funciona en grupos
        if message.chat.type not in ['group', 'supergroup']:
            bot.reply_to(message, "Este comando solo funciona en grupos.")
            return
        
        # Verificar si el usuario es profesor
        user_id = message.from_user.id
        user = get_user_by_telegram_id(user_id)
        
        if not user or user['Tipo'] != 'profesor':
            bot.reply_to(message, "Solo los profesores pueden configurar grupos.")
            return
        
        # Verificar si el bot es admin
        try:
            bot_member = bot.get_chat_member(message.chat.id, bot.get_me().id)
            is_admin = bot_member.status in ['administrator', 'creator']
            
            if not is_admin:
                bot.reply_to(
                    message, 
                    "Necesito ser administrador para configurar este grupo. "
                    "Por favor, hazme administrador y vuelve a intentarlo."
                )
                return
                
            # Iniciar configuración
            chat_id = message.chat.id
            chat_title = message.chat.title
            
            # Obtener SOLO las asignaturas del profesor
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Consulta para obtener asignaturas donde el profesor está matriculado
            cursor.execute('''
                SELECT a.Id_asignatura, a.Nombre 
                FROM Asignaturas a
                JOIN Matriculas m ON a.Id_asignatura = m.Id_asignatura
                WHERE m.Id_usuario = ?
            ''', (user['Id_usuario'],))
            
            asignaturas = cursor.fetchall()
            conn.close()
            
            if not asignaturas:
                bot.reply_to(message, "No tienes asignaturas asignadas. Contacta con administración.")
                return
            
            # Crear teclado con opciones de asignaturas
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            for asig in asignaturas:
                markup.add(types.InlineKeyboardButton(
                    asig[1], 
                    callback_data=f"config_asig_{asig[0]}"
                ))
            
            # Opción para sala de tutorías
            markup.add(types.InlineKeyboardButton(
                "🧑‍🏫 Sala de Tutorías", 
                callback_data="config_tutoria"
            ))
            
            bot.reply_to(
                message,
                "🔄 *Configuración de grupo*\n\n"
                f"Configurando el grupo *{chat_title}*\n\n"
                "Por favor, selecciona la asignatura o tipo de sala:",
                reply_markup=markup,
                parse_mode="Markdown"
            )
            
            # Guardar estado
            set_state(user_id, "configurando_grupo")
            user_data[user_id] = {
                'chat_id': chat_id,
                'chat_title': chat_title
            }
            
        except Exception as e:
            bot.reply_to(message, f"Error al configurar el grupo: {e}")
            logger.error(f"Error en configurar_grupo_comando: {e}")
    
    # Handler para detectar cuando el bot es añadida a un grupo
    @bot.my_chat_member_handler()
    def handle_my_chat_member(update):
        """Detecta cuando el bot es añadida o removido de un grupo"""
        # Verificar que sea un grupo o supergrupo
        if update.chat.type not in ['group', 'supergroup']:
            return
            
        # Verificar si el bot fue añadido al grupo
        if update.new_chat_member.status in ['member', 'administrator'] and update.old_chat_member.status in ['left', 'kicked']:
            # El bot fue añadido al grupo
            chat_id = update.chat.id
            user_id = update.from_user.id
            
            # Enviar mensaje de bienvenida
            bot.send_message(
                chat_id,
                "¡Hola a todos!\n\n"
                "Soy el asistente para gestión de grupos de clase y tutorías. Es un placer "
                "estar aquí y ayudar a organizar este espacio educativo.\n\n"
                "Para poder configurar correctamente el grupo necesito ser administrador. "
                "Por favor, sigue estos pasos:\n\n"
                "1. Entra en la información del grupo\n"
                "2. Selecciona 'Administradores'\n"
                "3. Añádeme como administrador con permisos para:\n"
                "   - Invitar usuarios mediante enlaces\n"
                "   - Eliminar mensajes\n"
                "   - Restringir usuarios"
            )
            
        # Detectar cuando el bot es promovido a administrador
        elif update.new_chat_member.status == 'administrator' and update.old_chat_member.status in ['member', 'restricted']:
            # El bot recibió derechos de administrador
            chat_id = update.chat.id
            user_id = update.from_user.id
            
            bot.send_message(
                chat_id,
                "¡Gracias por hacerme administrador!\n\n"
                "Ahora puedo gestionar completamente este grupo."
            )
            
            # Intentar enviar opciones de configuración al profesor
            try:
                # Verificar que el usuario es profesor en tu sistema
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT Tipo FROM Usuarios WHERE TelegramID = ?", (user_id,))
                usuario = cursor.fetchone()
                conn.close()
                
                if usuario and usuario[0] == 'profesor':
                    # Es profesor, enviar opciones de configuración directamente en el grupo
                    bot.send_message(
                        chat_id,
                        "Ahora puedo configurar este grupo para tus clases o tutorías.\n"
                        "Usa el comando /configurar_grupo dentro del grupo para comenzar."
                    )
            except Exception as e:
                print(f"Error al verificar usuario: {e}")
    
    # Después del handler bot_added_to_group, añade este nuevo handler
    @bot.my_chat_member_handler()
    def handle_my_chat_member(update):
        """Detecta cuando el bot es añadida o cambia de permisos en un grupo"""
        # Verificar que es un grupo
        if update.chat.type not in ['group', 'supergroup']:
            return
        
        # Extraer información relevante
        chat_id = update.chat.id
        chat_title = update.chat.title
        user_id = update.from_user.id
        old_status = update.old_chat_member.status
        new_status = update.new_chat_member.status
        
        print(f"⚠️ CAMBIO DE ESTADO DEL BOT en {chat_title}: {old_status} -> {new_status}")
        
        # Detectar promoción a administrador
        if old_status in ['member'] and new_status == 'administrator':
            # El bot acaba de ser promovido a administrador
            bot.send_message(
                chat_id,
                "✅ *¡Gracias por hacerme administrador!*\n\n"
                "Ahora puedo gestionar completamente el grupo. Usa /configurar_grupo para "
                "configurar este espacio como sala de tutorías o asignatura.",
                parse_mode="Markdown"
            )
            
            # Verificar si quien promueve es profesor
            user = get_user_by_telegram_id(user_id)
            if user and user['Tipo'] == 'profesor':
                # Mostrar directamente opciones de configuración
                configurar_grupo_comando_direct(bot, chat_id, user_id)
                
        # Otros cambios de estado que podrían ser relevantes
        elif old_status in ['left', 'kicked'] and new_status in ['member', 'administrator']:
            # El bot fue añadido al grupo - ya lo maneja el otro handler
            pass
        elif new_status in ['left', 'kicked']:
            # El bot fue removido del grupo
            logger.info(f"Bot removido del grupo {chat_title} (ID: {chat_id}) por usuario {user_id}")

def configurar_grupo_comando_direct(bot, chat_id, user_id):
    """Muestra opciones de configuración sin necesidad del comando"""
    try:
        # Importar las funciones necesarias
        from db.queries import get_user_by_telegram_id, get_db_connection
        from telebot import types
        from utils.state_manager import user_states, user_data, set_state, get_state, clear_state
        
        # Configurar logger
        logger = logging.getLogger(__name__)
        
        # Verificar usuario
        user = get_user_by_telegram_id(user_id)
        if not user or user['Tipo'] != 'profesor':
            return
            
        chat_info = bot.get_chat(chat_id)
        chat_title = chat_info.title
        
        # Obtener enlace de invitación
        enlace_invitacion = None
        if hasattr(chat_info, 'invite_link') and chat_info.invite_link:
            enlace_invitacion = chat_info.invite_link
        else:
            try:
                enlace_invitacion = bot.create_chat_invite_link(chat_id).invite_link
            except Exception as e:
                logger.error(f"Error creando enlace: {str(e)}")
        
        # Obtener asignaturas del profesor
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT a.Id_asignatura, a.Nombre 
            FROM Asignaturas a
            JOIN Matriculas m ON a.Id_asignatura = m.Id_asignatura
            WHERE m.Id_usuario = ? AND m.Tipo = 'docencia'
        ''', (user['Id_usuario'],))
        asignaturas = cursor.fetchall()
        conn.close()
        
        if not asignaturas:
            bot.send_message(
                chat_id, 
                "No tienes asignaturas asignadas. Contacta con administración para configurar este grupo."
            )
            return
        
        # Crear teclado con asignaturas
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        # Opción para tutorías individuales privadas
        markup.add(types.InlineKeyboardButton(
            "👤 Tutorías Individuales Privadas", 
            callback_data="config_tutoria_privada"
        ))
        
        # Opción para tutorías grupales generales
        markup.add(types.InlineKeyboardButton(
            "👥 Tutorías Grupales Generales", 
            callback_data="config_tutoria_general"
        ))
        
        # Asignaturas específicas
        for asig in asignaturas:
            markup.add(types.InlineKeyboardButton(
                f"📚 {asig[1]}", 
                callback_data=f"config_asig_{asig[0]}"
            ))
        
        # Enviar mensaje con opciones
        bot.send_message(
            chat_id,
            "🔄 *Configuración de sala*\n\n"
            "Por favor, selecciona el tipo de sala que deseas configurar:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
        
        # Guardar datos
        set_state(user_id, "configurando_grupo")
        user_data[user_id] = {
            'chat_id': chat_id,
            'chat_title': chat_title,
            'enlace_invitacion': enlace_invitacion
        }
    
    except Exception as e:
        logger.error(f"Error en configuración automática: {e}")
        print(f"⚠️ ERROR en configuración automática: {e}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("config_asig_"))
    def handle_configuracion_asignatura(call):
        from db.queries import crear_grupo_tutoria
        
        user_id = call.from_user.id
        id_asignatura = call.data.split('_')[2]  # Extraer ID de la asignatura
        
        # Verificar el estado correcto
        if get_state(user_id) != "configurando_grupo":
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
            
            # Obtener nombre de la asignatura
            cursor.execute("SELECT Nombre FROM Asignaturas WHERE Id_asignatura = ?", (id_asignatura,))
            asignatura_nombre = cursor.fetchone()[0]
            
            # Obtener Id_usuario del profesor a partir de su TelegramID
            cursor.execute("SELECT Id_usuario FROM Usuarios WHERE TelegramID = ?", (str(user_id),))
            id_usuario = cursor.fetchone()[0]
            
            # Crear enlace de invitación si es posible
            try:
                enlace_invitacion = bot.create_chat_invite_link(chat_id).invite_link
            except:
                enlace_invitacion = None
        
            # Usar la función existente para crear el grupo
            nombre_sala = f"Tutoría: {asignatura_nombre}"
            tipo_sala = 'pública'
            
            # Crear el grupo usando la función
            crear_grupo_tutoria(
                profesor_id=id_usuario,  # ✅ CORRECTO
                nombre_sala=nombre_sala,
                tipo_sala=tipo_sala,
                asignatura_id=id_asignatura,
                chat_id=str(chat_id),
                enlace=enlace_invitacion
            )
            
            conn.close()
            
            # Cambiar nombre del grupo (opcional)
            try:
                bot.set_chat_title(chat_id, nombre_sala)
            except:
                pass  # Si falla el cambio de nombre, continuamos
                
            # Mensaje de éxito
            bot.edit_message_text(
                f"✅ Grupo configurado exitosamente como sala de tutoría para *{asignatura_nombre}*",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
            
            # Enviar mensaje informativo
            # Crear un teclado para profesores
            def menu_profesor():
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                markup.row("👥 Invitar Alumno", "❌ Terminar Tutoria")
                markup.row("📊 Estadísticas", "🔙 Volver")
                return markup
                
            bot.send_message(
                chat_id,
                "🎓 *Sala de tutoría configurada*\n\n"
                "Esta sala está ahora configurada para tutorías de *{asignatura_nombre}*.\n\n"
                "Como profesor puedes:\n"
                "• Invitar estudiantes con el botón 'Invitar alumno'\n"
                "• Expulsar estudiantes cuando finalice su consulta\n"
                "• Ver estadísticas de uso de la sala",
                parse_mode="Markdown",
                reply_markup=menu_profesor()
            )
            
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error al configurar grupo: {str(e)}")
            logger.error(f"Error configurando grupo {chat_id}: {e}")
    
    @bot.callback_query_handler(func=lambda call: call.data == "config_tutoria_privada")
    def handle_configuracion_tutoria(call):
        user_id = call.from_user.id
        
        # Verificar estado
        if get_state(user_id) != "configurando_grupo":
            bot.answer_callback_query(call.id, "Esta opción ya no está disponible")
            return
        
        # Obtener datos guardados
        if user_id not in user_data:
            bot.answer_callback_query(call.id, "Error: Datos no encontrados")
            clear_state(user_id)
            return
            
        chat_id = user_data[user_id]["chat_id"]
        
        try:
            # Registrar el grupo en la base de datos
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Obtener Id_usuario del profesor
            cursor.execute("SELECT Id_usuario FROM Usuarios WHERE TelegramID = ?", (str(user_id),))
            id_usuario = cursor.fetchone()[0]
            
            # Crear enlace de invitación si es posible
            try:
                enlace_invitacion = bot.create_chat_invite_link(chat_id).invite_link
            except:
                enlace_invitacion = user_data[user_id].get('enlace_invitacion')
        
            # Usar la función existente para crear el grupo
            nombre_sala = "Sala de Tutorías Individuales"
            tipo_sala = 'privada'
            
            # Crear el grupo usando la función
            from db.queries import crear_grupo_tutoria
            crear_grupo_tutoria(
                profesor_id=id_usuario,  # ✅ CORRECTO
                nombre_sala=nombre_sala,
                tipo_sala=tipo_sala,
                asignatura_id=None,  # Sin asignatura para tutorías generales
                chat_id=str(chat_id),
                enlace=enlace_invitacion
            )
            
            conn.close()
            
            # Cambiar nombre del grupo (opcional)
            try:
                bot.set_chat_title(chat_id, nombre_sala)
            except:
                pass
            
            # Mensaje de éxito
            bot.edit_message_text(
                "✅ Grupo configurado exitosamente como sala de tutorías individuales",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
            
            # Crear un teclado para profesores
            def menu_profesor():
                markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
                markup.row("👥 Invitar Alumno", "❌ Terminar Tutoria")
                markup.row("📊 Estadísticas", "🔙 Volver")
                return markup
                
            # Enviar mensaje informativo
            bot.send_message(
                chat_id,
                "🎓 *Sala de tutorías configurada*\n\n"
                "Esta sala está configurada para tutorías individuales.\n\n"
                "Como profesor puedes:\n"
                "• Invitar estudiantes con el botón 'Invitar alumno'\n"
                "• Finalizar la sesión cuando termine la tutoría\n"
                "• Ver estadísticas de uso de la sala",
                parse_mode="Markdown",
                reply_markup=menu_profesor()
            )
            
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error al configurar grupo: {str(e)}")
            logger.error(f"Error configurando sala de tutorías {chat_id}: {e}")
        
        # Limpiar estado
        clear_state(user_id)

def cambiar_nombre_grupo_telegram(chat_id, nuevo_nombre):
    """
    Función para cambiar el nombre de un grupo de Telegram.
    Esta función está diseñada para ser llamada desde main.py
    
    Args:
        chat_id: ID del chat de Telegram
        nuevo_nombre: Nuevo nombre para el grupo
    
    Returns:
        bool: True si se cambió con éxito, False en caso contrario
    """
    try:
        # Importamos para usar el mismo bot que maneja los grupos
        from telegram import Bot
        from config import TOKEN as TELEGRAM_TOKEN  # Asegúrate de tener el token correcto
        
        bot = Bot(TELEGRAM_TOKEN)
        bot.set_chat_title(chat_id, nuevo_nombre)
        print(f"✅ Nombre del grupo {chat_id} actualizado a: {nuevo_nombre}")
        return True
    except Exception as e:
        print(f"⚠️ Error al cambiar nombre del grupo {chat_id}: {e}")
        return False
