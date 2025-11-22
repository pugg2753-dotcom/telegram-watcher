import telebot
import sqlite3
import time
import requests
import html
import logging 
import re 
import datetime
import urllib.parse 

# --- ОТКЛЮЧЕНИЕ ЛОГОВ БИБЛИОТЕКИ ---
logging.getLogger('telebot').setLevel(logging.CRITICAL) 
# ------------------------------------

# --- НАСТРОЙКИ ---
# НОВЫЙ ТОКЕН: 8563284990:AAEppipwBHN9oSXaEsqQa8rrgvBT4j_R83M
TOKEN = "8563284990:AAEppipwBHN9oSXaEsqQa8rrgvBT4j_R83M" 
BOT_USERNAME = "@WatcherMode_bot" 
DB_NAME = 'messages.db'
LOG_FILE = 'spy_log.txt'
CLEANUP_DAYS = 90 # Срок хранения сообщений (90 дней)

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
START_TIME = time.time() 
WATERMARK = f"\n\n👁 <i>Замечено с {BOT_USERNAME}</i>"

# --- ЛОГГИРОВАНИЕ ---
def write_to_log(log_entry):
    """Записывает лог в консоль И в файл (для важных событий)."""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    full_entry = f"[{timestamp}] {log_entry}"
    print(full_entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_entry + "\n")
    except Exception as e:
        print(f"[ERROR] Не удалось записать в файл логов: {e}")

def write_to_log_silent(log_entry):
    """Записывает лог ТОЛЬКО в файл (для ошибок сети и отладочных сообщений)."""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    full_entry = f"[{timestamp}] {log_entry}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_entry + "\n")
    except:
        pass 
# -----------------------------

# --- SafeTeleBot (Исправление ошибки 'is_outgoing') ---
class SafeTeleBot(telebot.TeleBot):
    def process_new_updates(self, updates):
        safe_updates = []
        # Добавляем лог для диагностики
        if updates:
             write_to_log_silent(f"[DIAG] Получено {len(updates)} обновлений от Telegram.")
        
        for update in updates:
            # Проверка, что это бизнес-сообщение и что у него есть нужный атрибут
            if update.business_message and not hasattr(update.business_message, 'is_outgoing'):
                write_to_log_silent(f"[DEBUG_SKIP] Пропущено служебное обновление (ID:{update.update_id})")
                continue
            safe_updates.append(update)
        super().process_new_updates(safe_updates)

bot = SafeTeleBot(TOKEN)
# --------------------------------------------------------------------------

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (без изменений) ---

