import logging
import os
import subprocess
import time
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters
)
from telegram.error import BadRequest
import re

# --- CONFIGURACIÓN ---
TOKEN_FILE = 'token.txt'
ARTIST_FILE = 'artista.txt'
COVER_IMAGE = 'cover.jpg'
DOWNLOAD_DIR = os.getcwd()
MESSAGES_ID_FILE = 'messages_id.txt'

# Estados del modo interactivo
(
    LIVE_MODE_OFF,
    AWAITING_TITLE,
    AWAITING_ARTIST,
    AWAITING_COVER,
) = range(4)

# Configuración del registro
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("log.txt"),
        logging.StreamHandler()
    ]
)
# Suprimir logs de librerías para una terminal limpia
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)

def get_token():
    """Lee el token de bot desde un archivo de texto."""
    try:
        if not os.path.exists(TOKEN_FILE):
            raise FileNotFoundError(f"El archivo '{TOKEN_FILE}' no existe. Por favor, créalo y pega tu token dentro.")
        with open(TOKEN_FILE, 'r') as f:
            return f.read().strip()
    except Exception as e:
        logging.error(f"Error al leer el token: {e}")
        return None

def get_artist():
    """Lee el nombre del artista desde un archivo de texto."""
    try:
        if not os.path.exists(ARTIST_FILE):
            with open(ARTIST_FILE, 'w') as f:
                f.write("Artista Desconocido\n")
            logging.info(f"Archivo '{ARTIST_FILE}' creado. Por favor, edítalo con el nombre del artista.")
            return "Artista Desconocido"
        with open(ARTIST_FILE, 'r') as f:
            return f.read().strip()
    except Exception as e:
        logging.error(f"Error al leer el archivo del artista: {e}")
        return "Artista Desconocido"

def save_message_id_to_file(message_id):
    """Guarda el ID de un mensaje en el archivo de registro."""
    try:
        with open(MESSAGES_ID_FILE, 'a') as f:
            f.write(str(message_id) + '\n')
        logging.info(f"ID de mensaje guardado en archivo: {message_id}")
    except Exception as e:
        logging.error(f"Error al guardar el ID del mensaje en el archivo: {e}")

def remove_message_id_from_file(message_id):
    """Elimina el ID de un mensaje del archivo de registro."""
    try:
        with open(MESSAGES_ID_FILE, 'r') as f:
            lines = f.readlines()
        with open(MESSAGES_ID_FILE, 'w') as f:
            for line in lines:
                if line.strip() != str(message_id):
                    f.write(line)
        logging.info(f"ID de mensaje eliminado del archivo: {message_id}")
    except FileNotFoundError:
        logging.warning("Archivo de IDs no encontrado, no se puede eliminar el ID.")
    except Exception as e:
        logging.error(f"Error al eliminar el ID del mensaje del archivo: {e}")

def escape_markdown_v2(text):
    """Escapa los caracteres especiales para MarkdownV2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# --- MANEJADORES DE COMANDOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /start y envía un mensaje de bienvenida."""
    logging.info(f"Comando /start recibido de {update.effective_user.id}")
    message = "¡Hola! Envíame un audio o video y lo convertiré a MP3. Usa */live* para empezar un proceso de conversión interactiva o */help* para ver los comandos disponibles."
    await update.message.reply_text(message, parse_mode='MarkdownV2')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /help y envía una guía de uso."""
    logging.info(f"Comando /help recibido de {update.effective_user.id}")
    help_text = (
        "*Guía de uso del bot:*\n\n"
        "1. *Conversión rápida:* Envía un archivo de audio o video directamente al bot y lo convertirá a MP3 usando el título y artista predeterminados.\n\n"
        "2. *Conversión interactiva:* Usa el comando `/live` para activar el modo de edición. El bot te guiará paso a paso para que personalices el título, el artista y la carátula antes de la conversión.\n\n"
        "3. *Más comandos:*\n"
        "    - `/start`: Muestra un mensaje de bienvenida.\n"
        "    - `/live`: Inicia un proceso de conversión interactivo.\n"
        "    - `/help`: Muestra esta guía de uso.\n"
        "    - `/owners`: Muestra el creador del bot."
    )
    await update.message.reply_text(help_text, parse_mode='MarkdownV2')

async def owners_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /owners y muestra el creador del bot."""
    logging.info(f"Comando /owners recibido de {update.effective_user.id}")
    await update.message.reply_text("Hecho por elmendezz")

