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

from database import (
    init_db,
    add_user,
    set_user_group,
    get_user_group,
    add_faculty,
    get_faculties,
    add_group,
    get_groups,
    get_groups_by_faculty,
    save_schedule,
    get_schedule,
    add_announcement,
    get_announcements,
    get_user_ids,
    get_stats,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "samati-secret")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "12345")
SECRET_KEY = os.getenv("SECRET_KEY", "change-this")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi")

init_db()

flask_app = Flask(__name__)
flask_app.secret_key = SECRET_KEY

tg_app = Application.builder().token(BOT_TOKEN).build()

menu = ReplyKeyboardMarkup(
    [
        ["📢 E'lonlar", "🏫 Fakultetlar"],
        ["👥 Guruhlar", "🕒 Mening jadvalim"],
        ["ℹ️ Yordam"]
    ],
    resize_keyboard=True
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.full_name, user.username or "")
    await update.message.reply_text(
        "Assalomu alaykum.\nSAMATI PRO botga xush kelibsiz.",
        reply_markup=menu
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - botni ishga tushirish\n"
        "/help - yordam\n"
        "/admin - admin panel link\n\n"
        "Guruh nomini yozsangiz, o'sha guruh saqlanadi."
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if RENDER_EXTERNAL_URL:
        await update.message.reply_text(f"Admin panel: {RENDER_EXTERNAL_URL}/admin/login")
    else:
        await update.message.reply_text("Admin panel URL hali tayyor emas.")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.full_name, user.username or "")

    text = update.message.text.strip()

    if text == "📢 E'lonlar":
        anns = get_announcements()
        if anns:
            msg = "\n\n".join([f"{i+1}. {a}" for i, a in enumerate(anns)])
        else:
            msg = "Hozircha e'lonlar yo'q."
        await update.message.reply_text(msg)
        return

    if text == "🏫 Fakultetlar":
        faculties = get_faculties()
        if faculties:
            await update.message.reply_text("\n".join(faculties))
        else:
            await update.message.reply_text("Fakultetlar hali kiritilmagan.")
        return

    if text == "👥 Guruhlar":
        groups = get_groups()
        if groups:
            await update.message.reply_text("\n".join(groups))
        else:
            await update.message.reply_text("Guruhlar hali kiritilmagan.")
        return

    if text == "🕒 Mening jadvalim":
        my_group = get_user_group(user.id)
        if not my_group:
            await update.message.reply_text("Avval guruh nomini yozing. Masalan: 0124")
            return

        schedule = get_schedule(my_group)
        if schedule:
            await update.message.reply_text(f"{my_group} jadvali:\n\n{schedule}")
        else:
            await update.message.reply_text("Bu guruh uchun jadval hali kiritilmagan.")
        return

    if text == "ℹ️ Yordam":
        await update.message.reply_text(
            "Guruh nomini yozing va bot uni eslab qoladi.\n"
            "Keyin '🕒 Mening jadvalim' ni bossangiz jadval chiqadi."
        )
        return

    all_groups = get_groups()
    if text in all_groups:
        set_user_group(user.id, text)
        schedule = get_schedule(text)
        if schedule:
            await update.message.reply_text(f"{text} saqlandi.\n\nJadval:\n{schedule}")
        else:
            await update.message.reply_text(f"{text} saqlandi. Bu guruh uchun jadval hali yo'q.")
        return

    await update.message.reply_text("Tugmadan foydalaning yoki guruh nomini yuboring. Masalan: 0124")


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
    return "SAMATI PRO bot ishlayapti"


@flask_app.get("/health")
def health():
    return jsonify({"ok": True})


@flask_app.get("/set-webhook")
def set_webhook():
    if not RENDER_EXTERNAL_URL:
        return jsonify({"ok": False, "error": "RENDER_EXTERNAL_URL yo'q"})
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


LOGIN_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Admin Login</title>
</head>
<body style="font-family:Arial;max-width:500px;margin:40px auto;">
  <h2>Admin Login</h2>
  <form method="post">
    <input type="password" name="password" placeholder="Parol" style="width:100%;padding:10px;">
    <br><br>
    <button type="submit" style="padding:10px 20px;">Kirish</button>
  </form>
  <p style="color:red;">{{ error }}</p>