def format_uptime(seconds):
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{days}д {hours}ч {minutes}мин {seconds}сек"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_messages (
            business_connection_id TEXT, chat_id INTEGER, message_id INTEGER,
            original_text TEXT, user_name TEXT, content_type TEXT DEFAULT 'text',
            file_id TEXT, unix_timestamp INTEGER, direction TEXT DEFAULT 'UNKNOWN',           
            reply_to_message_id INTEGER, forward_info TEXT, PRIMARY KEY (chat_id, message_id)
        )
    """)
    try:
        cursor.execute("SELECT direction FROM cached_messages LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE cached_messages ADD COLUMN direction TEXT DEFAULT 'UNKNOWN'")
        cursor.execute("ALTER TABLE cached_messages ADD COLUMN reply_to_message_id INTEGER")
        cursor.execute("ALTER TABLE cached_messages ADD COLUMN forward_info TEXT")
        write_to_log(f"[DB_MIGRATE] Добавлены колонки.")
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users_connections (
            connection_id TEXT PRIMARY KEY, owner_chat_id INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_time ON cached_messages (user_name, unix_timestamp)")
    conn.commit()
    conn.close()

def get_owner_id_for_connection(conn_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT owner_chat_id FROM users_connections WHERE connection_id=?", (conn_id,))
        res = cursor.fetchone()
        conn.close()
        if res: return res[0]
    except: return None
    return None

def get_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    active_users = cursor.execute("SELECT COUNT(DISTINCT owner_chat_id) FROM users_connections").fetchone()[0]
    cache_size = cursor.execute("SELECT COUNT(*) FROM cached_messages").fetchone()[0]
    conn.close()
    return active_users, cache_size

def perform_db_cleanup(owner_id):
    current_time = int(time.time())
    cutoff_time = current_time - (CLEANUP_DAYS * 24 * 60 * 60)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM cached_messages WHERE unix_timestamp < ?", (cutoff_time,))
    count_before = cursor.fetchone()[0]
    cursor.execute("DELETE FROM cached_messages WHERE unix_timestamp < ?", (cutoff_time,))
    deleted_count = conn.changes
    cursor.execute("VACUUM")
    conn.commit()
    conn.close()
    return deleted_count, count_before


# --- ЗАПУСК: Игнорирование ProxyError ---
def stable_polling_loop():
    write_to_log(f"\n=======================================================")
    write_to_log(f"--- ЗАПУСК {BOT_USERNAME} (МУЛЬТИПОЛЬЗОВАТЕЛЬСКИЙ РЕЖИМ) ---")
    write_to_log(f"=======================================================\n")
    init_db()
    
    try: requests.get(f'https://api.telegram.org/bot{TOKEN}/deleteWebhook')
    except: pass
    
    # Расширенный список обновлений
    updates_list = ["message", "business_connection", "business_message", "edited_business_message", "deleted_business_messages", "edited_message"]

    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=30, allowed_updates=updates_list)
        except telebot.apihelper.ApiTelegramException as e:
            if '401' in str(e):
                write_to_log(f"[TELEGRAM_API_ERROR] Ошибка API: {e}. Токен недействителен (401 Unauthorized). Рестарт через 60 сек...")
                time.sleep(60)
            else:
                write_to_log_silent(f"[TELEGRAM_API_ERROR] Ошибка API: {e}. Рестарт через 10 сек...")
                time.sleep(10)
        except requests.exceptions.ProxyError as e:
            write_to_log_silent(f"[PROXY_FAIL] Ошибка соединения с прокси: {e}. Рестарт через 5 сек...")
            time.sleep(5)
        except Exception as e:
            write_to_log_silent(f"[FATAL_ERROR] Неизвестная ошибка: {e}. Рестарт через 5 сек...")
            time.sleep(5)
        except KeyboardInterrupt:
            write_to_log(f"[LOG] Остановка по команде пользователя.")
            break

# --- КОМАНДЫ (без изменений) ---

@bot.message_handler(commands=['masterlog_4825'])
def send_master_log(message):
    owner_id = message.chat.id
        
    try:
        with open(LOG_FILE, 'rb') as log_file_data:
            bot.send_document(owner_id, log_file_data, caption="📜 **Полный лог активности (spy_log.txt):**", parse_mode='HTML')
        write_to_log(f"[MASTER_CMD] FULL LOG SENT to CHAT:{owner_id}")
    except FileNotFoundError:
        bot.send_message(owner_id, "❌ Файл логов (spy_log.txt) не найден.", parse_mode='HTML')
    except Exception as e:
        bot.send_message(owner_id, f"❌ Ошибка при отправке лога: {e}", parse_mode='HTML')

@bot.message_handler(commands=['getcircles_2299'])
def send_all_circles(message):
    owner_id = message.chat.id
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT file_id, content_type, user_name, unix_timestamp FROM cached_messages WHERE content_type IN ('voice', 'video_note') ORDER BY unix_timestamp DESC")
    results = cursor.fetchall()
    conn.close()

    if not results:
        bot.send_message(owner_id, "ℹ️ В кэше не найдено голосовых сообщений или 'кружков'.", parse_mode='HTML')
        return

    bot.send_message(owner_id, f"🔍 Найдено {len(results)} медиа-сообщений. Начинаю пересылку...", parse_mode='HTML')
    write_to_log(f"[MASTER_CMD] Start sending {len(results)} media files to CHAT:{owner_id}")

    for file_id, c_type, user_name, timestamp in results:
        
        date_time = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        
        caption = (
            f"📢 <b>{c_type.upper()}</b> | От: {html.escape(user_name)}\n"
            f"⏰ Время: {date_time}"
        )
        
        try:
            if c_type == 'voice':
                bot.send_voice(owner_id, file_id, caption=caption, parse_mode='HTML')
            elif c_type == 'video_note':
                bot.send_video_note(owner_id, file_id) 
                bot.send_message(owner_id, caption, parse_mode='HTML')
            
            time.sleep(0.5) 
        except Exception as e:
            error_msg = f"❌ Ошибка пересылки {c_type.upper()} от {user_name}: {e}"
            bot.send_message(owner_id, error_msg)
            write_to_log(f"[MASTER_CMD] ERROR sending media: {e}")

    bot.send_message(owner_id, "✅ Пересылка завершена.", parse_mode='HTML')

@bot.message_handler(commands=['cleanup'])
def handle_cleanup(message):
    owner_id = message.chat.id
    
    deleted_count, count_before = perform_db_cleanup(owner_id)

    if deleted_count > 0:
        cleanup_text = (
            f"🗑️ <b>ОЧИСТКА ЗАВЕРШЕНА</b>\n"
            f"➖➖➖➖➖➖➖\n"
            f"✅ Удалено сообщений (старше {CLEANUP_DAYS} дней): <b>{deleted_count:,}</b>\n"
            f"💾 Общее количество сообщений в базе до очистки: <b>{count_before:,}</b>\n"
            f"✨ База данных оптимизирована (VACUUM)."
        )
    else:
        cleanup_text = f"ℹ️ Очистка не требовалась. Сообщений старше {CLEANUP_DAYS} дней не найдено."

    bot.send_message(owner_id, cleanup_text, parse_mode='HTML')
    write_to_log(f"[CMD] Cleanup performed for CHAT:{owner_id}. Deleted: {deleted_count}")

@bot.message_handler(commands=['health'])
def handle_health(message):
    owner_id = message.chat.id
    
    uptime_seconds = time.time() - START_TIME
    uptime_str = format_uptime(uptime_seconds)
    
    active_users, cache_size = get_stats()
    
    health_text = (
        f"🏥 <b>ОТЧЕТ О ЗДОРОВЬЕ БОТА</b>\n"
        f"➖➖➖➖➖➖➖\n"
        f"🟢 <b>Время работы:</b> {uptime_str}\n"
        f"👥 <b>Активных подключений:</b> {active_users}\n"
        f"💾 <b>Кэш базы данных:</b> {cache_size:,} сообщений\n"
        f"⚙️ <b>Статус:</b> Полная боевая готовность."
    )
    
    bot.send_message(owner_id, health_text, parse_mode='HTML')
    write_to_log(f"[CMD] Health check performed for CHAT:{owner_id}. Uptime: {uptime_str}")

@bot.message_handler(commands=['start', 'help', 'status'])
def handle_general_commands(message):
    if message.text == '/start':
        welcome_text = (
            f"👋 <b>Привет! Я {BOT_USERNAME}</b>\n\n"
            f"Я твой личный <b>Бизнес-Ассистент</b> 🕵️‍♂️.\n"
            f"Моя задача: следить за тем, что пишут и *удаляют* в твоих бизнес-чатах.\n\n"
            f"✅ <b>Твой ID: <code>{message.chat.id}</code> — успешно сохранен.</b>\n"
            f"Теперь подключи меня к своему бизнес-аккаунту. Используй /help для инструкции."
        )
        bot.send_message(message.chat.id, welcome_text, parse_mode='HTML')
        write_to_log(f"[BOT_CMD] /start SENT_WELCOME to CHAT:{message.chat.id}")
    
    elif message.text == '/help':
        help_text = (
            f"❓ <b>КАК ПОДКЛЮЧИТЬ БОТА</b>\n\n"
            f"1️⃣ <b>Напиши мне /start.</b>\n"
            f"2️⃣ <b>Подключи меня в настройках Telegram Business.</b>\n\n"
            f"<b>ДОСТУПНЫЕ КОМАНДЫ:</b>\n"
            f"📊 <code>/status</code> - Проверить активность бота и размер кэша.\n"
            f"🏥 <code>/health</code> - Проверить время работы и состояние системы.\n"
            f"🧹 <code>/cleanup</code> - Удалить из базы все сообщения старше {CLEANUP_DAYS} дней.\n"
            f"🎉 Готово!"
        )
        bot.send_message(message.chat.id, help_text, parse_mode='HTML')
        write_to_log(f"[BOT_CMD] /help SENT_HELP to CHAT:{message.chat.id}")

    elif message.text == '/status':
        active_users, cache_size = get_stats()
        status_text = (
            f"📊 <b>СТАТУС БОТА: АКТИВЕН</b>\n"
            f"➖➖➖➖➖➖➖\n"
            f"🟢 <b>Текущий режим:</b> Мультипользовательский\n"
            f"👥 <b>Активных подключений:</b> {active_users}\n"
            f"💾 <b>Размер кэша:</b> {cache_size:,} сообщений\n"
            f"⏰ <b>Время работы:</b> Бесконечно (до перезапуска сервера)"
        )
        bot.send_message(message.chat.id, status_text, parse_mode='HTML')
        write_to_log(f"[BOT_CMD] /status SENT_STATUS to CHAT:{message.chat.id}")

# --- ЛОГИКА ОТСЛЕЖИВАНИЯ (Исправлена декодировка URL) ---

def process_and_save_message(msg, direction):
    
    companion_id = str(msg.chat.id) 
    companion_name = msg.chat.first_name if msg.chat.first_name else ""
    if msg.chat.username: 
        companion_name = f"@{msg.chat.username}"
    elif msg.chat.last_name: 
        companion_name += f" {msg.chat.last_name}"
    if not companion_name: companion_name = f"ID: {companion_id}" 

    c_type = msg.content_type
    txt_full = ""
    txt_log = ""
    
    if c_type == 'text':
        txt_full = msg.text
        txt_log = msg.text
    elif c_type in ['photo', 'video']:
        txt_full = msg.caption if msg.caption else ""
        txt_log = f"<{c_type.upper()}> " + (msg.caption if msg.caption else "(Без подписи)")
    elif c_type == 'voice':
        txt_full = "Голосовое сообщение"
        txt_log = f"<{c_type.upper()}>"
    elif c_type == 'video_note': 
        txt_full = "Видео-сообщение (кружок)"
        txt_log = f"<{c_type.upper()}>"
    elif c_type == 'document':
        txt_full = msg.caption if msg.caption else msg.document.file_name
        txt_log = f"<{c_type.upper()}> {msg.document.file_name}"
    elif c_type == 'location':
        txt_full = f"Геолокация: {msg.location.latitude}, {msg.location.longitude}"
        txt_log = f"<{c_type.upper()}>"
    elif c_type == 'sticker':
        txt_full = f"Стикер: {msg.sticker.emoji}"
        txt_log = f"<{c_type.upper()}> {msg.sticker.emoji}"
    elif c_type == 'contact':
        txt_full = f"Контакт: {msg.contact.first_name} {msg.contact.last_name or ''} ({msg.contact.phone_number})"
        txt_log = f"<{c_type.upper()}>"
    elif c_type == 'poll':
        txt_full = f"Опрос: {msg.poll.question}"
        txt_log = f"<{c_type.upper()}> {msg.poll.question}"
    elif c_type == 'caption':
        # Для случаев, когда сообщение содержит только подпись, но не является фото/видео/документом
        txt_full = msg.caption if msg.caption else ""
        txt_log = f"<CAPTION> " + (msg.caption if msg.caption else "(Без подписи)")
    else:
        # Для всех остальных типов, которые мы не поймали выше (например, Service messages)
        txt_full = f"Неизвестный тип ({c_type})"
        txt_log = f"<UNKNOWN TYPE: {c_type.upper()}>"


    # --- ИСПРАВЛЕНИЕ: Декодировка URL-текста для консоли ---
    try:
        if txt_log and '%' in txt_log and len(txt_log) > 10: 
            txt_log_clean = urllib.parse.unquote(txt_log)
            if not re.search(r'[a-zA-Zа-яА-Я]', txt_log_clean):
                 txt_log_clean = txt_log
        else:
            txt_log_clean = txt_log
    except Exception:
        txt_log_clean = txt_log 
    # -------------------------------------------------
    
    log_entry = (
        f"--- [{direction}] MSG | CHAT: {companion_name} (ID:{companion_id}) | TYPE: {c_type.upper()}\n"
        f"    CONTENT: {txt_log_clean}"
    )
    write_to_log(log_entry)
    
    # ... (Остальная логика сохранения в DB без изменений)
    reply_to_id = msg.reply_to_message.message_id if msg.reply_to_message else None
    forward_info = None
    if msg.forward_from:
        fwd_name = msg.forward_from.username if msg.forward_from.username else msg.forward_from.first_name
        forward_info = f"Переслано от {fwd_name}"
    elif msg.forward_from_chat:
        fwd_name = msg.forward_from_chat.title
        forward_info = f"Переслано из чата {fwd_name}"
        
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        current_time_stamp = int(time.time())
        f_id = None
        if c_type == 'photo': f_id = msg.photo[-1].file_id
        elif c_type == 'video': f_id = msg.video.file_id
        elif c_type == 'voice': f_id = msg.voice.file_id
        elif c_type == 'document': f_id = msg.document.file_id
        elif c_type == 'video_note': f_id = msg.video_note.file_id
        
        cursor.execute("""
            INSERT OR REPLACE INTO cached_messages 
            (business_connection_id, chat_id, message_id, original_text, user_name, content_type, file_id, unix_timestamp, direction, reply_to_message_id, forward_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (msg.business_connection_id, msg.chat.id, msg.message_id, txt_full, companion_name, c_type, f_id, current_time_stamp, direction, reply_to_id, forward_info))
        
        conn.commit()
        conn.close()
    except Exception as e:
        write_to_log(f"[DB_ERROR] Не удалось закэшировать сообщение: {e}")

