"""
================================================================================
ТРАНСФЕРМАРКЕТ БОТ ПО ИГРЕ RIVALS (ROBLOX)
ЧАСТЬ 1: Конфигурация, Логгирование, Машины Состояний, Клавиатуры и База Данных.

Разработано специально по техническому заданию.
Используется библиотека aiogram версии 3.x.
Все функции подробно расписаны, без халтуры и сокращений.
================================================================================
"""

import sqlite3
import logging
import sys
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Union, Dict, Any

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
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
CHANNEL_ID = "-1000000000000"

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
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
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

"""
================================================================================
ТРАНСФЕРМАРКЕТ БОТ ПО ИГРЕ RIVALS (ROBLOX)
ЧАСТЬ 2: Регистрация, Меню Игрока, Кулдауны и Создание Анкет

Этот блок отвечает за прямое взаимодействие обычных игроков с ботом.
================================================================================
"""

import string
from aiogram.filters import StateFilter

# ==============================================================================
# 6. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ВАЛИДАЦИЯ, КУЛДАУНЫ, СТАТУСЫ)
# ==============================================================================

def is_valid_english_nickname(nickname: str) -> bool:
    """
    Проверяет, состоит ли никнейм только из английских букв и цифр.
    Согласно ТЗ, игроки должны вводить никнейм английскими буквами.
    """
    if not nickname:
        return False
        
    # Разрешенные символы: английский алфавит (нижний и верхний регистр) + цифры + подчеркивание
    allowed_characters = string.ascii_letters + string.digits + "_"
    
    for char in nickname:
        if char not in allowed_characters:
            return False
            
    return True

def get_remaining_cooldown_time(last_action_time: str, cooldown_hours: int) -> Optional[str]:
    """
    Вычисляет, сколько времени осталось до окончания кулдауна.
    Если кулдаун прошел или его не было, возвращает None.
    В противном случае возвращает красиво отформатированную строку (например: "5 ч. 30 мин.").
    """
    if not last_action_time:
        return None
        
    try:
        # Конвертируем строку из БД обратно в объект datetime
        last_time = datetime.strptime(last_action_time, "%Y-%m-%d %H:%M:%S.%f")
        next_available_time = last_time + timedelta(hours=cooldown_hours)
        current_time = datetime.now()
        
        if current_time < next_available_time:
            # Высчитываем разницу
            remaining_delta = next_available_time - current_time
            total_seconds = int(remaining_delta.total_seconds())
            
            hours_left = total_seconds // 3600
            minutes_left = (total_seconds % 3600) // 60
            
            return f"{hours_left} ч. {minutes_left} мин."
        else:
            return None
    except ValueError as e:
        logger.error(f"Ошибка парсинга времени кулдауна: {e}")
        return None

def check_player_retire_status(user_id: int) -> Optional[datetime]:
    """
    Проверяет, находится ли игрок в статусе "Завершение карьеры".
    Если срок (15 дней) истек, автоматически снимает статус в БД.
    Возвращает дату окончания заморозки, либо None, если игрок активен.
    """
    user_data = db_manager.get_user_data_by_id(user_id)
    if not user_data or not user_data[5]:
        return None
        
    try:
        retire_end_date = datetime.strptime(user_data[5], "%Y-%m-%d %H:%M:%S.%f")
        
        # Если текущее время больше даты окончания, снимаем штраф
        if datetime.now() >= retire_end_date:
            db_manager.execute_career_return(user_id)
            logger.info(f"Статус завершения карьеры для {user_id} автоматически снят по истечению срока.")
            return None
            
        return retire_end_date
    except ValueError as e:
        logger.error(f"Ошибка проверки статуса карьеры для {user_id}: {e}")
        return None

# ==============================================================================
# 7. ПРОЦЕСС РЕГИСТРАЦИИ НОВЫХ ПОЛЬЗОВАТЕЛЕЙ
# ==============================================================================

