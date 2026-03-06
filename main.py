import os
import logging
from pathlib import Path
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

# =========================
# SOZLAMALAR
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKENINGIZNI_BU_YERGA_QOYING")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")

WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "supersecret")
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}" if RENDER_EXTERNAL_URL else ""

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"

DATA_DIR.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

# =========================
# MA'LUMOTLAR
# =========================
# Fakultetlar va guruhlar
FACULTIES = {
    "iqtisod": {
        "name": "Iqtisod fakulteti",
        "groups": ["0124", "0224", "0324"]
    },
    "agronomiya": {
        "name": "Agronomiya fakulteti",
        "groups": ["A-11", "A-12", "A-13"]
    },
    "zootexniya": {
        "name": "Zootexniya fakulteti",
        "groups": ["Z-11", "Z-12"]
    },
    "vet": {
        "name": "Veterinariya fakulteti",
        "groups": ["V-11", "V-12"]
    }
}

# Admin qaysi guruhga pdf yuklamoqchi ekanini vaqtincha saqlash
admin_upload_state = {
    "waiting_group": None
}


# =========================
# KLAVIATURALAR
# =========================
def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📚 Fakultetlar", callback_data="faculties")],
            [InlineKeyboardButton(text="ℹ️ Yordam", callback_data="help_info")],
        ]
    )


def admin_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 PDF yuklash", callback_data="admin_upload")],
            [InlineKeyboardButton(text="📂 Yuklangan fayllar", callback_data="admin_files")],
        ]
    )