</body>
</html>
"""

PANEL_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>SAMATI Admin Panel</title>
</head>
<body style="font-family:Arial;max-width:900px;margin:30px auto;">
  <h1>SAMATI Admin Panel</h1>
  <p><a href="/admin/logout">Chiqish</a></p>

  <h3>Statistika</h3>
  <ul>
    <li>Userlar: {{ stats.users }}</li>
    <li>Fakultetlar: {{ stats.faculties }}</li>
    <li>Guruhlar: {{ stats.groups }}</li>
    <li>Jadvallar: {{ stats.schedules }}</li>
    <li>E'lonlar: {{ stats.announcements }}</li>
  </ul>

  <hr>

  <h3>Fakultet qo'shish</h3>
  <form method="post" action="/admin/add_faculty">
    <input name="name" placeholder="Masalan: Iqtisod" style="width:100%;padding:8px;">
    <br><br>
    <button type="submit">Qo'shish</button>
  </form>

  <hr>

  <h3>Guruh qo'shish</h3>
  <form method="post" action="/admin/add_group">
    <input name="faculty_name" placeholder="Fakultet nomi" style="width:100%;padding:8px;">
    <br><br>
    <input name="group_name" placeholder="Masalan: 0124" style="width:100%;padding:8px;">
    <br><br>
    <button type="submit">Qo'shish</button>
  </form>

  <hr>

  <h3>Jadval saqlash</h3>
  <form method="post" action="/admin/save_schedule">
    <input name="group_name" placeholder="Guruh nomi" style="width:100%;padding:8px;">
    <br><br>
    <textarea name="schedule_text" rows="8" style="width:100%;" placeholder="Dushanba: ..."></textarea>
    <br><br>
    <button type="submit">Saqlash</button>
  </form>

  <hr>

  <h3>E'lon qo'shish</h3>
  <form method="post" action="/admin/add_announcement">
    <textarea name="text" rows="4" style="width:100%;" placeholder="E'lon matni"></textarea>
    <br><br>
    <button type="submit">Saqlash</button>
  </form>

  <hr>

  <h3>Broadcast</h3>
  <form method="post" action="/admin/broadcast">
    <textarea name="text" rows="4" style="width:100%;" placeholder="Barcha userlarga yuboriladigan xabar"></textarea>
    <br><br>
    <button type="submit">Yuborish</button>
  </form>

  <hr>

  <h3>Xabar</h3>
  <p style="color:green;">{{ message }}</p>
</body>
</html>
"""


def is_logged_in():
    return session.get("admin_logged_in") is True


@flask_app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_panel"))
        error = "Parol xato"
    return render_template_string(LOGIN_HTML, error=error)


@flask_app.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@flask_app.get("/admin")
def admin_panel():
    if not is_logged_in():
        return redirect(url_for("admin_login"))
    return render_template_string(PANEL_HTML, stats=get_stats(), message="")


@flask_app.post("/admin/add_faculty")
def admin_add_faculty():
    if not is_logged_in():
        return redirect(url_for("admin_login"))
    name = request.form.get("name", "").strip()
    if name:
        add_faculty(name)
    return render_template_string(PANEL_HTML, stats=get_stats(), message="Fakultet qo'shildi")


@flask_app.post("/admin/add_group")
def admin_add_group():
    if not is_logged_in():
        return redirect(url_for("admin_login"))
    faculty_name = request.form.get("faculty_name", "").strip()
    group_name = request.form.get("group_name", "").strip()
    if faculty_name and group_name:
        add_group(faculty_name, group_name)
    return render_template_string(PANEL_HTML, stats=get_stats(), message="Guruh qo'shildi")


@flask_app.post("/admin/save_schedule")
def admin_save_schedule():
    if not is_logged_in():
        return redirect(url_for("admin_login"))
    group_name = request.form.get("group_name", "").strip()
    schedule_text = request.form.get("schedule_text", "").strip()
    if group_name and schedule_text:
        save_schedule(group_name, schedule_text)
    return render_template_string(PANEL_HTML, stats=get_stats(), message="Jadval saqlandi")


@flask_app.post("/admin/add_announcement")
def admin_add_announcement():
    if not is_logged_in():
        return redirect(url_for("admin_login"))
    text = request.form.get("text", "").strip()
    if text:
        add_announcement(text)
    return render_template_string(PANEL_HTML, stats=get_stats(), message="E'lon saqlandi")


@flask_app.post("/admin/broadcast")
def admin_broadcast():
    if not is_logged_in():
        return redirect(url_for("admin_login"))
    text = request.form.get("text", "").strip()
    if text:
        user_ids = get_user_ids()
        sent = 0
        for user_id in user_ids:
            try:
                loop.run_until_complete(tg_app.bot.send_message(chat_id=user_id, text=text))
                sent += 1
            except Exception:
                pass
        return render_template_string(PANEL_HTML, stats=get_stats(), message=f"Broadcast yuborildi: {sent} ta user")
    return render_template_string(PANEL_HTML, stats=get_stats(), message="Matn bo'sh")


if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=10000)