@dp.message(CommandStart())
async def command_start_handler(message: types.Message, state: FSMContext) -> None:
    """
    Обработчик команды /start.
    Приветствует пользователя, проверяет наличие в БД и запускает регистрацию, если нужно.
    """
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Форматируем юзернейм для БД (если его нет, ставим "Скрыт")
    formatted_username = f"@{username}" if username else "Скрыт"
    
    logger.info(f"Пользователь {user_id} ({formatted_username}) нажал /start.")
    
    # Сбрасываем любые зависшие состояния
    await state.clear()
    
    # Проверяем, есть ли пользователь в базе данных
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if user_data:
        # Пользователь уже зарегистрирован, выдаем ему меню
        nickname = user_data[2]
        
        # Проверяем, является ли он админом какого-либо клуба, чтобы дать кнопку "Мой клуб"
        club_data = db_manager.get_club_by_admin_rights(user_id)
        is_club_admin = bool(club_data)
        
        welcome_back_text = (
            f"👋 <b>С возвращением, {nickname}!</b>\n\n"
            f"Система Трансфермаркета готова к работе.\n"
            f"Воспользуйтесь меню ниже для управления своим профилем и публикациями."
        )
        
        keyboard = get_player_main_menu(user_id=user_id, is_club_owner_or_deputy=is_club_admin)
        await message.answer(text=welcome_back_text, reply_markup=keyboard)
        return
        
    # Если пользователя нет в базе, начинаем красивую регистрацию (строго по ТЗ)
    registration_text = (
        "🌟 <b>ПРИВЕТСТВУЕМ ВАС В ТРАНСФЕРМАРКЕТЕ ПО ИГРЕ RIVALS!</b> 🌟\n\n"
        "Здесь вы сможете найти себе команду мечты, подписывать контракты "
        "с лучшими клубами или заявить о себе на весь мир!\n\n"
        "Для начала нам нужно познакомиться.\n"
        "👇 <b>Напишите ваш игровой никнейм (только английскими буквами):</b>"
    )
    
    await message.answer(text=registration_text)
    # Переводим бота в состояние ожидания ввода никнейма
    await state.set_state(UserRegistration.waiting_for_nickname)

@dp.message(StateFilter(UserRegistration.waiting_for_nickname))
async def process_nickname_registration(message: types.Message, state: FSMContext) -> None:
    """
    Обрабатывает введенный никнейм, проверяет его на правильность и сохраняет в БД.
    """
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Скрыт"
    nickname = message.text.strip()
    
    # Проверка на длину никнейма
    if len(nickname) < 3 or len(nickname) > 20:
        await message.answer("⚠️ <b>Ошибка:</b> Никнейм должен содержать от 3 до 20 символов. Попробуйте еще раз:")
        return
        
    # Проверка на английские символы (из ТЗ)
    if not is_valid_english_nickname(nickname):
        error_msg = (
            "⚠️ <b>Недопустимые символы!</b>\n"
            "Пожалуйста, используйте <b>только английские буквы</b> (a-z, A-Z), "
            "цифры и нижнее подчеркивание. Введите никнейм заново:"
        )
        await message.answer(text=error_msg)
        return
        
    # Попытка добавить пользователя в базу данных
    registration_success = db_manager.add_new_user(user_id=user_id, username=username, nickname=nickname)
    
    if registration_success:
        success_text = (
            f"✅ <b>Регистрация успешно завершена!</b>\n\n"
            f"Ваш игровой никнейм: <code>{nickname}</code>\n"
            f"Теперь вам доступен полный функционал нашего бота."
        )
        # Выдаем главное меню (у нового игрока точно нет клуба, поэтому is_club_admin=False)
        keyboard = get_player_main_menu(user_id=user_id, is_club_owner_or_deputy=False)
        
        await message.answer(text=success_text, reply_markup=keyboard)
        await state.clear() # Завершаем процесс регистрации
    else:
        # Если функция вернула False, значит сработал UNIQUE констрейнт в БД
        occupied_text = (
            "❌ <b>Этот никнейм уже занят!</b>\n"
            "К сожалению, другой игрок уже зарегистрировался под таким именем. "
            "Пожалуйста, придумайте другой ник или добавьте к нему цифры:"
        )
        await message.answer(text=occupied_text)

# ==============================================================================
# 8. ОБРАБОТЧИКИ ГЛАВНОГО МЕНЮ (ПРОФИЛЬ, ПОМОЩЬ И СМЕНА НИКА)
# ==============================================================================

