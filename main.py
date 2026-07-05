import telebot
from telebot import types
import sqlite3
import re
import logging
from datetime import datetime, timedelta
import threading
import time

# ========================================================================
# 1. НАСТРОЙКИ ЛОГИРОВАНИЯ И БОТА
# ========================================================================

# Настраиваем подробное логирование для отслеживания работы бота
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_log.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("RivalsTransferBot")

# Токен, который вы указали
TOKEN = '8768994062:AAFWMZZIl19tDmnKjBcyFXEnE_BZLw5ckw0'
bot = telebot.TeleBot(TOKEN, parse_mode='HTML')

# ========================================================================
# 2. ГЛОБАЛЬНЫЕ КОНФИГУРАЦИОННЫЕ ПЕРЕМЕННЫЕ
# ========================================================================

# ВАЖНО: Замените на реальные ID перед полноценным запуском
CHANNEL_ID = '@your_channel_id_here'  # ID канала, куда публикуются новости
MODERATION_CHAT_ID = -1000000000000  # ID чата админов для проверки анкет
GLOBAL_ADMINS = [123456789, 987654321]  # Список ID администраторов

# ========================================================================
# 3. КЛАСС УПРАВЛЕНИЯ БАЗОЙ ДАННЫХ
# ========================================================================

class DatabaseManager:
    """
    Класс для управления базой данных SQLite3.
    Все методы обернуты в блокировки (Lock) для безопасной работы в многопоточном режиме,
    так как pyTelegramBotAPI работает в несколько потоков.
    """
    
    def __init__(self, db_path: str = "rivals_transfers.db"):
        """Инициализация подключения и создание таблиц."""
        self.db_path = db_path
        self.lock = threading.Lock()
        self.init_db()

    def _get_connection(self):
        """Внутренний метод для получения подключения к БД."""
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        """Создание всех необходимых таблиц при запуске, если они не существуют."""
        logger.info("Инициализация базы данных...")
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Таблица пользователей
            # Хранит все данные игроков, их кулдауны и статусы банов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    nickname TEXT UNIQUE,
                    club_id INTEGER DEFAULT 0,
                    is_banned INTEGER DEFAULT 0,
                    free_agent_cd TEXT DEFAULT '2000-01-01 00:00:00',
                    custom_text_cd TEXT DEFAULT '2000-01-01 00:00:00',
                    career_ended_until TEXT DEFAULT '2000-01-01 00:00:00',
                    name_change_cd TEXT DEFAULT '2000-01-01 00:00:00'
                )
            ''')
            
            # Таблица клубов
            # Хранит информацию о командах, владельцах и заместителях
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS clubs (
                    club_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    owner_id INTEGER,
                    deputy1_nick TEXT DEFAULT '',
                    deputy2_nick TEXT DEFAULT '',
                    transfers_count INTEGER DEFAULT 0
                )
            ''')
            
            # Таблица заявок на проверку
            # Хранит посты, которые ждут одобрения администраторов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pending_posts (
                    post_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    post_text TEXT
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("База данных успешно инициализирована.")

    # --------------------------------------------------------------------
    # МЕТОДЫ ДЛЯ РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ
    # --------------------------------------------------------------------

    def register_user(self, user_id: int, username: str, nickname: str) -> bool:
        """
        Регистрация нового пользователя.
        Возвращает True, если успешно, и False, если ник уже занят.
        """
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    'INSERT INTO users (user_id, username, nickname) VALUES (?, ?, ?)',
                    (user_id, username, nickname)
                )
                conn.commit()
                logger.info(f"Зарегистрирован новый пользователь: {nickname} ({user_id})")
                return True
            except sqlite3.IntegrityError:
                logger.warning(f"Попытка регистрации с занятым ником: {nickname}")
                return False
            finally:
                conn.close()

    def get_user_by_id(self, user_id: int) -> dict:
        """Получение полной информации о пользователе по его Telegram ID."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    'user_id': row[0],
                    'username': row[1],
                    'nickname': row[2],
                    'club_id': row[3],
                    'is_banned': bool(row[4]),
                    'free_agent_cd': row[5],
                    'custom_text_cd': row[6],
                    'career_ended_until': row[7],
                    'name_change_cd': row[8]
                }
            return None

    def get_user_by_nickname(self, nickname: str) -> dict:
        """Получение полной информации о пользователе по игровому нику."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE nickname = ?', (nickname,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    'user_id': row[0],
                    'username': row[1],
                    'nickname': row[2],
                    'club_id': row[3],
                    'is_banned': bool(row[4]),
                    'free_agent_cd': row[5],
                    'custom_text_cd': row[6],
                    'career_ended_until': row[7],
                    'name_change_cd': row[8]
                }
            return None

    def update_user_nickname(self, user_id: int, new_nickname: str) -> bool:
        """Смена никнейма пользователя."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    'UPDATE users SET nickname = ? WHERE user_id = ?',
                    (new_nickname, user_id)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                conn.close()

    def update_user_club(self, nickname: str, club_id: int):
        """Обновление привязки пользователя к клубу (вступление/выход)."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET club_id = ? WHERE nickname = ?',
                (club_id, nickname)
            )
            conn.commit()
            conn.close()

    def set_user_ban_status(self, nickname: str, is_banned: int):
        """Выдача или снятие бана игроку."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE users SET is_banned = ? WHERE nickname = ?',
                (is_banned, nickname)
            )
            conn.commit()
            conn.close()

    # --- Отдельные методы для обновления каждого кулдауна ---

    def set_free_agent_cooldown(self, user_id: int, time_str: str):
        """Установка кулдауна для поиска клуба (Свободный агент)."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET free_agent_cd = ? WHERE user_id = ?', (time_str, user_id))
            conn.commit()
            conn.close()

    def set_custom_text_cooldown(self, user_id: int, time_str: str):
        """Установка кулдауна для публикации своего текста."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET custom_text_cd = ? WHERE user_id = ?', (time_str, user_id))
            conn.commit()
            conn.close()

    def set_career_end_cooldown(self, user_id: int, time_str: str):
        """Установка срока завершения карьеры."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET career_ended_until = ? WHERE user_id = ?', (time_str, user_id))
            conn.commit()
            conn.close()

    def set_name_change_cooldown(self, user_id: int, time_str: str):
        """Установка кулдауна на смену никнейма."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET name_change_cd = ? WHERE user_id = ?', (time_str, user_id))
            conn.commit()
            conn.close()

    # --------------------------------------------------------------------
    # МЕТОДЫ ДЛЯ РАБОТЫ С КЛУБАМИ
    # --------------------------------------------------------------------

    def create_club(self, club_name: str, owner_id: int) -> bool:
        """Создание нового клуба админом и автоматическая привязка владельца."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                # Создаем клуб
                cursor.execute(
                    'INSERT INTO clubs (name, owner_id) VALUES (?, ?)',
                    (club_name, owner_id)
                )
                club_id = cursor.lastrowid
                # Привязываем владельца к клубу
                cursor.execute(
                    'UPDATE users SET club_id = ? WHERE user_id = ?',
                    (club_id, owner_id)
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
            finally:
                conn.close()

    def delete_club(self, club_id: int):
        """Удаление клуба и автоматическое исключение всех игроков из него."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            # Отвязываем всех игроков от этого клуба
            cursor.execute('UPDATE users SET club_id = 0 WHERE club_id = ?', (club_id,))
            # Удаляем сам клуб
            cursor.execute('DELETE FROM clubs WHERE club_id = ?', (club_id,))
            conn.commit()
            conn.close()

    def get_all_clubs(self) -> list:
        """Получение списка всех существующих клубов."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT club_id, name FROM clubs')
            clubs = cursor.fetchall()
            conn.close()
            return clubs

    def get_club_by_id(self, club_id: int) -> dict:
        """Получение полной информации о клубе по его ID."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM clubs WHERE club_id = ?', (club_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    'club_id': row[0],
                    'name': row[1],
                    'owner_id': row[2],
                    'deputy1_nick': row[3],
                    'deputy2_nick': row[4],
                    'transfers_count': row[5]
                }
            return None

    def get_club_by_manager(self, user_id: int, user_nickname: str) -> dict:
        """
        Проверка, является ли игрок владельцем ИЛИ заместителем какого-либо клуба.
        Возвращает данные клуба, если у игрока есть права управления.
        """
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM clubs 
                WHERE owner_id = ? OR deputy1_nick = ? OR deputy2_nick = ?
            ''', (user_id, user_nickname, user_nickname))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    'club_id': row[0],
                    'name': row[1],
                    'owner_id': row[2],
                    'deputy1_nick': row[3],
                    'deputy2_nick': row[4],
                    'transfers_count': row[5]
                }
            return None

    def get_club_members(self, club_id: int) -> list:
        """Получение списка никнеймов всех игроков клуба."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT nickname FROM users WHERE club_id = ?', (club_id,))
            members = [row[0] for row in cursor.fetchall()]
            conn.close()
            return members

    def increment_club_transfers(self, club_id: int):
        """Увеличение счетчика успешных переходов для клуба."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE clubs SET transfers_count = transfers_count + 1 WHERE club_id = ?', 
                (club_id,)
            )
            conn.commit()
            conn.close()

    def set_club_deputy(self, club_id: int, slot: int, nickname: str):
        """Назначение или снятие заместителя (slot = 1 или 2)."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            column_name = 'deputy1_nick' if slot == 1 else 'deputy2_nick'
            
            query = f'UPDATE clubs SET {column_name} = ? WHERE club_id = ?'
            cursor.execute(query, (nickname, club_id))
            
            conn.commit()
            conn.close()

    # --------------------------------------------------------------------
    # МЕТОДЫ ДЛЯ РАБОТЫ С ЗАЯВКАМИ (ПОСТАМИ)
    # --------------------------------------------------------------------

    def create_pending_post(self, user_id: int, post_text: str) -> int:
        """Создание новой заявки на публикацию и возврат её ID."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO pending_posts (user_id, post_text) VALUES (?, ?)',
                (user_id, post_text)
            )
            post_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return post_id

    def get_pending_post(self, post_id: int) -> str:
        """Получение текста заявки по её ID."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT post_text FROM pending_posts WHERE post_id = ?', (post_id,))
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None

    def delete_pending_post(self, post_id: int):
        """Удаление заявки после одобрения или отклонения."""
        with self.lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM pending_posts WHERE post_id = ?', (post_id,))
            conn.commit()
            conn.close()

# Инициализируем базу данных в глобальную переменную
db = DatabaseManager()

# ========================================================================
# 4. ГЕНЕРАТОРЫ КЛАВИАТУР И ИНТЕРФЕЙСА
# ========================================================================

def get_main_menu_keyboard() -> types.ReplyKeyboardMarkup:
    """Генерация главной панели кнопок (ReplyKeyboardMarkup) для игрока."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    # Создаем кнопки по вашему ТЗ
    btn_free_agent = types.KeyboardButton("Свободный агент")
    btn_custom_text = types.KeyboardButton("Своего текста")
    btn_end_career = types.KeyboardButton("Завершения карьеры")
    btn_return_career = types.KeyboardButton("Возращения карьеры")
    btn_change_nick = types.KeyboardButton("Смена никнейма")
    btn_help = types.KeyboardButton("Помощь")
    btn_profile = types.KeyboardButton("Профиль")
    btn_my_club = types.KeyboardButton("мой клуб")
    
    # Добавляем кнопки в клавиатуру
    markup.add(
        btn_free_agent, 
        btn_custom_text, 
        btn_end_career, 
        btn_return_career, 
        btn_change_nick, 
        btn_help, 
        btn_profile, 
        btn_my_club
    )
    return markup

def get_moderation_keyboard(post_id: int) -> types.InlineKeyboardMarkup:
    """Генерация инлайн кнопок для админов (Принять / Отклонить)."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_accept = types.InlineKeyboardButton(
        text="✅ Принять", 
        callback_data=f"accept_post_{post_id}"
    )
    btn_reject = types.InlineKeyboardButton(
        text="❌ Отклонить", 
        callback_data=f"reject_post_{post_id}"
    )
    
    markup.add(btn_accept, btn_reject)
    return markup

