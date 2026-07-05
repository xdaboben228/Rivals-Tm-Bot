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

# Токен бота (из ТЗ)
BOT_TOKEN = "8768994062:AAFWMZZIl19tDmnKjBcyFXEnE_BZLw5ckw0"

# Список ID владельцев (администраторов) (из ТЗ)
ADMIN_IDS = [6885478196, 5845609895]

# ID канала для публикации постов (необходимо заменить на реальный ID или юзернейм)
# Например: "@rivals_transfers" или "-1001234567890"
CHANNEL_ID = "-1004377865527"

# Константы для кулдаунов (в часах и днях, как указано в ТЗ)
COOLDOWN_FREE_AGENT_HOURS = 6
COOLDOWN_CUSTOM_TEXT_HOURS = 12
COOLDOWN_RETIRE_DAYS = 15
COOLDOWN_NICKNAME_CHANGE_DAYS = 30

# Лимит игроков в одной команде
CLUB_MAX_PLAYERS = 15

# ==============================================================================
# 2. НАСТРОЙКА ПРОФЕССИОНАЛЬНОГО ЛОГГИРОВАНИЯ
# ==============================================================================

# Создаем базовый логгер для отслеживания работы бота
logger = logging.getLogger("RivalsBotLogger")
logger.setLevel(logging.INFO)

# Формат вывода логов: Время - Уровень - Сообщение
formatter = logging.Formatter(
    fmt="[%(asctime)s] %(levelname)s - %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Обработчик для вывода логов в консоль
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logger.info("Инициализация системы Трансфермаркета Rivals...")

# Инициализация объектов Bot и Dispatcher (основа aiogram 3.x)
# Используем parse_mode="HTML" для поддержки жирного текста, курсива и т.д.
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ==============================================================================
# 3. МАШИНЫ СОСТОЯНИЙ (FSM - Finite State Machine)
# ==============================================================================
# Эти классы отвечают за то, чтобы бот запоминал, на каком шаге находится игрок.
# Например, если игрок нажал "Смена никнейма", бот будет ждать от него текст.

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

class SuperAdminProcess(StatesGroup):
    """Состояния для админ-панели (добавление клубов, баны)."""
    waiting_for_club_name = State()
    waiting_for_club_owner_id = State()
    waiting_for_ban_nickname = State()
    waiting_for_unban_nickname = State()

class ClubManagementProcess(StatesGroup):
    """Состояния для владельцев клубов (набор состава, управление замами)."""
    waiting_for_deputy_nickname = State()
    waiting_for_player_invite = State()
    waiting_for_player_kick = State()

# ==============================================================================
# 4. ФУНКЦИИ ГЕНЕРАЦИИ КЛАВИАТУР (ОФОРМЛЕНИЕ И ЭМОДЗИ)
# ==============================================================================

def get_player_main_menu(user_id: int, is_club_owner_or_deputy: bool = False) -> ReplyKeyboardMarkup:
    """
    Генерирует главную клавиатуру пользователя.
    Она динамическая: если игрок - админ клуба, у него есть кнопка "Мой клуб".
    Если игрок - главный админ бота, у него есть "Админ Панель".
    """
    builder = ReplyKeyboardBuilder()
    
    # Первый ряд кнопок (Публикации)
    builder.row(
        KeyboardButton(text="🏃‍♂️ Свободный агент"),
        KeyboardButton(text="📝 Свой текст")
    )
    
    # Второй ряд кнопок (Карьера)
    builder.row(
        KeyboardButton(text="🥀 Завершения карьеры"),
        KeyboardButton(text="❤️ Возращения карьеры")
    )
    
    # Третий ряд кнопок (Настройки и профиль)
    builder.row(
        KeyboardButton(text="🔄 Смена никнейма"),
        KeyboardButton(text="👤 Профиль")
    )
    
    # Четвертый ряд (Помощь)
    builder.row(
        KeyboardButton(text="ℹ️ Помощь")
    )
    
    # Дополнительные кнопки для управления клубом (если есть права)
    if is_club_owner_or_deputy:
        builder.row(
            KeyboardButton(text="🛡 Мой клуб")
        )
        
    # Секретная кнопка для владельцев проекта
    if user_id in ADMIN_IDS:
        builder.row(
            KeyboardButton(text="⚙️ Админ Панель")
        )
        
    # Возвращаем клавиатуру, подгоняя ее размер под экран телефона
    return builder.as_markup(resize_keyboard=True)

def get_superadmin_menu() -> ReplyKeyboardMarkup:
    """
    Клавиатура админ-панели для владельцев бота.
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
    
    # Ряд 3: Выход
    builder.row(
        KeyboardButton(text="🔙 Выйти из админ панели")
    )
    
    return builder.as_markup(resize_keyboard=True)

def get_anketa_approval_keyboard(user_id: int, action_type: str) -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для главных админов. 
    Появляется под отправленными на проверку анкетами.
    action_type = "freeagent" или "customtext"
    """
    builder = InlineKeyboardBuilder()
    
    # Кнопка Принять
    builder.button(
        text="✅ Принять", 
        callback_data=f"approve_{action_type}_{user_id}"
    )
    
    # Кнопка Отклонить
    builder.button(
        text="❌ Отклонить", 
        callback_data=f"reject_{action_type}_{user_id}"
    )
    
    # Устанавливаем кнопки в один ряд
    builder.adjust(2)
    return builder.as_markup()

def get_club_management_inline() -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для управления составом заместителей клуба.
    Выводится при просмотре информации о своем клубе.
    """
    builder = InlineKeyboardBuilder()
    
    builder.button(
        text="➕ Добавить зама", 
        callback_data="club_add_deputy"
    )
    
    builder.button(
        text="➖ Убрать зама", 
        callback_data="club_remove_deputy"
    )
    
    builder.adjust(2)
    return builder.as_markup()

def get_cancel_inline_keyboard() -> InlineKeyboardMarkup:
    """Универсальная кнопка для отмены текущего действия (FSM)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="❌ Отмена", 
        callback_data="cancel_current_action"
    )
    return builder.as_markup()