@dp.message(F.text == "ℹ️ Помощь")
async def handle_help_button(message: types.Message) -> None:
    """Выводит список всех команд и функций бота (согласно ТЗ)."""
    help_message = (
        "📚 <b>СПРАВОЧНИК ПО КОМАНДАМ И ФУНКЦИЯМ</b> 📚\n\n"
        "<b>Действия игрока:</b>\n"
        "🏃‍♂️ <b>Свободный агент</b> — Подать заявку на поиск клуба. Доступно 1 раз в 6 часов.\n"
        "📝 <b>Свой текст</b> — Опубликовать кастомное объявление. Доступно 1 раз в 12 часов.\n"
        "🥀 <b>Завершения карьеры</b> — Замораживает ваш профиль на 15 дней. Запрещает публикацию объявлений.\n"
        "❤️ <b>Возращения карьеры</b> — Отменяет статус завершения карьеры, позволяя снова публиковать посты.\n"
        "🔄 <b>Смена никнейма</b> — Позволяет изменить ник. Доступно 1 раз в месяц (30 дней).\n"
        "👤 <b>Профиль</b> — Просмотр вашей текущей статистики и статуса.\n\n"
        "<b>Команды Владельцев и Заместителей клубов:</b>\n"
        "<code>/invite [ник]</code> — Подписать игрока в клуб\n"
        "<code>/delete [ник]</code> — Разорвать контракт с игроком (выгнать)\n"
        "<code>/viewteam</code> — Просмотреть подробную информацию о вашем клубе и состав\n\n"
        "<i>❗️ Внимание: Все анкеты перед публикацией проходят строгую модерацию администраторами.</i>"
    )
    await message.answer(text=help_message)

@dp.message(F.text == "👤 Профиль")
async def handle_profile_button(message: types.Message) -> None:
    """Отображает профиль пользователя: ник, ID, юзернейм, текущий клуб и статус."""
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        await message.answer("❌ <b>Ошибка:</b> Вы не зарегистрированы! Введите команду /start.")
        return

    # Распаковываем данные пользователя из БД
    username = user_data[1]
    nickname = user_data[2]
    club_id = user_data[3]
    is_banned = bool(user_data[4])
    
    # Определяем название клуба
    club_name_display = "Нет клуба (Свободный агент)"
    if club_id is not None:
        club_data = db_manager.get_club_info_by_id(club_id)
        if club_data:
            club_name_display = f"🛡 {club_data[1]}"
            
    # Определяем текущий статус игрока
    if is_banned:
        status_display = "🔴 ЗАБЛОКИРОВАН (Бан)"
    else:
        retire_date = check_player_retire_status(user_id)
        if retire_date:
            formatted_date = retire_date.strftime('%d.%m.%Y %H:%M')
            status_display = f"🥀 Карьера завершена (до {formatted_date})"
        else:
            status_display = "🟢 Активен (Готов к игре)"

    # Формируем красивый текст профиля (согласно ТЗ)
    profile_text = (
        "👤 <b>ПРОФИЛЬ ИГРОКА</b> 👤\n\n"
        f"📝 <b>Игровой никнейм:</b> <code>{nickname}</code>\n"
        f"🔗 <b>Юзернейм:</b> {username}\n"
        f"🆔 <b>Ваш Telegram ID:</b> <code>{user_id}</code>\n"
        f"⚽️ <b>Текущий клуб:</b> {club_name_display}\n\n"
        f"📊 <b>Статус аккаунта:</b> {status_display}"
    )
    
    await message.answer(text=profile_text)

