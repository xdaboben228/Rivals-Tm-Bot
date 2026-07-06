Понял, сделаю всё в лучшем виде. Лови первую часть кода. Здесь находятся все настройки, импорты, клавиатуры и полностью обновленная база данных с поддержкой кулдаунов, которые мы обсуждали.

**Часть 1: Настройки, клавиатуры и База Данных**

```python
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
import string
from aiogram.filters import StateFilter

# ==============================================================================
# 1. КОНФИГУРАЦИЯ БОТА И КОНСТАНТЫ
# ==============================================================================

# Токен бота
BOT_TOKEN = "8768994062:AAFWMZZIl19tDmnKjBcyFXEnE_BZLw5ckw0"

# Первоначальные владельцы (добавляются в БД при первом запуске)
INITIAL_ADMIN_IDS = [6885478196, 5845609895]

# ID канала для публикации постов 
CHANNEL_ID = "-1004377865527"

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
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ==============================================================================
# 3. МАШИНЫ СОСТОЯНИЙ (FSM - Finite State Machine)
# ==============================================================================

class UserRegistration(StatesGroup):
    waiting_for_nickname = State()

class FreeAgentProcess(StatesGroup):
    waiting_for_text = State()

class CustomTextProcess(StatesGroup):
    waiting_for_text = State()

class ChangeNicknameProcess(StatesGroup):
    waiting_for_new_nickname = State()

class SuperAdminProcess(StatesGroup):
    waiting_for_club_name = State()
    waiting_for_club_owner_id = State()
    waiting_for_ban_nickname = State()
    waiting_for_unban_nickname = State()
    waiting_for_new_admin_id = State()
    waiting_for_remove_admin_id = State()
    waiting_for_return_career_nick = State()

class ClubManagementProcess(StatesGroup):
    waiting_for_deputy_nickname = State()
    waiting_for_player_invite = State()
    waiting_for_player_kick = State()

# ==============================================================================
# 4. ФУНКЦИИ ГЕНЕРАЦИИ КЛАВИАТУР
# ==============================================================================

def get_player_main_menu(user_id: int, is_club_owner_or_deputy: bool = False, is_superadmin: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🏃‍♂️ Свободный агент"), KeyboardButton(text="📝 Свой текст"))
    builder.row(KeyboardButton(text="🥀 Завершения карьеры"), KeyboardButton(text="❤️ Возращения карьеры"))
    builder.row(KeyboardButton(text="🔄 Смена никнейма"), KeyboardButton(text="👤 Профиль"))
    builder.row(KeyboardButton(text="ℹ️ Помощь"))
    
    if is_club_owner_or_deputy:
        builder.row(KeyboardButton(text="🛡 Мой клуб"))
    if is_superadmin:
        builder.row(KeyboardButton(text="⚙️ Админ Панель"))
        
    return builder.as_markup(resize_keyboard=True)

def get_superadmin_menu() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="➕ Добавить клуб"), KeyboardButton(text="➖ Убрать клуб"))
    builder.row(KeyboardButton(text="🚫 Забанить игрока"), KeyboardButton(text="✅ Разбанить игрока"))
    builder.row(KeyboardButton(text="👑 Дать админа"), KeyboardButton(text="🚫 Убрать админа"))
    builder.row(KeyboardButton(text="❤️ Вернуть карьеру игроку"))
    builder.row(KeyboardButton(text="🔙 Выйти из админ панели"))
    return builder.as_markup(resize_keyboard=True)

def get_anketa_approval_keyboard(user_id: int, action_type: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=f"approve_{action_type}_{user_id}")
    builder.button(text="❌ Отклонить", callback_data=f"reject_{action_type}_{user_id}")
    builder.adjust(2)
    return builder.as_markup()

def get_invite_player_keyboard(club_id: int, club_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять", callback_data=f"player_accept_invite_{club_id}")
    builder.button(text="❌ Отказать", callback_data=f"player_reject_invite_{club_id}")
    builder.adjust(2)
    return builder.as_markup()

def get_transfer_mod_keyboard(user_id: int, club_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Одобрить переход", callback_data=f"mod_approve_transfer_{user_id}_{club_id}")
    builder.button(text="❌ Отклонить", callback_data=f"mod_reject_transfer_{user_id}_{club_id}")
    builder.adjust(2)
    return builder.as_markup()

def get_club_management_inline() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить зама", callback_data="club_add_deputy")
    builder.button(text="➖ Убрать зама", callback_data="club_remove_deputy")
    builder.adjust(2)
    return builder.as_markup()

def get_cancel_inline_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel_current_action")
    return builder.as_markup()

# ==============================================================================
# 5. БАЗА ДАННЫХ (Обновлена с учетом кулдаунов)
# ==============================================================================

class DatabaseManager:
    def __init__(self, db_path: str = "rivals_database.db"):
        self.db_path = db_path
        self.connection = None
        self.cursor = None
        self._connect_and_initialize()

    def _connect_and_initialize(self) -> None:
        try:
            self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self.cursor = self.connection.cursor()
            
            # Добавлены колонки кулдаунов
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    nickname TEXT UNIQUE COLLATE NOCASE,
                    club_id INTEGER DEFAULT NULL,
                    is_banned INTEGER DEFAULT 0,
                    is_retired INTEGER DEFAULT 0,
                    free_agent_cd REAL DEFAULT 0,
                    custom_text_cd REAL DEFAULT 0,
                    retire_cd REAL DEFAULT 0
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

            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_admins (
                    admin_id INTEGER PRIMARY KEY
                )
            ''')
            
            for adm_id in INITIAL_ADMIN_IDS:
                self.cursor.execute("INSERT OR IGNORE INTO bot_admins (admin_id) VALUES (?)", (adm_id,))
            
            self.connection.commit()
            logger.info("База данных SQLite успешно инициализирована.")
        except sqlite3.Error as e:
            logger.critical(f"Критическая ошибка при инициализации БД: {e}")
            sys.exit(1)

    # --------------------------------------------------------------------------
    # МЕТОД ОБНОВЛЕНИЯ КУЛДАУНОВ
    # --------------------------------------------------------------------------
    def update_cooldown(self, user_id: int, cd_field: str, timestamp: float) -> bool:
        allowed_fields = ['free_agent_cd', 'custom_text_cd', 'retire_cd']
        if cd_field not in allowed_fields: return False
        try:
            self.cursor.execute(f"UPDATE users SET {cd_field} = ? WHERE user_id = ?", (timestamp, user_id))
            self.connection.commit()
            return True
        except sqlite3.Error:
            return False

    # --------------------------------------------------------------------------
    # УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ
    # --------------------------------------------------------------------------
    def get_all_admins(self) -> List[int]:
        try:
            self.cursor.execute("SELECT admin_id FROM bot_admins")
            return [row[0] for row in self.cursor.fetchall()]
        except sqlite3.Error:
            return INITIAL_ADMIN_IDS

    def is_admin(self, user_id: int) -> bool:
        try:
            self.cursor.execute("SELECT 1 FROM bot_admins WHERE admin_id = ?", (user_id,))
            return bool(self.cursor.fetchone())
        except sqlite3.Error:
            return False

    def add_bot_admin(self, admin_id: int) -> bool:
        try:
            self.cursor.execute("INSERT INTO bot_admins (admin_id) VALUES (?)", (admin_id,))
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.Error:
            return False

    def remove_bot_admin(self, admin_id: int) -> bool:
        try:
            self.cursor.execute("DELETE FROM bot_admins WHERE admin_id = ?", (admin_id,))
            self.connection.commit()
            return self.cursor.rowcount > 0
        except sqlite3.Error:
            return False

    # --------------------------------------------------------------------------
    # УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ И КАРЬЕРОЙ
    # --------------------------------------------------------------------------
    def add_new_user(self, user_id: int, username: str, nickname: str) -> bool:
        try:
            self.cursor.execute('''
                INSERT INTO users (user_id, username, nickname) 
                VALUES (?, ?, ?)
            ''', (user_id, username, nickname))
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_user_data_by_id(self, user_id: int) -> Optional[Tuple]:
        try:
            self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return self.cursor.fetchone()
        except sqlite3.Error:
            return None

    def get_user_data_by_nickname(self, nickname: str) -> Optional[Tuple]:
        try:
            self.cursor.execute("SELECT * FROM users WHERE nickname = ?", (nickname,))
            return self.cursor.fetchone()
        except sqlite3.Error:
            return None

    def update_user_nickname(self, user_id: int, new_nickname: str) -> bool:
        try:
            self.cursor.execute('UPDATE users SET nickname = ? WHERE user_id = ?', (new_nickname, user_id))
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def execute_career_retirement(self, user_id: int) -> bool:
        try:
            self.cursor.execute('UPDATE users SET is_retired = 1, club_id = NULL WHERE user_id = ?', (user_id,))
            self.connection.commit()
            return True
        except sqlite3.Error:
            return False

    def execute_career_return(self, user_id: int) -> bool:
        try:
            self.cursor.execute('UPDATE users SET is_retired = 0 WHERE user_id = ?', (user_id,))
            self.connection.commit()
            return True
        except sqlite3.Error:
            return False
            
    def force_return_career_by_nick(self, nickname: str) -> bool:
        try:
            self.cursor.execute('UPDATE users SET is_retired = 0 WHERE nickname = ?', (nickname,))
            self.connection.commit()
            return self.cursor.rowcount > 0
        except sqlite3.Error:
            return False

    def change_ban_status(self, nickname: str, is_banned: int) -> bool:
        try:
            self.cursor.execute("UPDATE users SET is_banned = ? WHERE nickname = ?", (is_banned, nickname))
            self.connection.commit()
            return self.cursor.rowcount > 0
        except sqlite3.Error:
            return False

    # --------------------------------------------------------------------------
    # МЕТОДЫ УПРАВЛЕНИЯ КЛУБАМИ 
    # --------------------------------------------------------------------------
    def create_new_club(self, club_name: str, owner_id: int) -> bool:
        try:
            self.cursor.execute("INSERT INTO clubs (club_name, owner_id) VALUES (?, ?)", (club_name, owner_id))
            new_club_id = self.cursor.lastrowid
            self.cursor.execute("UPDATE users SET club_id = ? WHERE user_id = ?", (new_club_id, owner_id))
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_club_info_by_id(self, club_id: int) -> Optional[Tuple]:
        try:
            self.cursor.execute("SELECT * FROM clubs WHERE club_id = ?", (club_id,))
            return self.cursor.fetchone()
        except sqlite3.Error:
            return None

    def get_all_clubs(self) -> List[Tuple]:
        try:
            self.cursor.execute("SELECT club_id, club_name FROM clubs")
            return self.cursor.fetchall()
        except sqlite3.Error:
            return []

    def get_club_by_admin_rights(self, user_id: int) -> Optional[Tuple]:
        try:
            self.cursor.execute('''
                SELECT * FROM clubs 
                WHERE owner_id = ? OR deputy1_id = ? OR deputy2_id = ?
            ''', (user_id, user_id, user_id))
            return self.cursor.fetchone()
        except sqlite3.Error:
            return None

    def delete_club_fully(self, club_id: int) -> bool:
        try:
            self.cursor.execute("UPDATE users SET club_id = NULL WHERE club_id = ?", (club_id,))
            self.cursor.execute("DELETE FROM clubs WHERE club_id = ?", (club_id,))
            self.connection.commit()
            return True
        except sqlite3.Error:
            return False

    def get_club_players_list(self, club_id: int) -> List[Tuple]:
        try:
            self.cursor.execute("SELECT user_id, nickname FROM users WHERE club_id = ?", (club_id,))
            return self.cursor.fetchall()
        except sqlite3.Error:
            return []

    def change_player_club(self, user_id: int, new_club_id: Optional[int]) -> bool:
        try:
            self.cursor.execute("UPDATE users SET club_id = ? WHERE user_id = ?", (new_club_id, user_id))
            self.connection.commit()
            return True
        except sqlite3.Error:
            return False

    def add_transfer_count(self, club_id: int) -> bool:
        try:
            self.cursor.execute("UPDATE clubs SET transfers_count = transfers_count + 1 WHERE club_id = ?", (club_id,))
            self.connection.commit()
            return True
        except sqlite3.Error:
            return False

    def assign_club_deputy(self, club_id: int, deputy_id: int) -> str:
        try:
            club_data = self.get_club_info_by_id(club_id)
            if not club_data: return 'error'
            
            if club_data[3] is None:
                self.cursor.execute("UPDATE clubs SET deputy1_id = ? WHERE club_id = ?", (deputy_id, club_id))
            elif club_data[4] is None:
                self.cursor.execute("UPDATE clubs SET deputy2_id = ? WHERE club_id = ?", (deputy_id, club_id))
            else:
                return 'full'
                
            self.connection.commit()
            return 'success'
        except sqlite3.Error:
            return 'error'

    def remove_club_deputy(self, club_id: int, deputy_id: int) -> bool:
        try:
            club_data = self.get_club_info_by_id(club_id)
            if not club_data: return False
                
            if club_data[3] == deputy_id:
                self.cursor.execute("UPDATE clubs SET deputy1_id = NULL WHERE club_id = ?", (club_id,))
            elif club_data[4] == deputy_id:
                self.cursor.execute("UPDATE clubs SET deputy2_id = NULL WHERE club_id = ?", (club_id,))
            else:
                return False 
                
            self.connection.commit()
            return True
        except sqlite3.Error:
            return False

# Инициализируем глобальный объект базы данных
db_manager = DatabaseManager()

# ==============================================================================
# 6. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (ВАЛИДАЦИЯ)
# ==============================================================================

def is_valid_english_nickname(nickname: str) -> bool:
    if not nickname:
        return False
        
    allowed_characters = string.ascii_letters + string.digits + "_"
    for char in nickname:
        if char not in allowed_characters:
            return False
            
    return True

# ==============================================================================
# 7. ПРОЦЕСС РЕГИСТРАЦИИ НОВЫХ ПОЛЬЗОВАТЕЛЕЙ
# ==============================================================================

@dp.message(CommandStart())
async def command_start_handler(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    username = message.from_user.username
    formatted_username = f"@{username}" if username else "Скрыт"
    
    logger.info(f"Пользователь {user_id} ({formatted_username}) нажал /start.")
    await state.clear()
    
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if user_data:
        nickname = user_data[2]
        
        club_data = db_manager.get_club_by_admin_rights(user_id)
        is_club_admin = bool(club_data)
        is_superadmin = db_manager.is_admin(user_id)
        
        welcome_back_text = (
            f"👋 <b>С возвращением, {nickname}!</b>\n\n"
            f"Система Трансфермаркета готова к работе.\n"
            f"Воспользуйтесь меню ниже для управления своим профилем."
        )
        
        keyboard = get_player_main_menu(
            user_id=user_id, 
            is_club_owner_or_deputy=is_club_admin,
            is_superadmin=is_superadmin
        )
        await message.answer(text=welcome_back_text, reply_markup=keyboard)
        return
        
    registration_text = (
        "🌟 <b>ПРИВЕТСТВУЕМ ВАС В ТРАНСФЕРМАРКЕТЕ ПО ИГРЕ RIVALS!</b> 🌟\n\n"
        "Здесь вы сможете найти себе команду мечты, подписывать контракты "
        "с лучшими клубами или заявить о себе на весь мир!\n\n"
        "👇 <b>Напишите ваш игровой никнейм (только английскими буквами):</b>"
    )
    
    await message.answer(text=registration_text)
    await state.set_state(UserRegistration.waiting_for_nickname)

@dp.message(StateFilter(UserRegistration.waiting_for_nickname))
async def process_nickname_registration(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Скрыт"
    nickname = message.text.strip()
    
    if len(nickname) < 3 or len(nickname) > 20:
        await message.answer("⚠️ <b>Ошибка:</b> Никнейм должен содержать от 3 до 20 символов. Попробуйте еще раз:")
        return
        
    if not is_valid_english_nickname(nickname):
        await message.answer("⚠️ <b>Недопустимые символы!</b> Используйте только английские буквы. Введите заново:")
        return
        
    success = db_manager.add_new_user(user_id=user_id, username=username, nickname=nickname)
    
    if success:
        is_superadmin = db_manager.is_admin(user_id)
        keyboard = get_player_main_menu(user_id=user_id, is_club_owner_or_deputy=False, is_superadmin=is_superadmin)
        
        await message.answer(
            f"✅ <b>Регистрация успешно завершена!</b>\nВаш никнейм: <code>{nickname}</code>", 
            reply_markup=keyboard
        )
        await state.clear()
    else:
        await message.answer("❌ <b>Этот никнейм уже занят!</b> Придумайте другой ник:")

# ==============================================================================
# 8. ОБРАБОТЧИКИ ГЛАВНОГО МЕНЮ (ПРОФИЛЬ, ПОМОЩЬ И СМЕНА НИКА)
# ==============================================================================

@dp.message(F.text == "ℹ️ Помощь")
async def handle_help_button(message: types.Message) -> None:
    help_message = (
        "📚 <b>СПРАВОЧНИК ПО КОМАНДАМ</b> 📚\n\n"
        "<b>Действия игрока:</b>\n"
        "🏃‍♂️ <b>Свободный агент</b> — Подать заявку на поиск клуба.\n"
        "📝 <b>Свой текст</b> — Опубликовать кастомное объявление.\n"
        "🥀 <b>Завершения карьеры</b> — Заморозить профиль (выход из клуба).\n"
        "❤️ <b>Возращения карьеры</b> — Отменить статус завершения карьеры.\n"
        "🔄 <b>Смена никнейма</b> — Изменить игровой ник.\n"
        "👤 <b>Профиль</b> — Просмотр статистики.\n\n"
        "<b>Команды Владельцев клубов:</b>\n"
        "<code>/invite [ник]</code> — Подписать игрока\n"
        "<code>/delete [ник]</code> — Разорвать контракт\n"
        "<code>/viewteam</code> — Информация о клубе\n\n"
        "<i>❗️ Все публикации и трансферы проходят проверку.</i>"
    )
    await message.answer(text=help_message)

@dp.message(F.text == "👤 Профиль")
async def handle_profile_button(message: types.Message) -> None:
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data:
        await message.answer("❌ Вы не зарегистрированы! Введите /start.")
        return

    username, nickname, club_id, is_banned, is_retired = user_data[1], user_data[2], user_data[3], bool(user_data[4]), bool(user_data[5])
    
    club_name_display = "Нет клуба (Свободный агент)"
    if club_id is not None:
        club_data = db_manager.get_club_info_by_id(club_id)
        if club_data:
            club_name_display = f"🛡 {club_data[1]}"
            
    if is_banned:
        status_display = "🔴 ЗАБЛОКИРОВАН (Бан)"
    elif is_retired:
        status_display = "🥀 Карьера завершена"
    else:
        status_display = "🟢 Активен (Готов к игре)"

    profile_text = (
        "👤 <b>ПРОФИЛЬ ИГРОКА</b> 👤\n\n"
        f"📝 <b>Никнейм:</b> <code>{nickname}</code>\n"
        f"🔗 <b>Юзернейм:</b> {username}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"⚽️ <b>Клуб:</b> {club_name_display}\n\n"
        f"📊 <b>Статус:</b> {status_display}"
    )
    await message.answer(text=profile_text)

@dp.message(F.text == "🔄 Смена никнейма")
async def handle_change_nickname(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data: return
    if bool(user_data[4]):
        await message.answer("❌ <b>Отказано:</b> Ваш аккаунт заблокирован.")
        return

    await message.answer(
        "✍️ <b>Смена игрового никнейма</b>\nВведите ваш новый никнейм (только английские буквы):",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(ChangeNicknameProcess.waiting_for_new_nickname)

@dp.message(StateFilter(ChangeNicknameProcess.waiting_for_new_nickname))
async def process_new_nickname(message: types.Message, state: FSMContext) -> None:
    new_nickname = message.text.strip()
    
    if not is_valid_english_nickname(new_nickname) or len(new_nickname) < 3 or len(new_nickname) > 20:
        await message.answer("⚠️ Неверный формат. Используйте английские буквы от 3 до 20 символов:")
        return

    success = db_manager.update_user_nickname(user_id=message.from_user.id, new_nickname=new_nickname)
    if success:
        await message.answer(f"✅ <b>Успешно!</b> Ваш новый никнейм: <code>{new_nickname}</code>")
        await state.clear()
    else:
        await message.answer("❌ <b>Ошибка:</b> Никнейм занят. Придумайте другой.")

# ==============================================================================
# 9. ЗАВЕРШЕНИЕ И ВОЗВРАЩЕНИЕ КАРЬЕРЫ (С КУЛДАУНОМ 15 ДНЕЙ)
# ==============================================================================

@dp.message(F.text == "🥀 Завершения карьеры")
async def handle_career_retire(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data or bool(user_data[4]): return
    if bool(user_data[5]):
        await message.answer("⚠️ <b>Ваша карьера уже завершена!</b>")
        return

    # Проверка кулдауна (15 дней)
    if not db_manager.is_admin(user_id):
        current_time = datetime.now().timestamp()
        cd_time = user_data[8] if len(user_data) > 8 and user_data[8] else 0
        if current_time < cd_time:
            rem = cd_time - current_time
            days, remainder = divmod(rem, 86400)
            hours, _ = divmod(remainder, 3600)
            await message.answer(f"⏳ <b>Кулдаун!</b> Завершить карьеру снова можно будет через {int(days)}д {int(hours)}ч.")
            return

    post_content = f"❗️ОФИЦИАЛЬНО: ЗАВЕРШЕНИЕ КАРЬЕРЫ🥀\n\n😎 <b>{user_data[2]}</b> ({user_data[1]}) - завершение карьеры."
    
    admins = db_manager.get_all_admins()
    for admin_id in admins:
        try:
            admin_msg = f"🔔 <b>ЗАЯВКА НА ЗАВЕРШЕНИЕ КАРЬЕРЫ</b>\nОт: <code>{user_data[2]}</code>\n\n{post_content}"
            keyboard = get_anketa_approval_keyboard(user_id, "retire")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
        except Exception: pass

    await state.update_data(prepared_post=post_content)
    await message.answer("✅ <b>Заявка на завершение карьеры отправлена администраторам!</b>\nОжидайте одобрения.")
    
    # Выдача кулдауна 15 дней (15 * 24 * 60 * 60 = 1296000 секунд)
    if not db_manager.is_admin(user_id):
        db_manager.update_cooldown(user_id, 'retire_cd', datetime.now().timestamp() + 15 * 86400)

@dp.message(F.text == "❤️ Возращения карьеры")
async def handle_career_return(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data or bool(user_data[4]): return
    if not bool(user_data[5]):
        await message.answer("⚠️ <b>Ваша карьера активна.</b> Вы не завершали ее.")
        return

    post_content = f"❗️ОФИЦИАЛЬНО: ВОЗРАЩЕНИЕ КАРЬЕРЫ❤️\n\n😎 <b>{user_data[2]}</b> ({user_data[1]}) - возвращение в карьеру."
    
    admins = db_manager.get_all_admins()
    for admin_id in admins:
        try:
            admin_msg = f"🔔 <b>ЗАЯВКА НА ВОЗВРАЩЕНИЕ КАРЬЕРЫ</b>\nОт: <code>{user_data[2]}</code>\n\n{post_content}"
            keyboard = get_anketa_approval_keyboard(user_id, "return")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
        except Exception: pass

    await state.update_data(prepared_post=post_content)
    await message.answer("✅ <b>Заявка на возвращение отправлена администраторам на проверку!</b>")

# ==============================================================================
# 10. СОЗДАНИЕ ОБЪЯВЛЕНИЙ (С КУЛДАУНАМИ)
# ==============================================================================

@dp.message(F.text == "🏃‍♂️ Свободный агент")
async def handle_free_agent_button(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data: return
    if bool(user_data[4]):
        await message.answer("❌ <b>Ошибка:</b> Ваш аккаунт заблокирован.")
        return
    if bool(user_data[5]):
        await message.answer("🥀 <b>Вы завершили карьеру!</b> Сначала вернитесь в спорт.")
        return

    # Проверка кулдауна (6 часов)
    if not db_manager.is_admin(user_id):
        current_time = datetime.now().timestamp()
        cd_time = user_data[6] if len(user_data) > 6 and user_data[6] else 0
        if current_time < cd_time:
            rem = cd_time - current_time
            hours, remainder = divmod(rem, 3600)
            minutes, _ = divmod(remainder, 60)
            await message.answer(f"⏳ <b>Кулдаун!</b> Вы сможете подать анкету через {int(hours)}ч {int(minutes)}м.")
            return

    await message.answer(
        "📝 <b>Режим: Свободный агент</b>\n\nНапишите текст вашего объявления (позиция, прайм-тайм и т.д.):",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(FreeAgentProcess.waiting_for_text)

@dp.message(StateFilter(FreeAgentProcess.waiting_for_text))
async def process_free_agent_text(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    post_content = f"❗️СВОБОДНЫЙ АГЕНТ✌\n\n😎 <b>{user_data[2]}</b> ({user_data[1]}) - Ищет клуб\nP.s: {message.text}"
    
    admins = db_manager.get_all_admins()
    for admin_id in admins:
        try:
            admin_msg = f"🔔 <b>НОВАЯ АНКЕТА (Свободный агент)</b>\nОт: <code>{user_data[2]}</code>\n\n{post_content}"
            keyboard = get_anketa_approval_keyboard(user_id, "freeagent")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
        except Exception: pass

    await state.update_data(prepared_post=post_content)
    await message.answer("✅ <b>Анкета отправлена на проверку администраторам!</b>")
    await state.clear()
    
    # Выдача кулдауна 6 часов (6 * 3600 = 21600 секунд)
    if not db_manager.is_admin(user_id):
        db_manager.update_cooldown(user_id, 'free_agent_cd', datetime.now().timestamp() + 6 * 3600)

@dp.message(F.text == "📝 Свой текст")
async def handle_custom_text_button(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    
    if not user_data: return
    if bool(user_data[4]):
        await message.answer("❌ <b>Ошибка:</b> Аккаунт заблокирован.")
        return
    if bool(user_data[5]):
        await message.answer("🥀 <b>Вы завершили карьеру!</b>")
        return

    # Проверка кулдауна (12 часов)
    if not db_manager.is_admin(user_id):
        current_time = datetime.now().timestamp()
        cd_time = user_data[7] if len(user_data) > 7 and user_data[7] else 0
        if current_time < cd_time:
            rem = cd_time - current_time
            hours, remainder = divmod(rem, 3600)
            minutes, _ = divmod(remainder, 60)
            await message.answer(f"⏳ <b>Кулдаун!</b> Свой текст можно опубликовать через {int(hours)}ч {int(minutes)}м.")
            return

    await message.answer(
        "📝 <b>Режим: Свой текст</b>\nНапишите сообщение полностью, как хотите видеть его в канале:",
        reply_markup=get_cancel_inline_keyboard()
    )
    await state.set_state(CustomTextProcess.waiting_for_text)

@dp.message(StateFilter(CustomTextProcess.waiting_for_text))
async def process_custom_text(message: types.Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_data = db_manager.get_user_data_by_id(user_id)
    post_content = f"👤 От игрока: <b>{user_data[2]}</b>\n\n{message.text}"
    
    admins = db_manager.get_all_admins()
    for admin_id in admins:
        try:
            admin_msg = f"🔔 <b>НОВАЯ АНКЕТА (Свой текст)</b>\nОт: <code>{user_data[2]}</code>\n\n{post_content}"
            keyboard = get_anketa_approval_keyboard(user_id, "customtext")
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
        except Exception: pass

    await state.update_data(prepared_post=post_content)
    await message.answer("✅ <b>Ваш текст отправлен на модерацию!</b>")
    await state.clear()
    
    # Выдача кулдауна 12 часов (12 * 3600 = 43200 секунд)
    if not db_manager.is_admin(user_id):
        db_manager.update_cooldown(user_id, 'custom_text_cd', datetime.now().timestamp() + 12 * 3600)

# ==============================================================================
# 11. ОТМЕНА ДЕЙСТВИЙ (КОЛБЕК)
# ==============================================================================

@dp.callback_query(F.data == "cancel_current_action")
async def cancel_fsm_action(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ <b>Действие отменено.</b> Вы вернулись в главное меню.")
    await callback.answer()

# ==============================================================================
# 12. МОДЕРАЦИЯ АНКЕТ АДМИНИСТРАТОРАМИ (Включая карьеру)
# ==============================================================================

@dp.callback_query(F.data.startswith("approve_"))
async def process_anketa_approval(callback: types.CallbackQuery) -> None:
    parts = callback.data.split("_")
    action_type = parts[1]
    user_id = int(parts[2])
    
    original_text = callback.message.text
    try:
        post_content = "\n\n".join(original_text.split("\n\n")[1:])
    except IndexError:
        await callback.answer("❌ Ошибка парсинга сообщения.", show_alert=True)
        return

    try:
        if action_type == "retire":
            db_manager.execute_career_retirement(user_id)
            user_msg = "✅ <b>Одобрено:</b> Ваша заявка на завершение карьеры принята и опубликована!"
        elif action_type == "return":
            db_manager.execute_career_return(user_id)
            user_msg = "✅ <b>Одобрено:</b> Ваша заявка на возвращение карьеры принята и опубликована!"
        else:
            user_msg = "🎉 <b>Отличные новости!</b> Ваша анкета проверена администратором и успешно опубликована!"

        await bot.send_message(chat_id=CHANNEL_ID, text=post_content)
        await callback.message.edit_text(f"✅ <b>ОДОБРЕНО И ОПУБЛИКОВАНО</b>\n\n{post_content}")
        await bot.send_message(chat_id=user_id, text=user_msg)
    except Exception as e:
        logger.error(f"Ошибка публикации одобренного поста: {e}")
        await callback.answer("⚠️ Ошибка публикации. Проверьте права бота.", show_alert=True)

@dp.callback_query(F.data.startswith("reject_"))
async def process_anketa_rejection(callback: types.CallbackQuery) -> None:
    parts = callback.data.split("_")
    action_type = parts[1]
    user_id = int(parts[2])
    
    await callback.message.edit_text(f"❌ <b>ОТКЛОНЕНО</b>\n\n{callback.message.text}")
    
    try:
        await bot.send_message(
            chat_id=user_id,
            text="⚠️ <b>К сожалению, ваша заявка/анкета была отклонена модератором.</b>"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления об отклонении: {e}")

# ==============================================================================
# 13. КОМАНДЫ ДЛЯ ВЛАДЕЛЬЦЕВ КЛУБОВ (СИСТЕМА ИНВАЙТОВ И ПЕРЕХОДОВ)
# ==============================================================================

@dp.message(Command("invite"))
async def club_command_invite(message: types.Message) -> None:
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
    
    if target_id == user_id:
        await message.answer("❌ Вы не можете пригласить самого себя.")
        return
    if target_data[4]:
        await message.answer("❌ Этот игрок заблокирован.")
        return
    if target_data[3] is not None:
        await message.answer("❌ Этот игрок уже состоит в другом клубе!")
        return
    if target_data[5]:
        await message.answer("❌ Этот игрок завершил карьеру и не может вступить в клуб.")
        return

    invite_text = (
        f"📩 <b>ПРЕДЛОЖЕНИЕ КОНТРАКТА</b> 📩\n\n"
        f"Клуб <b>{club_name}</b> приглашает вас стать частью их команды!\n"
        f"Вы согласны подписать контракт?"
    )
    
    try:
        await bot.send_message(
            chat_id=target_id, 
            text=invite_text, 
            reply_markup=get_invite_player_keyboard(club_id, club_name)
        )
        await message.answer(f"⏳ Запрос отправлен игроку <code>{target_nickname}</code>. Ожидайте его ответа.")
    except Exception:
        await message.answer("❌ Ошибка: Не удалось отправить сообщение игроку (возможно, он заблокировал бота).")

@dp.callback_query(F.data.startswith("player_accept_invite_"))
async def player_accept_invite(callback: types.CallbackQuery) -> None:
    user_id = callback.from_user.id
    club_id = int(callback.data.split("_")[3])
    
    user_data = db_manager.get_user_data_by_id(user_id)
    club_data = db_manager.get_club_info_by_id(club_id)
    
    if not user_data or not club_data:
        await callback.answer("Ошибка данных.", show_alert=True)
        return
        
    nickname = user_data[2]
    club_name = club_data[1]
    
    await callback.message.edit_text(f"✅ Вы приняли приглашение от <b>{club_name}</b>!\n⏳ Трансфер отправлен на проверку администраторам.")
    
    admins = db_manager.get_all_admins()
    for admin_id in admins:
        try:
            admin_msg = (
                f"🔔 <b>НОВЫЙ ТРАНСФЕР НА ПРОВЕРКУ</b>\n"
                f"Игрок: <code>{nickname}</code>\n"
                f"Переходит в клуб: <b>{club_name}</b>\n\n"
                f"Одобрить переход?"
            )
            keyboard = get_transfer_mod_keyboard(user_id, club_id)
            await bot.send_message(chat_id=admin_id, text=admin_msg, reply_markup=keyboard)
        except Exception: pass

@dp.callback_query(F.data.startswith("player_reject_invite_"))
async def player_reject_invite(callback: types.CallbackQuery) -> None:
    await callback.message.edit_text("❌ Вы отклонили предложение о контракте.")

@dp.callback_query(F.data.startswith("mod_approve_transfer_"))
async def mod_approve_transfer(callback: types.CallbackQuery) -> None:
    parts = callback.data.split("_")
    target_id = int(parts[3])
    club_id = int(parts[4])
    
    user_data = db_manager.get_user_data_by_id(target_id)
    club_data = db_manager.get_club_info_by_id(club_id)
    
    if not user_data or not club_data:
        await callback.message.edit_text("❌ Ошибка: Данные устарели.")
        return
        
    nickname = user_data[2]
    club_name = club_data[1]
    
    success = db_manager.change_player_club(user_id=target_id, new_club_id=club_id)
    if success:
        db_manager.add_transfer_count(club_id)
        
        post_text = (
            "❗️ОФИЦИАЛЬНО: ТРАНСФЕРЫ📍\n\n"
            f"😎 <b>{nickname}</b> - Свободный агент ➡️ <b>{club_name}</b>"
        )
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=post_text)
            await bot.send_message(target_id, f"🎉 <b>Трансфер одобрен!</b>\nТеперь вы игрок команды <b>{club_name}</b>.")
        except Exception: pass
            
        await callback.message.edit_text(f"✅ Трансфер игрока {nickname} в {club_name} <b>ОДОБРЕН</b> и опубликован.")
    else:
        await callback.message.edit_text("❌ Системная ошибка БД при переводе.")

@dp.callback_query(F.data.startswith("mod_reject_transfer_"))
async def mod_reject_transfer(callback: types.CallbackQuery) -> None:
    parts = callback.data.split("_")
    target_id = int(parts[3])
    
    await callback.message.edit_text(f"❌ Трансфер <b>ОТКЛОНЕН</b> администратором.")
    try:
        await bot.send_message(target_id, "⚠️ <b>Ваш трансфер был заблокирован администрацией.</b>")
    except Exception: pass

@dp.message(Command("delete"))
async def club_command_delete(message: types.Message) -> None:
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        await message.answer("⚠️ <b>Использование:</b> <code>/delete [игровой ник]</code>")
        return
        
    target_nickname = args[1].strip()
    club_data = db_manager.get_club_by_admin_rights(user_id)
    
    if not club_data:
        await message.answer("❌ У вас нет прав для использования этой команды.")
        return
        
    club_id = club_data[0]
    owner_id = club_data[2]
    
    target_data = db_manager.get_user_data_by_nickname(target_nickname)
    if not target_data:
        await message.answer("❌ Игрок не найден.")
        return
        
    target_id = target_data[0]
    
    if target_id == owner_id:
        await message.answer("❌ Владельца клуба невозможно кикнуть!")
        return
        
    if target_data[3] != club_id:
        await message.answer("❌ Этот игрок не состоит в вашем клубе.")
        return

    db_manager.remove_club_deputy(club_id=club_id, deputy_id=target_id)
    success = db_manager.change_player_club(user_id=target_id, new_club_id=None)
    
    if success:
        try:
            await bot.send_message(target_id, "💔 <b>Контракт расторгнут.</b>\nВы были исключены из клуба.")
        except: pass
        await message.answer(f"✅ Игрок <code>{target_nickname}</code> успешно исключен из команды.")
    else:
        await message.answer("⚠️ Ошибка при удалении игрока.")

@dp.message(Command("viewteam"))
@dp.message(F.text == "🛡 Мой клуб")
async def club_command_viewteam(message: types.Message) -> None:
    user_id = message.from_user.id
    club_data = db_manager.get_club_by_admin_rights(user_id)
    
    if not club_data:
        await message.answer("❌ Вы не являетесь владельцем или заместителем ни в одном клубе.")
        return
        
    club_id, club_name, owner_id, deputy1_id, deputy2_id, transfers_count = club_data

    owner_data = db_manager.get_user_data_by_id(owner_id)
    owner_nick = owner_data[2] if owner_data else "Неизвестно"
    
    def get_nick(dep_id):
        if dep_id:
            d = db_manager.get_user_data_by_id(dep_id)
            if d: return f"{d[2]} (ID: {dep_id})"
        return "Нету"

    players = db_manager.get_club_players_list(club_id)
    
    msg_text = (
        "📋Даные клуба 📝\n"
        "─────────────────────────────\n"
        f"📊Названия клуба: <b>{club_name}</b>\n"
        f"👑 Владелец: {owner_nick} (ID: {owner_id})\n"
        f"👤Помощник 1: {get_nick(deputy1_id)}\n"
        f"👤Помощник 2: {get_nick(deputy2_id)}\n"
        f"📊 Успешных переходов: {transfers_count}\n"
        "🏆─────────────────────────────🏆\n\n"
        f"👥 Состав команды ({len(players)}/15):\n"
    )
    
    for i in range(1, 16):
        if i <= len(players):
            msg_text += f" {i}. ✏️ {players[i-1][1]}\n"
        else:
            msg_text += f" {i}. ✏️ \n"

    reply_markup = get_club_management_inline() if user_id == owner_id else None
    await message.answer(text=msg_text, reply_markup=reply_markup)

@dp.callback_query(F.data == "club_add_deputy")
async def process_add_deputy(callback: types.CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("✍️ <b>Добавление заместителя:</b>\nВведите ник игрока (он должен быть в клубе):", reply_markup=get_cancel_inline_keyboard())
    await state.set_state(ClubManagementProcess.waiting_for_deputy_nickname)
    await state.update_data(action="add")
    await callback.answer()

@dp.callback_query(F.data == "club_remove_deputy")
async def process_remove_deputy(callback: types.CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("✍️ <b>Снятие заместителя:</b>\nВведите ник заместителя:", reply_markup=get_cancel_inline_keyboard())
    await state.set_state(ClubManagementProcess.waiting_for_deputy_nickname)
    await state.update_data(action="remove")
    await callback.answer()

@dp.message(StateFilter(ClubManagementProcess.waiting_for_deputy_nickname))
async def handle_deputy_nickname(message: types.Message, state: FSMContext) -> None:
    target_nick = message.text.strip()
    user_id = message.from_user.id
    
    club_data = db_manager.get_club_by_admin_rights(user_id)
    if not club_data or club_data[2] != user_id:
        await message.answer("❌ У вас нет прав владельца клуба.")
        await state.clear()
        return
        
    club_id = club_data[0]
    action = (await state.get_data()).get("action")
    target_user = db_manager.get_user_data_by_nickname(target_nick)
    
    if not target_user:
        await message.answer("❌ Игрок не найден.")
        await state.clear()
        return
        
    target_id = target_user[0]
    
    if action == "add":
        if target_user[3] != club_id:
            await message.answer("❌ Игрок должен сначала вступить в ваш клуб.")
            await state.clear()
            return
        res = db_manager.assign_club_deputy(club_id, target_id)
        if res == 'success': await message.answer(f"✅ {target_nick} назначен замом.")
        elif res == 'full': await message.answer("❌ Лимит заместителей (2) исчерпан!")
        else: await message.answer("⚠️ Ошибка.")
            
    elif action == "remove":
        if db_manager.remove_club_deputy(club_id, target_id):
            await message.answer(f"✅ {target_nick} больше не заместитель.")
        else:
            await message.answer("❌ Этот игрок не является вашим заместителем.")
    await state.clear()

# ==============================================================================
# 14. СЕКРЕТНАЯ АДМИН ПАНЕЛЬ
# ==============================================================================

@dp.message(F.text == "⚙️ Админ Панель")
async def superadmin_panel_open(message: types.Message) -> None:
    if not db_manager.is_admin(message.from_user.id): return
    await message.answer("🛡 <b>Админ Панель:</b> Выберите действие:", reply_markup=get_superadmin_menu())

@dp.message(F.text == "🔙 Выйти из админ панели")
async def superadmin_panel_close(message: types.Message) -> None:
    if not db_manager.is_admin(message.from_user.id): return
    keyboard = get_player_main_menu(message.from_user.id, bool(db_manager.get_club_by_admin_rights(message.from_user.id)), True)
    await message.answer("Вы вышли из админ-панели.", reply_markup=keyboard)

@dp.message(F.text == "👑 Дать админа")
async def superadmin_give_admin(message: types.Message, state: FSMContext) -> None:
    if not db_manager.is_admin(message.from_user.id): return
    await message.answer("Введите <b>Telegram ID</b> пользователя, чтобы выдать ему права Администратора:", reply_markup=get_cancel_inline_keyboard())
    await state.set_state(SuperAdminProcess.waiting_for_new_admin_id)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_new_admin_id))
async def process_give_admin(message: types.Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("❌ ID должен содержать только цифры. Отмена.")
        await state.clear()
        return
        
    admin_id = int(message.text)
    if db_manager.add_bot_admin(admin_id):
        await message.answer(f"✅ Пользователь с ID <code>{admin_id}</code> успешно назначен администратором бота.")
    else:
        await message.answer("❌ Ошибка или пользователь уже является администратором.")
    await state.clear()

@dp.message(F.text == "🚫 Убрать админа")
async def superadmin_remove_admin(message: types.Message, state: FSMContext) -> None:
    if not db_manager.is_admin(message.from_user.id): return
    await message.answer("Введите <b>Telegram ID</b> администратора для снятия полномочий:", reply_markup=get_cancel_inline_keyboard())
    await state.set_state(SuperAdminProcess.waiting_for_remove_admin_id)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_remove_admin_id))
async def process_remove_admin(message: types.Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("❌ ID должен содержать только цифры.")
        await state.clear()
        return
        
    admin_id = int(message.text)
    if admin_id == message.from_user.id:
        await message.answer("❌ Вы не можете снять админку с самого себя.")
        await state.clear()
        return

    if db_manager.remove_bot_admin(admin_id):
        await message.answer(f"✅ Администратор <code>{admin_id}</code> снят с должности.")
    else:
        await message.answer("❌ Этот ID не найден в списке администраторов.")
    await state.clear()

@dp.message(F.text == "❤️ Вернуть карьеру игроку")
async def superadmin_return_career(message: types.Message, state: FSMContext) -> None:
    if not db_manager.is_admin(message.from_user.id): return
    await message.answer("Введите <b>игровой ник</b> игрока, которому нужно принудительно вернуть карьеру:", reply_markup=get_cancel_inline_keyboard())
    await state.set_state(SuperAdminProcess.waiting_for_return_career_nick)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_return_career_nick))
async def process_return_career(message: types.Message, state: FSMContext) -> None:
    target_nick = message.text.strip()
    
    if db_manager.force_return_career_by_nick(target_nick):
        await message.answer(f"✅ Игроку <code>{target_nick}</code> успешно возвращена карьера.")
    else:
        await message.answer(f"❌ Игрок <code>{target_nick}</code> не найден.")
    await state.clear()

@dp.message(F.text == "➕ Добавить клуб")
async def superadmin_add_club_start(message: types.Message, state: FSMContext) -> None:
    if not db_manager.is_admin(message.from_user.id): return
    await message.answer("Введите <b>название</b> нового клуба:", reply_markup=get_cancel_inline_keyboard())
    await state.set_state(SuperAdminProcess.waiting_for_club_name)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_club_name))
async def superadmin_add_club_name(message: types.Message, state: FSMContext) -> None:
    await state.update_data(club_name=message.text.strip())
    await message.answer("Введите <b>Telegram ID</b> владельца клуба (только цифры):", reply_markup=get_cancel_inline_keyboard())
    await state.set_state(SuperAdminProcess.waiting_for_club_owner_id)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_club_owner_id))
async def superadmin_add_club_owner(message: types.Message, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("❌ ID должен состоять только из цифр. Отмена.")
        await state.clear()
        return
        
    club_name = (await state.get_data()).get("club_name")
    owner_id = int(message.text)
    user_data = db_manager.get_user_data_by_id(owner_id)
    
    if not user_data:
        await message.answer("❌ Пользователь не зарегистрирован в боте.")
        await state.clear()
        return

    if db_manager.create_new_club(club_name=club_name, owner_id=owner_id):
        await message.answer(f"✅ Клуб <b>{club_name}</b> создан. Владелец: {user_data[2]}")
    else:
        await message.answer("❌ Ошибка: Клуб с таким названием уже существует.")
    await state.clear()

@dp.message(F.text == "➖ Убрать клуб")
async def superadmin_remove_club_start(message: types.Message) -> None:
    if not db_manager.is_admin(message.from_user.id): return
    clubs = db_manager.get_all_clubs()
    if not clubs:
        await message.answer("Нет зарегистрированных клубов.")
        return
        
    builder = InlineKeyboardBuilder()
    for club_id, club_name in clubs:
        builder.button(text=f"🗑 {club_name}", callback_data=f"delclub_{club_id}")
    builder.adjust(1)
    await message.answer("Выберите клуб для удаления:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("delclub_"))
async def superadmin_confirm_delete_club(callback: types.CallbackQuery) -> None:
    if not db_manager.is_admin(callback.from_user.id): return
    club_id = int(callback.data.split("_")[1])
    builder = InlineKeyboardBuilder()
    builder.button(text="⚠️ ДА, УДАЛИТЬ", callback_data=f"confirmdel_{club_id}")
    builder.button(text="❌ ОТМЕНА", callback_data="cancel_current_action")
    await callback.message.edit_text("Вы уверены? Это удалит клуб навсегда.", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("confirmdel_"))
async def superadmin_execute_delete_club(callback: types.CallbackQuery) -> None:
    if not db_manager.is_admin(callback.from_user.id): return
    club_id = int(callback.data.split("_")[1])
    if db_manager.delete_club_fully(club_id):
        await callback.message.edit_text("✅ <b>Клуб удален.</b> Игроки стали свободными агентами.")
    else:
        await callback.message.edit_text("❌ Ошибка.")

@dp.message(F.text == "🚫 Забанить игрока")
async def superadmin_ban_start(message: types.Message, state: FSMContext) -> None:
    if not db_manager.is_admin(message.from_user.id): return
    await message.answer("Введите игровой ник для <b>БЛОКИРОВКИ</b>:", reply_markup=get_cancel_inline_keyboard())
    await state.set_state(SuperAdminProcess.waiting_for_ban_nickname)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_ban_nickname))
async def superadmin_ban_execute(message: types.Message, state: FSMContext) -> None:
    target_nick = message.text.strip()
    if db_manager.change_ban_status(nickname=target_nick, is_banned=1):
        await message.answer(f"✅ Игрок <code>{target_nick}</code> забанен.")
    else:
        await message.answer("❌ Игрок не найден.")
    await state.clear()

@dp.message(F.text == "✅ Разбанить игрока")
async def superadmin_unban_start(message: types.Message, state: FSMContext) -> None:
    if not db_manager.is_admin(message.from_user.id): return
    await message.answer("Введите игровой ник для <b>РАЗБЛОКИРОВКИ</b>:", reply_markup=get_cancel_inline_keyboard())
    await state.set_state(SuperAdminProcess.waiting_for_unban_nickname)

@dp.message(StateFilter(SuperAdminProcess.waiting_for_unban_nickname))
async def superadmin_unban_execute(message: types.Message, state: FSMContext) -> None:
    target_nick = message.text.strip()
    if db_manager.change_ban_status(nickname=target_nick, is_banned=0):
        await message.answer(f"✅ Игрок <code>{target_nick}</code> разбанен.")
    else:
        await message.answer("❌ Игрок не найден.")
    await state.clear()

# ==============================================================================
# 15. ЗАПУСК БОТА (MAIN)
# ==============================================================================

async def main() -> None:
    logger.info("Бот Трансфермаркета успешно запущен и готов к работе!")
    await bot.delete_webhook(drop_pending_updates=True)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Критическая ошибка работы бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот был выключен вручную (KeyboardInterrupt).")