def faculties_kb():
    rows = []
    for fac_key, fac_data in FACULTIES.items():
        rows.append([
            InlineKeyboardButton(
                text=fac_data["name"],
                callback_data=f"faculty:{fac_key}"
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def groups_kb(faculty_key: str):
    rows = []
    groups = FACULTIES[faculty_key]["groups"]
    for group in groups:
        rows.append([
            InlineKeyboardButton(
                text=group,
                callback_data=f"group:{faculty_key}:{group}"
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="faculties")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_faculties_kb():
    rows = []
    for fac_key, fac_data in FACULTIES.items():
        rows.append([
            InlineKeyboardButton(
                text=fac_data["name"],
                callback_data=f"admin_faculty:{fac_key}"
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_groups_kb(faculty_key: str):
    rows = []
    groups = FACULTIES[faculty_key]["groups"]
    for group in groups:
        rows.append([
            InlineKeyboardButton(
                text=group,
                callback_data=f"admin_group:{faculty_key}:{group}"
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin_upload")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# =========================
# YORDAMCHI FUNKSIYALAR
# =========================
def get_pdf_path(faculty_key: str, group: str) -> Path:
    safe_group = group.replace("/", "_").replace("\\", "_").replace(" ", "_")
    return PDF_DIR / f"{faculty_key}_{safe_group}.pdf"


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def uploaded_files_text() -> str:
    files = list(PDF_DIR.glob("*.pdf"))
    if not files:
        return "📂 Hozircha hech qanday PDF yuklanmagan."
    text = "📂 Yuklangan fayllar:\n\n"
    for f in files:
        text += f"• {f.name}\n"
    return text


# =========================
# BUYRUQLAR
# =========================
@dp.message(Command("start"))
async def start_handler(message: Message):
    text = (
        "Assalomu alaykum!\n\n"
        "Bu bot orqali dars jadvali PDF fayllarini olishingiz mumkin.\n\n"
        "Kerakli bo‘limni tanlang:"
    )
    await message.answer(text, reply_markup=main_menu())

    if is_admin(message.from_user.id):
        await message.answer("🔐 Siz adminsiz.", reply_markup=admin_menu())


@dp.message(Command("admin"))
async def admin_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Siz admin emassiz.")
        return
    await message.answer("Admin panelga xush kelibsiz:", reply_markup=admin_menu())


@dp.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        "📌 Foydalanish:\n"
        "1. Fakultetni tanlang\n"
        "2. Guruhni tanlang\n"
        "3. PDF jadvalni oling\n\n"
        "Admin uchun: /admin"
    )


# =========================
# CALLBACKLAR
# =========================
@dp.callback_query(F.data == "back_main")
async def back_main_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "Asosiy menyu:",
        reply_markup=main_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "help_info")
async def help_info_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "📌 Botdan foydalanish:\n\n"
        "• Fakultetni tanlang\n"
        "• Guruhni tanlang\n"
        "• Agar PDF yuklangan bo‘lsa, bot sizga yuboradi\n\n"
        "Admin uchun: /admin",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main")]
            ]
        )
    )
    await callback.answer()


@dp.callback_query(F.data == "faculties")
async def faculties_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "📚 Fakultetni tanlang:",
        reply_markup=faculties_kb()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("faculty:"))
async def faculty_handler(callback: CallbackQuery):
    faculty_key = callback.data.split(":")[1]

    if faculty_key not in FACULTIES:
        await callback.answer("Fakultet topilmadi", show_alert=True)
        return

    await callback.message.edit_text(
        f"🏛 {FACULTIES[faculty_key]['name']}\n\nGuruhni tanlang:",
        reply_markup=groups_kb(faculty_key)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("group:"))
async def group_handler(callback: CallbackQuery):
    _, faculty_key, group = callback.data.split(":", 2)

    pdf_path = get_pdf_path(faculty_key, group)

    if not pdf_path.exists():
        await callback.message.answer(
            f"❌ {group} guruhi uchun PDF hali yuklanmagan."
        )
        await callback.answer()
        return

    await callback.message.answer_document(
        document=FSInputFile(pdf_path),
        caption=f"📄 {group} guruhi jadvali"
    )
    await callback.answer("PDF yuborildi")


# =========================
# ADMIN CALLBACKLAR
# =========================
@dp.callback_query(F.data == "admin_back")
async def admin_back_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return

    await callback.message.edit_text(
        "Admin panel:",
        reply_markup=admin_menu()
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_upload")
async def admin_upload_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return

    await callback.message.edit_text(
        "📤 PDF yuklash uchun fakultetni tanlang:",
        reply_markup=admin_faculties_kb()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_faculty:"))
async def admin_faculty_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return

    faculty_key = callback.data.split(":")[1]

    await callback.message.edit_text(
        f"🏛 {FACULTIES[faculty_key]['name']}\n\nQaysi guruhga PDF yuklaysiz?",
        reply_markup=admin_groups_kb(faculty_key)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_group:"))
async def admin_group_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return

    _, faculty_key, group = callback.data.split(":", 2)
    admin_upload_state["waiting_group"] = {
        "faculty_key": faculty_key,
        "group": group
    }

    await callback.message.answer(
        f"📥 Endi <b>{group}</b> guruhi uchun PDF fayl yuboring.\n"
        f"Bot shu guruhga saqlab qo‘yadi."
    )
    await callback.answer("Endi PDF yuboring")


@dp.callback_query(F.data == "admin_files")
async def admin_files_handler(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo‘q", show_alert=True)
        return

    await callback.message.answer(uploaded_files_text())
    await callback.answer()


# =========================
# PDF QABUL QILISH
# =========================
@dp.message(F.document)
async def document_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Sizga fayl yuklashga ruxsat yo‘q.")
        return

    current = admin_upload_state.get("waiting_group")
    if not current:
        await message.answer(
            "Avval /admin orqali guruhni tanlang, keyin PDF yuboring."
        )
        return

    document = message.document

    if not document.file_name.lower().endswith(".pdf"):
        await message.answer("❌ Faqat PDF fayl yuboring.")
        return

    faculty_key = current["faculty_key"]
    group = current["group"]
    save_path = get_pdf_path(faculty_key, group)

    await bot.download(document, destination=save_path)

    admin_upload_state["waiting_group"] = None

    await message.answer(
        f"✅ PDF saqlandi!\n\n"
        f"Fakultet: {FACULTIES[faculty_key]['name']}\n"
        f"Guruh: {group}\n"
        f"Fayl: {save_path.name}"
    )


# =========================
# ODDIY XABARLAR
# =========================
@dp.message()
async def all_messages_handler(message: Message):
    text = message.text.lower().strip() if message.text else ""

    if text in ["salom", "assalomu alaykum", "start"]:
        await message.answer(
            "Assalomu alaykum!\nKerakli bo‘limni tanlang:",
            reply_markup=main_menu()
        )
        return

    await message.answer(
        "Buyruqni tushunmadim.\n/start ni bosing.",
        reply_markup=main_menu()
    )


# =========================
# WEBHOOK + AIOHTTP
# =========================
async def on_startup(app: web.Application):
    if not BOT_TOKEN or BOT_TOKEN == "TOKENINGIZNI_BU_YERGA_QOYING":
        raise RuntimeError("BOT_TOKEN noto‘g‘ri yoki kiritilmagan.")

    if WEBHOOK_URL:
        await bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True
        )
        logging.info(f"Webhook o‘rnatildi: {WEBHOOK_URL}")
    else:
        logging.warning("RENDER_EXTERNAL_URL topilmadi. Webhook o‘rnatilmadi.")


async def on_shutdown(app: web.Application):
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.session.close()
    logging.info("Bot to‘xtadi.")


async def health(request):
    return web.Response(text="Bot is running!")


async def webhook_handler(request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != WEBHOOK_SECRET:
        return web.Response(status=403, text="Forbidden")

    data = await request.json()
    update = dp.resolve_update_type(data)
    telegram_update = dp.feed_webhook_update(bot=bot, update=data)
    await telegram_update
    return web.Response(text="ok")


def main():
    app = web.Application()

    app.router.add_get("/", health)
    app.router.add_post(WEBHOOK_PATH, webhook_handler)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    port = int(os.getenv("PORT", 10000))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