def get_club_management_keyboard(club_id: int, is_owner: bool) -> types.InlineKeyboardMarkup:
    """Генерация инлайн клавиатуры для управления замами (только для владельца)."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if is_owner:
        btn_add_deputy = types.InlineKeyboardButton(
            text="➕ Добавить зама", 
            callback_data=f"add_deputy_{club_id}"
        )
        btn_del_deputy = types.InlineKeyboardButton(
            text="➖ Убрать зама", 
            callback_data=f"del_deputy_{club_id}"
        )
        markup.add(btn_add_deputy, btn_del_deputy)
        
    return markup

def get_remove_deputy_keyboard(club_id: int, dep1: str, dep2: str) -> types.InlineKeyboardMarkup:
    """Генерация меню выбора заместителя для снятия с должности."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    if dep1:
        markup.add(types.InlineKeyboardButton(
            text=f"Снять: {dep1}", 
            callback_data=f"rm_dep_{club_id}_1"
        ))
    if dep2:
        markup.add(types.InlineKeyboardButton(
            text=f"Снять: {dep2}", 
            callback_data=f"rm_dep_{club_id}_2"
        ))
        
    markup.add(types.InlineKeyboardButton(
        text="🔙 Отмена", 
        callback_data="cancel_action"
    ))
    return markup

