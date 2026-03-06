import os
import json
import logging
from pathlib import Path
from typing import Dict, Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = str(os.getenv("ADMIN_ID", "")).strip()

DATA_FILE = Path("schedules.json")

DEFAULT_DATA = {
    "faculties": {
        "iqtisod": {
            "groups": {
                "0124": {
                    "schedule_url": "https://samati.edupage.org/timetable/"
                }
            }
        }
    }
}


# ---------------- DATA HELPERS ----------------
def load_data() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("JSON o'qishda xato: %s", e)
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA


def save_data(data: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_admin(user_id: int) -> bool:
    return str(user_id) == ADMIN_ID


# ---------------- COMMANDS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Assalomu alaykum.\n\n"
        "Men *SAMATI jadval botiman*.\n\n"
        "Buyruqlar:\n"
        "/help - yordam\n"
        "/faculties - fakultetlar ro'yxati\n"
        "/groups <fakultet> - guruhlar ro'yxati\n"
        "/schedule <fakultet> <guruh> - jadval havolasi\n\n"
        "Admin buyruqlari:\n"
        "/addfaculty <nom>\n"
        "/addgroup <fakultet> <guruh>\n"
        "/setschedule <fakultet> <guruh> <url>\n"
        "/stats"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def faculties(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = load_data()
    faculties_data = data.get("faculties", {})

    if not faculties_data:
        await update.message.reply_text("Hozircha fakultetlar qo‘shilmagan.")
        return

    text = "Fakultetlar:\n\n"
    for i, name in enumerate(faculties_data.keys(), start=1):
        text += f"{i}. {name}\n"

    await update.message.reply_text(text)


async def groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 1:
        await update.message.reply_text("Foydalanish: /groups <fakultet>")
        return

    faculty = context.args[0].strip().lower()
    data = load_data()
    faculty_data = data.get("faculties", {}).get(faculty)

    if not faculty_data:
        await update.message.reply_text("Bunday fakultet topilmadi.")
        return

    groups_data = faculty_data.get("groups", {})
    if not groups_data:
        await update.message.reply_text("Bu fakultetda guruhlar yo‘q.")
        return

    text = f"*{faculty}* fakulteti guruhlari:\n\n"
    for i, group_name in enumerate(groups_data.keys(), start=1):
        text += f"{i}. {group_name}\n"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if len(context.args) < 2:
        await update.message.reply_text("Foydalanish: /schedule <fakultet> <guruh>")
        return

    faculty = context.args[0].strip().lower()
    group = context.args[1].strip().lower()

    data = load_data()
    faculty_data = data.get("faculties", {}).get(faculty)

    if not faculty_data:
        await update.message.reply_text("Fakultet topilmadi.")
        return

    group_data = faculty_data.get("groups", {}).get(group)
    if not group_data:
        await update.message.reply_text("Guruh topilmadi.")
        return

    schedule_url = group_data.get("schedule_url", "").strip()
    if not schedule_url:
        await update.message.reply_text("Bu guruh uchun jadval hali kiritilmagan.")
        return

    text = (
        f"*Fakultet:* {faculty}\n"
        f"*Guruh:* {group}\n"
        f"*Jadval:* {schedule_url}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ---------------- ADMIN COMMANDS ----------------
async def addfaculty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Siz admin emassiz.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("Foydalanish: /addfaculty <nom>")
        return

    faculty = context.args[0].strip().lower()
    data = load_data()

    if faculty in data["faculties"]:
        await update.message.reply_text("Bu fakultet allaqachon mavjud.")
        return

    data["faculties"][faculty] = {"groups": {}}
    save_data(data)
    await update.message.reply_text(f"'{faculty}' fakulteti qo‘shildi.")


async def addgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Siz admin emassiz.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Foydalanish: /addgroup <fakultet> <guruh>")
        return

    faculty = context.args[0].strip().lower()
    group = context.args[1].strip().lower()

    data = load_data()

    if faculty not in data["faculties"]:
        await update.message.reply_text("Avval fakultet qo‘shing.")
        return

    if group in data["faculties"][faculty]["groups"]:
        await update.message.reply_text("Bu guruh allaqachon bor.")
        return

    data["faculties"][faculty]["groups"][group] = {"schedule_url": ""}
    save_data(data)
    await update.message.reply_text(f"{faculty} fakultetiga {group} guruhi qo‘shildi.")


async def setschedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Siz admin emassiz.")
        return

    if len(context.args) < 3:
        await update.message.reply_text(
            "Foydalanish: /setschedule <fakultet> <guruh> <url>"
        )
        return

    faculty = context.args[0].strip().lower()
    group = context.args[1].strip().lower()
    url = context.args[2].strip()

    data = load_data()

    if faculty not in data["faculties"]:
        await update.message.reply_text("Bunday fakultet yo‘q.")
        return

    if group not in data["faculties"][faculty]["groups"]:
        await update.message.reply_text("Bunday guruh yo‘q.")
        return

    data["faculties"][faculty]["groups"][group]["schedule_url"] = url
    save_data(data)

    await update.message.reply_text("Jadval muvaffaqiyatli saqlandi.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Siz admin emassiz.")
        return

    data = load_data()
    faculties_count = len(data.get("faculties", {}))
    groups_count = 0

    for faculty_data in data.get("faculties", {}).values():
        groups_count += len(faculty_data.get("groups", {}))

    text = (
        f"Statistika:\n"
        f"- Fakultetlar: {faculties_count}\n"
        f"- Guruhlar: {groups_count}"
    )
    await update.message.reply_text(text)


async def unknown_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Xatolik:", exc_info=context.error)


def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN topilmadi. Environment variable qo'ying.")

    if not ADMIN_ID:
        raise ValueError("ADMIN_ID topilmadi. Environment variable qo'ying.")

    # JSON bo'sh bo'lsa yaratib oladi
    load_data()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("faculties", faculties))
    application.add_handler(CommandHandler("groups", groups))
    application.add_handler(CommandHandler("schedule", schedule))

    application.add_handler(CommandHandler("addfaculty", addfaculty))
    application.add_handler(CommandHandler("addgroup", addgroup))
    application.add_handler(CommandHandler("setschedule", setschedule))
    application.add_handler(CommandHandler("stats", stats))

    application.add_error_handler(unknown_error)

    logger.info("Bot ishga tushdi...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