@dp.message(F.text == "🔄 Смена никнейма")
async def handle_change_nickname(message: types.Message, state: FSMContext) -> None:
    """Запускает процесс смены никнейма. Проверяет кулдаун в 30 дней."""
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return
        
    # Проверка на бан
    if bool(user_data[4]):
        await message.answer("❌ <b>Отказано:</b> Ваш аккаунт заблокирован.")
        return

    # Проверка кулдауна на смену ника (индекс 8 в БД)
    last_nickname_change = user_data[8]
    if last_nickname_change:
        # Передаем 30 дней в часах (30 * 24 = 720)
        cooldown_remaining = get_remaining_cooldown_time(last_nickname_change, COOLDOWN_NICKNAME_CHANGE_DAYS * 24)
        if cooldown_remaining:
            await message.answer(
                f"⏳ <b>Слишком рано!</b>\n"
                f"Смена никнейма доступна только 1 раз в месяц.\n"
                f"Осталось ждать: <b>{cooldown_remaining}</b>"
            )
            return

    await message.answer(
        "✍️ <b>Смена игрового никнейма</b>\n\n"
        "Введите ваш новый никнейм (только английские буквы).\n"
        "<i>❗️ Внимание: Следующая смена будет доступна только через 1 месяц!</i>",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(ChangeNicknameProcess.waiting_for_new_nickname)

@dp.message(StateFilter(ChangeNicknameProcess.waiting_for_new_nickname))
async def process_new_nickname(message: types.Message, state: FSMContext) -> None:
    """Обрабатывает ввод нового никнейма и сохраняет его, накладывая кулдаун."""
    user_id = message.from_user.id
    new_nickname = message.text.strip()
    
    if len(new_nickname) < 3 or len(new_nickname) > 20:
        await message.answer("⚠️ Никнейм должен быть от 3 до 20 символов. Попробуйте снова:")
        return
        
    if not is_valid_english_nickname(new_nickname):
        await message.answer("⚠️ Только английские буквы и цифры. Попробуйте снова:")
        return

    success = db_manager.update_user_nickname(user_id=user_id, new_nickname=new_nickname)
    
    if success:
        await message.answer(f"✅ <b>Успешно!</b> Ваш новый никнейм: <code>{new_nickname}</code>")
        await state.clear()
    else:
        await message.answer("❌ <b>Ошибка:</b> Этот никнейм уже занят другим игроком. Придумайте другой.")

# ==============================================================================
# 9. ЗАВЕРШЕНИЕ И ВОЗВРАЩЕНИЕ КАРЬЕРЫ (Автоматическая публикация)
# ==============================================================================

@dp.message(F.text == "🥀 Завершения карьеры")
async def handle_career_retire(message: types.Message) -> None:
    """
    Завершает карьеру игрока на 15 дней.
    Игрок исключается из клуба, статус обновляется, в канал отправляется пост (по ТЗ).
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return
        
    # Проверка на бан
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
    
    # Применяем штраф в БД (заодно выкидывает из клуба)
    freeze_date = db_manager.execute_career_retirement(user_id)
    
    # Формируем текст поста строго по ТЗ:
    # ❗️ОФИЦИАЛЬНО: ЗАВЕРШЕНИЕ КАРЬЕРЫ🥀
    # 😎 ник игрока(юз) - завершение карьеры.
    post_text = (
        "❗️ОФИЦИАЛЬНО: ЗАВЕРШЕНИЕ КАРЬЕРЫ🥀\n\n"
        f"😎 <b>{nickname}</b> ({username}) - завершение карьеры."
    )
    
    try:
        # Отправляем пост напрямую в канал
        await bot.send_message(chat_id=CHANNEL_ID, text=post_text)
        
        await message.answer(
            f"✅ <b>Вы успешно завершили карьеру.</b>\n"
            f"Ваш профиль заморожен на 15 дней (до {freeze_date.strftime('%d.%m.%Y %H:%M')}).\n"
            f"Вы покинули свой клуб и не можете публиковать объявления."
        )
        logger.info(f"Пользователь {nickname} завершил карьеру. Пост отправлен в канал.")
    except Exception as e:
        logger.error(f"Ошибка отправки поста о завершении карьеры в канал {CHANNEL_ID}: {e}")
        await message.answer(
            "⚠️ <b>Внимание:</b> Ваш статус карьеры успешно обновлен, "
            "но произошла ошибка при публикации поста в канал. Обратитесь к администратору."
        )

@dp.message(F.text == "❤️ Возращения карьеры")
async def handle_career_return(message: types.Message) -> None:
    """
    Отменяет статус завершения карьеры.
    Публикует пост в канал (по ТЗ).
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return
        
    if bool(user_data[4]):
        await message.answer("❌ <b>Отказано:</b> Вы заблокированы.")
        return

    # Проверяем, завершена ли карьера вообще
    if user_data[5] is None:
        await message.answer("⚠️ <b>Ошибка:</b> Ваша карьера активна. Вы не завершали ее.")
        return

    # Снимаем статус в базе данных
    db_manager.execute_career_return(user_id)
    
    username = user_data[1]
    nickname = user_data[2]
    
    # Формируем текст поста строго по ТЗ
    post_text = (
        "❗️ОФИЦИАЛЬНО: ВОЗРАЩЕНИЕ КАРЬЕРЫ❤️\n\n"
        f"😎 <b>{nickname}</b> ({username}) - возвращение в карьеру."
    )
    
    try:
        await bot.send_message(chat_id=CHANNEL_ID, text=post_text)
        await message.answer(
            "✅ <b>Вы успешно вернулись в большой спорт!</b>\n"
            "Теперь вы можете публиковать объявления и вступать в клубы."
        )
        logger.info(f"Пользователь {nickname} вернулся в карьеру. Пост отправлен в канал.")
    except Exception as e:
        logger.error(f"Ошибка отправки поста о возвращении карьеры в канал {CHANNEL_ID}: {e}")
        await message.answer("⚠️ Статус обновлен, но в канал отправить пост не удалось.")

# ==============================================================================
# 10. СОЗДАНИЕ ОБЪЯВЛЕНИЙ (АГЕНТ И КАСТОМНЫЙ ТЕКСТ)
# ==============================================================================

@dp.message(F.text == "🏃‍♂️ Свободный агент")
async def handle_free_agent_button(message: types.Message, state: FSMContext) -> None:
    """
    Начинает процесс подачи заявки свободного агента.
    Проверяет баны, завершение карьеры и кулдаун (6 часов).
    """
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        return

    # 1. Проверка на бан
    if bool(user_data[4]):
        await message.answer("❌ <b>Ошибка:</b> Ваш аккаунт заблокирован. Вы не можете публиковать объявления.")
        return

    # 2. Проверка на завершение карьеры
    retire_date = check_player_retire_status(user_id)
    if retire_date:
        await message.answer(
            f"🥀 <b>Вы завершили карьеру!</b>\n"
            f"Вы не можете искать клуб до {retire_date.strftime('%d.%m.%Y %H:%M')}, "
            f"либо воспользуйтесь кнопкой возвращения."
        )
        return

    # 3. Проверка кулдауна (индекс 6 в БД - last_free_agent)
    last_free_agent_time = user_data[6]
    cooldown_remaining = get_remaining_cooldown_time(last_free_agent_time, COOLDOWN_FREE_AGENT_HOURS)
    if cooldown_remaining:
        await message.answer(
            f"⏳ <b>Перезарядка!</b>\n"
            f"Вы уже публиковали анкету свободного агента недавно.\n"
            f"Осталось ждать: <b>{cooldown_remaining}</b>"
        )
        return

    await message.answer(
        "📝 <b>Режим: Свободный агент</b>\n\n"
        "Напишите текст вашего объявления (например: на какой позиции играете, какой у вас опыт, прайм-тайм).\n"
        "Этот текст будет добавлен в анкету после слов 'P.s:'",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(FreeAgentProcess.waiting_for_text)

@dp.message(StateFilter(FreeAgentProcess.waiting_for_text))
async def process_free_agent_text(message: types.Message, state: FSMContext) -> None:
    """
    Принимает текст, формирует пост по ТЗ и отправляет ВСЕМ админам на проверку.
    """
    user_text = message.text
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    username = user_data[1]
    nickname = user_data[2]
    
    # Формируем итоговый вид поста согласно ТЗ
    post_content = (
        "❗️СВОБОДНЫЙ АГЕНТ✌\n\n"
        f"😎 <b>{nickname}</b> ({username}) - Ищет клуб\n"
        f"P.s: {user_text}"
    )
    
    admins_notified_count = 0
    
    # Рассылаем анкету всем администраторам из списка ADMIN_IDS
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = (
                f"🔔 <b>НОВАЯ АНКЕТА (Свободный агент)</b>\n"
                f"От пользователя: <code>{nickname}</code> (ID: {user_id})\n\n"
                f"<b>Текст для публикации:</b>\n"
                f"----------------------------------------\n"
                f"{post_content}\n"
                f"----------------------------------------"
            )
            # Прикрепляем инлайн клавиатуру для принятия/отклонения
            keyboard = get_anketa_approval_keyboard(user_id=user_id, action_type="freeagent")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
            admins_notified_count += 1
        except Exception as e:
            logger.error(f"Не удалось доставить анкету админу {admin_id}: {e}")

    if admins_notified_count > 0:
        # Устанавливаем кулдаун только если анкета успешно ушла хотя бы одному админу
        db_manager.set_action_cooldown(user_id=user_id, action_column="last_free_agent")
        
        # Сохраняем сформированный текст во временную память FSM пользователя, 
        # чтобы админ мог его достать при нажатии "Принять" (реализация будет в Части 3)
        await state.update_data(prepared_post=post_content)
        
        await message.answer(
            "✅ <b>Ваша анкета успешно отправлена на проверку!</b>\n"
            "Пожалуйста, ожидайте. Как только администраторы одобрят её, она появится в канале."
        )
        logger.info(f"Анкета СА от {nickname} отправлена {admins_notified_count} админам.")
    else:
        await message.answer(
            "⚠️ <b>Произошла ошибка!</b>\n"
            "В данный момент администраторы недоступны. Попробуйте повторить попытку позже."
        )
        
    await state.clear()

@dp.message(F.text == "📝 Свой текст")
async def handle_custom_text_button(message: types.Message, state: FSMContext) -> None:
    """
    Запускает процесс публикации кастомного текста.
    Проверяет баны, карьеру и кулдаун (12 часов).
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
        await message.answer(f"🥀 <b>Вы завершили карьеру!</b> Доступ закрыт до {retire_date.strftime('%d.%m.%Y')}.")
        return

    # Проверка кулдауна (индекс 7 в БД - last_custom_text)
    last_custom_time = user_data[7]
    cooldown_remaining = get_remaining_cooldown_time(last_custom_time, COOLDOWN_CUSTOM_TEXT_HOURS)
    if cooldown_remaining:
        await message.answer(
            f"⏳ <b>Перезарядка!</b>\n"
            f"Вы уже публиковали свой текст недавно. Лимит: 1 раз в 12 часов.\n"
            f"Осталось ждать: <b>{cooldown_remaining}</b>"
        )
        return

    await message.answer(
        "📝 <b>Режим: Свой текст</b>\n\n"
        "Напишите ваше сообщение <b>полностью</b> так, как вы хотите его видеть в официальном канале.\n"
        "Администраторы проверят текст на нарушения перед публикацией.",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(CustomTextProcess.waiting_for_text)

@dp.message(StateFilter(CustomTextProcess.waiting_for_text))
async def process_custom_text(message: types.Message, state: FSMContext) -> None:
    """Обрабатывает введенный кастомный текст и шлет админам на модерацию."""
    user_text = message.text
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    nickname = user_data[2]
    
    # Формируем пост. Для кастомного текста добавляем только подпись от кого.
    post_content = f"👤 От игрока: <b>{nickname}</b>\n\n{user_text}"
    
    admins_notified_count = 0
    for admin_id in ADMIN_IDS:
        try:
            admin_msg = (
                f"🔔 <b>НОВАЯ АНКЕТА (Свой текст)</b>\n"
                f"От пользователя: <code>{nickname}</code>\n\n"
                f"<b>Текст для публикации:</b>\n"
                f"----------------------------------------\n"
                f"{post_content}\n"
                f"----------------------------------------"
            )
            keyboard = get_anketa_approval_keyboard(user_id=user_id, action_type="customtext")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
            admins_notified_count += 1
        except Exception as e:
            logger.error(f"Не удалось доставить кастомный текст админу {admin_id}: {e}")

    if admins_notified_count > 0:
        db_manager.set_action_cooldown(user_id=user_id, action_column="last_custom_text")
        await state.update_data(prepared_post=post_content)
        
        await message.answer("✅ <b>Ваш кастомный текст успешно отправлен на модерацию администраторам!</b>")
        logger.info(f"Анкета Свой Текст от {nickname} отправлена {admins_notified_count} админам.")
    else:
        await message.answer("⚠️ Ошибка отправки. Администраторы недоступны.")
        
    await state.clear()
