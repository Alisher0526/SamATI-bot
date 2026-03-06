import os
import time
import sqlite3
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# =========================
# SOZLAMALAR
# =========================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_IDS = set(
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
)

INSTITUTE_SITE = os.getenv("INSTITUTE_SITE", "https://samaguni.uz").strip()
SCHEDULE_URL = os.getenv("SCHEDULE_URL", "https://samati.edupage.org/timetable/").strip()

DB_PATH = "samati.db"


# =========================
# BAZA
# =========================
def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS faculties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS programs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        UNIQUE(faculty_id, name)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS groups_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        UNIQUE(program_id, name)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        faculty_id INTEGER,
        program_id INTEGER,
        group_id INTEGER,
        updated_at INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scope TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )
    """)

    con.commit()
    con.close()


def seed_demo_data():
    con = db()
    cur = con.cursor()

    # Fakultetlar
    faculties = ["Iqtisod", "Agrotexnologiya", "Veterinariya", "IT"]
    for f in faculties:
        cur.execute("INSERT OR IGNORE INTO faculties(name) VALUES(?)", (f,))

    cur.execute("SELECT id, name FROM faculties")
    fac_map = {name: fid for fid, name in cur.fetchall()}

    # Yo'nalishlar
    programs = [
        (fac_map["Iqtisod"], "Iqtisodiyot"),
        (fac_map["Iqtisod"], "Buxgalteriya"),
        (fac_map["Agrotexnologiya"], "Agronomiya"),
        (fac_map["Veterinariya"], "Veterinariya ishi"),
        (fac_map["IT"], "Axborot tizimlari"),
    ]
    for faculty_id, name in programs:
        cur.execute(
            "INSERT OR IGNORE INTO programs(faculty_id, name) VALUES(?, ?)",
            (faculty_id, name)
        )

    # Guruhlar
    cur.execute("SELECT id, name FROM programs")
    rows = cur.fetchall()

    for pid, pname in rows:
        if pname == "Iqtisodiyot":
            demo_groups = ["0124", "0111"]
        else:
            demo_groups = ["0101"]

        for g in demo_groups:
            cur.execute(
                "INSERT OR IGNORE INTO groups_table(program_id, name) VALUES(?, ?)",
                (pid, g)
            )

    now = int(time.time())

    # Demo e'lon
    cur.execute("""
    INSERT INTO announcements(scope, title, body, created_at)
    SELECT ?, ?, ?, ?
    WHERE NOT EXISTS (SELECT 1 FROM announcements WHERE title = ?)
    """, (
        "all",
        "SamATI bot ishga tushdi",
        "Bot orqali profil, e'lonlar, shablonlar va jadval linklarini ko‘rishingiz mumkin.",
        now,
        "SamATI bot ishga tushdi"
    ))

    # Demo shablon
    cur.execute("""
    INSERT INTO templates(title, body, created_at)
    SELECT ?, ?, ?
    WHERE NOT EXISTS (SELECT 1 FROM templates WHERE title = ?)
    """, (
        "Ariza namunasi",
        "Rektorga ariza\n\nF.I.O: __________\nGuruh: __________\nSabab: __________",
        now,
        "Ariza namunasi"
    ))

    con.commit()
    con.close()


# =========================
# YORDAMCHI FUNKSIYALAR
# =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def upsert_user(chat_id: int, faculty_id=None, program_id=None, group_id=None):
    con = db()
    cur = con.cursor()
    now = int(time.time())

    cur.execute("SELECT chat_id FROM users WHERE chat_id=?", (chat_id,))
    exists = cur.fetchone()

    if exists:
        cur.execute("""
        UPDATE users
        SET faculty_id = COALESCE(?, faculty_id),
            program_id = COALESCE(?, program_id),
            group_id   = COALESCE(?, group_id),
            updated_at = ?
        WHERE chat_id = ?
        """, (faculty_id, program_id, group_id, now, chat_id))
    else:
        cur.execute("""
        INSERT INTO users(chat_id, faculty_id, program_id, group_id, updated_at)
        VALUES(?, ?, ?, ?, ?)
        """, (chat_id, faculty_id, program_id, group_id, now))

    con.commit()
    con.close()


def get_user_profile(chat_id: int):
    con = db()
    cur = con.cursor()

    cur.execute("""
    SELECT
        u.faculty_id,
        u.program_id,
        u.group_id,
        f.name,
        p.name,
        g.name
    FROM users u
    LEFT JOIN faculties f ON f.id = u.faculty_id
    LEFT JOIN programs p ON p.id = u.program_id
    LEFT JOIN groups_table g ON g.id = u.group_id
    WHERE u.chat_id = ?
    """, (chat_id,))

    row = cur.fetchone()
    con.close()
    return row


def parse_pipe_args(text: str):
    parts = text.split(" ", 1)
    if len(parts) < 2:
        return []
    return [x.strip() for x in parts[1].split("|")]


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Profil", callback_data="profile:fac")],
        [InlineKeyboardButton("📅 Jadval", callback_data="menu:schedule")],
        [InlineKeyboardButton("📢 E'lonlar", callback_data="menu:ann")],
        [InlineKeyboardButton("📄 Shablonlar", callback_data="menu:tpl")],
        [InlineKeyboardButton("🌐 Sayt", callback_data="menu:site")],
        [InlineKeyboardButton("ℹ️ Yordam", callback_data="menu:help")],
    ])


def require_group(profile):
    if not profile or not profile[2]:
        return False, "⚠️ Avval profil tanlang: Fakultet → Yo‘nalish → Guruh."
    return True, ""


# =========================
# FOYDALANUVCHI BUYRUQLARI
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    upsert_user(chat_id)

    text = (
        "👋 Assalomu alaykum!\n\n"
        "*SamATI bot* ga xush kelibsiz.\n\n"
        "Bu bot orqali siz:\n"
        "• Profil tanlaysiz\n"
        "• Jadval linkini ko‘rasiz\n"
        "• E'lonlarni o‘qiysiz\n"
        "• Hujjat shablonlarini olasiz\n\n"
        "Boshlash uchun *📌 Profil* ni bosing."
    )
    await update.message.reply_text(text, reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ *Yordam*\n\n"
        "/start — botni boshlash\n"
        "/myid — Telegram ID ko‘rish\n"
        "/admin_help — admin buyruqlari\n\n"
        "Asosiy ishlash tartibi:\n"
        "1. Profil tanlang\n"
        "2. Jadval yoki e'lonlarni oching"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Sizning Telegram ID: `{update.effective_user.id}`", parse_mode=ParseMode.MARKDOWN)


# =========================
# INLINE MENU
# =========================
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu:help":
        text = (
            "ℹ️ *Yordam*\n\n"
            "• Profil — fakultet, yo‘nalish, guruh tanlash\n"
            "• Jadval — rasmiy jadval sahifasi\n"
            "• E'lonlar — institut e'lonlari\n"
            "• Shablonlar — ariza namunasi\n"
            "• Sayt — rasmiy sayt linki"
        )
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "menu:site":
        text = (
            f"🌐 Rasmiy sayt:\n{INSTITUTE_SITE}\n\n"
            f"📅 Jadval:\n{SCHEDULE_URL}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")]
        ])
        await query.edit_message_text(text, reply_markup=kb)
        return

    if data == "menu:schedule":
        profile = get_user_profile(query.message.chat_id)
        ok, msg = require_group(profile)
        if not ok:
            await query.edit_message_text(msg, reply_markup=main_menu())
            return

        group_name = profile[5]
        text = (
            f"📅 Guruhingiz: *{group_name}*\n\n"
            f"Rasmiy dars jadvali:\n{SCHEDULE_URL}\n\n"
            "Hozircha eng barqaror usul sifatida jadval linki berilmoqda."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")]
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "menu:ann":
        profile = get_user_profile(query.message.chat_id)
        scope = "all"
        if profile and profile[0]:
            scope = f"faculty:{profile[0]}"

        con = db()
        cur = con.cursor()
        cur.execute("""
        SELECT title, body, scope, created_at
        FROM announcements
        WHERE scope='all' OR scope=?
        ORDER BY id DESC
        LIMIT 10
        """, (scope,))
        rows = cur.fetchall()
        con.close()

        if not rows:
            text = "Hozircha e'lonlar yo‘q."
        else:
            parts = ["📢 *E'lonlar:*\n"]
            for title, body, sc, created_at in rows:
                dt = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M")
                where = "Institut" if sc == "all" else "Fakultet"
                parts.append(f"• *{title}* ({where}, {dt})\n{body}\n")
            text = "\n".join(parts)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")]
        ])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "menu:tpl":
        con = db()
        cur = con.cursor()
        cur.execute("SELECT id, title FROM templates ORDER BY id DESC LIMIT 20")
        rows = cur.fetchall()
        con.close()

        if not rows:
            await query.edit_message_text("Hozircha shablonlar yo‘q.", reply_markup=main_menu())
            return

        buttons = [[InlineKeyboardButton(f"📄 {title}", callback_data=f"tpl:{tid}")]
                   for tid, title in rows]
        buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")])

        await query.edit_message_text("Shablonni tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("tpl:"):
        tid = int(data.split(":")[1])
        con = db()
        cur = con.cursor()
        cur.execute("SELECT title, body FROM templates WHERE id=?", (tid,))
        row = cur.fetchone()
        con.close()

        if not row:
            await query.edit_message_text("Topilmadi.", reply_markup=main_menu())
            return

        title, body = row
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="menu:tpl")],
            [InlineKeyboardButton("🏠 Bosh menyu", callback_data="back:main")]
        ])
        await query.edit_message_text(f"📄 *{title}*\n\n{body}", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "back:main":
        await query.edit_message_text("🏠 Bosh menyu:", reply_markup=main_menu())
        return


# =========================
# PROFIL TANLASH
# =========================
async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "profile:fac":
        con = db()
        cur = con.cursor()
        cur.execute("SELECT id, name FROM faculties ORDER BY name ASC")
        rows = cur.fetchall()
        con.close()

        buttons = [[InlineKeyboardButton(f"🏛 {name}", callback_data=f"profile:fac:{fid}")]
                   for fid, name in rows]
        buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")])

        await query.edit_message_text("Fakultetni tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("profile:fac:"):
        fid = int(data.split(":")[2])
        upsert_user(query.message.chat_id, faculty_id=fid, program_id=None, group_id=None)

        con = db()
        cur = con.cursor()
        cur.execute("SELECT id, name FROM programs WHERE faculty_id=? ORDER BY name ASC", (fid,))
        rows = cur.fetchall()
        con.close()

        buttons = [[InlineKeyboardButton(f"📚 {name}", callback_data=f"profile:prog:{pid}")]
                   for pid, name in rows]
        buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="profile:fac")])

        await query.edit_message_text("Yo‘nalishni tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("profile:prog:"):
        pid = int(data.split(":")[2])
        upsert_user(query.message.chat_id, program_id=pid, group_id=None)

        con = db()
        cur = con.cursor()
        cur.execute("SELECT id, name FROM groups_table WHERE program_id=? ORDER BY name ASC", (pid,))
        rows = cur.fetchall()
        con.close()

        buttons = [[InlineKeyboardButton(f"👥 {name}", callback_data=f"profile:grp:{gid}")]
                   for gid, name in rows]
        buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="profile:fac")])

        await query.edit_message_text("Guruhni tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("profile:grp:"):
        gid = int(data.split(":")[2])
        upsert_user(query.message.chat_id, group_id=gid)

        profile = get_user_profile(query.message.chat_id)
        text = (
            "✅ Profil saqlandi!\n\n"
            f"🏛 Fakultet: *{profile[3] or '-'}*\n"
            f"📚 Yo‘nalish: *{profile[4] or '-'}*\n"
            f"👥 Guruh: *{profile[5] or '-'}*"
        )
        await query.edit_message_text(text, reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN)
        return


# =========================
# ADMIN BUYRUQLARI
# =========================
async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return

    text = (
        "🛠 *Admin buyruqlari*\n\n"
        "/admin_list\n"
        "/admin_add_faculty FakultetNomi\n"
        "/admin_add_program faculty_id|Yo‘nalish\n"
        "/admin_add_group program_id|Guruh\n"
        "/admin_announce all|Sarlavha|Matn\n"
        "/admin_announce faculty:1|Sarlavha|Matn\n"
        "/admin_template Sarlavha|Matn"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return

    con = db()
    cur = con.cursor()

    cur.execute("SELECT id, name FROM faculties ORDER BY id")
    faculties = cur.fetchall()

    cur.execute("SELECT id, faculty_id, name FROM programs ORDER BY id")
    programs = cur.fetchall()

    cur.execute("SELECT id, program_id, name FROM groups_table ORDER BY id LIMIT 100")
    groups = cur.fetchall()

    con.close()

    parts = ["📚 *Ro‘yxatlar*\n"]

    parts.append("*Fakultetlar:*")
    for fid, name in faculties:
        parts.append(f"• {fid}: {name}")

    parts.append("\n*Yo‘nalishlar:*")
    for pid, fid, name in programs:
        parts.append(f"• {pid}: (fac {fid}) {name}")

    parts.append("\n*Guruhlar:*")
    for gid, pid, name in groups:
        parts.append(f"• {gid}: (prog {pid}) {name}")

    await update.message.reply_text("\n".join(parts), parse_mode=ParseMode.MARKDOWN)


async def admin_add_faculty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return

    if " " not in update.message.text:
        await update.message.reply_text("Misol: /admin_add_faculty Iqtisod")
        return

    name = update.message.text.split(" ", 1)[1].strip()

    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO faculties(name) VALUES(?)", (name,))
    con.commit()
    con.close()

    await update.message.reply_text("✅ Fakultet qo‘shildi.")


async def admin_add_program(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return

    args = parse_pipe_args(update.message.text)
    if len(args) != 2 or not args[0].isdigit():
        await update.message.reply_text("Misol: /admin_add_program 1|Iqtisodiyot")
        return

    faculty_id = int(args[0])
    name = args[1]

    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO programs(faculty_id, name) VALUES(?, ?)", (faculty_id, name))
    con.commit()
    con.close()

    await update.message.reply_text("✅ Yo‘nalish qo‘shildi.")


async def admin_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return

    args = parse_pipe_args(update.message.text)
    if len(args) != 2 or not args[0].isdigit():
        await update.message.reply_text("Misol: /admin_add_group 2|0124")
        return

    program_id = int(args[0])
    name = args[1]

    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO groups_table(program_id, name) VALUES(?, ?)", (program_id, name))
    con.commit()
    con.close()

    await update.message.reply_text("✅ Guruh qo‘shildi.")


async def admin_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return

    args = parse_pipe_args(update.message.text)
    if len(args) < 3:
        await update.message.reply_text("Misol: /admin_announce all|Sarlavha|Matn")
        return

    scope = args[0]
    title = args[1]
    body = "|".join(args[2:])

    con = db()
    cur = con.cursor()
    cur.execute("""
    INSERT INTO announcements(scope, title, body, created_at)
    VALUES(?, ?, ?, ?)
    """, (scope, title, body, int(time.time())))
    con.commit()
    con.close()

    await update.message.reply_text("✅ E'lon qo‘shildi.")


async def admin_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return

    args = parse_pipe_args(update.message.text)
    if len(args) < 2:
        await update.message.reply_text("Misol: /admin_template Ariza|Matn")
        return

    title = args[0]
    body = "|".join(args[1:])

    con = db()
    cur = con.cursor()
    cur.execute("""
    INSERT INTO templates(title, body, created_at)
    VALUES(?, ?, ?)
    """, (title, body, int(time.time())))
    con.commit()
    con.close()

    await update.message.reply_text("✅ Shablon qo‘shildi.")


# =========================
# MAIN
# =========================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN topilmadi.")

    init_db()
    seed_demo_data()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myid", myid))

    app.add_handler(CommandHandler("admin_help", admin_help))
    app.add_handler(CommandHandler("admin_list", admin_list))
    app.add_handler(CommandHandler("admin_add_faculty", admin_add_faculty))
    app.add_handler(CommandHandler("admin_add_program", admin_add_program))
    app.add_handler(CommandHandler("admin_add_group", admin_add_group))
    app.add_handler(CommandHandler("admin_announce", admin_announce))
    app.add_handler(CommandHandler("admin_template", admin_template))

    app.add_handler(CallbackQueryHandler(profile_callback, pattern=r"^profile:"))
    app.add_handler(CallbackQueryHandler(menu_callback))

    print("SamATI bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
