import os
import re
import json
import time
import sqlite3
import logging
from datetime import datetime, timedelta

import requests
import feedparser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_IDS = set(int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit())

# Siz bergan manbalar
EDUPAGE_BASE = os.getenv("EDUPAGE_BASE", "https://samati.edupage.org").strip().rstrip("/")
INSTITUTE_SITE = os.getenv("INSTITUTE_SITE", "https://samaguni.uz").strip().rstrip("/")

# Agar saytda RSS bo‘lsa shu yerga qo‘ying (bo‘lmasa bo‘sh qolishi mumkin)
NEWS_RSS_URL = os.getenv("NEWS_RSS_URL", "").strip()

DB_PATH = "samati.db"

DAYS_UZ = {1: "Dushanba", 2: "Seshanba", 3: "Chorshanba", 4: "Payshanba", 5: "Juma", 6: "Shanba", 7: "Yakshanba"}


# -------------------- DB --------------------
def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS faculties (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS programs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      faculty_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      UNIQUE(faculty_id, name)
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS groups (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      program_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      UNIQUE(program_id, name)
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
      chat_id INTEGER PRIMARY KEY,
      faculty_id INTEGER,
      program_id INTEGER,
      group_id INTEGER,
      updated_at INTEGER
    )""")

    # jadval cache: group_name -> json
    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedule_cache (
      group_name TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      updated_at INTEGER NOT NULL
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      scope TEXT NOT NULL,          -- all / faculty:<id>
      title TEXT NOT NULL,
      body TEXT NOT NULL,
      created_at INTEGER NOT NULL
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS templates (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      body TEXT NOT NULL,
      created_at INTEGER NOT NULL
    )""")

    con.commit()
    con.close()


def seed_demo():
    """Boshlang'ich ma'lumotlar (xohlasangiz keyin admin bilan o'zgartirasiz)."""
    con = db()
    cur = con.cursor()

    for f in ["Iqtisod", "Agrotexnologiya", "Veterinariya", "IT"]:
        cur.execute("INSERT OR IGNORE INTO faculties(name) VALUES(?)", (f,))

    cur.execute("SELECT id, name FROM faculties")
    fac = {name: fid for fid, name in cur.fetchall()}

    demo_programs = [
        (fac["Iqtisod"], "Iqtisodiyot"),
        (fac["Iqtisod"], "Buxgalteriya"),
        (fac["Agrotexnologiya"], "Agronomiya"),
        (fac["IT"], "Axborot tizimlari"),
    ]
    for fid, name in demo_programs:
        cur.execute("INSERT OR IGNORE INTO programs(faculty_id, name) VALUES(?,?)", (fid, name))

    # Demo groups
    cur.execute("SELECT id, name FROM programs")
    prows = cur.fetchall()
    for pid, pname in prows:
        for g in (["0124", "0111"] if "Iqtisod" in pname else ["0101"]):
            cur.execute("INSERT OR IGNORE INTO groups(program_id, name) VALUES(?,?)", (pid, g))

    # Demo announcement + template
    now = int(time.time())
    cur.execute("""
    INSERT INTO announcements(scope, title, body, created_at)
    VALUES(?,?,?,?)
    """, ("all", "SamATI bot", "Bot ishga tushdi. Jadval va e'lonlarni shu yerdan olasiz.", now))

    cur.execute("""
    INSERT INTO templates(title, body, created_at)
    VALUES(?,?,?)
    """, ("Ariza namunasi", "Rektorga ariza...\nF.I.O: ______\nGuruh: ______\nSabab: ______", now))

    con.commit()
    con.close()


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def upsert_user(chat_id: int, faculty_id=None, program_id=None, group_id=None):
    con = db()
    cur = con.cursor()
    now = int(time.time())
    cur.execute("SELECT chat_id FROM users WHERE chat_id=?", (chat_id,))
    if cur.fetchone():
        cur.execute("""
        UPDATE users
        SET faculty_id=COALESCE(?, faculty_id),
            program_id=COALESCE(?, program_id),
            group_id=COALESCE(?, group_id),
            updated_at=?
        WHERE chat_id=?
        """, (faculty_id, program_id, group_id, now, chat_id))
    else:
        cur.execute("""
        INSERT INTO users(chat_id, faculty_id, program_id, group_id, updated_at)
        VALUES(?,?,?,?,?)
        """, (chat_id, faculty_id, program_id, group_id, now))
    con.commit()
    con.close()