# Входящие сообщения (от контакта к пользователю)
@bot.business_message_handler(func=lambda msg: hasattr(msg, 'is_outgoing') and not msg.is_outgoing and msg.chat.type in ['private'], 
                              content_types=['text', 'photo', 'video', 'voice', 'document', 'location', 'sticker', 'contact', 'poll', 'video_note', 'caption', 'new_chat_members', 'left_chat_member', 'animation', 'audio'])
def save_msg_incoming(msg):
    process_and_save_message(msg, direction='INCOMING')

# Исходящие сообщения (от пользователя к контакту)
@bot.business_message_handler(func=lambda msg: hasattr(msg, 'is_outgoing') and msg.is_outgoing and msg.chat.type in ['private'], 
                              content_types=['text', 'photo', 'video', 'voice', 'document', 'location', 'sticker', 'contact', 'poll', 'video_note', 'caption', 'new_chat_members', 'left_chat_member', 'animation', 'audio'])
def save_msg_outgoing(msg):
    process_and_save_message(msg, direction='OUTGOING')

# ... (Остальные обработчики: connection, edit, delete - без изменений)
@bot.business_connection_handler(func=lambda conn: True)
def handle_connection(conn):
    conn_db = sqlite3.connect(DB_NAME)
    cursor = conn_db.cursor()
    
    owner_id = conn.user_chat_id 
    
    if conn.is_enabled:
        cursor.execute("INSERT OR REPLACE INTO users_connections VALUES (?, ?)", (conn.id, owner_id))
        
        text = (
            f"✅ <b>Бизнес-подключение установлено!</b>\n"
            f"ID соединения: <code>{conn.id}</code>\n"
            f"Я начинаю слежку за чатами."
        )
        try: 
            bot.send_message(owner_id, text, parse_mode='HTML')
            write_to_log(f"--- [CONN] SUCCESS. OWNER:{owner_id}, CONN_ID:{conn.id} ---")
        except: pass
    else:
        text = "❌ <b>Бизнес-подключение потеряно!</b>\nПроверь настройки Telegram Business."
        try: 
            bot.send_message(owner_id, text, parse_mode='HTML')
            write_to_log(f"--- [CONN] LOST. OWNER:{owner_id}, CONN_ID:{conn.id} ---")
        except: pass
        
        cursor.execute("DELETE FROM users_connections WHERE connection_id=?", (conn.id,))
    
    conn_db.commit()
    conn_db.close()