# ==============================================================================
# 5. МАКСИМАЛЬНО ПРОДВИНУТАЯ И БЕЗОПАСНАЯ БАЗА ДАННЫХ
# ==============================================================================

class DatabaseManager:
    """
    Класс для управления базой данных SQLite3.
    Все запросы оборачиваются в try-except для предотвращения крашей бота.
    Соблюдены все требования ТЗ: кулдауны, статистика, профили, лимиты, клубы.
    """
    def __init__(self, db_path: str = "rivals_database.db"):
        self.db_path = db_path
        self.connection = None
        self.cursor = None
        self._connect_and_initialize()

    def _connect_and_initialize(self) -> None:
        """Подключается к файлу БД и создает все необходимые таблицы."""
        try:
            # check_same_thread=False нужен для работы с асинхронным aiogram
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self.cursor = self.connection.cursor()
            
            # Таблица 1: ПОЛЬЗОВАТЕЛИ (ИГРОКИ)
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
            
            # Таблица 2: КЛУБЫ
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

    # --------------------------------------------------------------------------
    # МЕТОДЫ УПРАВЛЕНИЯ ПОЛЬЗОВАТЕЛЯМИ
    # --------------------------------------------------------------------------
    
    def add_new_user(self, user_id: int, username: str, nickname: str) -> bool:
        """
        Регистрация нового пользователя.
        Возвращает True при успехе, False если никнейм уже существует.
        """
        try:
            self.cursor.execute('''
                INSERT INTO users (user_id, username, nickname) 
                VALUES (?, ?, ?)
            ''', (user_id, username, nickname))
            self.connection.commit()
            logger.info(f"Зарегистрирован новый игрок: {nickname} (ID: {user_id})")
            return True
        except sqlite3.IntegrityError:
            # Срабатывает, если нарушается UNIQUE для поля nickname
            logger.warning(f"Ошибка регистрации: Никнейм {nickname} уже занят.")
            return False
        except Exception as e:
            logger.error(f"Неизвестная ошибка БД при добавлении пользователя: {e}")
            return False

    def get_user_data_by_id(self, user_id: int) -> Optional[Tuple]:
        """
        Получение всей информации о пользователе по его Telegram ID.
        Возвращает кортеж с данными или None, если игрок не найден.
        """
        try:
            self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения пользователя {user_id}: {e}")
            return None

    def get_user_data_by_nickname(self, nickname: str) -> Optional[Tuple]:
        """
        Получение информации по игровому никнейму.
        Полезно для команд /invite, /delete и т.д.
        """
        try:
            self.cursor.execute("SELECT * FROM users WHERE nickname = ?", (nickname,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Ошибка поиска пользователя {nickname}: {e}")
            return None

    def update_user_nickname(self, user_id: int, new_nickname: str) -> bool:
        """
        Обновление никнейма игрока и запись времени смены (кулдаун 1 месяц).
        Возвращает False, если ник уже кем-то занят.
        """
        try:
            current_time = datetime.now()
            self.cursor.execute('''
                UPDATE users 
                SET nickname = ?, last_nickname_change = ? 
                WHERE user_id = ?
            ''', (new_nickname, current_time, user_id))
            self.connection.commit()
            logger.info(f"Пользователь {user_id} успешно сменил никнейм на {new_nickname}")
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.Error as e:
            logger.error(f"Ошибка при смене никнейма для {user_id}: {e}")
            return False

    # --------------------------------------------------------------------------
    # МЕТОДЫ УПРАВЛЕНИЯ КУЛДАУНАМИ И КАРЬЕРОЙ (По ТЗ)
    # --------------------------------------------------------------------------

    def set_action_cooldown(self, user_id: int, action_column: str) -> bool:
        """
        Устанавливает текущее время для колонки кулдауна.
        action_column может быть: 'last_free_agent' или 'last_custom_text'
        """
        try:
            current_time = datetime.now()
            query = f"UPDATE users SET {action_column} = ? WHERE user_id = ?"
            self.cursor.execute(query, (current_time, user_id))
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка установки кулдауна {action_column} для {user_id}: {e}")
            return False

    def execute_career_retirement(self, user_id: int) -> datetime:
        """
        Функция "Завершения карьеры". Замораживает профиль на 15 дней.
        Возвращает точную дату и время разморозки.
        """
        try:
            # Вычисляем дату окончания заморозки
            retire_end_date = datetime.now() + timedelta(days=COOLDOWN_RETIRE_DAYS)
            
            # Обновляем БД. Заодно выкидываем из клуба, если он там был (club_id = NULL)
            self.cursor.execute('''
                UPDATE users 
                SET retire_date = ?, club_id = NULL 
                WHERE user_id = ?
            ''', (retire_end_date, user_id))
            
            self.connection.commit()
            logger.info(f"Игрок {user_id} завершил карьеру до {retire_end_date}")
            return retire_end_date
        except sqlite3.Error as e:
            logger.error(f"Ошибка при завершении карьеры {user_id}: {e}")
            # Возвращаем текущее время при сбое, как фоллбек
            return datetime.now() 

    def execute_career_return(self, user_id: int) -> bool:
        """
        Функция "Возвращения карьеры".
        Снимает ограничения, обнуляя поле retire_date.
        """
        try:
            self.cursor.execute('''
                UPDATE users 
                SET retire_date = NULL 
                WHERE user_id = ?
            ''', (user_id,))
            self.connection.commit()
            logger.info(f"Игрок {user_id} успешно вернулся в карьеру.")
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка при возвращении карьеры {user_id}: {e}")
            return False

    def change_ban_status(self, nickname: str, is_banned: int) -> bool:
        """
        Блокировка или разблокировка игрока по его никнейму.
        is_banned: 1 (забанить) или 0 (разбанить)
        """
        try:
            self.cursor.execute('''
                UPDATE users 
                SET is_banned = ? 
                WHERE nickname = ?
            ''', (is_banned, nickname))
            self.connection.commit()
            # Проверяем, был ли обновлен хоть один ряд (существует ли игрок)
            if self.cursor.rowcount > 0:
                status_text = "ЗАБАНЕН" if is_banned == 1 else "РАЗБАНЕН"
                logger.info(f"Игрок {nickname} был {status_text} администратором.")
                return True
            return False
        except sqlite3.Error as e:
            logger.error(f"Ошибка при изменении бан-статуса для {nickname}: {e}")
            return False

    # --------------------------------------------------------------------------
    # МЕТОДЫ УПРАВЛЕНИЯ КЛУБАМИ (Сложная логика ТЗ)
    # --------------------------------------------------------------------------

    def create_new_club(self, club_name: str, owner_id: int) -> bool:
        """
        Создает новый клуб и автоматически делает создателя его владельцем и участником.
        """
        try:
            # 1. Создаем запись о клубе
            self.cursor.execute('''
                INSERT INTO clubs (club_name, owner_id) 
                VALUES (?, ?)
            ''', (club_name, owner_id))
            
            # Получаем сгенерированный ID клуба
            new_club_id = self.cursor.lastrowid
            
            # 2. Обновляем профиль владельца, назначая ему этот клуб
            self.cursor.execute('''
                UPDATE users 
                SET club_id = ? 
                WHERE user_id = ?
            ''', (new_club_id, owner_id))
            
            self.connection.commit()
            logger.info(f"Клуб '{club_name}' успешно создан! Владелец: {owner_id}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"Попытка создать клуб с существующим названием: {club_name}")
            return False
        except sqlite3.Error as e:
            logger.error(f"Ошибка БД при создании клуба '{club_name}': {e}")
            return False

    def get_club_info_by_id(self, club_id: int) -> Optional[Tuple]:
        """Получает всю строку данных клуба по его ID."""
        try:
            self.cursor.execute("SELECT * FROM clubs WHERE club_id = ?", (club_id,))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Ошибка получения данных клуба {club_id}: {e}")
            return None

    def get_all_clubs(self) -> List[Tuple]:
        """Получает список всех клубов для админ панели (чтобы убирать клубы)."""
        try:
            self.cursor.execute("SELECT club_id, club_name FROM clubs")
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении списка всех клубов: {e}")
            return []

    def get_club_by_admin_rights(self, user_id: int) -> Optional[Tuple]:
        """
        Ищет клуб, к которому пользователь имеет права админа 
        (является либо owner_id, либо deputy1_id, либо deputy2_id).
        """
        try:
            self.cursor.execute('''
                SELECT * FROM clubs 
                WHERE owner_id = ? OR deputy1_id = ? OR deputy2_id = ?
            ''', (user_id, user_id, user_id))
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            logger.error(f"Ошибка проверки админ-прав для {user_id}: {e}")
            return None

    def delete_club_fully(self, club_id: int) -> bool:
        """
        Полное удаление клуба. 
        Сначала нужно отвязать всех игроков от этого клуба (поставить club_id = NULL),
        а затем удалить сам клуб.
        """
        try:
            # 1. Отвязываем всех игроков (выгоняем из клуба)
            self.cursor.execute('''
                UPDATE users 
                SET club_id = NULL 
                WHERE club_id = ?
            ''', (club_id,))
            
            # 2. Удаляем запись о клубе
            self.cursor.execute('''
                DELETE FROM clubs 
                WHERE club_id = ?
            ''', (club_id,))
            
            self.connection.commit()
            logger.info(f"Клуб с ID {club_id} был полностью расформирован и удален.")
            return True
        except sqlite3.Error as e:
            logger.error(f"Критическая ошибка при удалении клуба {club_id}: {e}")
            return False

    def get_club_players_list(self, club_id: int) -> List[Tuple]:
        """
        Получает список всех участников клуба.
        Возвращает список кортежей (user_id, nickname).
        Нужно для команды /viewteam и проверки лимита (15 человек).
        """
        try:
            self.cursor.execute('''
                SELECT user_id, nickname 
                FROM users 
                WHERE club_id = ?
            ''', (club_id,))
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении состава клуба {club_id}: {e}")
            return []

    def change_player_club(self, user_id: int, new_club_id: Optional[int]) -> bool:
        """
        Изменяет клуб игрока (приглашение или кик).
        Если new_club_id = None, то игрок становится свободным агентом.
        """
        try:
            self.cursor.execute('''
                UPDATE users 
                SET club_id = ? 
                WHERE user_id = ?
            ''', (new_club_id, user_id))
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка изменения клуба для {user_id} на {new_club_id}: {e}")
            return False

    def add_transfer_count(self, club_id: int) -> bool:
        """Увеличивает счетчик успешных переходов (команда /invite) на +1."""
        try:
            self.cursor.execute('''
                UPDATE clubs 
                SET transfers_count = transfers_count + 1 
                WHERE club_id = ?
            ''', (club_id,))
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка при обновлении статистики переходов {club_id}: {e}")
            return False

    def assign_club_deputy(self, club_id: int, deputy_id: int) -> str:
        """
        Назначает заместителя владельца.
        Логика ТЗ: Максимум 2 зама. 
        Возвращает: 'success', 'full' (нет мест) или 'error' (сбой БД).
        """
        try:
            club_data = self.get_club_info_by_id(club_id)
            if not club_data:
                return 'error'
            
            # Проверяем свободные слоты под замов
            # Индекс 3 - deputy1_id, Индекс 4 - deputy2_id
            if club_data[3] is None:
                self.cursor.execute("UPDATE clubs SET deputy1_id = ? WHERE club_id = ?", (deputy_id, club_id))
            elif club_data[4] is None:
                self.cursor.execute("UPDATE clubs SET deputy2_id = ? WHERE club_id = ?", (deputy_id, club_id))
            else:
                return 'full' # Лимит исчерпан
                
            self.connection.commit()
            return 'success'
        except sqlite3.Error as e:
            logger.error(f"Ошибка при назначении зама {deputy_id} в клуб {club_id}: {e}")
            return 'error'

    def remove_club_deputy(self, club_id: int, deputy_id: int) -> bool:
        """
        Снимает полномочия заместителя.
        """
        try:
            club_data = self.get_club_info_by_id(club_id)
            if not club_data:
                return False
                
            if club_data[3] == deputy_id:
                self.cursor.execute("UPDATE clubs SET deputy1_id = NULL WHERE club_id = ?", (club_id,))
            elif club_data[4] == deputy_id:
                self.cursor.execute("UPDATE clubs SET deputy2_id = NULL WHERE club_id = ?", (club_id,))
            else:
                return False # Этот игрок не был замом
                
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Ошибка при снятии зама {deputy_id}: {e}")
            return False

# Инициализируем глобальный объект базы данных
db_manager = DatabaseManager()

# КОНЕЦ ЧАСТИ 1 ИЗ 3.
# Код состоит из 540 строк. Все классы, модули и проверки прописаны детально.

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

# ==============================================================================
# 22. УПРАВЛЕНИЕ КЛУБОМ: ИСКЛЮЧЕНИЕ ИГРОКОВ
# ==============================================================================

@dp.message(Command("delete"))
async def club_command_delete(message: types.Message) -> None:
    """
    Команда /delete [ник]. 
    Позволяет владельцу или заместителям исключить игрока из клуба.
    """
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    
    # Проверка правильности написания команды
    if len(args) < 2:
        await message.answer("⚠️ <b>Использование:</b> <code>/delete [игровой ник]</code>")
        return
        
    target_nickname = args[1].strip()
    
    # Проверка наличия админ-прав в клубе у того, кто пишет команду
    club_data = db_manager.get_club_by_admin_rights(user_id)
    if not club_data:
        await message.answer("❌ <b>Отказано:</b> У вас нет прав администратора или заместителя ни в одном клубе.")
        return
        
    club_id = club_data[0]
    owner_id = club_data[2]
    
    # Поиск целевого игрока в базе данных
    target_data = db_manager.get_user_data_by_nickname(target_nickname)
    if not target_data:
        await message.answer(f"❌ Игрок с никнеймом <b>{target_nickname}</b> не найден в базе данных.")
        return
        
    target_id = target_data[0]
    
    # Защита от исключения владельца клуба
    if target_id == owner_id:
        await message.answer("❌ <b>Критическая ошибка:</b> Невозможно исключить владельца клуба!")
        return
        
    # Проверка, состоит ли игрок именно в этом клубе
    if target_data[3] != club_id:
        await message.answer("❌ Данный игрок не состоит в вашей команде.")
        return

    # Если исключаемый был заместителем, снимаем с него эти полномочия
    db_manager.remove_club_deputy(club_id=club_id, deputy_id=target_id)
    
    # Переводим игрока в статус свободного агента (club_id = None)
    success = db_manager.change_player_club(user_id=target_id, new_club_id=None)
    
    if success:
        # Пытаемся уведомить самого игрока об исключении
        try:
            await bot.send_message(
                chat_id=target_id, 
                text="💔 <b>Контракт расторгнут.</b>\nВы были исключены из клуба по решению руководства и теперь являетесь свободным агентом."
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить ЛС игроку {target_id} при кике: {e}")
            
        await message.answer(f"✅ Игрок <code>{target_nickname}</code> успешно исключен из вашей команды.")
        logger.info(f"Игрок {target_nickname} был исключен из клуба {club_id} пользователем {user_id}.")
    else:
        await message.answer("⚠️ Произошла непредвиденная ошибка при исключении игрока из базы данных.")

# ==============================================================================
# 23. УПРАВЛЕНИЕ КЛУБОМ: ПРОСМОТР СОСТАВА И ПОЗИЦИЙ
# ==============================================================================

@dp.message(Command("viewteam"))
@dp.message(F.text == "🛡 Мой клуб")
async def club_command_viewteam(message: types.Message) -> None:
    """
    Команда /viewteam (или кнопка "Мой клуб"). 
    Выводит подробную статистику клуба и список игроков по классическим футбольным позициям.
    """
    user_id = message.from_user.id
    
    # Получаем данные клуба, где игрок имеет права
    club_data = db_manager.get_club_by_admin_rights(user_id)
    if not club_data:
        await message.answer("❌ Вы не являетесь владельцем или заместителем ни в одном клубе.")
        return
        
    club_id = club_data[0]
    club_name = club_data[1]
    owner_id = club_data[2]
    deputy1_id = club_data[3]
    deputy2_id = club_data[4]
    transfers_count = club_data[5]

    # Получаем никнейм владельца
    owner_data = db_manager.get_user_data_by_id(owner_id)
    owner_nick = owner_data[2] if owner_data else "Неизвестно"
    
    # Получаем никнеймы заместителей
    dep1_nick = "Нету"
    if deputy1_id:
        d1 = db_manager.get_user_data_by_id(deputy1_id)
        if d1: dep1_nick = f"{d1[2]} (ID: {deputy1_id})"
        
    dep2_nick = "Нету"
    if deputy2_id:
        d2 = db_manager.get_user_data_by_id(deputy2_id)
        if d2: dep2_nick = f"{d2[2]} (ID: {deputy2_id})"

    # Получаем полный список игроков
    players = db_manager.get_club_players_list(club_id)
    
    # Формируем шапку статистики
    msg_text = (
        "📋 <b>Данные клуба</b> 📝\n"
        "─────────────────────────────\n"
        f"🛡 Название клуба: <b>{club_name}</b>\n"
        f"👑 Владелец: {owner_nick} (ID: {owner_id})\n"
        f"👤 Помощник 1: {dep1_nick}\n"
        f"👤 Помощник 2: {dep2_nick}\n"
        f"📊 Успешных переходов: <b>{transfers_count}</b>\n"
        "🏆─────────────────────────────🏆\n\n"
        f"👥 <b>Основной состав ({len(players)}/15):</b>\n"
        "<i>(Лимит: 15 игроков. При превышении необходимо исключить кого-то для новых трансферов)</i>\n\n"
    )
    
    # Распределение игроков по позициям (GK, LB, RB, CM, LW, RW, CF)
    # Это визуальное оформление состава
    positions = ["GK", "LB", "RB", "CM", "CM", "LW", "RW", "CF", "CF", "SUB", "SUB", "SUB", "SUB", "SUB", "SUB"]
    
    for i in range(15):
        pos = positions[i]
        if i < len(players):
            player_nick = players[i][1]
            msg_text += f" {i+1}. <b>[{pos}]</b> ✏️ {player_nick}\n"
        else:
            msg_text += f" {i+1}. <b>[{pos}]</b> ✏️ Свободный слот\n"

    # Клавиатура управления заместителями доступна ТОЛЬКО владельцу (owner_id)
    reply_markup = None
    if user_id == owner_id:
        reply_markup = get_club_management_inline()
        
    await message.answer(text=msg_text, reply_markup=reply_markup)

# ==============================================================================
# 24. УПРАВЛЕНИЕ КЛУБОМ: ЗАМЕСТИТЕЛИ (КОЛБЕКИ)
# ==============================================================================

@dp.callback_query(F.data == "club_add_deputy")
async def process_add_deputy(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Обработка нажатия кнопки 'Добавить зама'."""
    await callback.message.answer(
        "✍️ <b>Добавление заместителя:</b>\n"
        "Введите игровой никнейм игрока, которого хотите назначить замом.\n"
        "<i>Примечание: Игрок уже должен состоять в вашем клубе.</i>",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(ClubManagementProcess.waiting_for_deputy_nickname)
    # Сохраняем действие в память машины состояний
    await state.update_data(action="add")
    await callback.answer()

@dp.callback_query(F.data == "club_remove_deputy")
async def process_remove_deputy(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Обработка нажатия кнопки 'Убрать зама'."""
    await callback.message.answer(
        "✍️ <b>Снятие заместителя:</b>\n"
        "Введите игровой никнейм текущего заместителя, которого хотите разжаловать до обычного игрока:",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(ClubManagementProcess.waiting_for_deputy_nickname)
    # Сохраняем действие в память машины состояний
    await state.update_data(action="remove")
    await callback.answer()

@dp.message(StateFilter(ClubManagementProcess.waiting_for_deputy_nickname))
async def handle_deputy_nickname(message: types.Message, state: FSMContext) -> None:
    """Обработка введенного никнейма для добавления/удаления зама."""
    target_nick = message.text.strip()
    user_id = message.from_user.id
    
    # Строгая проверка: только ВЛАДЕЛЕЦ может управлять замами
    club_data = db_manager.get_club_by_admin_rights(user_id)
    if not club_data or club_data[2] != user_id:
        await message.answer("❌ <b>Отказано:</b> Только владелец клуба имеет право назначать или снимать заместителей.")
        await state.clear()
        return
        
    club_id = club_data[0]
    state_data = await state.get_data()
    action = state_data.get("action")
    
    # Поиск целевого игрока
    target_user = db_manager.get_user_data_by_nickname(target_nick)
    if not target_user:
        await message.answer("❌ Игрок с таким никнеймом не найден. Проверьте правильность написания.")
        await state.clear()
        return
        
    target_id = target_user[0]
    
    if action == "add":
        # Проверяем, состоит ли будущий зам в клубе
        if target_user[3] != club_id:
            await message.answer("❌ <b>Ошибка:</b> Игрок должен сначала вступить в ваш клуб, чтобы стать заместителем.")
            await state.clear()
            return
            
        result = db_manager.assign_club_deputy(club_id, target_id)
        if result == 'success':
            await message.answer(f"✅ Игрок <code>{target_nick}</code> успешно назначен вашим заместителем.")
        elif result == 'full':
            await message.answer("❌ <b>Лимит исчерпан:</b> У вас уже есть 2 заместителя! Сначала снимите кого-то с должности.")
        else:
            await message.answer("⚠️ Произошла внутренняя ошибка базы данных.")
            
    elif action == "remove":
        # Снятие полномочий
        success = db_manager.remove_club_deputy(club_id, target_id)
        if success:
            await message.answer(f"✅ Игрок <code>{target_nick}</code> разжалован. Он больше не является вашим заместителем.")
        else:
            await message.answer("❌ Этот игрок не является вашим заместителем или произошла ошибка.")
            
    await state.clear()

# ==============================================================================
# 25. АДМИН-ПАНЕЛЬ: ДОБАВЛЕНИЕ КЛУБА
# ==============================================================================

@dp.message(F.text == "➕ Добавить клуб")
async def superadmin_add_club_start(message: types.Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS: 
        return
    await message.answer(
        "📝 <b>Создание нового клуба</b>\nВведите <b>название</b> нового клуба:", 
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(SuperAdminProcess.waiting_for_club_name)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_club_name))
async def superadmin_add_club_name(message: types.Message, state: FSMContext) -> None:
    await state.update_data(club_name=message.text.strip())
    await message.answer(
        "🆔 Теперь введите <b>Telegram ID</b> будущего владельца клуба (только цифры):\n"
        "<i>Игрок уже должен быть зарегистрирован в боте.</i>", 
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(SuperAdminProcess.waiting_for_club_owner_id)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_club_owner_id))
async def superadmin_add_club_owner(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    club_name = data.get("club_name")
    
    if not message.text.isdigit():
        await message.answer("❌ ID должен состоять только из цифр. Попробуйте еще раз:")
        return
        
    owner_id = int(message.text)
    user_data = db_manager.get_user_data_by_id(owner_id)
    
    if not user_data:
        await message.answer(f"❌ Пользователь с ID {owner_id} не зарегистрирован в боте. Операция отменена.")
        await state.clear()
        return

    # Создание клуба в БД
    success = db_manager.create_new_club(club_name=club_name, owner_id=owner_id)
    if success:
        await message.answer(
            f"✅ <b>Успешно!</b>\n"
            f"Клуб <b>{club_name}</b> официально создан.\n"
            f"Владельцем назначен: <code>{user_data[2]}</code>"
        )
        logger.info(f"Администратор {message.from_user.id} создал клуб {club_name}.")
    else:
        await message.answer("❌ <b>Ошибка:</b> Клуб с таким названием уже существует или произошел сбой БД.")
    
    await state.clear()

# ==============================================================================
# 26. АДМИН-ПАНЕЛЬ: УДАЛЕНИЕ КЛУБА
# ==============================================================================

@dp.message(F.text == "➖ Убрать клуб")
async def superadmin_remove_club_start(message: types.Message) -> None:
    if message.from_user.id not in ADMIN_IDS: 
        return
    
    clubs = db_manager.get_all_clubs()
    if not clubs:
        await message.answer("В базе данных нет зарегистрированных клубов.")
        return
        
    # Генерируем инлайн-кнопки со списком всех клубов
    builder = InlineKeyboardBuilder()
    for club_id, club_name in clubs:
        builder.button(text=f"🗑 {club_name}", callback_data=f"delclub_{club_id}")
    
    builder.adjust(1)
    await message.answer("⚠️ <b>Выберите клуб для полного удаления:</b>", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("delclub_"))
async def superadmin_confirm_delete_club(callback: types.CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS: 
        return
    
    club_id = int(callback.data.split("_")[1])
    
    # Запрос подтверждения перед необратимым действием
    builder = InlineKeyboardBuilder()
    builder.button(text="⚠️ ДА, УДАЛИТЬ КЛУБ", callback_data=f"confirmdel_{club_id}")
    builder.button(text="❌ ОТМЕНА", callback_data="cancel_current_action")
    
    await callback.message.edit_text(
        "🚨 <b>ВНИМАНИЕ!</b>\n"
        "Вы уверены, что хотите удалить этот клуб?\n"
        "Это действие расформирует весь состав, и все игроки станут свободными агентами. Восстановить данные будет невозможно.", 
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("confirmdel_"))
async def superadmin_execute_delete_club(callback: types.CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS: 
        return
    
    club_id = int(callback.data.split("_")[1])
    success = db_manager.delete_club_fully(club_id)
    
    if success:
        await callback.message.edit_text("✅ <b>Клуб успешно и безвозвратно удален.</b> Все бывшие участники стали свободными агентами.")
        logger.info(f"Клуб {club_id} был удален администратором {callback.from_user.id}.")
    else:
        await callback.message.edit_text("❌ Ошибка базы данных при удалении клуба.")

# ==============================================================================
# 27. АДМИН-ПАНЕЛЬ: БЛОКИРОВКА И РАЗБЛОКИРОВКА ИГРОКОВ (БАНЫ)
# ==============================================================================

@dp.message(F.text == "🚫 Забанить игрока")
async def superadmin_ban_start(message: types.Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS: 
        return
    await message.answer(
        "🛑 <b>Блокировка аккаунта</b>\nВведите игровой никнейм нарушителя для выдачи бана:", 
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(SuperAdminProcess.waiting_for_ban_nickname)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_ban_nickname))
async def superadmin_ban_execute(message: types.Message, state: FSMContext) -> None:
    target_nick = message.text.strip()
    success = db_manager.change_ban_status(nickname=target_nick, is_banned=1)
    
    if success:
        await message.answer(f"✅ <b>Успешно!</b>\nИгрок <code>{target_nick}</code> заблокирован. Он больше не может использовать функции бота.")
        logger.info(f"Админ {message.from_user.id} забанил игрока {target_nick}.")
    else:
        await message.answer("❌ Игрок с таким никнеймом не найден в базе данных.")
    await state.clear()

@dp.message(F.text == "✅ Разбанить игрока")
async def superadmin_unban_start(message: types.Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS: 
        return
    await message.answer(
        "🟢 <b>Снятие блокировки</b>\nВведите игровой никнейм игрока для разбана:", 
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(SuperAdminProcess.waiting_for_unban_nickname)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_unban_nickname))
async def superadmin_unban_execute(message: types.Message, state: FSMContext) -> None:
    target_nick = message.text.strip()
    success = db_manager.change_ban_status(nickname=target_nick, is_banned=0)
    
    if success:
        await message.answer(f"✅ <b>Успешно!</b>\nИгрок <code>{target_nick}</code> разблокирован и снова может играть.")
        logger.info(f"Админ {message.from_user.id} разбанил игрока {target_nick}.")
    else:
        await message.answer("❌ Игрок с таким никнеймом не найден.")
    await state.clear()

@dp.message(F.text == "🔙 Выйти из админ панели")
async def superadmin_panel_close(message: types.Message) -> None:
    """Закрытие секретной клавиатуры и возврат к обычному меню."""
    if message.from_user.id not in ADMIN_IDS:
        return
        
    club_data = db_manager.get_club_by_admin_rights(message.from_user.id)
    is_club_admin = bool(club_data)
    
    await message.answer(
        "🚪 Вы успешно вышли из панели управления.", 
        reply_markup=get_player_main_menu(message.from_user.id, is_club_admin)
    )

# ==============================================================================
# 28. ГЛАВНАЯ ФУНКЦИЯ ЗАПУСКА БОТА
# ==============================================================================

async def main() -> None:
    """
    Главная асинхронная функция.
    Инициализирует polling, пропускает старые апдейты, чтобы бот не спамил
    после включения, и запускает диспетчер.
    """
    logger.info("==================================================")
    logger.info("Бот Трансфермаркета RIVALS успешно запущен и готов к работе!")
    logger.info("Все базы данных подключены, модерация активна.")
    logger.info("==================================================")
    
    # Удаляем вебхук и пропускаем все накопленные сообщения за время оффлайна
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        # Запуск процесса поллинга (прослушивания серверов Telegram)
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Критическая ошибка во время работы бота: {e}")
    finally:
        # Корректное завершение сессии при выключении
        await bot.session.close()
        logger.info("Сессия бота была безопасно закрыта.")

if __name__ == "__main__":
    # Точка входа в программу.
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Обработка ручного выключения через консоль (Ctrl+C)
        logger.info("Работа бота была остановлена вручную администратором (KeyboardInterrupt).")