def get_user_profile(chat_id: int):
    con = db()
    cur = con.cursor()
    cur.execute("""
    SELECT u.faculty_id, u.program_id, u.group_id,
           f.name, p.name, g.name
    FROM users u
    LEFT JOIN faculties f ON f.id=u.faculty_id
    LEFT JOIN programs p ON p.id=u.program_id
    LEFT JOIN groups g ON g.id=u.group_id
    WHERE u.chat_id=?
    """, (chat_id,))
    row = cur.fetchone()
    con.close()
    return row  # (fid,pid,gid,fname,pname,gname)


# -------------------- UI --------------------
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📌 Profil", callback_data="profile:fac")],
        [InlineKeyboardButton("📅 Jadval", callback_data="menu:schedule")],
        [InlineKeyboardButton("📢 E'lonlar", callback_data="menu:ann")],
        [InlineKeyboardButton("📄 Shablonlar", callback_data="menu:tpl")],
        [InlineKeyboardButton("🌐 Sayt", callback_data="menu:site"),
         InlineKeyboardButton("ℹ️ Yordam", callback_data="menu:help")],
    ])


def need_group(profile):
    if not profile or not profile[2]:
        return False, "⚠️ Avval *Profil* tanlang (fakultet → yo‘nalish → guruh)."
    return True, ""


# -------------------- EduPage (best-effort) --------------------
def edupage_try_get_data() -> dict | None:
    """
    EduPage public timetable data olishga urinadi.
    EduPage har xil bo'lishi mumkin, shuning uchun xato qilsa None qaytaramiz.
    """
    try:
        url = f"{EDUPAGE_BASE}/timetable/server/regulartt.js"
        payload = {"__func": "regularttGetData", "__args": [None]}
        r = requests.post(url, json=payload, timeout=25)
        r.raise_for_status()
        j = r.json()
        return j.get("r", j)
    except Exception as e:
        logging.warning("EduPage data olishda muammo: %s", e)
        return None


def cache_set_group(group_name: str, payload: dict):
    con = db()
    cur = con.cursor()
    cur.execute("""
    INSERT INTO schedule_cache(group_name, payload, updated_at)
    VALUES(?,?,?)
    ON CONFLICT(group_name) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at
    """, (group_name, json.dumps(payload, ensure_ascii=False), int(time.time())))
    con.commit()
    con.close()


def cache_get_group(group_name: str):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT payload, updated_at FROM schedule_cache WHERE group_name=?", (group_name,))
    row = cur.fetchone()
    con.close()
    if not row:
        return None, None
    return json.loads(row[0]), row[1]


def format_schedule_fallback(group_name: str, day: int) -> str:
    return (
        f"📅 *{DAYS_UZ.get(day,'Kun')}* — Guruh: *{group_name}*\n\n"
        "Hozircha EduPage’dan jadvalni avtomatik ajratib olish sozlanmadi.\n"
        f"🔗 Jadval: {EDUPAGE_BASE}/timetable/\n\n"
        "✅ Keyingi bosqichda men sizning EduPage sahifangizga moslab "
        "guruh bo‘yicha jadvalni bot ichida to‘liq chiqaradigan qilib qo‘yaman."
    )