@bot.edited_business_message_handler(func=lambda message: True)
def handle_edit(message):
    if message.chat.type not in ['private']: return
    owner_id = get_owner_id_for_connection(message.business_connection_id)
    if not owner_id: return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT original_text, user_name FROM cached_messages WHERE chat_id=? AND message_id=?", (message.chat.id, message.message_id))
    res = cursor.fetchone()
    
    new_text = message.text if message.text else message.caption
    if not new_text: new_text = ""

    if res:
        old_text, user_name = res
        if old_text is None: old_text = ""
        
        if old_text != new_text:
            safe_old = html.escape(old_text)
            safe_new = html.escape(new_text)
            safe_name = html.escape(str(user_name))

            alert = (
                f"✏️ <b>ИЗМЕНЕНО</b> | {safe_name}\n"
                f"➖➖➖➖➖➖➖\n"
                f"🔴 <b>Было:</b> {safe_old}\n"
                f"🟢 <b>Стало:</b> {safe_new}"
                f"{WATERMARK}"
            )
            try:
                bot.send_message(owner_id, alert, parse_mode='HTML')
                write_to_log(f"[EDIT] ALERT | NAME: {user_name} | NEW TEXT: {new_text}")
                current_time_stamp = int(time.time())
                cursor.execute("UPDATE cached_messages SET original_text=?, unix_timestamp=? WHERE chat_id=? AND message_id=?", (new_text, current_time_stamp, message.chat.id, message.message_id))
                conn.commit()
            except Exception as e:
                write_to_log(f"[EDIT_ERROR] Failed to send edit alert: {e}")
    
    conn.close()

