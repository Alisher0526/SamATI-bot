import os
import threading
import logging
from flask import Flask

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

# Render ENV dan olinadi
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# --- Telegram bot komandalar ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ SamATI bot ishlayapti!\n\n"
        "Buyruqlar:\n"
        "/jadval - dars jadvali\n"
        "/sayt - institut sayti\n"
        "/help - yordam"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Yordam:\n"
        "/jadval - EduPage jadvali\n"
        "/sayt - samaguni.uz\n"
    )

async def sayt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("https://samaguni.uz")

async def jadval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("https://samati.edupage.org/timetable/")

def run_telegram_bot():
    if not TOKEN:
        # TOKEN bo‘lmasa Render logda ko‘rinasiz
        raise RuntimeError("TELEGRAM_BOT_TOKEN topilmadi. Render -> Environment ga token qo'ying.")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("sayt", sayt))
    app.add_handler(CommandHandler("jadval", jadval))

    logging.info("Telegram bot polling boshlandi...")
    app.run_polling(close_loop=False)

# --- Flask (Render Web Service uchun PORT) ---
web = Flask(__name__)

@web.get("/")
def home():
    return "SamATI-bot is running ✅", 200

@web.get("/health")
def health():
    return {"status": "ok"}, 200

if __name__ == "__main__":
    # Telegram botni alohida thread’da ishga tushiramiz
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()

    # Render port
    port = int(os.getenv("PORT", "10000"))
    web.run(host="0.0.0.0", port=port)