# -------------------- RSS News (best-effort) --------------------
def fetch_news_rss(limit=5):
    if not NEWS_RSS_URL:
        return []
    try:
        feed = feedparser.parse(NEWS_RSS_URL)
        items = []
        for e in feed.entries[:limit]:
            title = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()
            published = getattr(e, "published", "") or getattr(e, "updated", "")
            items.append((title, link, published))
        return items
    except Exception as e:
        logging.warning("RSS olishda muammo: %s", e)
        return []


# -------------------- Handlers --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_chat.id)
    txt = (
        "👋 Assalomu alaykum!\n\n"
        "*SamATI bot*:\n"
        "• Profil tanlang\n"
        "• Jadval (bugun/ertaga/hafta)\n"
        "• E'lonlar, shablonlar\n\n"
        "Boshlash uchun: **📌 Profil**"
    )
    await update.message.reply_text(txt, reply_markup=kb_main(), parse_mode=ParseMode.MARKDOWN)


async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "menu:help":
        txt = (
            "ℹ️ *Yordam*\n\n"
            "1) 📌 Profil → fakultet/yo‘nalish/guruh tanlang\n"
            "2) 📅 Jadval → bugun/ertaga/haftalik\n"
            "3) 📢 E'lonlar → institut yoki fakultet\n"
            "4) 📄 Shablonlar → ariza va boshqalar\n\n"
            "Admin: /admin_help"
        )
        await q.edit_message_text(txt, reply_markup=kb_main(), parse_mode=ParseMode.MARKDOWN)
        return

    if data == "menu:site":
        await q.edit_message_text(
            f"🌐 Rasmiy sayt: {INSTITUTE_SITE}\n📅 Jadval: {EDUPAGE_BASE}/timetable/",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")]]),
        )
        return

    if data == "menu:schedule":
        profile = get_user_profile(q.message.chat_id)
        ok, hint = need_group(profile)
        if not ok:
            await q.edit_message_text(hint, reply_markup=kb_main(), parse_mode=ParseMode.MARKDOWN)
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Bugun", callback_data="schedule:today"),
             InlineKeyboardButton("📅 Ertaga", callback_data="schedule:tomorrow")],
            [InlineKeyboardButton("🗓 Haftalik", callback_data="schedule:week")],
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")]
        ])
        await q.edit_message_text("Jadvalni tanlang:", reply_markup=kb)
        return

    if data == "menu:ann":
        profile = get_user_profile(q.message.chat_id)
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
        LIMIT 8
        """, (scope,))
        rows = cur.fetchall()
        con.close()

        # RSS ham bo'lsa, yuqoriga qo'shib ko'rsatamiz
        rss_items = fetch_news_rss(limit=5)

        parts = ["📢 *E'lonlar*:\n"]
        if rss_items:
            parts.append("🗞 *Saytdagi yangiliklar (RSS):*")
            for t, link, pub in rss_items:
                line = f"• {t}"
                if pub:
                    line += f" ({pub})"
                if link:
                    line += f"\n{link}"
                parts.append(line)
            parts.append("")

        if rows:
            parts.append("📌 *Bot ichidagi e'lonlar:*")
            for title, body, sc, created in rows:
                who = "Institut" if sc == "all" else "Fakultet"
                dt = datetime.fromtimestamp(created).strftime("%Y-%m-%d %H:%M")
                parts.append(f"• *{title}* ({who}, {dt})\n{body}\n")
        else:
            parts.append("Hozircha bot ichida e'lonlar yo‘q.")

        kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")]])
        await q.edit_message_text("\n".join(parts), reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    if data == "menu:tpl":
        con = db()
        cur = con.cursor()
        cur.execute("SELECT id, title FROM templates ORDER BY id DESC LIMIT 12")
        rows = cur.fetchall()
        con.close()

        if not rows:
            await q.edit_message_text("Hozircha shablonlar yo‘q.", reply_markup=kb_main())
            return

        buttons = [[InlineKeyboardButton(f"📄 {title}", callback_data=f"tpl:{tid}")]
                   for tid, title in rows]
        buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")])
        await q.edit_message_text("Shablonni tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("tpl:"):
        tid = int(data.split(":")[1])
        con = db()
        cur = con.cursor()
        cur.execute("SELECT title, body FROM templates WHERE id=?", (tid,))
        row = cur.fetchone()
        con.close()
        if not row:
            await q.edit_message_text("Topilmadi.", reply_markup=kb_main())
            return
        title, body = row
        await q.edit_message_text(
            f"📄 *{title}*\n\n{body}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Orqaga", callback_data="menu:tpl")],
                [InlineKeyboardButton("🏠 Bosh menyu", callback_data="back:main")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data == "back:main":
        await q.edit_message_text("🏠 Bosh menyu:", reply_markup=kb_main())
        return


async def schedule_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    profile = get_user_profile(q.message.chat_id)
    ok, hint = need_group(profile)
    if not ok:
        await q.edit_message_text(hint, reply_markup=kb_main(), parse_mode=ParseMode.MARKDOWN)
        return

    group_name = profile[5]
    wd = datetime.now().isoweekday()

    if q.data == "schedule:today":
        day = wd
    elif q.data == "schedule:tomorrow":
        day = 1 if wd == 7 else wd + 1
    else:
        day = wd

    # Hozircha best-effort: agar cache bo'lsa ishlatamiz, bo'lmasa fallback
    cached, updated_at = cache_get_group(group_name)
    if cached:
        # Sizning EduPage mapping to'liq mos bo'lmaguncha cache faqat "bor"ligini ko'rsatadi
        dt = datetime.fromtimestamp(updated_at).strftime("%Y-%m-%d %H:%M")
        txt = (
            f"📅 *{DAYS_UZ.get(day,'Kun')}* — Guruh: *{group_name}*\n\n"
            f"✅ Jadval cache bor (yangilangan: {dt}).\n"
            f"🔗 Jadval: {EDUPAGE_BASE}/timetable/\n\n"
            "📌 Hozircha jadvalni bot ichida to‘liq chiqarish uchun EduPage sahifasidagi "
            "guruh/lesson mapping’ni sizning saytingizga moslab qo‘yish kerak."
        )
    else:
        txt = format_schedule_fallback(group_name, day)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Sync", callback_data="schedule:sync")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="menu:schedule")],
        [InlineKeyboardButton("🏠 Bosh menyu", callback_data="back:main")]
    ])
    await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def schedule_sync_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    profile = get_user_profile(q.message.chat_id)
    ok, hint = need_group(profile)
    if not ok:
        await q.edit_message_text(hint, reply_markup=kb_main(), parse_mode=ParseMode.MARKDOWN)
        return

    group_name = profile[5]
    raw = edupage_try_get_data()
    if not raw:
        await q.edit_message_text(
            "❌ EduPage’dan ma’lumot olinmadi.\n"
            f"🔗 Jadval: {EDUPAGE_BASE}/timetable/",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="menu:schedule")]])
        )
        return

    cache_set_group(group_name, raw)
    await q.edit_message_text(
        "✅ Sync bo‘ldi (cache yangilandi).\n"
        "Hozircha jadvalni to‘liq chiqarish uchun mapping’ni moslab qo‘yamiz.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Orqaga", callback_data="menu:schedule")]])
    )


# -------------------- Profile Flow --------------------
async def profile_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "profile:fac":
        con = db()
        cur = con.cursor()
        cur.execute("SELECT id, name FROM faculties ORDER BY name")
        rows = cur.fetchall()
        con.close()
        buttons = [[InlineKeyboardButton(f"🏛 {name}", callback_data=f"profile:fac:{fid}")]
                   for fid, name in rows]
        buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="back:main")])
        await q.edit_message_text("Fakultetni tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("profile:fac:"):
        fid = int(data.split(":")[2])
        upsert_user(q.message.chat_id, faculty_id=fid, program_id=None, group_id=None)

        con = db()
        cur = con.cursor()
        cur.execute("SELECT id, name FROM programs WHERE faculty_id=? ORDER BY name", (fid,))
        rows = cur.fetchall()
        con.close()

        buttons = [[InlineKeyboardButton(f"📚 {name}", callback_data=f"profile:prog:{pid}")]
                   for pid, name in rows]
        buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="profile:fac")])
        await q.edit_message_text("Yo‘nalishni tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("profile:prog:"):
        pid = int(data.split(":")[2])
        upsert_user(q.message.chat_id, program_id=pid, group_id=None)

        con = db()
        cur = con.cursor()
        cur.execute("SELECT id, name FROM groups WHERE program_id=? ORDER BY name", (pid,))
        rows = cur.fetchall()
        con.close()

        buttons = [[InlineKeyboardButton(f"👥 {name}", callback_data=f"profile:grp:{gid}")]
                   for gid, name in rows]
        buttons.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="profile:fac")])
        await q.edit_message_text("Guruhni tanlang:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("profile:grp:"):
        gid = int(data.split(":")[2])
        upsert_user(q.message.chat_id, group_id=gid)
        prof = get_user_profile(q.message.chat_id)
        txt = (
            "✅ Profil saqlandi!\n\n"
            f"🏛 Fakultet: *{prof[3] or '-'}*\n"
            f"📚 Yo‘nalish: *{prof[4] or '-'}*\n"
            f"👥 Guruh: *{prof[5] or '-'}*\n"
        )
        await q.edit_message_text(txt, reply_markup=kb_main(), parse_mode=ParseMode.MARKDOWN)


# -------------------- Admin Commands --------------------
def parse_pipe(text: str):
    parts = text.split(" ", 1)
    if len(parts) < 2:
        return []
    payload = parts[1].strip()
    if not payload:
        return []
    return [x.strip() for x in payload.split("|")]


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return
    msg = (
        "🛠 *Admin buyruqlari*\n\n"
        "• /admin_list\n"
        "• /admin_add_faculty FakultetNomi\n"
        "• /admin_add_program faculty_id|Yo‘nalishNomi\n"
        "• /admin_add_group program_id|GuruhNomi\n\n"
        "E'lon:\n"
        "• /admin_announce all|Sarlavha|Matn\n"
        "• /admin_announce faculty:3|Sarlavha|Matn\n\n"
        "Shablon:\n"
        "• /admin_template Sarlavha|Matn\n\n"
        "Sozlamalar (Railway Variables):\n"
        "• ADMIN_IDS, EDUPAGE_BASE, INSTITUTE_SITE, NEWS_RSS_URL\n"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return
    con = db()
    cur = con.cursor()
    cur.execute("SELECT id, name FROM faculties ORDER BY id")
    fac = cur.fetchall()
    cur.execute("SELECT id, faculty_id, name FROM programs ORDER BY id")
    prog = cur.fetchall()
    cur.execute("SELECT g.id, g.program_id, g.name FROM groups g ORDER BY g.id LIMIT 80")
    gr = cur.fetchall()
    con.close()

    lines = ["📚 *Ro‘yxatlar*"]
    lines.append("\n*Fakultetlar:*")
    for fid, name in fac:
        lines.append(f"• {fid}: {name}")
    lines.append("\n*Yo‘nalishlar:*")
    for pid, fid, name in prog:
        lines.append(f"• {pid}: (fac {fid}) {name}")
    lines.append("\n*Guruhlar (1–80):*")
    for gid, pid, name in gr:
        lines.append(f"• {gid}: (prog {pid}) {name}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def admin_add_faculty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return
    name = update.message.text.split(" ", 1)[1].strip() if " " in update.message.text else ""
    if not name:
        await update.message.reply_text("Misol: /admin_add_faculty Iqtisod")
        return
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
    args = parse_pipe(update.message.text)
    if len(args) != 2 or not args[0].isdigit():
        await update.message.reply_text("Misol: /admin_add_program 1|Iqtisodiyot")
        return
    fid = int(args[0])
    name = args[1]
    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO programs(faculty_id, name) VALUES(?,?)", (fid, name))
    con.commit()
    con.close()
    await update.message.reply_text("✅ Yo‘nalish qo‘shildi.")


async def admin_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return
    args = parse_pipe(update.message.text)
    if len(args) != 2 or not args[0].isdigit():
        await update.message.reply_text("Misol: /admin_add_group 2|0124")
        return
    pid = int(args[0])
    name = args[1]
    con = db()
    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO groups(program_id, name) VALUES(?,?)", (pid, name))
    con.commit()
    con.close()
    await update.message.reply_text("✅ Guruh qo‘shildi.")


async def admin_announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return
    args = parse_pipe(update.message.text)
    if len(args) < 3:
        await update.message.reply_text("Misol: /admin_announce all|Sarlavha|Matn")
        return
    scope, title = args[0], args[1]
    body = "|".join(args[2:])
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO announcements(scope, title, body, created_at) VALUES(?,?,?,?)",
                (scope, title, body, int(time.time())))
    con.commit()
    con.close()
    await update.message.reply_text("✅ E’lon qo‘shildi.")


async def admin_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔️ Siz admin emassiz.")
        return
    args = parse_pipe(update.message.text)
    if len(args) < 2:
        await update.message.reply_text("Misol: /admin_template Ariza|Matn")
        return
    title = args[0]
    body = "|".join(args[1:])
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO templates(title, body, created_at) VALUES(?,?,?)",
                (title, body, int(time.time())))
    con.commit()
    con.close()
    await update.message.reply_text("✅ Shablon qo‘shildi.")


# -------------------- Jobs --------------------
async def job_auto_sync(context: ContextTypes.DEFAULT_TYPE):
    """
    Har soatda EduPage datani tortishga urinadi.
    Hozircha group bo‘yicha to‘liq ajratmaymiz, lekin cache yangilash uchun foydali.
    """
    try:
        raw = edupage_try_get_data()
        if not raw:
            return
        # barcha user guruh nomlarini olib, o‘sha nomga bitta payload saqlaymiz (keyin mapping moslaymiz)
        con = db()
        cur = con.cursor()
        cur.execute("""
        SELECT DISTINCT g.name
        FROM users u
        JOIN groups g ON g.id=u.group_id
        WHERE u.group_id IS NOT NULL
        """)
        groups = [r[0] for r in cur.fetchall()]
        con.close()

        now = 0
        for gn in groups:
            cache_set_group(gn, raw)
            now += 1
        logging.info("Auto sync: %s guruh cache yangilandi", now)
    except Exception as e:
        logging.warning("Auto sync xato: %s", e)


# -------------------- Main --------------------
def build_app():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN yo‘q. Railway Variables ga token qo‘ying.")

    init_db()
    seed_demo()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin_help", admin_help))
    app.add_handler(CommandHandler("admin_list", admin_list))
    app.add_handler(CommandHandler("admin_add_faculty", admin_add_faculty))
    app.add_handler(CommandHandler("admin_add_program", admin_add_program))
    app.add_handler(CommandHandler("admin_add_group", admin_add_group))
    app.add_handler(CommandHandler("admin_announce", admin_announce))
    app.add_handler(CommandHandler("admin_template", admin_template))

    # callbacks
    app.add_handler(CallbackQueryHandler(profile_cb, pattern=r"^profile:"))
    app.add_handler(CallbackQueryHandler(schedule_sync_cb, pattern=r"^schedule:sync$"))
    app.add_handler(CallbackQueryHandler(schedule_cb, pattern=r"^schedule:"))
    app.add_handler(CallbackQueryHandler(menu_cb))

    # ignore other texts
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, noop))

    # jobs
    app.job_queue.run_repeating(job_auto_sync, interval=60 * 60, first=30)

    return app


if __name__ == "__main__":
    application = build_app()
    logging.info("✅ SamATI bot ishga tushdi.")
    application.run_polling()
