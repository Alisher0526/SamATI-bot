import os
import logging
from typing import Optional

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
)
from aiogram.exceptions import TelegramBadRequest

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_WEBHOOK_URL = os.getenv("BASE_WEBHOOK_URL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "SAMATI_helper_bot")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi")

ADMIN_IDS = {
    int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()
}
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{BASE_WEBHOOK_URL.rstrip('/')}{WEBHOOK_PATH}" if BASE_WEBHOOK_URL else ""

app = FastAPI(title="SAMATI Pro Bot")
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


class AdminStates(StatesGroup):
    broadcast_text = State()
    add_group_name = State()
    add_group_faculty = State()
    add_schedule_group = State()
    add_schedule_title = State()
    add_schedule_file_id = State()
    add_schedule_file_name = State()


class UserStates(StatesGroup):
    waiting_search = State()


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        await self.init_tables()

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def init_tables(self):
        query = """
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            faculty TEXT,
            group_name TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS groups (
            id SERIAL PRIMARY KEY,
            faculty TEXT NOT NULL,
            group_name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS schedules (
            id SERIAL PRIMARY KEY,
            group_name TEXT NOT NULL,
            title TEXT NOT NULL,
            file_id TEXT NOT NULL,
            file_name TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
        async with self.pool.acquire() as con:
            await con.execute(query)
            for admin_id in ADMIN_IDS:
                await con.execute(
                    """
                    INSERT INTO users (user_id, is_admin)
                    VALUES ($1, TRUE)
                    ON CONFLICT (user_id)
                    DO UPDATE SET is_admin = TRUE
                    """,
                    admin_id,
                )

    async def upsert_user(self, user_id: int, full_name: str, username: Optional[str]):
        async with self.pool.acquire() as con:
            await con.execute(
                """
                INSERT INTO users (user_id, full_name, username)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id)
                DO UPDATE SET full_name = EXCLUDED.full_name,
                              username = EXCLUDED.username
                """,
                user_id,
                full_name,
                username,
            )

    async def set_user_group(self, user_id: int, faculty: str, group_name: str):
        async with self.pool.acquire() as con:
            await con.execute(
                "UPDATE users SET faculty = $2, group_name = $3 WHERE user_id = $1",
                user_id,
                faculty,
                group_name,
            )

    async def is_admin(self, user_id: int) -> bool:
        async with self.pool.acquire() as con:
            row = await con.fetchrow(
                "SELECT is_admin FROM users WHERE user_id = $1", user_id
            )
            return bool(row and row["is_admin"])

    async def add_group(self, faculty: str, group_name: str):
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO groups (faculty, group_name) VALUES ($1, $2) ON CONFLICT (group_name) DO NOTHING",
                faculty,
                group_name,
            )

    async def get_faculties(self):
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT DISTINCT faculty FROM groups ORDER BY faculty ASC"
            )
            return [r["faculty"] for r in rows]

    async def get_groups_by_faculty(self, faculty: str):
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT group_name FROM groups WHERE faculty = $1 ORDER BY group_name ASC",
                faculty,
            )
            return [r["group_name"] for r in rows]

    async def add_schedule(self, group_name: str, title: str, file_id: str, file_name: str):
        async with self.pool.acquire() as con:
            await con.execute(
                "INSERT INTO schedules (group_name, title, file_id, file_name) VALUES ($1, $2, $3, $4)",
                group_name,
                title,
                file_id,
                file_name,
            )

    async def get_schedules_by_group(self, group_name: str):
        async with self.pool.acquire() as con:
            return await con.fetch(
                "SELECT id, title, file_id, file_name, created_at FROM schedules WHERE group_name = $1 ORDER BY created_at DESC",
                group_name,
            )

    async def get_user(self, user_id: int):
        async with self.pool.acquire() as con:
            return await con.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

    async def get_all_user_ids(self):
        async with self.pool.acquire() as con:
            rows = await con.fetch("SELECT user_id FROM users ORDER BY user_id ASC")
            return [r["user_id"] for r in rows]

    async def stats(self):
        async with self.pool.acquire() as con:
            users = await con.fetchval("SELECT COUNT(*) FROM users")
            groups = await con.fetchval("SELECT COUNT(*) FROM groups")
            schedules = await con.fetchval("SELECT COUNT(*) FROM schedules")
            admins = await con.fetchval("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
            return {
                "users": users,
                "groups": groups,
                "schedules": schedules,
                "admins": admins,
            }

    async def search_groups(self, text: str):
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT faculty, group_name FROM groups WHERE LOWER(group_name) LIKE LOWER($1) ORDER BY group_name ASC LIMIT 20",
                f"%{text}%",
            )
            return rows


db = Database()


def main_menu(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎓 Fakultetlar", callback_data="faculties")],
        [InlineKeyboardButton(text="📚 Mening guruhim", callback_data="my_group")],
        [InlineKeyboardButton(text="🔎 Guruh qidirish", callback_data="search_group")],
        [InlineKeyboardButton(text="📢 So'nggi e'lon", callback_data="latest_announcement")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Admin panel", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_menu(to: str = "home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data=to)]]
    )


def list_to_keyboard(items: list[str], prefix: str, back_to: str, columns: int = 1):
    rows = []
    row = []
    for item in items:
        row.append(InlineKeyboardButton(text=item, callback_data=f"{prefix}:{item}"))
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_to)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Guruh qo'shish", callback_data="admin_add_group")],
            [InlineKeyboardButton(text="📄 Jadval yuklash", callback_data="admin_add_schedule")],
            [InlineKeyboardButton(text="📣 Broadcast", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
            [InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="home")],
        ]
    )


async def safe_edit(call: CallbackQuery, text: str, reply_markup=None):
    try:
        await call.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=reply_markup)


@router.message(CommandStart())
async def start_handler(message: Message):
    await db.upsert_user(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username,
    )
    is_admin = await db.is_admin(message.from_user.id)
    text = (
        "<b>SAMATI Pro Bot</b>ga xush kelibsiz.\n\n"
        "Bu bot orqali siz:\n"
        "• fakultet va guruhlarni ko'rasiz\n"
        "• o'z guruhingizni saqlaysiz\n"
        "• jadval PDF fayllarini olasiz\n"
        "• e'lonlarni ko'rasiz\n"
        "• admin bo'lsangiz panelga kirasiz\n"
    )
    await message.answer(text, reply_markup=main_menu(is_admin))


@router.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        "/start - botni ishga tushirish\n"
        "/help - yordam\n"
        "/menu - bosh menyu\n"
        "/me - profilim",
    )


@router.message(Command("menu"))
async def menu_handler(message: Message):
    is_admin = await db.is_admin(message.from_user.id)
    await message.answer("Bosh menyu:", reply_markup=main_menu(is_admin))


@router.message(Command("me"))
async def me_handler(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        return await message.answer("Avval /start bosing")
    text = (
        f"<b>Profil</b>\n"
        f"ID: <code>{user['user_id']}</code>\n"
        f"Ism: {user['full_name'] or '-'}\n"
        f"Username: @{user['username'] if user['username'] else '-'}\n"
        f"Fakultet: {user['faculty'] or '-'}\n"
        f"Guruh: {user['group_name'] or '-'}"
    )
    await message.answer(text, reply_markup=back_menu("home"))


@router.callback_query(F.data == "home")
async def home_callback(call: CallbackQuery):
    is_admin = await db.is_admin(call.from_user.id)
    await safe_edit(call, "Bosh menyu:", reply_markup=main_menu(is_admin))
    await call.answer()


@router.callback_query(F.data == "faculties")
async def faculties_callback(call: CallbackQuery):
    faculties = await db.get_faculties()
    if not faculties:
        return await safe_edit(call, "Hali fakultetlar kiritilmagan.", reply_markup=back_menu())
    await safe_edit(call, "Fakultetni tanlang:", reply_markup=list_to_keyboard(faculties, "faculty", "home"))
    await call.answer()


@router.callback_query(F.data.startswith("faculty:"))
async def faculty_selected(call: CallbackQuery):
    faculty = call.data.split(":", 1)[1]
    groups = await db.get_groups_by_faculty(faculty)
    if not groups:
        return await safe_edit(call, f"{faculty} uchun guruhlar yo'q.", reply_markup=back_menu("faculties"))
    await safe_edit(
        call,
        f"<b>{faculty}</b> guruhlari:\nGuruhni tanlang:",
        reply_markup=list_to_keyboard(groups, f"group|{faculty}", "faculties"),
    )
    await call.answer()


@router.callback_query(F.data.startswith("group|"))
async def group_selected(call: CallbackQuery):
    _, payload = call.data.split("group|", 1)
    faculty, group_name = payload.split(":", 1)
    await db.set_user_group(call.from_user.id, faculty, group_name)
    schedules = await db.get_schedules_by_group(group_name)
    text = f"<b>{group_name}</b> tanlandi.\nFakultet: {faculty}\n\n"
    if schedules:
        text += "Quyida shu guruh uchun jadval fayllari yuboriladi."
    else:
        text += "Bu guruh uchun hali jadval yuklanmagan."
    await safe_edit(call, text, reply_markup=back_menu("home"))
    for item in schedules[:5]:
        await call.message.answer_document(
            document=item["file_id"],
            caption=f"📄 {item['title']}\nGuruh: {group_name}",
        )
    await call.answer("Guruh saqlandi")


@router.callback_query(F.data == "my_group")
async def my_group_callback(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    if not user or not user["group_name"]:
        return await safe_edit(call, "Siz hali guruh tanlamagansiz.", reply_markup=back_menu("home"))
    schedules = await db.get_schedules_by_group(user["group_name"])
    text = (
        f"<b>Mening guruhim</b>\n"
        f"Fakultet: {user['faculty']}\n"
        f"Guruh: {user['group_name']}\n\n"
    )
    text += "Jadval fayllari yuborildi." if schedules else "Jadval fayli topilmadi."
    await safe_edit(call, text, reply_markup=back_menu("home"))
    for item in schedules[:5]:
        await call.message.answer_document(
            document=item["file_id"],
            caption=f"📄 {item['title']}\nGuruh: {user['group_name']}",
        )
    await call.answer()


@router.callback_query(F.data == "search_group")
async def search_group_callback(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_search)
    await safe_edit(call, "Qidirish uchun guruh nomini yozing. Masalan: 0124", reply_markup=back_menu("home"))
    await call.answer()


@router.message(UserStates.waiting_search)
async def search_group_text(message: Message, state: FSMContext):
    text = message.text.strip()
    rows = await db.search_groups(text)
    await state.clear()
    if not rows:
        return await message.answer("Mos guruh topilmadi.", reply_markup=back_menu("home"))
    groups = [f"{r['group_name']} ({r['faculty']})" for r in rows]
    await message.answer("Topilgan guruhlar:\n- " + "\n- ".join(groups[:20]), reply_markup=back_menu("home"))


@router.callback_query(F.data == "latest_announcement")
async def latest_announcement_callback(call: CallbackQuery):
    async with db.pool.acquire() as con:
        row = await con.fetchrow("SELECT text, created_at FROM announcements ORDER BY id DESC LIMIT 1")
    if not row:
        return await safe_edit(call, "Hali e'lon yo'q.", reply_markup=back_menu("home"))
    await safe_edit(call, f"<b>So'nggi e'lon</b>\n\n{row['text']}", reply_markup=back_menu("home"))
    await call.answer()


@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(call: CallbackQuery):
    if not await db.is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q", show_alert=True)
    await safe_edit(call, "Admin panel", reply_markup=admin_menu())
    await call.answer()


@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(call: CallbackQuery):
    if not await db.is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q", show_alert=True)
    stats = await db.stats()
    text = (
        "<b>Bot statistikasi</b>\n"
        f"Foydalanuvchilar: {stats['users']}\n"
        f"Adminlar: {stats['admins']}\n"
        f"Guruhlar: {stats['groups']}\n"
        f"Jadval fayllari: {stats['schedules']}"
    )
    await safe_edit(call, text, reply_markup=admin_menu())
    await call.answer()


@router.callback_query(F.data == "admin_add_group")
async def admin_add_group_start(call: CallbackQuery, state: FSMContext):
    if not await db.is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q", show_alert=True)
    await state.set_state(AdminStates.add_group_name)
    await safe_edit(call, "Yangi guruh nomini yuboring. Masalan: 0124", reply_markup=admin_menu())
    await call.answer()


@router.message(AdminStates.add_group_name)
async def admin_add_group_name(message: Message, state: FSMContext):
    await state.update_data(group_name=message.text.strip())
    await state.set_state(AdminStates.add_group_faculty)
    await message.answer("Endi fakultet nomini yuboring. Masalan: Iqtisod")


@router.message(AdminStates.add_group_faculty)
async def admin_add_group_faculty(message: Message, state: FSMContext):
    data = await state.get_data()
    group_name = data["group_name"]
    faculty = message.text.strip()
    await db.add_group(faculty, group_name)
    await state.clear()
    await message.answer(
        f"✅ Guruh saqlandi\nFakultet: {faculty}\nGuruh: {group_name}",
        reply_markup=admin_menu(),
    )


@router.callback_query(F.data == "admin_add_schedule")
async def admin_add_schedule_start(call: CallbackQuery, state: FSMContext):
    if not await db.is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q", show_alert=True)
    await state.set_state(AdminStates.add_schedule_group)
    await safe_edit(call, "Qaysi guruhga jadval yuklaysiz? Guruh nomini yuboring.", reply_markup=admin_menu())
    await call.answer()


@router.message(AdminStates.add_schedule_group)
async def admin_schedule_group(message: Message, state: FSMContext):
    await state.update_data(group_name=message.text.strip())
    await state.set_state(AdminStates.add_schedule_title)
    await message.answer("Jadval sarlavhasini yuboring. Masalan: 1-semestr dars jadvali")


@router.message(AdminStates.add_schedule_title)
async def admin_schedule_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminStates.add_schedule_file_id)
    await message.answer("Endi PDF yoki hujjatni yuboring.")


@router.message(AdminStates.add_schedule_file_id, F.document)
async def admin_schedule_file(message: Message, state: FSMContext):
    data = await state.get_data()
    document = message.document
    await db.add_schedule(
        group_name=data["group_name"],
        title=data["title"],
        file_id=document.file_id,
        file_name=document.file_name or "schedule.pdf",
    )
    await state.clear()
    await message.answer(
        f"✅ Jadval yuklandi\nGuruh: {data['group_name']}\nSarlavha: {data['title']}",
        reply_markup=admin_menu(),
    )


@router.message(AdminStates.add_schedule_file_id)
async def admin_schedule_need_document(message: Message):
    await message.answer("Iltimos, PDF yoki boshqa hujjat yuboring.")


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext):
    if not await db.is_admin(call.from_user.id):
        return await call.answer("Ruxsat yo'q", show_alert=True)
    await state.set_state(AdminStates.broadcast_text)
    await safe_edit(call, "Barcha foydalanuvchilarga yuboriladigan matnni kiriting.", reply_markup=admin_menu())
    await call.answer()


@router.message(AdminStates.broadcast_text)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if not await db.is_admin(message.from_user.id):
        return await state.clear()
    text = message.text.strip()
    async with db.pool.acquire() as con:
        await con.execute("INSERT INTO announcements (text) VALUES ($1)", text)
    user_ids = await db.get_all_user_ids()
    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, f"<b>Yangi e'lon</b>\n\n{text}")
            sent += 1
        except Exception:
            failed += 1
    await state.clear()
    await message.answer(
        f"✅ Broadcast tugadi\nYuborildi: {sent}\nXato: {failed}",
        reply_markup=admin_menu(),
    )


@router.message(F.text)
async def fallback_text(message: Message):
    is_admin = await db.is_admin(message.from_user.id)
    await message.answer(
        "Buyruq yoki tugmalardan foydalaning. /menu ni bosing.",
        reply_markup=main_menu(is_admin),
    )


@app.on_event("startup")
async def on_startup():
    await db.connect()
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info("Webhook o'rnatildi: %s", WEBHOOK_URL)
    else:
        logger.warning("BASE_WEBHOOK_URL topilmadi. Webhook o'rnatilmadi.")


@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass
    await db.close()
    await bot.session.close()


@app.get("/")
async def health_check():
    return {"ok": True, "bot": BOT_USERNAME}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=True)
