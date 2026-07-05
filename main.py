
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