async def live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el comando /live para activar el modo interactivo una sola vez."""
    user_data = context.user_data
    chat_id = update.message.chat_id

    if user_data.get('live_mode', LIVE_MODE_OFF) != LIVE_MODE_OFF:
        await update.message.reply_text("Ya hay un proceso de conversión interactivo en curso. Por favor, espera a que termine.")
        return

    user_data['live_mode'] = AWAITING_TITLE
    user_data['live_data'] = {
        'requester_id': update.effective_user.id,
        'messages_to_delete': []
    }
    
    # Agregar mensaje del usuario a la lista de eliminación
    user_data['live_data']['messages_to_delete'].append(update.message.message_id)

    response = await update.message.reply_text("Modo interactivo activado. Por favor, envía el *título* de la canción.", parse_mode='MarkdownV2')
    user_data['live_data']['messages_to_delete'].append(response.message_id)

    logging.info(f"Modo live activado por {update.effective_user.id}")

# --- MANEJADOR DE MENSAJES DE TEXTO ---

async def handle_live_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los mensajes de texto en modo interactivo."""
    user_data = context.user_data
    current_state = user_data.get('live_mode', LIVE_MODE_OFF)

    if user_data.get('live_data', {}).get('requester_id') != update.effective_user.id:
        return

    user_data['live_data']['messages_to_delete'].append(update.message.message_id)

    if current_state == AWAITING_TITLE:
        title = update.message.text
        user_data['live_data']['title'] = title
        user_data['live_mode'] = AWAITING_ARTIST
        
        response = await update.message.reply_text(
            f"Título guardado: *{escape_markdown_v2(title)}*. Ahora, envía el *artista* o escribe 'default' para usar el artista predeterminado.", parse_mode='MarkdownV2'
        )
        user_data['live_data']['messages_to_delete'].append(response.message_id)
        logging.info(f"Título guardado para {update.effective_user.id}: '{title}'")

    elif current_state == AWAITING_ARTIST:
        artist_input = update.message.text
        if artist_input.lower() == 'default':
            artist = get_artist()
        else:
            artist = artist_input
        user_data['live_data']['artist'] = artist
        user_data['live_mode'] = AWAITING_COVER
        
        response = await update.message.reply_text(
            f"Artista guardado: *{escape_markdown_v2(artist)}*. ¿Quieres usar una carátula incrustada? Responde 'si' o 'no'.", parse_mode='MarkdownV2'
        )
        user_data['live_data']['messages_to_delete'].append(response.message_id)
        logging.info(f"Artista guardado para {update.effective_user.id}: '{artist}'")

    elif current_state == AWAITING_COVER:
        cover_choice = update.message.text.lower()
        if cover_choice == 'si':
            user_data['live_data']['use_cover'] = True
            response_text = "Usaré la carátula 'cover.jpg'."
        elif cover_choice == 'no':
            user_data['live_data']['use_cover'] = False
            response_text = "No se incrustará ninguna carátula."
        else:
            user_data['live_data']['use_cover'] = False
            response_text = "Respuesta no válida. No se incrustará ninguna carátula."
        
        user_data['live_mode'] = LIVE_MODE_OFF
        
        response = await update.message.reply_text(f"{response_text}\nAhora envía el audio o video para convertirlo.", parse_mode='MarkdownV2')
        user_data['live_data']['messages_to_delete'].append(response.message_id)
        logging.info(f"Preferencia de carátula para {update.effective_user.id}: {user_data['live_data']['use_cover']}")
    else:
        pass

# --- MANEJADOR DE AUDIO Y VIDEO ---