def get_club_deletion_list_keyboard(clubs: list) -> types.InlineKeyboardMarkup:
    """Генерация списка клубов для админ-панели (Удаление клуба)."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for club in clubs:
        club_id = club[0]
        club_name = club[1]
        markup.add(types.InlineKeyboardButton(
            text=f"🗑 {club_name}", 
            callback_data=f"confirm_del_club_{club_id}"
        ))
        
    return markup

def get_club_deletion_confirm_keyboard(club_id: int) -> types.InlineKeyboardMarkup:
    """Подтверждение удаления клуба администратором."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_yes = types.InlineKeyboardButton(
        text="⚠️ Да, удалить клуб", 
        callback_data=f"execute_del_club_{club_id}"
    )
    btn_no = types.InlineKeyboardButton(
        text="Отмена", 
        callback_data="cancel_action"
    )
    
    markup.add(btn_yes, btn_no)
    return markup

# ========================================================================
# 5. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ПРОВЕРКИ И ВРЕМЯ)
# ========================================================================

def get_current_time() -> datetime:
    """Возвращает текущее время для расчетов кулдаунов."""
    return datetime.now()

def parse_db_time(time_str: str) -> datetime:
    """Преобразует строку времени из базы данных в объект datetime."""
    try:
        return datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        logger.error(f"Ошибка парсинга времени: {time_str}")
        return datetime(2000, 1, 1)

def check_user_access(message: types.Message, user_data: dict) -> bool:
    """
    Глобальная проверка прав пользователя перед любым действием.
    Проверяет, зарегистрирован ли игрок, не забанен ли он и не завершил ли карьеру.
    """
    if not user_data:
        bot.send_message(
            message.chat.id, 
            "⚠️ Вы не зарегистрированы! Напишите /start для регистрации."
        )
        return False
        
    if user_data['is_banned']:
        bot.send_message(
            message.chat.id, 
            "⛔️ Вы были заблокированы администрацией и не можете использовать эту функцию."
        )
        return False
        
    career_end_time = parse_db_time(user_data['career_ended_until'])
    if get_current_time() < career_end_time:
        days_left = (career_end_time - get_current_time()).days
        bot.send_message(
            message.chat.id, 
            f"🥀 Вы завершили карьеру. \n"
            f"Ожидайте окончания срока. Осталось дней: {days_left}\n"
            f"Дата окончания: {career_end_time.strftime('%Y-%m-%d %H:%M')}"
        )
        return False
        
    return True

def send_post_to_moderation(user_id: int, text: str, original_message: types.Message):
    """Отправляет сформированный пост в чат модерации."""
    try:
        # Сохраняем пост в БД и получаем его ID
        post_id = db.create_pending_post(user_id, text)
        
        # Генерируем клавиатуру Принять/Отклонить
        markup = get_moderation_keyboard(post_id)
        
        # Отправляем админам
        admin_text = f"📩 <b>НОВАЯ АНКЕТА НА ПРОВЕРКУ</b> 📩\n\n{text}"
        bot.send_message(
            MODERATION_CHAT_ID, 
            admin_text, 
            reply_markup=markup
        )
        
        # Уведомляем пользователя
        bot.send_message(
            original_message.chat.id, 
            "✅ Ваша анкета успешно отправлена на проверку администраторам! Ожидайте публикации."
        )
        logger.info(f"Пользователь {user_id} отправил пост {post_id} на модерацию.")
    except Exception as e:
        logger.error(f"Ошибка при отправке на модерацию: {e}")
        bot.send_message(original_message.chat.id, "❌ Произошла ошибка при отправке анкеты.")

# ========================================================================
# 6. РЕГИСТРАЦИЯ И СТАРТ КОМАНДЫ
# ========================================================================

@bot.message_handler(commands=['start'])
def command_start(message: types.Message):
    """Обработчик команды /start."""
    user_id = message.from_user.id
    user_data = db.get_user_by_id(user_id)
    
    if user_data:
        # Если пользователь уже есть в базе
        bot.send_message(
            message.chat.id, 
            f"👋 С возвращением, {user_data['nickname']}!\n"
            f"Добро пожаловать в трансфермаркет по игре Rivals.", 
            reply_markup=get_main_menu_keyboard()
        )
    else:
        # Начинаем процесс регистрации
        welcome_text = (
            "👋 Привествуем вас в трансфермаркете по игре Rivals!\n\n"
            "Для начала работы нам нужно зарегистрировать ваш игровой профиль.\n"
            "Пожалуйста, введите ваш никнейм в игре <b>(ТОЛЬКО английскими буквами и цифрами)</b>:"
        )
        msg = bot.send_message(message.chat.id, welcome_text)
        bot.register_next_step_handler(msg, process_registration_nickname)

