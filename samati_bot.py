import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "SamATI bot ishlayapti!\n\n"
        "Buyruqlar:\n"
        "/jadval - dars jadvali\n"
        "/sayt - institut sayti"
    )

async def sayt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("https://samaguni.uz")

async def jadval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("https://samati.edupage.org/timetable/")

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("sayt", sayt))
app.add_handler(CommandHandler("jadval", jadval))

app.run_polling()
