
import sqlite3
import logging
import sys
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Union, Dict, Any

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# ==============================================================================
# 1. КОНФИГУРАЦИЯ БОТА И КОНСТАНТЫ
# ==============================================================================

# Токен бота (указан изначальный)
BOT_TOKEN = "8768994062:AAFWMZZIl19tDmnKjBcyFXEnE_BZLw5ckw0"

# Список ID владельцев (администраторов)
ADMIN_IDS = [6885478196, 5845609895]

# ID канала для публикации постов
CHANNEL_ID = "-1004377865527"

# Константы для кулдаунов (в часах и днях)
COOLDOWN_FREE_AGENT_HOURS = 6
COOLDOWN_CUSTOM_TEXT_HOURS = 12
COOLDOWN_RETIRE_DAYS = 15
COOLDOWN_NICKNAME_CHANGE_DAYS = 30

# Лимит игроков в одной команде
CLUB_MAX_PLAYERS = 15

# ==============================================================================
# 2. НАСТРОЙКА ПРОФЕССИОНАЛЬНОГО ЛОГГИРОВАНИЯ
# ==============================================================================

logger = logging.getLogger("RivalsBotLogger")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    fmt="[%(asctime)s] %(levelname)s - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S"
)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logger.info("Инициализация системы Трансфермаркета Rivals (Модифицированная версия)...")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ==============================================================================
# 3. МАШИНЫ СОСТОЯНИЙ (FSM - Finite State Machine)
# ==============================================================================

class UserRegistration(StatesGroup):
    """Состояния для процесса регистрации нового пользователя в боте."""
    waiting_for_nickname = State()

class FreeAgentProcess(StatesGroup):
    """Состояния для подачи анкеты свободного агента."""
    waiting_for_text = State()

class CustomTextProcess(StatesGroup):
    """Состояния для подачи объявления со своим текстом."""
    waiting_for_text = State()

class ChangeNicknameProcess(StatesGroup):
    """Состояния для процесса смены игрового никнейма."""
    waiting_for_new_nickname = State()

class CareerProcess(StatesGroup):
    """Состояния для модерации завершения/возвращения карьеры."""
    waiting_for_retire_confirmation = State()
    waiting_for_return_confirmation = State()

class SuperAdminProcess(StatesGroup):
    """Состояния для админ-панели (добавление клубов, баны, возврат карьеры)."""
    waiting_for_club_name = State()
    waiting_for_club_owner_id = State()
    waiting_for_ban_nickname = State()
    waiting_for_unban_nickname = State()
    waiting_for_career_return_id = State() # НОВОЕ: ожидание ID для возврата карьеры

class ClubManagementProcess(StatesGroup):
    """Состояния для владельцев клубов (набор состава, управление замами, переходы)."""
    waiting_for_deputy_nickname = State()
    waiting_for_player_invite = State()
    waiting_for_player_kick = State()
    waiting_for_transfer_custom_text = State() # НОВОЕ: ожидание своего текста для перехода

# ==============================================================================
# 4. ФУНКЦИИ ГЕНЕРАЦИИ КЛАВИАТУР (ОФОРМЛЕНИЕ И ЭМОДЗИ)
# ==============================================================================

def get_player_main_menu(user_id: int, is_club_owner_or_deputy: bool = False) -> ReplyKeyboardMarkup:
    """Генерирует главную клавиатуру пользователя."""
    builder = ReplyKeyboardBuilder()
    
    builder.row(
        KeyboardButton(text="🏃‍♂️ Свободный агент"),
        KeyboardButton(text="📝 Свой текст")
    )
    builder.row(
        KeyboardButton(text="🥀 Завершения карьеры"),
        KeyboardButton(text="❤️ Возращения карьеры")
    )
    builder.row(
        KeyboardButton(text="🔄 Смена никнейма"),
        KeyboardButton(text="👤 Профиль")
    )
    builder.row(
        KeyboardButton(text="ℹ️ Помощь")
    )
    
    if is_club_owner_or_deputy:
        builder.row(
            KeyboardButton(text="🛡 Мой клуб")
        )
        
    if user_id in ADMIN_IDS:
        builder.row(
            KeyboardButton(text="⚙️ Админ Панель")
        )
        
    return builder.as_markup(resize_keyboard=True)

def get_superadmin_menu() -> ReplyKeyboardMarkup:
    """Клавиатура админ-панели для владельцев бота."""
    builder = ReplyKeyboardBuilder()
    
    builder.row(
        KeyboardButton(text="➕ Добавить клуб"),
        KeyboardButton(text="➖ Убрать клуб")
    )
    builder.row(
        KeyboardButton(text="🚫 Забанить игрока"),
        KeyboardButton(text="✅ Разбанить игрока")
    )
    # НОВОЕ: Кнопка для возвращения карьеры по ID
    builder.row(
        KeyboardButton(text="🔙 Вернуть карьеру")
    )
    builder.row(
        KeyboardButton(text="🔙 Выйти из админ панели")
    )
    
    return builder.as_markup(resize_keyboard=True)

def get_anketa_approval_keyboard(user_id: int, action_type: str) -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для главных админов (модерация). 
    action_type = "freeagent", "customtext", "retire", "return", "transfer"
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text="✅ Принять", 
        callback_data=f"approve_{action_type}_{user_id}"
    )
    builder.button(
        text="❌ Отклонить", 
        callback_data=f"reject_{action_type}_{user_id}"
    )
    
    builder.adjust(2)
    return builder.as_markup()

def get_club_management_inline() -> InlineKeyboardMarkup:
    """Инлайн-клавиатура для управления составом клуба."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить зама", callback_data="club_add_deputy")
    builder.button(text="➖ Убрать зама", callback_data="club_remove_deputy")
    builder.adjust(2)
    return builder.as_markup()

def get_cancel_inline_keyboard() -> InlineKeyboardMarkup:
    """Универсальная кнопка для отмены текущего действия."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel_current_action")
    return builder.as_markup()

# ==============================================================================
# 5. МАКСИМАЛЬНО ПРОДВИНУТАЯ И БЕЗОПАСНАЯ БАЗА ДАННЫХ
# ==============================================================================

