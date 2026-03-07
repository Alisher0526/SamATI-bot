import os
import sqlite3
import logging
from datetime import datetime

import telebot
from telebot import types
from flask import Flask, request

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")  # misol: 123456789,987654321
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")  # Render avtomatik beradi
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. Render Environment ga BOT_TOKEN qo'ying.")

ADMIN_IDS = set()
for x in ADMIN_IDS_RAW.split(","):
    x = x.strip()
    if x.isdigit():
        ADMIN_IDS.add(int(x))

DB_NAME = "samati_bot.db"
PDF_FOLDER = "pdfs"

os.makedirs(PDF_FOLDER, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# =========================
# DATABASE
# =========================
def db_connect():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

conn = db_connect()

def init_db():
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            joined_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS faculties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS groups_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(faculty_id, name),
            FOREIGN KEY (faculty_id) REFERENCES faculties(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            UNIQUE(faculty_id, group_id),
            FOREIGN KEY (faculty_id) REFERENCES faculties(id),
            FOREIGN KEY (group_id) REFERENCES groups_table(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()

    seed_data()

def seed_data():
    cur = conn.cursor()

    faculties = [
        "Iqtisod",
        "Agronomiya",
        "Veterinariya",
        "Zooinjeneriya",
        "Agrotexnologiya"
    ]

    for faculty in faculties:
        cur.execute("INSERT OR IGNORE INTO faculties(name) VALUES(?)", (faculty,))

    conn.commit()

    # Demo guruhlar
    demo_groups = {
        "Iqtisod": ["0124", "0224", "0324"],
        "Agronomiya": ["A-101", "A-102"],
        "Veterinariya": ["V-201", "V-202"],
        "Zooinjeneriya": ["Z-301"],
        "Agrotexnologiya": ["AT-401"]
    }

    for faculty_name, groups in demo_groups.items():
        faculty = cur.execute("SELECT id FROM faculties WHERE name=?", (faculty_name,)).fetchone()
        if faculty:
            for g in groups:
                cur.execute(
                    "INSERT OR IGNORE INTO groups_table(faculty_id, name) VALUES(?, ?)",
                    (faculty["id"], g)
                )

    conn.commit()

def add_user(message):
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users(user_id, full_name, username, joined_at)
        VALUES(?, ?, ?, ?)
    """, (
        message.from_user.id,
        f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip(),
        message.from_user.username or "",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# =========================
# HELPERS
# =========================
user_state = {}

def main_menu(is_user_admin=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("📚 Dars jadvali"),
        types.KeyboardButton("🔎 Guruh qidirish")
    )
    markup.add(
        types.KeyboardButton("ℹ️ Bot haqida"),
        types.KeyboardButton("☎️ Bog'lanish")
    )
    if is_user_admin:
        markup.add(types.KeyboardButton("🛠 Admin panel"))
    return markup

def admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("➕ Fakultet qo'shish"),
        types.KeyboardButton("➕ Guruh qo'shish")
    )
    markup.add(
        types.KeyboardButton("📤 Jadval yuklash"),
        types.KeyboardButton("🗑 Jadval o'chirish")
    )
    markup.add(
        types.KeyboardButton("📢 Reklama yuborish"),
        types.KeyboardButton("📊 Statistika")
    )
    markup.add(
        types.KeyboardButton("📋 Fakultetlar"),
        types.KeyboardButton("📋 Guruhlar")
    )
    markup.add(types.KeyboardButton("🏠 Bosh menu"))
    return markup

def back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("🏠 Bosh menu"))
    return markup

def get_faculties():
    return conn.cursor().execute("SELECT * FROM faculties ORDER BY name").fetchall()

def get_faculty_by_name(name):
    return conn.cursor().execute("SELECT * FROM faculties WHERE name=?", (name,)).fetchone()

def get_groups_by_faculty_id(faculty_id):
    return conn.cursor().execute(
        "SELECT * FROM groups_table WHERE faculty_id=? ORDER BY name",
        (faculty_id,)
    ).fetchall()

def get_group_by_name_and_faculty(faculty_id, group_name):
    return conn.cursor().execute(
        "SELECT * FROM groups_table WHERE faculty_id=? AND name=?",
        (faculty_id, group_name)
    ).fetchone()

def get_schedule(faculty_id, group_id):
    return conn.cursor().execute(
        "SELECT * FROM schedules WHERE faculty_id=? AND group_id=?",
        (faculty_id, group_id)
    ).fetchone()

def faculty_inline_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    for faculty in get_faculties():
        markup.add(types.InlineKeyboardButton(
            text=f"🎓 {faculty['name']}",
            callback_data=f"faculty_{faculty['id']}"
        ))
    return markup

def groups_inline_keyboard(faculty_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    groups = get_groups_by_faculty_id(faculty_id)
    for g in groups:
        markup.add(types.InlineKeyboardButton(
            text=f"👥 {g['name']}",
            callback_data=f"group_{faculty_id}_{g['id']}"
        ))
    markup.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="back_faculties"))
    return markup

# =========================
# START / COMMANDS
# =========================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    add_user(message)
    bot.send_message(
        message.chat.id,
        "Assalomu alaykum!\n\n"
        "<b>SAMATI Professional Bot</b> ga xush kelibsiz.\n"
        "Bu bot orqali siz fakultet va guruh bo'yicha dars jadvalini olishingiz mumkin.",
        reply_markup=main_menu(is_admin(message.from_user.id))
    )

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    add_user(message)
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "Siz admin emassiz.")
        return

    bot.send_message(
        message.chat.id,
        "🛠 <b>Admin panel</b>",
        reply_markup=admin_menu()
    )

@bot.message_handler(commands=['help'])
def help_cmd(message):
    add_user(message)
    txt = (
        "<b>Buyruqlar:</b>\n"
        "/start - botni ishga tushirish\n"
        "/help - yordam\n"
        "/admin - admin panel\n\n"
        "<b>Asosiy imkoniyatlar:</b>\n"
        "• Fakultet tanlash\n"
        "• Guruh tanlash\n"
        "• PDF jadval olish\n"
        "• Admin orqali jadval yuklash\n"
        "• Statistika\n"
        "• Reklama yuborish"
    )
    bot.send_message(message.chat.id, txt, reply_markup=main_menu(is_admin(message.from_user.id)))

# =========================
# TEXT MENU
# =========================
@bot.message_handler(content_types=['text'])
def text_handler(message):
    add_user(message)
    text = (message.text or "").strip()

    if text == "🏠 Bosh menu":
        user_state.pop(message.from_user.id, None)
        bot.send_message(
            message.chat.id,
            "Bosh menuga qaytdingiz.",
            reply_markup=main_menu(is_admin(message.from_user.id))
        )
        return

    if text == "📚 Dars jadvali":
        bot.send_message(
            message.chat.id,
            "Fakultetni tanlang:",
            reply_markup=types.ReplyKeyboardRemove()
        )
        bot.send_message(
            message.chat.id,
            "Quyidagilardan birini tanlang:",
            reply_markup=faculty_inline_keyboard()
        )
        return

    if text == "🔎 Guruh qidirish":
        user_state[message.from_user.id] = {"step": "search_group"}
        bot.send_message(
            message.chat.id,
            "Guruh nomini yuboring.\n\nMisol: <b>0124</b>",
            reply_markup=back_menu()
        )
        return

    if text == "ℹ️ Bot haqida":
        bot.send_message(
            message.chat.id,
            "Bu bot SAMATI talabalariga dars jadvalini tez topish uchun yaratildi.\n\n"
            "<b>Versiya:</b> PRO\n"
            "<b>Tizim:</b> Render + Webhook + SQLite",
            reply_markup=main_menu(is_admin(message.from_user.id))
        )
        return

    if text == "☎️ Bog'lanish":
        bot.send_message(
            message.chat.id,
            "Admin bilan bog'lanish uchun bot adminiga yozing.\n"
            "Agar xohlasangiz bu joyga username ham qo'shib beraman.",
            reply_markup=main_menu(is_admin(message.from_user.id))
        )
        return

    if text == "🛠 Admin panel":
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "Siz admin emassiz.")
            return
        bot.send_message(message.chat.id, "🛠 Admin panel", reply_markup=admin_menu())
        return

    # =========================
    # ADMIN ACTIONS
    # =========================
    if is_admin(message.from_user.id):
        if text == "➕ Fakultet qo'shish":
            user_state[message.from_user.id] = {"step": "add_faculty"}
            bot.send_message(
                message.chat.id,
                "Yangi fakultet nomini yuboring:",
                reply_markup=back_menu()
            )
            return

        if text == "➕ Guruh qo'shish":
            user_state[message.from_user.id] = {"step": "add_group_faculty"}
            bot.send_message(
                message.chat.id,
                "Avval fakultet nomini yuboring.\nMisol: <b>Iqtisod</b>",
                reply_markup=back_menu()
            )
            return

        if text == "📤 Jadval yuklash":
            user_state[message.from_user.id] = {"step": "upload_schedule_faculty"}
            bot.send_message(
                message.chat.id,
                "Fakultet nomini yuboring.\nMisol: <b>Iqtisod</b>",
                reply_markup=back_menu()
            )
            return

        if text == "🗑 Jadval o'chirish":
            user_state[message.from_user.id] = {"step": "delete_schedule_faculty"}
            bot.send_message(
                message.chat.id,
                "Qaysi fakultetdan o'chirasiz?\nMisol: <b>Iqtisod</b>",
                reply_markup=back_menu()
            )
            return

        if text == "📢 Reklama yuborish":
            user_state[message.from_user.id] = {"step": "broadcast_text"}
            bot.send_message(
                message.chat.id,
                "Barcha foydalanuvchilarga yuboriladigan xabarni yuboring:",
                reply_markup=back_menu()
            )
            return

        if text == "📊 Statistika":
            cur = conn.cursor()
            users_count = cur.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
            faculty_count = cur.execute("SELECT COUNT(*) as c FROM faculties").fetchone()["c"]
            groups_count = cur.execute("SELECT COUNT(*) as c FROM groups_table").fetchone()["c"]
            schedules_count = cur.execute("SELECT COUNT(*) as c FROM schedules").fetchone()["c"]

            bot.send_message(
                message.chat.id,
                f"📊 <b>Statistika</b>\n\n"
                f"👤 Foydalanuvchilar: <b>{users_count}</b>\n"
                f"🎓 Fakultetlar: <b>{faculty_count}</b>\n"
                f"👥 Guruhlar: <b>{groups_count}</b>\n"
                f"📄 Yuklangan jadvallar: <b>{schedules_count}</b>",
                reply_markup=admin_menu()
            )
            return

        if text == "📋 Fakultetlar":
            faculties = get_faculties()
            if not faculties:
                bot.send_message(message.chat.id, "Fakultetlar topilmadi.", reply_markup=admin_menu())
                return
            txt = "🎓 <b>Fakultetlar:</b>\n\n" + "\n".join([f"• {f['name']}" for f in faculties])
            bot.send_message(message.chat.id, txt, reply_markup=admin_menu())
            return

        if text == "📋 Guruhlar":
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT f.name as faculty_name, g.name as group_name
                FROM groups_table g
                JOIN faculties f ON f.id = g.faculty_id
                ORDER BY f.name, g.name
            """).fetchall()
            if not rows:
                bot.send_message(message.chat.id, "Guruhlar topilmadi.", reply_markup=admin_menu())
                return
            txt = "👥 <b>Guruhlar:</b>\n\n"
            txt += "\n".join([f"• {r['faculty_name']} — {r['group_name']}" for r in rows[:100]])
            if len(rows) > 100:
                txt += f"\n\nYana {len(rows) - 100} ta bor..."
            bot.send_message(message.chat.id, txt, reply_markup=admin_menu())
            return

    # =========================
    # STATE LOGIC
    # =========================
    state = user_state.get(message.from_user.id)

    if state:
        step = state.get("step")

        if step == "search_group":
            q = text.lower()
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT f.name as faculty_name, g.name as group_name, g.id as group_id, f.id as faculty_id
                FROM groups_table g
                JOIN faculties f ON f.id = g.faculty_id
                WHERE lower(g.name) LIKE ?
                ORDER BY f.name, g.name
            """, (f"%{q}%",)).fetchall()

            if not rows:
                bot.send_message(
                    message.chat.id,
                    "Bunday guruh topilmadi.",
                    reply_markup=main_menu(is_admin(message.from_user.id))
                )
                user_state.pop(message.from_user.id, None)
                return

            markup = types.InlineKeyboardMarkup(row_width=1)
            for r in rows[:20]:
                markup.add(types.InlineKeyboardButton(
                    text=f"{r['faculty_name']} — {r['group_name']}",
                    callback_data=f"group_{r['faculty_id']}_{r['group_id']}"
                ))

            bot.send_message(message.chat.id, "Topilgan guruhlar:", reply_markup=markup)
            user_state.pop(message.from_user.id, None)
            return

        if is_admin(message.from_user.id):
            cur = conn.cursor()

            if step == "add_faculty":
                try:
                    cur.execute("INSERT INTO faculties(name) VALUES(?)", (text,))
                    conn.commit()
                    bot.send_message(message.chat.id, f"✅ Fakultet qo'shildi: <b>{text}</b>", reply_markup=admin_menu())
                except sqlite3.IntegrityError:
                    bot.send_message(message.chat.id, "Bu fakultet allaqachon mavjud.", reply_markup=admin_menu())
                user_state.pop(message.from_user.id, None)
                return

            if step == "add_group_faculty":
                faculty = get_faculty_by_name(text)
                if not faculty:
                    bot.send_message(message.chat.id, "Bunday fakultet topilmadi.", reply_markup=admin_menu())
                    user_state.pop(message.from_user.id, None)
                    return
                user_state[message.from_user.id] = {
                    "step": "add_group_name",
                    "faculty_id": faculty["id"],
                    "faculty_name": faculty["name"]
                }
                bot.send_message(
                    message.chat.id,
                    f"<b>{faculty['name']}</b> uchun guruh nomini yuboring:",
                    reply_markup=back_menu()
                )
                return

            if step == "add_group_name":
                faculty_id = state["faculty_id"]
                try:
                    cur.execute(
                        "INSERT INTO groups_table(faculty_id, name) VALUES(?, ?)",
                        (faculty_id, text)
                    )
                    conn.commit()
                    bot.send_message(
                        message.chat.id,
                        f"✅ Guruh qo'shildi: <b>{state['faculty_name']} — {text}</b>",
                        reply_markup=admin_menu()
                    )
                except sqlite3.IntegrityError:
                    bot.send_message(message.chat.id, "Bu guruh allaqachon mavjud.", reply_markup=admin_menu())
                user_state.pop(message.from_user.id, None)
                return

            if step == "upload_schedule_faculty":
                faculty = get_faculty_by_name(text)
                if not faculty:
                    bot.send_message(message.chat.id, "Bunday fakultet topilmadi.", reply_markup=admin_menu())
                    user_state.pop(message.from_user.id, None)
                    return
                user_state[message.from_user.id] = {
                    "step": "upload_schedule_group",
                    "faculty_id": faculty["id"],
                    "faculty_name": faculty["name"]
                }
                bot.send_message(
                    message.chat.id,
                    f"<b>{faculty['name']}</b> uchun guruh nomini yuboring:",
                    reply_markup=back_menu()
                )
                return

            if step == "upload_schedule_group":
                group = get_group_by_name_and_faculty(state["faculty_id"], text)
                if not group:
                    bot.send_message(message.chat.id, "Bu fakultetda bunday guruh topilmadi.", reply_markup=admin_menu())
                    user_state.pop(message.from_user.id, None)
                    return
                user_state[message.from_user.id] = {
                    "step": "upload_schedule_file",
                    "faculty_id": state["faculty_id"],
                    "faculty_name": state["faculty_name"],
                    "group_id": group["id"],
                    "group_name": group["name"]
                }
                bot.send_message(
                    message.chat.id,
                    f"Endi PDF fayl yuboring.\n\n"
                    f"<b>{state['faculty_name']} — {group['name']}</b>",
                    reply_markup=back_menu()
                )
                return

            if step == "delete_schedule_faculty":
                faculty = get_faculty_by_name(text)
                if not faculty:
                    bot.send_message(message.chat.id, "Bunday fakultet topilmadi.", reply_markup=admin_menu())
                    user_state.pop(message.from_user.id, None)
                    return
                user_state[message.from_user.id] = {
                    "step": "delete_schedule_group",
  
