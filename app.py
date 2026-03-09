import os
import asyncio
import logging
from flask import Flask, request, jsonify

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "samati-secret")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi")

flask_app = Flask(__name__)
tg_app = Application.builder().token(BOT_TOKEN).build()

DATA = {
    "announcements": ["SAMATI botga xush kelibsiz"],
    "faculties": ["Iqtisod", "Agronomiya", "Veterinariya"],
    "groups": ["0124", "0125"],
    "schedules": {
        "0124": "Dushanba: Iqtisodiyot nazariyasi\nSeshanba: Ingliz tili",
        "0125": "Dushanba: Matematika\nSeshanba: Informatika"
    }
}

menu = ReplyKeyboardMarkup(
    [
        ["📢 E'lonlar", "🏫 Fakultetlar"],
        ["👥 Guruhlar", "🕒 Jadval"],
        ["ℹ️ Yordam"]
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalomu alaykum.\nBu SAMATI bot.",
        reply_markup=menu
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - botni ishga tushirish\n"
        "/help - yordam\n"
        "/admin - admin link"
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if RENDER_EXTERNAL_URL:
        await update.message.reply_text(f"Panel link: {RENDER_EXTERNAL_URL}")
    else:
        await update.message.reply_text("Hali URL tayyor emas.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📢 E'lonlar":
        await update.message.reply_text("\n".join(DATA["announcements"]))
    elif text == "🏫 Fakultetlar":
        await update.message.reply_text("\n".join(DATA["faculties"]))
    elif text == "👥 Guruhlar":
        await update.message.reply_text("\n".join(DATA["groups"]))
    elif text == "🕒 Jadval":
        await update.message.reply_text("Guruh yuboring. Masalan: 0124")
    elif text in DATA["groups"]:
        await update.message.reply_text(DATA["schedules"].get(text, "Jadval topilmadi"))
    else:
        await update.message.reply_text("Tugmalardan foydalaning.")

tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("help", help_command))
tg_app.add_handler(CommandHandler("admin", admin_command))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

async def setup_tg():
    await tg_app.initialize()
    await tg_app.start()

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(setup_tg())

@flask_app.get("/")
def home():
    return "SAMATI bot ishlayapti"

@flask_app.get("/health")
def health():
    return jsonify({"ok": True})

@flask_app.get("/set-webhook")
def set_webhook():
    if not RENDER_EXTERNAL_URL:
        return jsonify({"ok": False, "error": "RENDER_EXTERNAL_URL yoq"})
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook/{WEBHOOK_SECRET}"
    result = loop.run_until_complete(tg_app.bot.set_webhook(webhook_url))
    return jsonify({"ok": result, "webhook_url": webhook_url})

@flask_app.post("/webhook/<secret>")
def webhook(secret):
    if secret != WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "unauthorized"}), 403

    data = request.get_json(force=True)
    update = Update.de_json(data, tg_app.bot)
    loop.run_until_complete(tg_app.process_update(update))
    return jsonify({"ok": True})

if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=10000)