async def convert_to_mp3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los archivos de audio y video para la conversión."""
    user_data = context.user_data
    
    file_info = None
    if update.message.audio:
        file_info = update.message.audio
    elif update.message.video:
        file_info = update.message.video
    elif update.message.document and update.message.document.mime_type in ['audio/flac', 'audio/x-flac']:
        file_info = update.message.document
    else:
        return

    if user_data.get('live_mode', LIVE_MODE_OFF) != LIVE_MODE_OFF:
        if user_data.get('live_data', {}).get('requester_id') != update.effective_user.id:
            await update.message.reply_text("Hay un proceso de conversión interactivo en curso. Por favor, espera a que termine o inicia uno nuevo con /live.")
            return

    live_data = user_data.get('live_data', {})
    
    file_name = file_info.file_name if file_info.file_name else f"{file_info.file_unique_id}.temp"
    title = live_data.get('title', os.path.splitext(file_name)[0])
    artist = live_data.get('artist', get_artist())
    use_cover = live_data.get('use_cover', False)

    start_time = time.time()
    converting_message = await update.message.reply_text("Convirtiendo tu archivo... ⏳")
    
    messages_to_delete = live_data.get('messages_to_delete', [])
    messages_to_delete.append(update.message.message_id) # Se agrega el mensaje del usuario con el archivo
    
    # Almacenar IDs en el archivo para su posterior eliminación
    for msg_id in messages_to_delete:
        save_message_id_to_file(msg_id)
    save_message_id_to_file(converting_message.message_id)

    try:
        file_obj = await context.bot.get_file(file_info.file_id)
    except BadRequest as e:
        if "File is too big" in str(e):
            await converting_message.edit_text("❌ La conversión falló. El archivo es demasiado grande (límite de 50MB).")
            remove_message_id_from_file(converting_message.message_id)
            logging.error(f"Error para {update.effective_user.id}: Archivo demasiado grande. Conversión cancelada.")
            return
        else:
            raise

    input_file_path = os.path.join(DOWNLOAD_DIR, f"{file_obj.file_unique_id}.temp")
    output_file_path = os.path.join(DOWNLOAD_DIR, f"{file_obj.file_unique_id}.mp3")
    
    try:
        await file_obj.download_to_drive(input_file_path)
        logging.info(f"Archivo descargado: {input_file_path}")

        command = ['ffmpeg']

        if use_cover:
            if not os.path.exists(COVER_IMAGE):
                await update.message.reply_text("Error: No se encontró el archivo de carátula 'cover.jpg'.")
                remove_message_id_from_file(converting_message.message_id)
                return
            command.extend(['-i', input_file_path, '-i', COVER_IMAGE])
            command.extend(['-map', '0:a', '-map', '1:v'])
            command.extend(['-disposition:v:0', 'attached_pic'])
            command.extend(['-c:a', 'libmp3lame', '-q:a', '2'])
            command.extend(['-metadata', f'title={title}', '-metadata', f'artist={artist}'])
            command.append(output_file_path)
        else:
            command.extend(['-i', input_file_path])
            command.extend(['-c:a', 'libmp3lame', '-q:a', '2'])
            command.extend(['-metadata', f'title={title}', '-metadata', f'artist={artist}'])
            command.append(output_file_path)
            
        logging.info(f"Ejecutando comando de conversión para {update.effective_user.id}")
        subprocess.run(command, check=True, capture_output=True, text=True)
        
        with open(output_file_path, 'rb') as audio_file:
            await update.message.reply_audio(
                audio=audio_file,
                title=title,
                performer=artist
            )
        end_time = time.time()
        duration = round(end_time - start_time, 2)
        # Se aplica la función de escape a la variable 'duration'
        final_message = await converting_message.edit_text(f"✅ Conversión exitosa. Duración: *{escape_markdown_v2(str(duration))}* segundos.", parse_mode='MarkdownV2')
        save_message_id_to_file(final_message.message_id)
        logging.info(f"Conversión exitosa y archivo enviado para {update.effective_user.id}")
        
        await asyncio.sleep(10)

        # Intento de eliminación de mensajes
        all_messages_to_delete = messages_to_delete + [converting_message.message_id, final_message.message_id]
        
        for msg_id in all_messages_to_delete:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
                remove_message_id_from_file(msg_id)
                logging.info(f"Mensaje eliminado: {msg_id}")
            except Exception as e:
                logging.error(f"Error al eliminar el mensaje {msg_id}: {e}")
                
    except subprocess.CalledProcessError as e:
        await converting_message.edit_text(f"❌ La conversión falló. \nDetalles: `{escape_markdown_v2(e.stderr)}`", parse_mode='MarkdownV2')
        remove_message_id_from_file(converting_message.message_id)
        logging.error(f"Error en la conversión para {update.effective_user.id}: {e.stderr}")
    finally:
        # Limpieza de archivos temporales
        if os.path.exists(input_file_path):
            os.remove(input_file_path)
            logging.info(f"Archivo temporal eliminado: {input_file_path}")
        if os.path.exists(output_file_path):
            os.remove(output_file_path)
            logging.info(f"Archivo de salida eliminado: {output_file_path}")
            
        user_data['live_mode'] = LIVE_MODE_OFF
        user_data['live_data'] = {}

# --- FUNCIÓN PRINCIPAL ---
def main():
    token = get_token()
    if not token:
        return

    application = ApplicationBuilder().token(token).read_timeout(30).write_timeout(30).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("live", live))
    application.add_handler(CommandHandler("owners", owners_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_live_text))
    
    file_handler = MessageHandler(
        filters.AUDIO | filters.VIDEO | filters.Document.AUDIO,
        convert_to_mp3
    )
    application.add_handler(file_handler)

    application.run_polling()

if __name__ == '__main__':
    main()