def process_registration_nickname(message: types.Message):
    """Проверка и сохранение никнейма при регистрации."""
    user_id = message.from_user.id
    nickname = message.text.strip()
    
    # Получаем юзернейм или ставим заглушку
    username = f"@{message.from_user.username}" if message.from_user.username else "Скрыт"
    
    # Строгая проверка на английские буквы и цифры
    if not re.match(r'^[A-Za-z0-9_]+$', nickname):
        msg = bot.send_message(
            message.chat.id, 
            "❌ Ошибка! Никнейм должен содержать только английские буквы, цифры и символ подчеркивания.\n\n"
            "Попробуйте ввести никнейм еще раз:"
        )
        bot.register_next_step_handler(msg, process_registration_nickname)
        return
        
    # Попытка записи в базу данных
    success = db.register_user(user_id, username, nickname)
    
    if success:
        bot.send_message(
            message.chat.id, 
            f"✅ Отлично! Вы успешно зарегистрированы под ником <b>{nickname}</b>.\n"
            f"Теперь вам доступно меню трансфермаркета.", 
            reply_markup=get_main_menu_keyboard()
        )
    else:
        msg = bot.send_message(
            message.chat.id, 
            "⚠️ Этот никнейм уже занят другим игроком!\n\n"
            "Пожалуйста, придумайте и введите другой никнейм:"
        )
        bot.register_next_step_handler(msg, process_registration_nickname)

# ========================================================================
# 7. ИНФОРМАЦИОННЫЕ КОМАНДЫ (ПРОФИЛЬ И ПОМОЩЬ)
# ========================================================================