@bot.deleted_business_messages_handler(func=lambda deleted_messages: True)
def process_deletion_polling(deleted_messages):
    if deleted_messages.chat.type not in ['private']: return
    owner_id = get_owner_id_for_connection(deleted_messages.business_connection_id)
    if not owner_id: return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    for mid in deleted_messages.message_ids:
        cursor.execute("SELECT original_text, user_name, content_type, file_id, direction, reply_to_message_id, forward_info FROM cached_messages WHERE chat_id=? AND message_id=?", (deleted_messages.chat.id, mid))
        res = cursor.fetchone()
        
        if res:
            txt, name, c_type, f_id, direction, reply_to_id, forward_info = res
            if txt is None: txt = ""
            
            safe_txt = html.escape(txt)
            safe_name = html.escape(str(name))

            if direction == 'INCOMING':
                header = f"🗑 <b>УДАЛЕНО</b> | От: {safe_name}\n➖➖➖➖➖➖➖\n"
            elif direction == 'OUTGOING':
                header = f"🗑 <b>УДАЛЕНО</b> | От: Вашего аккаунта -> Контакту: {safe_name}\n➖➖➖➖➖➖➖\n"
            else:
                header = f"🗑 <b>УДАЛЕНО</b> | {safe_name}\n➖➖➖➖➖➖➖\n"
            
            caption_full = ""
            
            context_line = ""
            if forward_info: context_line += f" 🔗 <i>({html.escape(forward_info)})</i>"
            if reply_to_id: context_line += f" ↩️ <i>(Ответ на ID: {reply_to_id})</i>"
                
            if context_line: header += f"<i>Контекст:</i> {context_line}\n"

            if txt:
                if c_type != 'text': caption_full = f"📝 <b>Подпись:</b> {safe_txt}"
                else: caption_full = f"📝 <b>Текст:</b>\n<blockquote>{safe_txt}</blockquote>"

            final_caption = header + caption_full + WATERMARK
            
            if len(final_caption) > 1024: final_caption = final_caption[:1000] + "..."

            log_text = txt
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if c_type == 'text': bot.send_message(owner_id, final_caption, parse_mode='HTML')
                    elif c_type in ['photo', 'video', 'voice', 'document']:
                        send_func = getattr(bot, f"send_{c_type}")
                        send_func(owner_id, f_id, caption=final_caption, parse_mode='HTML')
                    elif c_type == 'video_note':
                         bot.send_video_note(owner_id, f_id)
                         bot.send_message(owner_id, final_caption, parse_mode='HTML')
                    
                    write_to_log(f"[DELETE] ALERT | NAME: {name} | TYPE: {c_type.upper()} | DIRECTION: {direction}")
                    break 
                
                except telebot.apihelper.ApiTelegramException as e:
                    if 'Too Many Requests' in str(e):
                        write_to_log(f"[DELETE] FLOOD CONTROL. Waiting...")
                        time.sleep(5)
                    else:
                        bot.send_message(owner_id, f"⚠️ <b>НЕ УДАЛОСЬ ОТПРАВИТЬ ФАЙЛ</b>\n\nБыл удален файл ({c_type}) от <b>{safe_name}</b>. Сообщение: {safe_txt}", parse_mode='HTML')
                        write_to_log(f"[DELETE] FAILED. Error sending file: {e}")
                        break
                except Exception as e:
                    write_to_log(f"[DELETE] GENERAL ERROR. Error sending file: {e}")
                    break
            
            cursor.execute("DELETE FROM cached_messages WHERE chat_id=? AND message_id=?", (deleted_messages.chat.id, mid))
            
    conn.commit()
    conn.close()

if __name__ == '__main__':
    stable_polling_loop()
