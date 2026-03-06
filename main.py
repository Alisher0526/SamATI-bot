import os
import logging
from datetime import datetime

import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB_NAME = "bot.db"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

router = Router()


# =========================
# DATABASE
# =========================
class Database:
    def __init__(self, db_name: str):
        self.db_name = db_name

    async def init(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    full_name TEXT,
                    username TEXT,
                    created_at TEXT
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS faculties (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at TEXT
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS groups_table (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    faculty_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    pdf_file_id TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    UNIQUE(faculty_id, name),
                    FOREIGN KEY (faculty_id) REFERENCES faculties(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            await db.commit()

    async def add_user(self, user_id: int, full_name: str, username: str | None):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                INSERT OR IGNORE INTO users (user_id, full_name, username, created_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, full_name, username or "", datetime.now().isoformat()))
            await db.commit()

    async def get_user_count(self) -> int:
        async with aiosqlite.connect(self.db_name) as db:
            cur = await db.execute("SELECT COUNT(*) FROM users")
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_all_users(self) -> list[int]:
        async with aiosqlite.connect(self.db_name) as db:
            cur = await db.execute("SELECT user_id FROM users")
            rows = await cur.fetchall()
            return [row[0] for row in rows]

    async def add_faculty(self, name: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("""
                    INSERT INTO faculties (name, created_at)
                    VALUES (?, ?)
                """, (name.strip(), datetime.now().isoformat()))
                await db.commit()
            return True
        except Exception:
            return False

    async def get_faculties(self):
        async with aiosqlite.connect(self.db_name) as db:
            cur = await db.execute("""
                SELECT id, name FROM faculties ORDER BY name ASC
            """)
            return await cur.fetchall()

    async def get_faculty(self, faculty_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cur = await db.execute("""
                SELECT id, name FROM faculties WHERE id=?
            """, (faculty_id,))
            return await cur.fetchone()

    async def add_group(self, faculty_id: int, name: str) -> bool:
        try:
            async with aiosqlite.connect(self.db_name) as db:
                await db.execute("""
                    INSERT INTO groups_table (faculty_id, name, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    faculty_id,
                    name.strip(),
                    datetime.now().isoformat(),
                    datetime.now().isoformat()
                ))
                await db.commit()
            return True
        except Exception:
            return False

    async def get_groups_by_faculty(self, faculty_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cur = await db.execute("""
                SELECT id, name, pdf_file_id
                FROM groups_table
                WHERE faculty_id=?
                ORDER BY name ASC
            """, (faculty_id,))
            return await cur.fetchall()

    async def get_group(self, group_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            cur = await db.execute("""
                SELECT id, faculty_id, name, pdf_file_id
                FROM groups_table
                WHERE id=?
            """, (group_id,))
            return await cur.fetchone()

    async def set_group_pdf(self, group_id: int, file_id: str):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                UPDATE groups_table
                SET pdf_file_id=?, updated_at=?
                WHERE id=?
            """, (file_id, datetime.now().isoformat(), group_id))
            await db.commit()

    async def delete_group(self, group_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM groups_table WHERE id=?", (group_id,))
            await db.commit()

    async def delete_faculty(self, faculty_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("DELETE FROM groups_table WHERE faculty_id=?", (faculty_id,))
            await db.execute("DELETE FROM faculties WHERE id=?", (faculty_id,))
            await db.commit()

    async def set_setting(self, key: str, value: str):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """, (key, value))
            await db.commit()

    async def get_setting(self, key: str):
        async with aiosqlite.connect(self.db_name) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = await cur.fetchone()
            return row[0] if row else None


db = Database(DB_NAME)


# =========================
# STATES
# =========================
class AdminStates(StatesGroup):
    waiting_faculty_name = State()
    waiting_group_faculty = State()
    waiting_group_name = State()
    waiting_pdf_group = State()
    waiting_pdf_file = State()
    waiting_delete_faculty = State()
    waiting_delete_group = State()
    waiting_broadcast_text = State()


# =========================
# HELPERS
# =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def main_menu(admin: bool = False):
    buttons = [
        [KeyboardButton(text="📚 Fakultetlar")],
        [KeyboardButton(text="ℹ️ Yordam")],
    ]
    if admin:
        buttons.append([KeyboardButton(text="🔐 Admin panel")])

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True
    )


async def send_main_menu(message: Message):
    await message.answer(
        "Kerakli bo‘limni tanlang:",
        reply_markup=main_menu(is_admin(message.from_user.id))
    )


def faculties_kb(faculties):
    kb = InlineKeyboardBuilder()
    for faculty_id, name in faculties:
        kb.button(text=name, callback_data=f"faculty:{faculty_id}")
    kb.adjust(1)
    return kb.as_markup()


def groups_kb(groups):
    kb = InlineKeyboardBuilder()
    for group_id, name, _ in groups:
        kb.button(text=name, callback_data=f"group:{group_id}")
    kb.button(text="⬅️ Orqaga", callback_data="back:faculties")
    kb.adjust(1)
    return kb.as_markup()


def admin_panel_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Fakultet qo‘shish", callback_data="admin:add_faculty")
    kb.button(text="➕ Guruh qo‘shish", callback_data="admin:add_group")
    kb.button(text="📄 PDF yuklash", callback_data="admin:upload_pdf")
    kb.button(text="📢 E'lon yuborish", callback_data="admin:broadcast")
    kb.button(text="👥 Userlar soni", callback_data="admin:user_count")
    kb.button(text="🗑 Fakultet o‘chirish", callback_data="admin:delete_faculty")
    kb.button(text="🗑 Guruh o‘chirish", callback_data="admin:delete_group")
    kb.button(text="🏠 Bosh menyu", callback_data="admin:home")
    kb.adjust(1)
    return kb.as_markup()


def faculty_choose_admin_kb(faculties, action_prefix: str):
    kb = InlineKeyboardBuilder()
    for faculty_id, name in faculties:
        kb.button(text=name, callback_data=f"{action_prefix}:{faculty_id}")
    kb.button(text="❌ Bekor qilish", callback_data="admin:cancel")
    kb.adjust(1)
    return kb.as_markup()


def groups_choose_admin_kb(groups, action_prefix: str):
    kb = InlineKeyboardBuilder()
    for group_id, name, _ in groups:
        kb.button(text=name, callback_data=f"{action_prefix}:{group_id}")
    kb.button(text="❌ Bekor qilish", callback_data="admin:cancel")
    kb.adjust(1)
    return kb.as_markup()


# =========================
# USER
# =========================
@router.message(CommandStart())
async def start_handler(message: Message):
    await db.add_user(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username
    )

    text = (
        "Assalomu alaykum.\n\n"
        "Bu bot orqali fakultet va guruh bo‘yicha jadval PDF’larini olasiz.\n"
        "Kerakli bo‘limni tanlang."
    )
    await message.answer(
        text,
        reply_markup=main_menu(is_admin(message.from_user.id))
    )


@router.message(F.text == "ℹ️ Yordam")
async def help_handler(message: Message):
    await message.answer(
        "Foydalanish tartibi:\n"
        "1) 📚 Fakultetlar ni bosing\n"
        "2) Fakultet tanlang\n"
        "3) Guruh tanlang\n"
        "4) PDF bo‘lsa bot yuboradi\n\n"
        "Agar siz admin bo‘lsangiz, 🔐 Admin panel ham ko‘rinadi."
    )


@router.message(F.text == "📚 Fakultetlar")
async def faculties_handler(message: Message):
    faculties = await db.get_faculties()
    if not faculties:
        await message.answer("Hozircha fakultetlar kiritilmagan.")
        return

    await message.answer(
        "Fakultetni tanlang:",
        reply_markup=faculties_kb(faculties)
    )


@router.callback_query(F.data.startswith("faculty:"))
async def faculty_callback(callback: CallbackQuery):
    faculty_id = int(callback.data.split(":")[1])
    faculty = await db.get_faculty(faculty_id)

    if not faculty:
        await callback.message.edit_text("Fakultet topilmadi.")
        await callback.answer()
        return

    groups = await db.get_groups_by_faculty(faculty_id)
    if not groups:
        await callback.message.edit_text(
            f"📚 {faculty[1]}\n\nHozircha guruhlar qo‘shilmagan."
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"📚 {faculty[1]}\n\nGuruhni tanlang:",
        reply_markup=groups_kb(groups)
    )
    await callback.answer()


@router.callback_query(F.data == "back:faculties")
async def back_faculties(callback: CallbackQuery):
    faculties = await db.get_faculties()
    if not faculties:
        await callback.message.edit_text("Hozircha fakultetlar kiritilmagan.")
        await callback.answer()
        return

    await callback.message.edit_text(
        "Fakultetni tanlang:",
        reply_markup=faculties_kb(faculties)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("group:"))
async def group_callback(callback: CallbackQuery):
    group_id = int(callback.data.split(":")[1])
    group = await db.get_group(group_id)

    if not group:
        await callback.message.answer("Guruh topilmadi.")
        await callback.answer()
        return

    _, faculty_id, group_name, pdf_file_id = group
    faculty = await db.get_faculty(faculty_id)
    faculty_name = faculty[1] if faculty else "Noma'lum fakultet"

    if not pdf_file_id:
        await callback.message.answer(
            f"📘 Fakultet: {faculty_name}\n"
            f"👥 Guruh: {group_name}\n\n"
            f"Hozircha bu guruh uchun PDF yuklanmagan."
        )
        await callback.answer()
        return

    await callback.message.answer_document(
        document=pdf_file_id,
        caption=(
            f"📘 Fakultet: {faculty_name}\n"
            f"👥 Guruh: {group_name}"
        )
    )
    await callback.answer()


# =========================
# ADMIN
# =========================
@router.message(F.text == "🔐 Admin panel")
async def admin_panel_open(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Siz admin emassiz.")
        return

    await message.answer(
        "Admin panel:",
        reply_markup=admin_panel_kb()
    )


@router.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Siz admin emassiz.")
        return

    await message.answer(
        "Admin panel:",
        reply_markup=admin_panel_kb()
    )


@router.callback_query(F.data == "admin:home")
async def admin_home(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "Bosh menyuga qaytdingiz.",
        reply_markup=main_menu(is_admin(callback.from_user.id))
    )
    await callback.answer()


@router.callback_query(F.data == "admin:cancel")
async def admin_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Bekor qilindi.", reply_markup=admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:add_faculty")
async def admin_add_faculty(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_faculty_name)
    await callback.message.answer(
        "Yangi fakultet nomini yuboring.\n\nMisol: Iqtisod"
    )
    await callback.answer()


@router.message(AdminStates.waiting_faculty_name)
async def save_faculty(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Fakultet nomi juda qisqa.")
        return

    ok = await db.add_faculty(name)
    if ok:
        await message.answer("✅ Fakultet qo‘shildi.", reply_markup=admin_panel_kb())
    else:
        await message.answer("⚠️ Fakultet mavjud yoki xatolik bo‘ldi.", reply_markup=admin_panel_kb())

    await state.clear()


@router.callback_query(F.data == "admin:add_group")
async def admin_add_group(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return

    faculties = await db.get_faculties()
    if not faculties:
        await callback.message.answer("Avval fakultet qo‘shing.")
        await callback.answer()
        return

    await state.set_state(AdminStates.waiting_group_faculty)
    await callback.message.answer(
        "Qaysi fakultetga guruh qo‘shiladi?",
        reply_markup=faculty_choose_admin_kb(faculties, "admin_group_faculty")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_group_faculty:"))
async def choose_group_faculty(callback: CallbackQuery, state: FSMContext):
    faculty_id = int(callback.data.split(":")[1])
    await state.update_data(faculty_id=faculty_id)
    await state.set_state(AdminStates.waiting_group_name)
    await callback.message.answer("Endi guruh nomini yuboring.\n\nMisol: 0124")
    await callback.answer()


@router.message(AdminStates.waiting_group_name)
async def save_group(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    faculty_id = data.get("faculty_id")
    name = message.text.strip()

    if not faculty_id:
        await message.answer("Xatolik: fakultet tanlanmagan.")
        await state.clear()
        return

    if len(name) < 1:
        await message.answer("Guruh nomi noto‘g‘ri.")
        return

    ok = await db.add_group(faculty_id, name)
    if ok:
        await message.answer("✅ Guruh qo‘shildi.", reply_markup=admin_panel_kb())
    else:
        await message.answer("⚠️ Guruh mavjud yoki xatolik bo‘ldi.", reply_markup=admin_panel_kb())

    await state.clear()


@router.callback_query(F.data == "admin:upload_pdf")
async def admin_upload_pdf(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return

    faculties = await db.get_faculties()
    if not faculties:
        await callback.message.answer("Avval fakultet va guruh qo‘shing.")
        await callback.answer()
        return

    await callback.message.answer(
        "PDF yuklash uchun avval fakultetni tanlang:",
        reply_markup=faculty_choose_admin_kb(faculties, "admin_pdf_faculty")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_pdf_faculty:"))
async def admin_pdf_faculty(callback: CallbackQuery, state: FSMContext):
    faculty_id = int(callback.data.split(":")[1])
    groups = await db.get_groups_by_faculty(faculty_id)

    if not groups:
        await callback.message.answer("Bu fakultetda guruhlar yo‘q.")
        await callback.answer()
        return

    await callback.message.answer(
        "PDF biriktiriladigan guruhni tanlang:",
        reply_markup=groups_choose_admin_kb(groups, "admin_pdf_group")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_pdf_group:"))
async def admin_pdf_group(callback: CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split(":")[1])
    await state.update_data(group_id=group_id)
    await state.set_state(AdminStates.waiting_pdf_file)
    await callback.message.answer(
        "Endi PDF faylni yuboring.\nFaqat document sifatida yuboring."
    )
    await callback.answer()


@router.message(AdminStates.waiting_pdf_file, F.document)
async def save_pdf_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    group_id = data.get("group_id")

    if not group_id:
        await message.answer("Xatolik: guruh topilmadi.")
        await state.clear()
        return

    document = message.document
    if not document.file_name.lower().endswith(".pdf"):
        await message.answer("Iltimos, PDF fayl yuboring.")
        return

    await db.set_group_pdf(group_id, document.file_id)
    await message.answer("✅ PDF saqlandi.", reply_markup=admin_panel_kb())
    await state.clear()


@router.message(AdminStates.waiting_pdf_file)
async def wrong_pdf_type(message: Message):
    await message.answer("Iltimos, PDF faylni document qilib yuboring.")


@router.callback_query(F.data == "admin:user_count")
async def admin_u
