# Estados de usuario y datos temporales (compartidos entre módulos)
user_states = {}
user_data = {}

def get_state(chat_id):
    """Obtiene el estado actual del chat"""
    return user_states.get(chat_id, 'INICIO')

def set_state(chat_id, state):
    """Establece el estado para un chat"""
    user_states[chat_id] = state
    return state

def clear_state(chat_id):
    """Limpia el estado del usuario"""
    if chat_id in user_states:
        del user_states[chat_id]
    if chat_id in user_data:
        del user_data[chat_id]