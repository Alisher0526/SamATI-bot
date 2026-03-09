import os
import asyncio
import logging
from flask import Flask, request, jsonify, session, redirect, url_for, render_template_string

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
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "12345")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "my-secret-path")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. Render env variable kiriting.")

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Oddiy xotira storage
DATA = {
    "announcements": [],
    "faculties": ["Iqtisod", "Agronomiya", "Veterinariya"],
    "groups": ["0124", "0125"],
    "schedules": {
        "0124": "Dushanba: Iqtisodiyot nazariyasi\nSeshanba: Ingliz tili",
        "0125": "Dushanba: Matematika\nSeshanba: Informatika"
    }
}

telegram_app = Application.builder().token(BOT_TOKEN).build()

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
        "Assalomu alaykum.\nBu SAMATI botining PRO versiyasi.",
        reply_markup=menu
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Buyruqlar:\n"
        "/start - botni ishga tushirish\n"
        "/help - yordam\n"
        "/admin - admin panel linki"
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if RENDER_EXTERNAL_URL:
        await update.message.reply_text(f"Admin panel: {RENDER_EXTERNAL_URL}/admin/login")
    else:
        await update.message.reply_text("Admin panel URL hali tayyor emas.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📢 E'lonlar":
        anns = DATA["announcements"]
        if anns:
            msg = "\n\n".join([f"{i+1}. {a}" for i, a in enumerate(anns[-10:])])
        else:
            msg = "Hozircha e'lonlar yo'q."
        await update.message.reply_text(msg)

    elif text == "🏫 Fakultetlar":
        msg = "\n".join(DATA["faculties"]) if DATA["faculties"] else "Fakultetlar yo'q."
        await update.message.reply_text(msg)

    elif text == "👥 Guruhlar":
        msg = "\n".join(DATA["groups"]) if DATA["groups"] else "Guruhlar yo'q."
        await update.message.reply_text(msg)

    elif text == "🕒 Jadval":
        msg = "Guruh nomini yuboring. Masalan: 0124"
        await update.message.reply_text(msg)

    elif text in DATA["schedules"]:
        await update.message.reply_text(DATA["schedules"][text])

    elif text in DATA["groups"]:
        await update.message.reply_text(DATA["schedules"].get(text, "Bu guruh uchun jadval yo'q."))

    else:
        await update.message.reply_text("Buyruq yoki tugmadan foydalaning.")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("admin", admin_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

HTML_LOGIN = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Admin Login</title>
</head>
<body style="font-family:Arial;max-width:500px;margin:40px auto;">
  <h2>Admin Login</h2>
  <form method="post">
    <input type="password" name="password" placeholder="Parol" style="width:100%;padding:10px;"><br><br>
    <button type="submit" style="padding:10px 20px;">Kirish</button>
  </form>
  <p style="color:red;">{{ error }}</p>
</body>
</html>
"""

HTML_PANEL = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Admin Panel</title>
</head>
<body style="font-family:Arial;max-width:900px;margin:30px auto;">
  <h1>SAMATI Admin Panel</h1>

  <p><a href="/admin/logout">Chiqish</a></p>

  <h2>Yangi e'lon</h2>
  <form method="post" action="/admin/add_announcement">
    <textarea name="text" rows="4" style="width:100%;" placeholder="E'lon matni"></textarea><br><br>
    <button type="submit">Saqlash</button>
  </form>

  <h2>Fakultet qo'shish</h2>
  <form method="post" action="/admin/add_faculty">
    <input name="name" style="width:100%;padding:8px;" placeholder="Fakultet nomi"><