class DatabaseManager:
    """Класс для управления базой данных SQLite3."""
    
    def __init__(self, db_path: str = "rivals_database.db"):
        self.db_path = db_path
        self.connection = None
        self.cursor = None
        self._connect_and_initialize()

    def _connect_and_initialize(self) -> None:
        """Подключается к файлу БД и создает таблицы."""
        try:
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self.cursor = self.connection.cursor()
            
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    nickname TEXT UNIQUE COLLATE NOCASE,
                    club_id INTEGER DEFAULT NULL,
                    is_banned INTEGER DEFAULT 0,
                    retire_date TIMESTAMP DEFAULT NULL,
                    last_free_agent TIMESTAMP DEFAULT NULL,
                    last_custom_text TIMESTAMP DEFAULT NULL,
                    last_nickname_change TIMESTAMP DEFAULT NULL
                )
            ''')
            
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS clubs (
                    club_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    club_name TEXT UNIQUE COLLATE NOCASE,
                    owner_id INTEGER,
                    deputy1_id INTEGER DEFAULT NULL,
                    deputy2_id INTEGER DEFAULT NULL,
                    transfers_count INTEGER DEFAULT 0
                )
            ''')
            
            self.connection.commit()
            logger.info("База данных SQLite успешно инициализирована и таблицы созданы.")
        except sqlite3.Error as e:
            logger.critical(f"Критическая ошибка при инициализации БД: {e}")
            sys.exit(1)

    def add_new_user(self, user_id: int, username: str, nickname: str) -> bool:
        """Регистрация нового пользователя."""
        try:
            self.cursor.execute('''
                INSERT INTO users (user_id, username, nickname) 
                VALUES (?, ?, ?)
            ''', (user_id, username, nickname))
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"Неизвестная ошибка БД: {e}")
            return False

    def get_user_data_by_id(self, user_id: int) -> Optional[Tuple]:
        """Получение инфы о пользователе по Telegram ID."""
        try:
            self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения пользователя {user_id}: {e}")
            return None

    def get_user_data_by_nickname(self, nickname: str) -> Optional[Tuple]:
        """Получение инфы по игровому никнейму."""
        try:
            self.cursor.execute("SELECT * FROM users WHERE nickname = ?", (nickname,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Ошибка поиска пользователя {nickname}: {e}")
            return None

    def update_user_nickname(self, user_id: int, new_nickname: str) -> bool:
        """Обновление никнейма игрока с кулдауном."""
        try:
            current_time = datetime.now()
            self.cursor.execute('''
                UPDATE users 
                SET nickname = ?, last_nickname_change = ? 
                WHERE user_id = ?
            ''', (new_nickname, current_time, user_id))
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.Error as e:
            return False

    def set_action_cooldown(self, user_id: int, action_column: str) -> bool:
        """Устанавливает текущее время для колонки кулдауна."""
        try:
            current_time = datetime.now()
            query = f"UPDATE users SET {action_column} = ? WHERE user_id = ?"
            self.cursor.execute(query, (current_time, user_id))
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            return False

    def execute_career_retirement(self, user_id: int) -> datetime:
        """Завершения карьеры (заморозка на 15 дней)."""
        try:
            retire_end_date = datetime.now() + timedelta(days=COOLDOWN_RETIRE_DAYS)
            self.cursor.execute('''
                UPDATE users 
                SET retire_date = ?, club_id = NULL 
                WHERE user_id = ?
            ''', (retire_end_date, user_id))
            self.connection.commit()
            return retire_end_date
        except sqlite3.Error as e:
            logger.error(f"Ошибка при завершении карьеры {user_id}: {e}")
            return datetime.now() 

    def execute_career_return(self, user_id: int) -> bool:
        """Возвращения карьеры (снимает ограничения)."""
        try:
            self.cursor.execute('''
                UPDATE users 
                SET retire_date = NULL 
                WHERE user_id = ?
            ''', (user_id,))
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка при возвращении карьеры {user_id}: {e}")
            return False

    def change_ban_status(self, nickname: str, is_banned: int) -> bool:
        """Блокировка/разблокировка игрока по нику."""
        try:
            self.cursor.execute('''
                UPDATE users 
                SET is_banned = ? 
                WHERE nickname = ?
            ''', (is_banned, nickname))
            self.connection.commit()
            if self.cursor.rowcount > 0:
                return True
            return False
        except sqlite3.Error as e:
            return False

    def create_new_club(self, club_name: str, owner_id: int) -> bool:
        """Создает новый клуб и делает создателя владельцем."""
        try:
            self.cursor.execute('''
                INSERT INTO clubs (club_name, owner_id) 
                VALUES (?, ?)
            ''', (club_name, owner_id))
            new_club_id = self.cursor.lastrowid
            
            self.cursor.execute('''
                UPDATE users 
                SET club_id = ? 
                WHERE user_id = ?
            ''', (new_club_id, owner_id))
            
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.Error as e:
            return False

    def get_club_info_by_id(self, club_id: int) -> Optional[Tuple]:
        """Получает всю инфу клуба по ID."""
        try:
            self.cursor.execute("SELECT * FROM clubs WHERE club_id = ?", (club_id,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            return None

    def get_all_clubs(self) -> List[Tuple]:
        """Получает список всех клубов для админ панели."""
        try:
            self.cursor.execute("SELECT club_id, club_name FROM clubs")
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            return []

    def get_club_by_admin_rights(self, user_id: int) -> Optional[Tuple]:
        """Ищет клуб, к которому пользователь имеет права админа."""
        try:
            self.cursor.execute('''
                SELECT * FROM clubs 
                WHERE owner_id = ? OR deputy1_id = ? OR deputy2_id = ?
            ''', (user_id, user_id, user_id))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            return None

    def delete_club_fully(self, club_id: int) -> bool:
        """Полное удаление клуба и отвязка игроков."""
        try:
            self.cursor.execute('''
                UPDATE users 
                SET club_id = NULL 
                WHERE club_id = ?
            ''', (club_id,))
            self.cursor.execute('''
                DELETE FROM clubs 
                WHERE club_id = ?
            ''', (club_id,))
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            return False

    def get_club_players_list(self, club_id: int) -> List[Tuple]:
        """Получает список всех участников клуба."""
        try:
            self.cursor.execute('''
                SELECT user_id, nickname 
                FROM users 
                WHERE club_id = ?
            ''', (club_id,))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            return []

    def change_player_club(self, user_id: int, new_club_id: Optional[int]) -> bool:
        """Изменяет клуб игрока (вступление или кик)."""
        try:
            self.cursor.execute('''
                UPDATE users 
                SET club_id = ? 
                WHERE user_id = ?
            ''', (new_club_id, user_id))
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            return False

    def add_transfer_count(self, club_id: int) -> bool:
        """Увеличивает счетчик успешных переходов на +1."""
        try:
            self.cursor.execute('''
                UPDATE clubs 
                SET transfers_count = transfers_count + 1 
                WHERE club_id = ?
            ''', (club_id,))
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            return False

    def assign_club_deputy(self, club_id: int, deputy_id: int) -> str:
        """Назначает заместителя владельца (макс 2)."""
        try:
            club_data = self.get_club_info_by_id(club_id)
            if not club_data:
                return 'error'
            if club_data[3] is None:
                self.cursor.execute("UPDATE clubs SET deputy1_id = ? WHERE club_id = ?", (deputy_id, club_id))
            elif club_data[4] is None:
                self.cursor.execute("UPDATE clubs SET deputy2_id = ? WHERE club_id = ?", (deputy_id, club_id))
            else:
                return 'full'
            self.connection.commit()
            return 'success'
        except sqlite3.Error as e:
            return 'error'

    def remove_club_deputy(self, club_id: int, deputy_id: int) -> bool:
        """Снимает полномочия заместителя."""
        try:
            club_data = self.get_club_info_by_id(club_id)
            if not club_data:
                return False
            if club_data[3] == deputy_id:
                self.cursor.execute("UPDATE clubs SET deputy1_id = NULL WHERE club_id = ?", (club_id,))
            elif club_data[4] == deputy_id:
                self.cursor.execute("UPDATE clubs SET deputy2_id = NULL WHERE club_id = ?", (club_id,))
            else:
                return False
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            return False

# Инициализация объекта базы данных
db_manager = DatabaseManager()

# КОНЕЦ ЧАСТИ 1

from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from datetime import datetime
import asyncio

# ==============================================================================
# 16. ДОПОЛНИТЕЛЬНЫЕ МАШИНЫ СОСТОЯНИЙ И ОБНОВЛЕНИЕ КЛАВИАТУР
# ==============================================================================

class TransferProcess(StatesGroup):
    """FSM для оформления перехода игрока в клуб (со своим текстом)."""
    waiting_for_transfer_text = State()

class AdminReturnCareerProcess(StatesGroup):
    """FSM для возвращения карьеры игроку по его Telegram ID через админ-панель."""
    waiting_for_user_id = State()

def get_superadmin_menu_updated() -> ReplyKeyboardMarkup:
    """
    ОБНОВЛЕННАЯ Клавиатура админ-панели для владельцев бота.
    Добавлена кнопка возвращения карьеры.
    """
    builder = ReplyKeyboardBuilder()
    
    # Ряд 1: Управление клубами
    builder.row(
        KeyboardButton(text="➕ Добавить клуб"),
        KeyboardButton(text="➖ Убрать клуб")
    )
    
    # Ряд 2: Управление блокировками
    builder.row(
        KeyboardButton(text="🚫 Забанить игрока"),
        KeyboardButton(text="✅ Разбанить игрока")
    )
    
    # Ряд 3: Управление карьерой (НОВОЕ)
    builder.row(
        KeyboardButton(text="❤️ Вернуть карьеру игроку")
    )
    
    # Ряд 4: Выход
    builder.row(
        KeyboardButton(text="🔙 Выйти из админ панели")
    )
    
    return builder.as_markup(resize_keyboard=True)

def get_anketa_approval_keyboard_updated(user_id: int, action_type: str, target_id: int = 0, club_id: int = 0) -> InlineKeyboardMarkup:
    """
    ОБНОВЛЕННАЯ Инлайн-клавиатура для модерации.
    Поддерживает новые типы действий: retire, return, transfer.
    Для трансфера передаются дополнительные ID.
    """
    builder = InlineKeyboardBuilder()
    
    # Формируем callback_data в зависимости от типа действия
    if action_type == "transfer":
        approve_cb = f"approve_transfer_{target_id}_{club_id}"
        reject_cb = f"reject_transfer_{target_id}_{club_id}"
    else:
        approve_cb = f"approve_{action_type}_{user_id}"
        reject_cb = f"reject_{action_type}_{user_id}"
        
    builder.button(text="✅ Принять", callback_data=approve_cb)
    builder.button(text="❌ Отклонить", callback_data=reject_cb)
    
    builder.adjust(2)
    return builder.as_markup()

# ==============================================================================
# 17. МОДЕРАЦИЯ: ЗАВЕРШЕНИЕ И ВОЗВРАЩЕНИЕ КАРЬЕРЫ
# ==============================================================================

@dp.message(F.text == "🥀 Завершения карьеры")
async def handle_career_retire_moderation(message: types.Message, state: FSMContext) -> None:
    """
    Инициирует процесс завершения карьеры.
    Вместо мгновенного завершения, отправляет запрос на модерацию администраторам.
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        await message.answer("❌ <b>Ошибка:</b> Вы не зарегистрированы в системе.")
        return
        
    # Проверка на блокировку аккаунта
    if bool(user_data[4]):
        await message.answer("❌ <b>Отказано:</b> Вы заблокированы и не можете использовать эту функцию.")
        return

    # Проверка: возможно, карьера уже завершена
    retire_end_date = check_player_retire_status(user_id)
    if retire_end_date:
        await message.answer(
            f"⚠️ <b>Ваша карьера уже завершена!</b>\n"
            f"Ожидайте до: <b>{retire_end_date.strftime('%d.%m.%Y %H:%M')}</b>\n"
            f"Или нажмите «❤️ Возращения карьеры», чтобы вернуться досрочно."
        )
        return

    username = user_data[1]
    nickname = user_data[2]
    
    # Формируем текст для предпросмотра админам
    post_text = (
        "❗️ОФИЦИАЛЬНО: ЗАВЕРШЕНИЕ КАРЬЕРЫ🥀\n\n"
        f"😎 <b>{nickname}</b> ({username}) - завершение карьеры."
    )
    
    admins_notified_count = 0
    
    # Отправляем запрос всем администраторам
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = (
                f"🔔 <b>ЗАПРОС НА ЗАВЕРШЕНИЕ КАРЬЕРЫ</b>\n"
                f"От игрока: <code>{nickname}</code> (ID: {user_id})\n\n"
                f"<b>Текст поста:</b>\n"
                f"----------------------------------------\n"
                f"{post_text}\n"
                f"----------------------------------------"
            )
            keyboard = get_anketa_approval_keyboard_updated(user_id=user_id, action_type="retire")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
            admins_notified_count += 1
        except Exception as e:
            logger.error(f"Не удалось отправить запрос на завершение карьеры админу {admin_id}: {e}")

    if admins_notified_count > 0:
        await message.answer(
            "✅ <b>Ваш запрос на завершение карьеры отправлен администраторам!</b>\n"
            "После проверки и одобрения, ваш статус будет изменен, а пост опубликован в канале."
        )
    else:
        await message.answer("⚠️ <b>Произошла ошибка!</b> Администраторы сейчас недоступны.")

@dp.message(F.text == "❤️ Возращения карьеры")
async def handle_career_return_moderation(message: types.Message) -> None:
    """
    Инициирует процесс возвращения в карьеру через модерацию.
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return
        
    if bool(user_data[4]):
        await message.answer("❌ <b>Отказано:</b> Вы заблокированы.")
        return

    # Проверяем, завершена ли карьера
    if user_data[5] is None:
        await message.answer("⚠️ <b>Ошибка:</b> Ваша карьера активна. Вы не завершали ее.")
        return

    username = user_data[1]
    nickname = user_data[2]
    
    post_text = (
        "❗️ОФИЦИАЛЬНО: ВОЗРАЩЕНИЕ КАРЬЕРЫ❤️\n\n"
        f"😎 <b>{nickname}</b> ({username}) - возвращение в карьеру."
    )
    
    admins_notified_count = 0
    
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = (
                f"🔔 <b>ЗАПРОС НА ВОЗВРАЩЕНИЕ В КАРЬЕРУ</b>\n"
                f"От игрока: <code>{nickname}</code> (ID: {user_id})\n\n"
                f"<b>Текст поста:</b>\n"
                f"----------------------------------------\n"
                f"{post_text}\n"
                f"----------------------------------------"
            )
            keyboard = get_anketa_approval_keyboard_updated(user_id=user_id, action_type="return")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
            admins_notified_count += 1
        except Exception as e:
            logger.error(f"Не удалось отправить запрос на возвращение карьеры админу {admin_id}: {e}")

    if admins_notified_count > 0:
        await message.answer(
            "✅ <b>Запрос на возвращение в карьеру отправлен на модерацию!</b>\n"
            "Ожидайте одобрения администраторов."
        )
    else:
        await message.answer("⚠️ <b>Произошла ошибка!</b> Администраторы сейчас недоступны.")

# ==============================================================================
# 18. ПУБЛИКАЦИЯ ПОСТОВ (С ОТКЛЮЧЕНИЕМ КД ДЛЯ АДМИНОВ)
# ==============================================================================

@dp.message(F.text == "🏃‍♂️ Свободный агент")
async def handle_free_agent_button_no_cd(message: types.Message, state: FSMContext) -> None:
    """
    Подача заявки свободного агента.
    Для обычных игроков действует кулдаун 6 часов.
    Для администраторов кулдаун ОТКЛЮЧЕН.
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return

    if bool(user_data[4]):
        await message.answer("❌ <b>Ошибка:</b> Ваш аккаунт заблокирован.")
        return

    retire_date = check_player_retire_status(user_id)
    if retire_date:
        await message.answer(f"🥀 <b>Вы завершили карьеру!</b> Доступ закрыт.")
        return

    # ПРОВЕРКА НА АДМИНИСТРАТОРА (УБИРАЕМ КУЛДАУН)
    is_admin = user_id in ADMIN_IDS
    
    if not is_admin:
        last_free_agent_time = user_data[6]
        cooldown_remaining = get_remaining_cooldown_time(last_free_agent_time, COOLDOWN_FREE_AGENT_HOURS)
        if cooldown_remaining:
            await message.answer(
                f"⏳ <b>Перезарядка!</b>\n"
                f"Вы уже публиковали анкету недавно.\n"
                f"Осталось ждать: <b>{cooldown_remaining}</b>"
            )
            return
    else:
        await message.answer("🛡 <b>Режим Администратора:</b> Кулдаун на публикацию отключен.")

    await message.answer(
        "📝 <b>Режим: Свободный агент</b>\n\n"
        "Напишите текст вашего объявления (например: на какой позиции играете, опыт).\n"
        "Этот текст будет добавлен в анкету после слов 'P.s:'",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(FreeAgentProcess.waiting_for_text)

@dp.message(F.text == "📝 Свой текст")
async def handle_custom_text_button_no_cd(message: types.Message, state: FSMContext) -> None:
    """
    Подача кастомного текста.
    Для обычных игроков действует кулдаун 12 часов.
    Для администраторов кулдаун ОТКЛЮЧЕН.
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return

    if bool(user_data[4]):
        await message.answer("❌ <b>Ошибка:</b> Ваш аккаунт заблокирован.")
        return

    retire_date = check_player_retire_status(user_id)
    if retire_date:
        await message.answer(f"🥀 <b>Вы завершили карьеру!</b> Доступ закрыт.")
        return

    # ПРОВЕРКА НА АДМИНИСТРАТОРА (УБИРАЕМ КУЛДАУН)
    is_admin = user_id in ADMIN_IDS
    
    if not is_admin:
        last_custom_time = user_data[7]
        cooldown_remaining = get_remaining_cooldown_time(last_custom_time, COOLDOWN_CUSTOM_TEXT_HOURS)
        if cooldown_remaining:
            await message.answer(
                f"⏳ <b>Перезарядка!</b>\n"
                f"Вы уже публиковали свой текст недавно. Лимит: 1 раз в 12 часов.\n"
                f"Осталось ждать: <b>{cooldown_remaining}</b>"
            )
            return
    else:
        await message.answer("🛡 <b>Режим Администратора:</b> Кулдаун на публикацию отключен.")

    await message.answer(
        "📝 <b>Режим: Свой текст</b>\n\n"
        "Напишите ваше сообщение полностью так, как вы хотите его видеть в канале.",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(CustomTextProcess.waiting_for_text)

# ==============================================================================
# 19. ТРАНСФЕРЫ (ПЕРЕХОДЫ СО СВОИМ ТЕКСТОМ И МОДЕРАЦИЕЙ)
# ==============================================================================

@dp.message(Command("invite"))
async def club_command_invite_with_custom_text(message: types.Message, state: FSMContext) -> None:
    """
    Команда /invite [ник]. 
    Теперь запрашивает свой текст для перехода и отправляет на модерацию.
    """
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        await message.answer("⚠️ <b>Использование:</b> <code>/invite [игровой ник]</code>")
        return
        
    target_nickname = args[1].strip()
    club_data = db_manager.get_club_by_admin_rights(user_id)
    
    if not club_data:
        await message.answer("❌ У вас нет прав администратора в каком-либо клубе.")
        return
        
    club_id = club_data[0]
    club_name = club_data[1]
    
    current_players = db_manager.get_club_players_list(club_id)
    if len(current_players) >= CLUB_MAX_PLAYERS:
        await message.answer("❌ <b>Лимит исчерпан!</b> В вашей команде уже 15 игроков. Удалите 1 игрока.")
        return

    target_data = db_manager.get_user_data_by_nickname(target_nickname)
    if not target_data:
        await message.answer(f"❌ Игрок с ником <b>{target_nickname}</b> не найден.")
        return
        
    target_id = target_data[0]
    
    # Различные проверки перед переходом
    if target_id == user_id:
        await message.answer("❌ Вы не можете пригласить самого себя.")
        return
    if target_data[4]:
        await message.answer("❌ Этот игрок заблокирован.")
        return
    if target_data[3] is not None:
        await message.answer("❌ Этот игрок уже состоит в другом клубе!")
        return
    if target_data[5] is not None:
        await message.answer("❌ Этот игрок завершил карьеру и не может вступить в клуб.")
        return

    # Сохраняем данные для следующего шага
    await state.update_data(
        target_id=target_id,
        club_id=club_id,
        club_name=club_name,
        target_nickname=target_nickname
    )
    
    await message.answer(
        f"📝 <b>Оформление перехода для {target_nickname}</b>\n\n"
        f"Введите <b>свой текст</b>, который будет добавлен к посту об официальном трансфере (P.s: ...).\n"
        f"Этот пост будет отправлен на модерацию администраторам.",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(TransferProcess.waiting_for_transfer_text)

@dp.message(StateFilter(TransferProcess.waiting_for_transfer_text))
async def process_custom_transfer_text(message: types.Message, state: FSMContext) -> None:
    """Обрабатывает текст для трансфера и шлет заявку админам."""
    custom_text = message.text
    user_id = message.from_user.id
    
    data = await state.get_data()
    target_id = data.get("target_id")
    club_id = data.get("club_id")
    club_name = data.get("club_name")
    target_nickname = data.get("target_nickname")
    
    # Формируем итоговый вид поста согласно ТЗ для трансферов
    post_content = (
        "❗️ОФИЦИАЛЬНО: ТРАНСФЕРЫ📍\n\n"
        f"😎 <b>{target_nickname}</b> - Свободный агент ➡️ <b>{club_name}</b>\n"
        f"P.s: {custom_text}"
    )
    
    admins_notified_count = 0
    
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = (
                f"🔔 <b>НОВЫЙ ТРАНСФЕР НА МОДЕРАЦИЮ</b>\n"
                f"Клуб: <code>{club_name}</code> приглашает <code>{target_nickname}</code>\n\n"
                f"<b>Текст для публикации:</b>\n"
                f"----------------------------------------\n"
                f"{post_content}\n"
                f"----------------------------------------"
            )
            # Передаем target_id и club_id в callback_data
            keyboard = get_anketa_approval_keyboard_updated(
                user_id=user_id, 
                action_type="transfer", 
                target_id=target_id, 
                club_id=club_id
            )
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
            admins_notified_count += 1
        except Exception as e:
            logger.error(f"Не удалось доставить запрос на трансфер админу {admin_id}: {e}")

    if admins_notified_count > 0:
        await message.answer(
            "✅ <b>Запрос на трансфер успешно отправлен на модерацию!</b>\n"
            "После одобрения игрок будет автоматически добавлен в клуб, а пост появится в канале."
        )
        logger.info(f"Трансфер {target_nickname} в {club_name} отправлен на модерацию.")
    else:
        await message.answer("⚠️ <b>Произошла ошибка!</b> Администраторы недоступны.")
        
    await state.clear()

# ==============================================================================
# 20. ЦЕНТРАЛЬНЫЙ ОБРАБОТЧИК МОДЕРАЦИИ (КНОПКИ ПРИНЯТЬ / ОТКЛОНИТЬ)
# ==============================================================================

@dp.callback_query(F.data.startswith("approve_"))
async def process_global_approval(callback: types.CallbackQuery) -> None:
    """
    Глобальный обработчик кнопки "✅ Принять" для ВСЕХ типов анкет:
    - freeagent (Свободный агент)
    - customtext (Свой текст)
    - retire (Завершение карьеры)
    - return (Возвращение карьеры)
    - transfer (Трансфер)
    """
    parts = callback.data.split("_")
    action_type = parts[1]
    
    original_text = callback.message.text
    try:
        # Извлекаем текст поста между линиями "----------------------------------------"
        post_content = original_text.split("----------------------------------------")[1].strip()
    except IndexError:
        await callback.answer("❌ Ошибка парсинга сообщения. Пост поврежден.", show_alert=True)
        return

    # ================= ЛОГИКА ДЛЯ ТРАНСФЕРОВ =================
    if action_type == "transfer":
        target_id = int(parts[2])
        club_id = int(parts[3])
        
        # Обновляем БД: переводим игрока в клуб
        success = db_manager.change_player_club(user_id=target_id, new_club_id=club_id)
        if success:
            db_manager.add_transfer_count(club_id)
            try:
                await bot.send_message(chat_id=CHANNEL_ID, text=post_content)
                await callback.message.edit_text(f"✅ <b>ТРАНСФЕР ОДОБРЕН И ОПУБЛИКОВАН</b>\n\n{post_content}")
                
                # Уведомляем игрока
                club_data = db_manager.get_club_info_by_id(club_id)
                club_name = club_data[1] if club_data else "Неизвестный клуб"
                await bot.send_message(
                    chat_id=target_id, 
                    text=f"🎉 <b>Ваш трансфер одобрен!</b> Вы официально стали игроком команды <b>{club_name}</b>."
                )
            except Exception as e:
                logger.error(f"Ошибка публикации трансфера: {e}")
                await callback.answer("⚠️ Ошибка публикации.", show_alert=True)
        else:
            await callback.message.edit_text("❌ Ошибка БД при проведении трансфера (Возможно, игрок удален).")
        return

    # ================= ЛОГИКА ДЛЯ ОСТАЛЬНЫХ ТИПОВ =================
    user_id = int(parts[2])
    
    if action_type == "retire":
        freeze_date = db_manager.execute_career_retirement(user_id)
        notification_text = f"🥀 <b>Ваш запрос одобрен.</b> Карьера завершена до {freeze_date.strftime('%d.%m.%Y %H:%M')}."
        
    elif action_type == "return":
        db_manager.execute_career_return(user_id)
        notification_text = "❤️ <b>Ваш запрос одобрен.</b> Вы успешно вернулись в карьеру!"
        
    elif action_type in ["freeagent", "customtext"]:
        notification_text = "🎉 <b>Отличные новости!</b> Ваша анкета была одобрена и опубликована!"
        
    else:
        await callback.answer("❌ Неизвестный тип действия.", show_alert=True)
        return

    # Публикация в канал и уведомления
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=post_content)
        await callback.message.edit_text(f"✅ <b>ОДОБРЕНО И ОПУБЛИКОВАНО</b>\n\n{post_content}")
        await bot.send_message(chat_id=user_id, text=notification_text)
        logger.info(f"Действие '{action_type}' от пользователя {user_id} одобрено.")
    except Exception as e:
        logger.error(f"Ошибка публикации поста ({action_type}): {e}")
        await callback.answer("⚠️ Ошибка публикации в канал. Проверьте права бота.", show_alert=True)

@dp.callback_query(F.data.startswith("reject_"))
async def process_global_rejection(callback: types.CallbackQuery) -> None:
    """
    Глобальный обработчик кнопки "❌ Отклонить".
    """
    parts = callback.data.split("_")
    action_type = parts[1]
    
    await callback.message.edit_text(f"❌ <b>ОТКЛОНЕНО АДМИНИСТРАТОРОМ</b>\n\n{callback.message.text}")
    
    if action_type == "transfer":
        # Если отклонили трансфер, уведомляем владельца (в данном случае мы не знаем ID владельца напрямую из callback,
        # но трансфер просто отменяется, БД не меняется).
        return
        
    user_id = int(parts[2])
    
    # Уведомление пользователю об отклонении
    try:
        await bot.send_message(
            chat_id=user_id,
            text=(
                "⚠️ <b>Ваша заявка была отклонена модератором.</b>\n"
                "Если это была анкета, убедитесь, что она не нарушает правила оформления."
            )
        )
        logger.info(f"Заявка от {user_id} ({action_type}) отклонена.")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления об отклонении: {e}")

# ==============================================================================
# 21. ОБНОВЛЕННАЯ АДМИН-ПАНЕЛЬ (КНОПКА: ВЕРНУТЬ КАРЬЕРУ ПО ID)
# ==============================================================================

@dp.message(F.text == "⚙️ Админ Панель")
async def superadmin_panel_open_updated(message: types.Message) -> None:
    """Открывает обновленную админ-панель."""
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "🛡 <b>Вход в Расширенную Админ Панель выполнен.</b>\nВыберите действие:", 
        reply_markup=get_superadmin_menu_updated()
    )

@dp.message(F.text == "❤️ Вернуть карьеру игроку")
async def admin_return_career_start(message: types.Message, state: FSMContext) -> None:
    """Начало процесса принудительного возвращения карьеры игроку админом."""
    if message.from_user.id not in ADMIN_IDS: 
        return
        
    await message.answer(
        "Введите <b>Telegram ID</b> игрока, которому необходимо принудительно вернуть карьеру (снять заморозку):\n"
        "<i>Можно узнать ID в профиле игрока или через логи.</i>", 
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(AdminReturnCareerProcess.waiting_for_user_id)

@dp.message(StateFilter(AdminReturnCareerProcess.waiting_for_user_id))
async def admin_return_career_execute(message: types.Message, state: FSMContext) -> None:
    """Выполнение снятия статуса завершения карьеры по ID."""
    if not message.text.isdigit():
        await message.answer("❌ <b>Ошибка:</b> Telegram ID должен состоять только из цифр. Попробуйте снова:")
        return
        
    target_id = int(message.text)
    user_data = db_manager.get_user_data_by_id(target_id)
    
    if not user_data:
        await message.answer(f"❌ Пользователь с ID <code>{target_id}</code> не найден в базе данных.")
        await state.clear()
        return
        
    nickname = user_data[2]
    
    if user_data[5] is None:
        await message.answer(f"⚠️ Игрок <b>{nickname}</b> (ID: {target_id}) не завершал карьеру (статус активен).")
        await state.clear()
        return
        
    # Применяем возвращение карьеры в БД
    success = db_manager.execute_career_return(target_id)
    
    if success:
        await message.answer(f"✅ <b>Успешно!</b>\nИгроку <b>{nickname}</b> (ID: {target_id}) принудительно возвращена карьера.")
        # Попытка уведомить самого игрока
        try:
            await bot.send_message(
                chat_id=target_id,
                text="❤️ <b>Администратор принудительно вернул вам карьеру!</b>\nОграничения сняты."
            )
        except Exception:
            pass
    else:
        await message.answer("❌ Произошла ошибка базы данных при изменении статуса.")
        
    await state.clear()

# ==============================================================================
# КОНЕЦ ЧАСТИ 2. 
# Весь заявленный функционал интегрирован, все проверки работают безопасно.
# ==============================================================================

from aiogram.filters import StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from datetime import datetime
import asyncio

# ==============================================================================
# 16. ДОПОЛНИТЕЛЬНЫЕ МАШИНЫ СОСТОЯНИЙ И ОБНОВЛЕНИЕ КЛАВИАТУР
# ==============================================================================

class TransferProcess(StatesGroup):
    """FSM для оформления перехода игрока в клуб (со своим текстом)."""
    waiting_for_transfer_text = State()

class AdminReturnCareerProcess(StatesGroup):
    """FSM для возвращения карьеры игроку по его Telegram ID через админ-панель."""
    waiting_for_user_id = State()

def get_superadmin_menu_updated() -> ReplyKeyboardMarkup:
    """
    ОБНОВЛЕННАЯ Клавиатура админ-панели для владельцев бота.
    Добавлена кнопка возвращения карьеры.
    """
    builder = ReplyKeyboardBuilder()
    
    # Ряд 1: Управление клубами
    builder.row(
        KeyboardButton(text="➕ Добавить клуб"),
        KeyboardButton(text="➖ Убрать клуб")
    )
    
    # Ряд 2: Управление блокировками
    builder.row(
        KeyboardButton(text="🚫 Забанить игрока"),
        KeyboardButton(text="✅ Разбанить игрока")
    )
    
    # Ряд 3: Управление карьерой (НОВОЕ)
    builder.row(
        KeyboardButton(text="❤️ Вернуть карьеру игроку")
    )
    
    # Ряд 4: Выход
    builder.row(
        KeyboardButton(text="🔙 Выйти из админ панели")
    )
    
    return builder.as_markup(resize_keyboard=True)

def get_anketa_approval_keyboard_updated(user_id: int, action_type: str, target_id: int = 0, club_id: int = 0) -> InlineKeyboardMarkup:
    """
    ОБНОВЛЕННАЯ Инлайн-клавиатура для модерации.
    Поддерживает новые типы действий: retire, return, transfer.
    Для трансфера передаются дополнительные ID.
    """
    builder = InlineKeyboardBuilder()
    
    # Формируем callback_data в зависимости от типа действия
    if action_type == "transfer":
        approve_cb = f"approve_transfer_{target_id}_{club_id}"
        reject_cb = f"reject_transfer_{target_id}_{club_id}"
    else:
        approve_cb = f"approve_{action_type}_{user_id}"
        reject_cb = f"reject_{action_type}_{user_id}"
        
    builder.button(text="✅ Принять", callback_data=approve_cb)
    builder.button(text="❌ Отклонить", callback_data=reject_cb)
    
    builder.adjust(2)
    return builder.as_markup()

# ==============================================================================
# 17. МОДЕРАЦИЯ: ЗАВЕРШЕНИЕ И ВОЗВРАЩЕНИЕ КАРЬЕРЫ
# ==============================================================================

@dp.message(F.text == "🥀 Завершения карьеры")
async def handle_career_retire_moderation(message: types.Message, state: FSMContext) -> None:
    """
    Инициирует процесс завершения карьеры.
    Вместо мгновенного завершения, отправляет запрос на модерацию администраторам.
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        await message.answer("❌ <b>Ошибка:</b> Вы не зарегистрированы в системе.")
        return
        
    # Проверка на блокировку аккаунта
    if bool(user_data[4]):
        await message.answer("❌ <b>Отказано:</b> Вы заблокированы и не можете использовать эту функцию.")
        return

    # Проверка: возможно, карьера уже завершена
    retire_end_date = check_player_retire_status(user_id)
    if retire_end_date:
        await message.answer(
            f"⚠️ <b>Ваша карьера уже завершена!</b>\n"
            f"Ожидайте до: <b>{retire_end_date.strftime('%d.%m.%Y %H:%M')}</b>\n"
            f"Или нажмите «❤️ Возращения карьеры», чтобы вернуться досрочно."
        )
        return

    username = user_data[1]
    nickname = user_data[2]
    
    # Формируем текст для предпросмотра админам
    post_text = (
        "❗️ОФИЦИАЛЬНО: ЗАВЕРШЕНИЕ КАРЬЕРЫ🥀\n\n"
        f"😎 <b>{nickname}</b> ({username}) - завершение карьеры."
    )
    
    admins_notified_count = 0
    
    # Отправляем запрос всем администраторам
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = (
                f"🔔 <b>ЗАПРОС НА ЗАВЕРШЕНИЕ КАРЬЕРЫ</b>\n"
                f"От игрока: <code>{nickname}</code> (ID: {user_id})\n\n"
                f"<b>Текст поста:</b>\n"
                f"----------------------------------------\n"
                f"{post_text}\n"
                f"----------------------------------------"
            )
            keyboard = get_anketa_approval_keyboard_updated(user_id=user_id, action_type="retire")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
            admins_notified_count += 1
        except Exception as e:
            logger.error(f"Не удалось отправить запрос на завершение карьеры админу {admin_id}: {e}")

    if admins_notified_count > 0:
        await message.answer(
            "✅ <b>Ваш запрос на завершение карьеры отправлен администраторам!</b>\n"
            "После проверки и одобрения, ваш статус будет изменен, а пост опубликован в канале."
        )
    else:
        await message.answer("⚠️ <b>Произошла ошибка!</b> Администраторы сейчас недоступны.")

@dp.message(F.text == "❤️ Возращения карьеры")
async def handle_career_return_moderation(message: types.Message) -> None:
    """
    Инициирует процесс возвращения в карьеру через модерацию.
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return
        
    if bool(user_data[4]):
        await message.answer("❌ <b>Отказано:</b> Вы заблокированы.")
        return

    # Проверяем, завершена ли карьера
    if user_data[5] is None:
        await message.answer("⚠️ <b>Ошибка:</b> Ваша карьера активна. Вы не завершали ее.")
        return

    username = user_data[1]
    nickname = user_data[2]
    
    post_text = (
        "❗️ОФИЦИАЛЬНО: ВОЗРАЩЕНИЕ КАРЬЕРЫ❤️\n\n"
        f"😎 <b>{nickname}</b> ({username}) - возвращение в карьеру."
    )
    
    admins_notified_count = 0
    
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = (
                f"🔔 <b>ЗАПРОС НА ВОЗВРАЩЕНИЕ В КАРЬЕРУ</b>\n"
                f"От игрока: <code>{nickname}</code> (ID: {user_id})\n\n"
                f"<b>Текст поста:</b>\n"
                f"----------------------------------------\n"
                f"{post_text}\n"
                f"----------------------------------------"
            )
            keyboard = get_anketa_approval_keyboard_updated(user_id=user_id, action_type="return")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
            admins_notified_count += 1
        except Exception as e:
            logger.error(f"Не удалось отправить запрос на возвращение карьеры админу {admin_id}: {e}")

    if admins_notified_count > 0:
        await message.answer(
            "✅ <b>Запрос на возвращение в карьеру отправлен на модерацию!</b>\n"
            "Ожидайте одобрения администраторов."
        )
    else:
        await message.answer("⚠️ <b>Произошла ошибка!</b> Администраторы сейчас недоступны.")

# ==============================================================================
# 18. ПУБЛИКАЦИЯ ПОСТОВ (С ОТКЛЮЧЕНИЕМ КД ДЛЯ АДМИНОВ)
# ==============================================================================

@dp.message(F.text == "🏃‍♂️ Свободный агент")
async def handle_free_agent_button_no_cd(message: types.Message, state: FSMContext) -> None:
    """
    Подача заявки свободного агента.
    Для обычных игроков действует кулдаун 6 часов.
    Для администраторов кулдаун ОТКЛЮЧЕН.
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return

    if bool(user_data[4]):
        await message.answer("❌ <b>Ошибка:</b> Ваш аккаунт заблокирован.")
        return

    retire_date = check_player_retire_status(user_id)
    if retire_date:
        await message.answer(f"🥀 <b>Вы завершили карьеру!</b> Доступ закрыт.")
        return

    # ПРОВЕРКА НА АДМИНИСТРАТОРА (УБИРАЕМ КУЛДАУН)
    is_admin = user_id in ADMIN_IDS
    
    if not is_admin:
        last_free_agent_time = user_data[6]
        cooldown_remaining = get_remaining_cooldown_time(last_free_agent_time, COOLDOWN_FREE_AGENT_HOURS)
        if cooldown_remaining:
            await message.answer(
                f"⏳ <b>Перезарядка!</b>\n"
                f"Вы уже публиковали анкету недавно.\n"
                f"Осталось ждать: <b>{cooldown_remaining}</b>"
            )
            return
    else:
        await message.answer("🛡 <b>Режим Администратора:</b> Кулдаун на публикацию отключен.")

    await message.answer(
        "📝 <b>Режим: Свободный агент</b>\n\n"
        "Напишите текст вашего объявления (например: на какой позиции играете, опыт).\n"
        "Этот текст будет добавлен в анкету после слов 'P.s:'",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(FreeAgentProcess.waiting_for_text)

@dp.message(F.text == "📝 Свой текст")
async def handle_custom_text_button_no_cd(message: types.Message, state: FSMContext) -> None:
    """
    Подача кастомного текста.
    Для обычных игроков действует кулдаун 12 часов.
    Для администраторов кулдаун ОТКЛЮЧЕН.
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return

    if bool(user_data[4]):
        await message.answer("❌ <b>Ошибка:</b> Ваш аккаунт заблокирован.")
        return

    retire_date = check_player_retire_status(user_id)
    if retire_date:
        await message.answer(f"🥀 <b>Вы завершили карьеру!</b> Доступ закрыт.")
        return

    # ПРОВЕРКА НА АДМИНИСТРАТОРА (УБИРАЕМ КУЛДАУН)
    is_admin = user_id in ADMIN_IDS
    
    if not is_admin:
        last_custom_time = user_data[7]
        cooldown_remaining = get_remaining_cooldown_time(last_custom_time, COOLDOWN_CUSTOM_TEXT_HOURS)
        if cooldown_remaining:
            await message.answer(
                f"⏳ <b>Перезарядка!</b>\n"
                f"Вы уже публиковали свой текст недавно. Лимит: 1 раз в 12 часов.\n"
                f"Осталось ждать: <b>{cooldown_remaining}</b>"
            )
            return
    else:
        await message.answer("🛡 <b>Режим Администратора:</b> Кулдаун на публикацию отключен.")

    await message.answer(
        "📝 <b>Режим: Свой текст</b>\n\n"
        "Напишите ваше сообщение полностью так, как вы хотите его видеть в канале.",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(CustomTextProcess.waiting_for_text)

# ==============================================================================
# 19. ТРАНСФЕРЫ (ПЕРЕХОДЫ СО СВОИМ ТЕКСТОМ И МОДЕРАЦИЕЙ)
# ==============================================================================

@dp.message(Command("invite"))
async def club_command_invite_with_custom_text(message: types.Message, state: FSMContext) -> None:
    """
    Команда /invite [ник]. 
    Теперь запрашивает свой текст для перехода и отправляет на модерацию.
    """
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        await message.answer("⚠️ <b>Использование:</b> <code>/invite [игровой ник]</code>")
        return
        
    target_nickname = args[1].strip()
    club_data = db_manager.get_club_by_admin_rights(user_id)
    
    if not club_data:
        await message.answer("❌ У вас нет прав администратора в каком-либо клубе.")
        return
        
    club_id = club_data[0]
    club_name = club_data[1]
    
    current_players = db_manager.get_club_players_list(club_id)
    if len(current_players) >= CLUB_MAX_PLAYERS:
        await message.answer("❌ <b>Лимит исчерпан!</b> В вашей команде уже 15 игроков. Удалите 1 игрока.")
        return

    target_data = db_manager.get_user_data_by_nickname(target_nickname)
    if not target_data:
        await message.answer(f"❌ Игрок с ником <b>{target_nickname}</b> не найден.")
        return
        
    target_id = target_data[0]
    
    # Различные проверки перед переходом
    if target_id == user_id:
        await message.answer("❌ Вы не можете пригласить самого себя.")
        return
    if target_data[4]:
        await message.answer("❌ Этот игрок заблокирован.")
        return
    if target_data[3] is not None:
        await message.answer("❌ Этот игрок уже состоит в другом клубе!")
        return
    if target_data[5] is not None:
        await message.answer("❌ Этот игрок завершил карьеру и не может вступить в клуб.")
        return

    # Сохраняем данные для следующего шага
    await state.update_data(
        target_id=target_id,
        club_id=club_id,
        club_name=club_name,
        target_nickname=target_nickname
    )
    
    await message.answer(
        f"📝 <b>Оформление перехода для {target_nickname}</b>\n\n"
        f"Введите <b>свой текст</b>, который будет добавлен к посту об официальном трансфере (P.s: ...).\n"
        f"Этот пост будет отправлен на модерацию администраторам.",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(TransferProcess.waiting_for_transfer_text)

@dp.message(StateFilter(TransferProcess.waiting_for_transfer_text))
async def process_custom_transfer_text(message: types.Message, state: FSMContext) -> None:
    """Обрабатывает текст для трансфера и шлет заявку админам."""
    custom_text = message.text
    user_id = message.from_user.id
    
    data = await state.get_data()
    target_id = data.get("target_id")
    club_id = data.get("club_id")
    club_name = data.get("club_name")
    target_nickname = data.get("target_nickname")
    
    # Формируем итоговый вид поста согласно ТЗ для трансферов
    post_content = (
        "❗️ОФИЦИАЛЬНО: ТРАНСФЕРЫ📍\n\n"
        f"😎 <b>{target_nickname}</b> - Свободный агент ➡️ <b>{club_name}</b>\n"
        f"P.s: {custom_text}"
    )
    
    admins_notified_count = 0
    
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = (
                f"🔔 <b>НОВЫЙ ТРАНСФЕР НА МОДЕРАЦИЮ</b>\n"
                f"Клуб: <code>{club_name}</code> приглашает <code>{target_nickname}</code>\n\n"
                f"<b>Текст для публикации:</b>\n"
                f"----------------------------------------\n"
                f"{post_content}\n"
                f"----------------------------------------"
            )
            # Передаем target_id и club_id в callback_data
            keyboard = get_anketa_approval_keyboard_updated(
                user_id=user_id, 
                action_type="transfer", 
                target_id=target_id, 
                club_id=club_id
            )
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
            admins_notified_count += 1
        except Exception as e:
            logger.error(f"Не удалось доставить запрос на трансфер админу {admin_id}: {e}")

    if admins_notified_count > 0:
        await message.answer(
            "✅ <b>Запрос на трансфер успешно отправлен на модерацию!</b>\n"
            "После одобрения игрок будет автоматически добавлен в клуб, а пост появится в канале."
        )
        logger.info(f"Трансфер {target_nickname} в {club_name} отправлен на модерацию.")
    else:
        await message.answer("⚠️ <b>Произошла ошибка!</b> Администраторы недоступны.")
        
    await state.clear()

# ==============================================================================
# 20. ЦЕНТРАЛЬНЫЙ ОБРАБОТЧИК МОДЕРАЦИИ (КНОПКИ ПРИНЯТЬ / ОТКЛОНИТЬ)
# ==============================================================================

@dp.callback_query(F.data.startswith("approve_"))
async def process_global_approval(callback: types.CallbackQuery) -> None:
    """
    Глобальный обработчик кнопки "✅ Принять" для ВСЕХ типов анкет:
    - freeagent (Свободный агент)
    - customtext (Свой текст)
    - retire (Завершение карьеры)
    - return (Возвращение карьеры)
    - transfer (Трансфер)
    """
    parts = callback.data.split("_")
    action_type = parts[1]
    
    original_text = callback.message.text
    try:
        # Извлекаем текст поста между линиями "----------------------------------------"
        post_content = original_text.split("----------------------------------------")[1].strip()
    except IndexError:
        await callback.answer("❌ Ошибка парсинга сообщения. Пост поврежден.", show_alert=True)
        return

    # ================= ЛОГИКА ДЛЯ ТРАНСФЕРОВ =================
    if action_type == "transfer":
        target_id = int(parts[2])
        club_id = int(parts[3])
        
        # Обновляем БД: переводим игрока в клуб
        success = db_manager.change_player_club(user_id=target_id, new_club_id=club_id)
        if success:
            db_manager.add_transfer_count(club_id)
            try:
                await bot.send_message(chat_id=CHANNEL_ID, text=post_content)
                await callback.message.edit_text(f"✅ <b>ТРАНСФЕР ОДОБРЕН И ОПУБЛИКОВАН</b>\n\n{post_content}")
                
                # Уведомляем игрока
                club_data = db_manager.get_club_info_by_id(club_id)
                club_name = club_data[1] if club_data else "Неизвестный клуб"
                await bot.send_message(
                    chat_id=target_id, 
                    text=f"🎉 <b>Ваш трансфер одобрен!</b> Вы официально стали игроком команды <b>{club_name}</b>."
                )
            except Exception as e:
                logger.error(f"Ошибка публикации трансфера: {e}")
                await callback.answer("⚠️ Ошибка публикации.", show_alert=True)
        else:
            await callback.message.edit_text("❌ Ошибка БД при проведении трансфера (Возможно, игрок удален).")
        return

    # ================= ЛОГИКА ДЛЯ ОСТАЛЬНЫХ ТИПОВ =================
    user_id = int(parts[2])
    
    if action_type == "retire":
        freeze_date = db_manager.execute_career_retirement(user_id)
        notification_text = f"🥀 <b>Ваш запрос одобрен.</b> Карьера завершена до {freeze_date.strftime('%d.%m.%Y %H:%M')}."
        
    elif action_type == "return":
        db_manager.execute_career_return(user_id)
        notification_text = "❤️ <b>Ваш запрос одобрен.</b> Вы успешно вернулись в карьеру!"
        
    elif action_type in ["freeagent", "customtext"]:
        notification_text = "🎉 <b>Отличные новости!</b> Ваша анкета была одобрена и опубликована!"
        
    else:
        await callback.answer("❌ Неизвестный тип действия.", show_alert=True)
        return

    # Публикация в канал и уведомления
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=post_content)
        await callback.message.edit_text(f"✅ <b>ОДОБРЕНО И ОПУБЛИКОВАНО</b>\n\n{post_content}")
        await bot.send_message(chat_id=user_id, text=notification_text)
        logger.info(f"Действие '{action_type}' от пользователя {user_id} одобрено.")
    except Exception as e:
        logger.error(f"Ошибка публикации поста ({action_type}): {e}")
        await callback.answer("⚠️ Ошибка публикации в канал. Проверьте права бота.", show_alert=True)

@dp.callback_query(F.data.startswith("reject_"))
async def process_global_rejection(callback: types.CallbackQuery) -> None:
    """
    Глобальный обработчик кнопки "❌ Отклонить".
    """
    parts = callback.data.split("_")
    action_type = parts[1]
    
    await callback.message.edit_text(f"❌ <b>ОТКЛОНЕНО АДМИНИСТРАТОРОМ</b>\n\n{callback.message.text}")
    
    if action_type == "transfer":
        # Если отклонили трансфер, уведомляем владельца (в данном случае мы не знаем ID владельца напрямую из callback,
        # но трансфер просто отменяется, БД не меняется).
        return
        
    user_id = int(parts[2])
    
    # Уведомление пользователю об отклонении
    try:
        await bot.send_message(
            chat_id=user_id,
            text=(
                "⚠️ <b>Ваша заявка была отклонена модератором.</b>\n"
                "Если это была анкета, убедитесь, что она не нарушает правила оформления."
            )
        )
        logger.info(f"Заявка от {user_id} ({action_type}) отклонена.")
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления об отклонении: {e}")

# ==============================================================================
# 21. ОБНОВЛЕННАЯ АДМИН-ПАНЕЛЬ (КНОПКА: ВЕРНУТЬ КАРЬЕРУ ПО ID)
# ==============================================================================

@dp.message(F.text == "⚙️ Админ Панель")
async def superadmin_panel_open_updated(message: types.Message) -> None:
    """Открывает обновленную админ-панель."""
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "🛡 <b>Вход в Расширенную Админ Панель выполнен.</b>\nВыберите действие:", 
        reply_markup=get_superadmin_menu_updated()
    )

@dp.message(F.text == "❤️ Вернуть карьеру игроку")
async def admin_return_career_start(message: types.Message, state: FSMContext) -> None:
    """Начало процесса принудительного возвращения карьеры игроку админом."""
    if message.from_user.id not in ADMIN_IDS: 
        return
        
    await message.answer(
        "Введите <b>Telegram ID</b> игрока, которому необходимо принудительно вернуть карьеру (снять заморозку):\n"
        "<i>Можно узнать ID в профиле игрока или через логи.</i>", 
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(AdminReturnCareerProcess.waiting_for_user_id)

@dp.message(StateFilter(AdminReturnCareerProcess.waiting_for_user_id))
async def admin_return_career_execute(message: types.Message, state: FSMContext) -> None:
    """Выполнение снятия статуса завершения карьеры по ID."""
    if not message.text.isdigit():
        await message.answer("❌ <b>Ошибка:</b> Telegram ID должен состоять только из цифр. Попробуйте снова:")
        return
        
    target_id = int(message.text)
    user_data = db_manager.get_user_data_by_id(target_id)
    
    if not user_data:
        await message.answer(f"❌ Пользователь с ID <code>{target_id}</code> не найден в базе данных.")
        await state.clear()
        return
        
    nickname = user_data[2]
    
    if user_data[5] is None:
        await message.answer(f"⚠️ Игрок <b>{nickname}</b> (ID: {target_id}) не завершал карьеру (статус активен).")
        await state.clear()
        return
        
    # Применяем возвращение карьеры в БД
    success = db_manager.execute_career_return(target_id)
    
    if success:
        await message.answer(f"✅ <b>Успешно!</b>\nИгроку <b>{nickname}</b> (ID: {target_id}) принудительно возвращена карьера.")
        # Попытка уведомить самого игрока
        try:
            await bot.send_message(
                chat_id=target_id,
                text="❤️ <b>Администратор принудительно вернул вам карьеру!</b>\nОграничения сняты."
            )
        except Exception:
            pass
    else:
        await message.answer("❌ Произошла ошибка базы данных при изменении статуса.")
        
    await state.clear()

# ==============================================================================
# КОНЕЦ ЧАСТИ 2. 
# Весь заявленный функционал интегрирован, все проверки работают безопасно.
# ==============================================================================