@bot.message_handler(func=lambda message: message.text == "Профиль")
def menu_profile(message: types.Message):
    """Отображение профиля пользователя."""
    user_data = db.get_user_by_id(message.from_user.id)
    if not user_data:
        bot.send_message(message.chat.id, "Для начала работы напишите /start")
        return
        
    # Формируем информацию о клубе
    club_name = "Нет клуба"
    if user_data['club_id'] != 0:
        club_data = db.get_club_by_id(user_data['club_id'])
        if club_data:
            club_name = club_data['name']
            
    # Статус бана
    status_text = "🔴 ЗАБАНЕН" if user_data['is_banned'] else "🟢 Активен"
    
    # Формируем и отправляем текст профиля
    profile_text = (
        f"👤 <b>Ваш профиль в Трансфермаркете:</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📎 Юз: {user_data['username']}\n"
        f"😎 Ник: <b>{user_data['nickname']}</b>\n"
        f"🆔 ID: {user_data['user_id']}\n"
        f"🛡 Текущий клуб: <b>{club_name}</b>\n"
        f"📊 Статус: {status_text}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    bot.send_message(message.chat.id, profile_text)

@bot.message_handler(func=lambda message: message.text == "Помощь")
def menu_help(message: types.Message):
    """Отображение справочной информации."""
    help_text = (
        "📚 <b>СПРАВОЧНИК КОМАНД</b>\n\n"
        "<b>Для игроков:</b>\n"
        "🔹 <i>Свободный агент</i> - оставить анкету на поиск клуба (КД: 6 часов).\n"
        "🔹 <i>Своего текста</i> - опубликовать свое объявление (КД: 12 часов).\n"
        "🔹 <i>Завершения карьеры</i> - заморозить аккаунт на 15 дней (публикации запрещены).\n"
        "🔹 <i>Возращения карьеры</i> - снять статус завершения карьеры (после 15 дней).\n"
        "🔹 <i>Смена никнейма</i> - изменить свой игровой ник (КД: 30 дней).\n"
        "🔹 <i>Профиль</i> - посмотреть свою статистику.\n"
        "🔹 <i>мой клуб</i> - управление и просмотр своего клуба.\n\n"
        "<b>Для владельцев клубов и заместителей:</b>\n"
        "🔸 <b>/invite [ник]</b> - подписать свободного агента в свой клуб.\n"
        "🔸 <b>/delete [ник]</b> - разорвать контракт с игроком.\n"
        "🔸 <b>/viewteam</b> - просмотр состава и управление заместителями."
    )
    bot.send_message(message.chat.id, help_text)

# ========================================================================
# 8. ПУБЛИКАЦИЯ ОБЪЯВЛЕНИЙ (ГЛАВНОЕ МЕНЮ)
# ========================================================================

@bot.message_handler(func=lambda message: message.text == "Свободный агент")
def menu_free_agent(message: types.Message):
    """Начало оформления анкеты свободного агента."""
    user_id = message.from_user.id
    user_data = db.get_user_by_id(user_id)
    
    # Базовые проверки
    if not check_user_access(message, user_data):
        return
        
    # Проверка кулдауна (6 часов)
    cd_time = parse_db_time(user_data['free_agent_cd'])
    if get_current_time() < cd_time:
        time_left = cd_time - get_current_time()
        hours, remainder = divmod(int(time_left.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        
        bot.send_message(
            message.chat.id, 
            f"⏳ <b>Кулдаун!</b>\nВы сможете опубликовать анкету свободного агента через: "
            f"<b>{hours} ч. {minutes} мин.</b>\n"
            f"(До {cd_time.strftime('%H:%M %d.%m.%Y')})"
        )
        return
        
    msg = bot.send_message(
        message.chat.id, 
        "📝 Пожалуйста, напишите текст, который будет указан в поле <b>P.s:</b> (ваши пожелания к клубу, позиция и т.д.):\n\n"
        "<i>Для отмены напишите 'отмена'</i>"
    )
    bot.register_next_step_handler(msg, process_free_agent_text, user_data)

def process_free_agent_text(message: types.Message, user_data: dict):
    """Формирование и отправка анкеты свободного агента."""
    if message.text.lower() == 'отмена':
        bot.send_message(message.chat.id, "Действие отменено.", reply_markup=get_main_menu_keyboard())
        return
        
    user_text = message.text
    
    # Формируем итоговый текст по ТЗ
    final_post = (
        f"❗️СВОБОДНЫЙ АГЕНТ✌\n\n"
        f"😎 {user_data['nickname']} ({user_data['username']}) - Ищет клуб\n"
        f"P.s: {user_text}"
    )
    
    # Обновляем кулдаун (+6 часов)
    new_cd = get_current_time() + timedelta(hours=6)
    db.set_free_agent_cooldown(user_data['user_id'], new_cd.strftime('%Y-%m-%d %H:%M:%S'))
    
    # Отправляем на модерацию
    send_post_to_moderation(user_data['user_id'], final_post, message)

@bot.message_handler(func=lambda message: message.text == "Своего текста")
def menu_custom_text(message: types.Message):
    """Начало публикации своего текста."""
    user_id = message.from_user.id
    user_data = db.get_user_by_id(user_id)
    
    if not check_user_access(message, user_data):
        return
        
    # Проверка кулдауна (12 часов)
    cd_time = parse_db_time(user_data['custom_text_cd'])
    if get_current_time() < cd_time:
        time_left = cd_time - get_current_time()
        hours, remainder = divmod(int(time_left.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        
        bot.send_message(
            message.chat.id, 
            f"⏳ <b>Кулдаун!</b>\nВы сможете опубликовать свой текст через: "
            f"<b>{hours} ч. {minutes} мин.</b>\n"
            f"(До {cd_time.strftime('%H:%M %d.%m.%Y')})"
        )
        return
        
    msg = bot.send_message(
        message.chat.id, 
        "📝 Введите текст вашего объявления, который вы хотите опубликовать в канал:\n\n"
        "<i>Для отмены напишите 'отмена'</i>"
    )
    bot.register_next_step_handler(msg, process_custom_text, user_data)

def process_custom_text(message: types.Message, user_data: dict):
    """Обработка публикации своего текста."""
    if message.text.lower() == 'отмена':
        bot.send_message(message.chat.id, "Действие отменено.", reply_markup=get_main_menu_keyboard())
        return
        
    # Обновляем кулдаун (+12 часов)
    new_cd = get_current_time() + timedelta(hours=12)
    db.set_custom_text_cooldown(user_data['user_id'], new_cd.strftime('%Y-%m-%d %H:%M:%S'))
    
    # Отправляем на модерацию напрямую текст пользователя
    send_post_to_moderation(user_data['user_id'], message.text, message)

# ========================================================================
# 9. КАРЬЕРА И СМЕНА НИКА
# ========================================================================

@bot.message_handler(func=lambda message: message.text == "Завершения карьеры")
def menu_end_career(message: types.Message):
    """Обработчик завершения карьеры."""
    user_id = message.from_user.id
    user_data = db.get_user_by_id(user_id)
    
    # Если игрок уже в бане - игнорируем
    if not user_data or user_data['is_banned']: 
        return
        
    # Вычисляем дату окончания (15 дней) и устанавливаем ровно на 00:00
    future_date = get_current_time() + timedelta(days=15)
    midnight_date = future_date.replace(hour=0, minute=0, second=0, microsecond=0)
    time_str = midnight_date.strftime('%Y-%m-%d %H:%M:%S')
    
    # Сохраняем дату в БД
    db.set_career_end_cooldown(user_id, time_str)
    
    # Формируем пост для канала
    final_post = (
        f"❗️ОФИЦИАЛЬНО: ЗАВЕРШЕНИЕ КАРЬЕРЫ🥀\n\n"
        f"😎 {user_data['nickname']}({user_data['username']}) - завершение карьеры."
    )
    
    bot.send_message(
        message.chat.id, 
        f"🥀 Вы завершили карьеру. Теперь вы не сможете ничего публиковать в течение 15 дней.\n"
        f"Ваш статус обновится: {midnight_date.strftime('%d.%m.%Y в %H:%M')}"
    )
    
    # Отправляем новость в предложку
    send_post_to_moderation(user_id, final_post, message)

@bot.message_handler(func=lambda message: message.text == "Возращения карьеры")
def menu_return_career(message: types.Message):
    """Обработчик возвращения из завершения карьеры."""
    user_id = message.from_user.id
    user_data = db.get_user_by_id(user_id)
    
    if not user_data:
        return
        
    career_ended = parse_db_time(user_data['career_ended_until'])
    
    # Если время еще не прошло
    if get_current_time() < career_ended:
        days_left = (career_ended - get_current_time()).days
        bot.send_message(
            message.chat.id, 
            f"⚠️ Вы не можете вернуться! Вы завершили карьеру, ждите еще {days_left} дней.\n"
            f"Срок истекает: {career_ended.strftime('%d.%m.%Y в %H:%M')}"
        )
        return
        
    # Сбрасываем статус (ставим старую дату)
    db.set_career_end_cooldown(user_id, '2000-01-01 00:00:00')
    
    final_post = (
        f"❗️ОФИЦИАЛЬНО: ВОЗРАЩЕНИЕ  КАРЬЕРЫ❤️\n\n"
        f"😎 {user_data['nickname']}({user_data['username']}) - возращение карьеры."
    )
    
    bot.send_message(message.chat.id, "❤️ С возвращением! Теперь вы снова можете публиковать объявления.")
    send_post_to_moderation(user_id, final_post, message)

@bot.message_handler(func=lambda message: message.text == "Смена никнейма")
def menu_change_nick(message: types.Message):
    """Начало процесса смены игрового никнейма."""
    user_id = message.from_user.id
    user_data = db.get_user_by_id(user_id)
    
    if not user_data:
        return
        
    # Проверка кулдауна (30 дней / месяц)
    cd_time = parse_db_time(user_data['name_change_cd'])
    if get_current_time() < cd_time:
        days_left = (cd_time - get_current_time()).days
        bot.send_message(
            message.chat.id, 
            f"⏳ <b>Кулдаун!</b> Менять никнейм можно только раз в месяц.\n"
            f"Осталось дней: {days_left} (До {cd_time.strftime('%d.%m.%Y')})"
        )
        return
        
    msg = bot.send_message(
        message.chat.id, 
        "📝 Введите ваш НОВЫЙ никнейм (только английские буквы и цифры):\n\n"
        "<i>Для отмены напишите 'отмена'</i>"
    )
    bot.register_next_step_handler(msg, process_nickname_change, user_data)

def process_nickname_change(message: types.Message, user_data: dict):
    """Обработка нового никнейма и обновление в базе."""
    if message.text.lower() == 'отмена':
        bot.send_message(message.chat.id, "Действие отменено.")
        return
        
    new_nickname = message.text.strip()
    
    if not re.match(r'^[A-Za-z0-9_]+$', new_nickname):
        msg = bot.send_message(
            message.chat.id, 
            "❌ Ошибка! Только английские буквы и цифры. Попробуйте еще раз:"
        )
        bot.register_next_step_handler(msg, process_nickname_change, user_data)
        return
        
    if db.update_user_nickname(user_data['user_id'], new_nickname):
        # Если ник успешно обновлен, ставим кулдаун на 30 дней
        new_cd = get_current_time() + timedelta(days=30)
        db.set_name_change_cooldown(user_data['user_id'], new_cd.strftime('%Y-%m-%d %H:%M:%S'))
        
        bot.send_message(
            message.chat.id, 
            f"✅ Ваш никнейм успешно изменен на <b>{new_nickname}</b>!\n"
            f"Следующая смена будет доступна через месяц."
        )
        logger.info(f"Пользователь {user_data['user_id']} сменил ник на {new_nickname}")
    else:
        bot.send_message(
            message.chat.id, 
            "⚠️ Этот никнейм уже занят кем-то другим! Попробуйте сменить ник позже или выберите другой."
        )

# Конец 2 части.

# ========================================================================
# 10. КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ КЛУБАМИ (ВЛАДЕЛЬЦЫ И ЗАМЫ)
# ========================================================================

@bot.message_handler(commands=['invite'])
def club_invite_player(message: types.Message):
    """Подписание нового игрока в клуб (только для владельца и замов)."""
    user_id = message.from_user.id
    user_data = db.get_user_by_id(user_id)
    
    if not check_user_access(message, user_data):
        return
        
    # Проверка прав менеджера (владелец или заместитель)
    club_data = db.get_club_by_manager(user_id, user_data['nickname'])
    if not club_data:
        bot.send_message(message.chat.id, "❌ У вас нет прав для управления каким-либо клубом.")
        return
        
    # Разбор аргументов команды
    args = message.text.split()
    if len(args) < 2:
        bot.send_message(message.chat.id, "⚠️ Использование команды: <b>/invite [ник_игрока]</b>")
        return
        
    target_nickname = args[1]
    target_data = db.get_user_by_nickname(target_nickname)
    
    # Проверки целевого игрока
    if not target_data:
        bot.send_message(message.chat.id, f"❌ Игрок с ником <b>{target_nickname}</b> не найден в базе.")
        return
        
    if target_data['club_id'] != 0:
        bot.send_message(message.chat.id, f"❌ Игрок <b>{target_nickname}</b> уже состоит в другом клубе!")
        return
        
    # Проверка лимита игроков в клубе (максимум 15)
    current_members = db.get_club_members(club_data['club_id'])
    if len(current_members) >= 15:
        bot.send_message(
            message.chat.id, 
            "⚠️ Удалите 1 игрока, лимит исчерпан. В клубе может быть не более 15 игроков."
        )
        return
        
    # Выполнение трансфера
    db.update_user_club(target_nickname, club_data['club_id'])
    db.increment_club_transfers(club_data['club_id'])
    
    # Формирование поста о трансфере
    transfer_post = (
        f"❗ОФИЦИАЛЬНО: ТРАНСФЕРЫ📍\n\n"
        f"😎 {target_nickname} - Свободный агент ➡️ {club_data['name']}"
    )
    
    bot.send_message(
        message.chat.id, 
        f"✅ Игрок <b>{target_nickname}</b> успешно подписан в ваш клуб <b>{club_data['name']}</b>!\n"
        f"Пост о трансфере отправлен на проверку администраторам."
    )
    logger.info(f"Трансфер: {target_nickname} перешел в клуб ID {club_data['club_id']}")
    
    # Отправка поста на модерацию
    send_post_to_moderation(user_id, transfer_post, message)

@bot.message_handler(commands=['delete'])
def club_delete_player(message: types.Message):
    """Разрыв контракта с игроком (удаление из клуба)."""
    user_id = message.from_user.id
    user_data = db.get_user_by_id(user_id)
    
    if not check_user_access(message, user_data):
        return
        
    club_data = db.get_club_by_manager(user_id, user_data['nickname'])
    if not club_data:
        bot.send_message(message.chat.id, "❌ У вас нет прав для управления каким-либо клубом.")
        return
        
    args = message.text.split()
    if len(args) < 2:
        bot.send_message(message.chat.id, "⚠️ Использование команды: <b>/delete [ник_игрока]</b>")
        return
        
    target_nickname = args[1]
    target_data = db.get_user_by_nickname(target_nickname)
    
    if not target_data or target_data['club_id'] != club_data['club_id']:
        bot.send_message(
            message.chat.id, 
            f"❌ Игрок <b>{target_nickname}</b> не найден в вашем клубе."
        )
        return
        
    # Удаление игрока из клуба
    db.update_user_club(target_nickname, 0)
    
    # Если удаляемый игрок был заместителем - снимаем с него должность
    if club_data['deputy1_nick'] == target_nickname:
        db.set_club_deputy(club_data['club_id'], 1, "")
    elif club_data['deputy2_nick'] == target_nickname:
        db.set_club_deputy(club_data['club_id'], 2, "")
        
    bot.send_message(message.chat.id, f"✅ Контракт с игроком <b>{target_nickname}</b> успешно расторгнут.")
    logger.info(f"Расторжение: {target_nickname} покинул клуб ID {club_data['club_id']}")

@bot.message_handler(commands=['viewteam'])
@bot.message_handler(func=lambda message: message.text == "мой клуб")
def view_club_team(message: types.Message):
    """Просмотр состава команды и информации о клубе."""
    user_id = message.from_user.id
    user_data = db.get_user_by_id(user_id)
    
    if not user_data:
        return
        
    # Определяем клуб для показа
    club_data = None
    if message.text == "мой клуб":
        if user_data['club_id'] != 0:
            club_data = db.get_club_by_id(user_data['club_id'])
    else:
        # Для команды /viewteam проверяем права менеджера
        club_data = db.get_club_by_manager(user_id, user_data['nickname'])
        
    if not club_data:
        bot.send_message(message.chat.id, "❌ У вас нет клуба или вы не состоите в нем.")
        return
        
    # Получаем данные владельца клуба
    owner_data = db.get_user_by_id(club_data['owner_id'])
    owner_text = f"{owner_data['nickname']} (ID: {owner_data['user_id']})" if owner_data else "Неизвестно"
    
    dep1 = club_data['deputy1_nick'] if club_data['deputy1_nick'] else "Нету"
    dep2 = club_data['deputy2_nick'] if club_data['deputy2_nick'] else "Нету"
    
    # Получаем состав
    members = db.get_club_members(club_data['club_id'])
    
    # Формируем заголовок клуба по ТЗ
    team_text = (
        f"📋Даные клуба 📝\n"
        f"─────────────────────────────\n"
        f"📊Названия клуба: {club_data['name']}\n"
        f"👑 Владелец: {owner_text}\n"
        f"👤Помощник 1: {dep1}\n"
        f"👤Помощник 2: {dep2}\n"
        f"📊 Успешных переходов: {club_data['transfers_count']}\n"
        f"🏆─────────────────────────────🏆\n\n"
        f"👥 Состав команды ({len(members)}/15):\n"
    )
    
    # Формируем список из 15 слотов
    for i in range(15):
        if i < len(members):
            team_text += f" {i+1}. ✏️ {members[i]}\n"
        else:
            team_text += f" {i+1}. ✏️ \n"
            
    # Проверяем, является ли запрос от владельца для выдачи кнопок управления замами
    is_owner = (user_id == club_data['owner_id'])
    markup = get_club_management_keyboard(club_data['club_id'], is_owner)
    
    bot.send_message(message.chat.id, team_text, reply_markup=markup)

# ========================================================================
# 11. АДМИН-ПАНЕЛЬ
# ========================================================================

def is_global_admin(user_id: int) -> bool:
    """Проверка прав глобального администратора."""
    return user_id in GLOBAL_ADMINS

@bot.message_handler(commands=['admin', 'apanel'])
def admin_menu(message: types.Message):
    """Вывод списка админ-команд."""
    if not is_global_admin(message.from_user.id):
        return
        
    admin_text = (
        "🔐 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "<b>Управление клубами:</b>\n"
        "🔸 /addclub [Название] [ID_Владельца] - Создать клуб\n"
        "🔸 /delclub - Открыть меню удаления клубов\n\n"
        "<b>Модерация игроков:</b>\n"
        "🔸 /ban [ник] - Заблокировать игрока\n"
        "🔸 /unban [ник] - Разблокировать игрока"
    )
    bot.send_message(message.chat.id, admin_text)

@bot.message_handler(commands=['addclub'])
def admin_add_club(message: types.Message):
    """Создание нового клуба админом."""
    if not is_global_admin(message.from_user.id):
        return
        
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        bot.send_message(message.chat.id, "⚠️ Использование: <b>/addclub [Название] [ID_Владельца]</b>")
        return
        
    club_name = args[1]
    try:
        owner_id = int(args[2])
    except ValueError:
        bot.send_message(message.chat.id, "❌ ID владельца должен быть числом.")
        return
        
    # Проверяем, существует ли пользователь-владелец
    owner_data = db.get_user_by_id(owner_id)
    if not owner_data:
        bot.send_message(message.chat.id, f"❌ Пользователь с ID {owner_id} не найден.")
        return
        
    # Создаем клуб
    if db.create_club(club_name, owner_id):
        bot.send_message(message.chat.id, f"✅ Клуб <b>{club_name}</b> успешно создан! Владелец: {owner_data['nickname']}")
        logger.info(f"Админ {message.from_user.id} создал клуб {club_name} для {owner_id}")
    else:
        bot.send_message(message.chat.id, "❌ Ошибка! Возможно, клуб с таким названием уже существует.")

@bot.message_handler(commands=['delclub'])
def admin_del_club(message: types.Message):
    """Меню удаления клубов (через инлайн кнопки)."""
    if not is_global_admin(message.from_user.id):
        return
        
    clubs = db.get_all_clubs()
    if not clubs:
        bot.send_message(message.chat.id, "ℹ️ На данный момент нет созданных клубов.")
        return
        
    markup = get_club_deletion_list_keyboard(clubs)
    bot.send_message(message.chat.id, "🗑 <b>Выберите клуб для удаления:</b>", reply_markup=markup)

@bot.message_handler(commands=['ban', 'unban'])
def admin_ban_system(message: types.Message):
    """Выдача и снятие блокировок."""
    if not is_global_admin(message.from_user.id):
        return
        
    args = message.text.split()
    if len(args) < 2:
        bot.send_message(message.chat.id, f"⚠️ Использование: <b>{args[0]} [ник]</b>")
        return
        
    target_nickname = args[1]
    target_data = db.get_user_by_nickname(target_nickname)
    
    if not target_data:
        bot.send_message(message.chat.id, f"❌ Игрок <b>{target_nickname}</b> не найден.")
        return
        
    # 1 - бан, 0 - разбан
    status = 1 if message.text.startswith('/ban') else 0
    db.set_user_ban_status(target_nickname, status)
    
    action = "ЗАБЛОКИРОВАН" if status == 1 else "РАЗБЛОКИРОВАН"
    bot.send_message(message.chat.id, f"✅ Игрок <b>{target_nickname}</b> был успешно {action}.")
    logger.info(f"Админ {message.from_user.id} изменил статус бана {target_nickname} на {status}")

# ========================================================================
# 12. ОБРАБОТКА ВСЕХ INLINE КНОПОК (CALLBACK QUERIES)
# ========================================================================

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call: types.CallbackQuery):
    """Универсальный обработчик всех нажатий на инлайн-кнопки."""
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    try:
        # --- ЛОГИКА МОДЕРАЦИИ АНКЕТ ---
        if data.startswith("accept_post_"):
            post_id = int(data.split("_")[2])
            post_text = db.get_pending_post(post_id)
            
            if post_text:
                # Отправляем в публичный канал
                bot.send_message(CHANNEL_ID, post_text)
                # Удаляем из БД
                db.delete_pending_post(post_id)
                
                # Обновляем сообщение в админке
                bot.edit_message_text(
                    f"{call.message.text}\n\n✅ <b>ОДОБРЕНО И ОПУБЛИКОВАНО</b>",
                    chat_id, msg_id, reply_markup=None
                )
            else:
                bot.answer_callback_query(call.id, "⚠️ Ошибка: Анкета уже обработана или не найдена.")
                
        elif data.startswith("reject_post_"):
            post_id = int(data.split("_")[2])
            db.delete_pending_post(post_id)
            
            bot.edit_message_text(
                f"{call.message.text}\n\n❌ <b>ОТКЛОНЕНО</b>",
                chat_id, msg_id, reply_markup=None
            )

        # --- ЛОГИКА УДАЛЕНИЯ КЛУБА (АДМИНЫ) ---
        elif data.startswith("confirm_del_club_"):
            club_id = int(data.split("_")[3])
            markup = get_club_deletion_confirm_keyboard(club_id)
            bot.edit_message_text(
                "⚠️ Вы уверены, что хотите полностью удалить этот клуб? Все игроки будут исключены.",
                chat_id, msg_id, reply_markup=markup
            )
            
        elif data.startswith("execute_del_club_"):
            club_id = int(data.split("_")[3])
            db.delete_club(club_id)
            bot.edit_message_text(
                "✅ Клуб успешно удален, а все игроки откреплены.",
                chat_id, msg_id, reply_markup=None
            )
            logger.info(f"Клуб ID {club_id} был удален администратором.")

        # --- ЛОГИКА УПРАВЛЕНИЯ ЗАМАМИ (ВЛАДЕЛЬЦЫ) ---
        elif data.startswith("add_deputy_"):
            club_id = int(data.split("_")[2])
            msg = bot.send_message(chat_id, "📝 Введите точный никнейм игрока для назначения заместителем:")
            bot.register_next_step_handler(msg, process_add_deputy, club_id)
            bot.answer_callback_query(call.id)
            
        elif data.startswith("del_deputy_"):
            club_id = int(data.split("_")[2])
            club_data = db.get_club_by_id(club_id)
            
            if not club_data['deputy1_nick'] and not club_data['deputy2_nick']:
                bot.answer_callback_query(call.id, "⚠️ У вас нет назначенных заместителей.", show_alert=True)
                return
                
            markup = get_remove_deputy_keyboard(club_id, club_data['deputy1_nick'], club_data['deputy2_nick'])
            bot.edit_message_text(
                "Выберите заместителя, которого хотите снять с должности:",
                chat_id, msg_id, reply_markup=markup
            )
            
        elif data.startswith("rm_dep_"):
            # rm_dep_{club_id}_{slot}
            parts = data.split("_")
            club_id = int(parts[2])
            slot = int(parts[3])
            
            db.set_club_deputy(club_id, slot, "")
            bot.edit_message_text("✅ Заместитель успешно снят с должности.", chat_id, msg_id, reply_markup=None)

        # --- ОТМЕНА ДЕЙСТВИЯ (УНИВЕРСАЛЬНАЯ) ---
        elif data == "cancel_action":
            bot.delete_message(chat_id, msg_id)
            
    except Exception as e:
        logger.error(f"Ошибка в callback_query_handler: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при обработке нажатия.")

def process_add_deputy(message: types.Message, club_id: int):
    """Процесс назначения нового заместителя клуба."""
    nickname = message.text.strip()
    club_data = db.get_club_by_id(club_id)
    target_data = db.get_user_by_nickname(nickname)
    
    if not target_data or target_data['club_id'] != club_id:
        bot.send_message(message.chat.id, f"❌ Игрок <b>{nickname}</b> не найден или не состоит в вашем клубе.")
        return
        
    # Проверяем свободные слоты для замов
    if not club_data['deputy1_nick']:
        db.set_club_deputy(club_id, 1, nickname)
        bot.send_message(message.chat.id, f"✅ Игрок <b>{nickname}</b> назначен на слот Помощника 1!")
    elif not club_data['deputy2_nick']:
        db.set_club_deputy(club_id, 2, nickname)
        bot.send_message(message.chat.id, f"✅ Игрок <b>{nickname}</b> назначен на слот Помощника 2!")
    else:
        bot.send_message(message.chat.id, "❌ Лимит заместителей исчерпан (максимум 2). Сначала снимите одного из текущих.")

# ========================================================================
# 13. ЗАПУСК БОТА (POLLING)
# ========================================================================

if __name__ == '__main__':
    logger.info("Бот успешно запущен и готов к работе!")
    try:
        # infinity_polling защищает бота от падений при кратковременных ошибках сети
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
    except Exception as e:
        logger.critical(f"Критическая ошибка при работе бота: {e}")

# Конец 1 части. Жду команду, чтобы скинуть 2 часть.
