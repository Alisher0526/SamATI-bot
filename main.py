import os
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, redirect, url_for, render_template_string, send_from_directory
from werkzeug.utils import secure_filename
import telebot
from telebot import types

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_KEY = os.getenv("ADMIN_KEY", "123456").strip()
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env topilmadi")

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

UPLOAD_FOLDER = "uploads"
DB_PATH = "bot.db"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# =========================
# DATABASE
# =========================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            full_name TEXT,
            username TEXT,
            faculty_id INTEGER,
            group_id INTEGER,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS faculties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS groups_table (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(faculty_id, name)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        )
    """)

    conn.commit()

    # default faculty/group lar
    defaults = {
        "Iqtisod": ["0124", "0125", "0126"],
        "Agronomiya": ["0201", "0202"],
        "Veterinariya": ["0301", "0302"],
        "Zooinjeneriya": ["0401", "0402"]
    }

    for fac_name, groups in defaults.items():
        cur.execute("INSERT OR IGNORE INTO faculties (name, created_at) VALUES (?, ?)",
                    (fac_name, datetime.now().isoformat()))
        conn.commit()

        cur.execute("SELECT id FROM faculties WHERE name=?", (fac_name,))
        fac = cur.fetchone()
        if fac:
            for g in groups:
                cur.execute("""
                    INSERT OR IGNORE INTO groups_table (faculty_id, name, created_at)
                    VALUES (?, ?, ?)
                """, (fac["id"], g, datetime.now().isoformat()))
    conn.commit()
    conn.close()


init_db()

# =========================
# HELPERS
# =========================
def query_one(sql, params=()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return row


def query_all(sql, params=()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def execute(sql, params=()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def get_faculties():
    return query_all("SELECT * FROM faculties ORDER BY name")


def get_groups_by_faculty(faculty_id):
    return query_all("SELECT * FROM groups_table WHERE faculty_id=? ORDER BY name", (faculty_id,))


def get_faculty_by_id(faculty_id):
    return query_one("SELECT * FROM faculties WHERE id=?", (faculty_id,))


def get_group_by_id(group_id):
    return query_one("SELECT * FROM groups_table WHERE id=?", (group_id,))


def save_user(user, faculty_id=None, group_id=None):
    existing = query_one("SELECT id FROM users WHERE tg_id=?", (user.id,))
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

    if existing:
        if faculty_id is not None and group_id is not None:
            execute("""
                UPDATE users
                SET full_name=?, username=?, faculty_id=?, group_id=?
                WHERE tg_id=?
            """, (full_name, user.username, faculty_id, group_id, user.id))
        else:
            execute("""
                UPDATE users
                SET full_name=?, username=?
                WHERE tg_id=?
            """, (full_name, user.username, user.id))
    else:
        execute("""
            INSERT INTO users (tg_id, full_name, username, faculty_id, group_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user.id,
            full_name,
            user.username,
            faculty_id,
            group_id,
            datetime.now().isoformat()
        ))


def get_user_data(tg_id):
    return query_one("SELECT * FROM users WHERE tg_id=?", (tg_id,))


def get_docs_for_group(group_id):
    return query_all("""
        SELECT d.*, f.name AS faculty_name, g.name AS group_name
        FROM documents d
        JOIN faculties f ON d.faculty_id = f.id
        JOIN groups_table g ON d.group_id = g.id
        WHERE d.group_id = ?
        ORDER BY d.id DESC
    """, (group_id,))


def docs_keyboard(rows):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for row in rows:
        markup.add(
            types.InlineKeyboardButton(
                f"📄 {row['title']}",
                url=f"{BASE_URL}/files/{row['filename']}"
            )
        )
    return markup


def faculties_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    faculties = get_faculties()
    for fac in faculties:
        markup.add(types.InlineKeyboardButton(
            fac["name"],
            callback_data=f"fac:{fac['id']}"
        ))
    return markup


def groups_keyboard(faculty_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    groups = get_groups_by_faculty(faculty_id)
    for g in groups:
        markup.add(types.InlineKeyboardButton(
            g["name"],
            callback_data=f"group:{faculty_id}:{g['id']}"
        ))
    markup.add(types.InlineKeyboardButton("⬅ Orqaga", callback_data="back_faculties"))
    return markup


def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📚 Fakultet tanlash", "📄 Mening jadvalim")
    markup.row("👤 Mening profilim", "ℹ Yordam")
    return markup


def admin_only(key):
    return key == ADMIN_KEY


def safe_delete_file(filename):
    path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)


# =========================
# TELEGRAM BOT
# =========================
@bot.message_handler(commands=["start"])
def start_handler(message):
    save_user(message.from_user)
    text = (
        f"Assalomu alaykum, <b>{message.from_user.first_name}</b>.\n\n"
        "Bu <b>SAMATI PRO BOT</b>.\n"
        "Bu bot orqali siz:\n"
        "• fakultet/guruh tanlaysiz\n"
        "• o‘z jadvalingizni olasiz\n"
        "• admin yuklagan PDF fayllarni ochasiz\n\n"
        "Pastdagi menyudan foydalaning."
    )
    bot.send_message(message.chat.id, text, reply_markup=main_menu())


@bot.message_handler(commands=["help"])
def help_handler(message):
    bot.send_message(
        message.chat.id,
        "Buyruqlar:\n"
        "/start - botni ishga tushirish\n"
        "/help - yordam\n\n"
        "Tugmalar orqali fakultet va guruh tanlaysiz.\n"
        "Admin esa panel orqali PDF joylaydi."
    )


@bot.message_handler(func=lambda m: m.text == "📚 Fakultet tanlash")
def select_faculty(message):
    bot.send_message(message.chat.id, "Fakultetni tanlang:", reply_markup=faculties_keyboard())


@bot.message_handler(func=lambda m: m.text == "📄 Mening jadvalim")
def my_schedule(message):
    user_data = get_user_data(message.from_user.id)

    if not user_data or not user_data["group_id"]:
        bot.send_message(message.chat.id, "Avval fakultet va guruhni tanlang.", reply_markup=faculties_keyboard())
        return

    group_row = get_group_by_id(user_data["group_id"])
    faculty_row = get_faculty_by_id(user_data["faculty_id"])

    docs = get_docs_for_group(user_data["group_id"])
    if not docs:
        bot.send_message(
            message.chat.id,
            f"<b>{faculty_row['name']} / {group_row['name']}</b> uchun hozircha PDF topilmadi."
        )
        return

    bot.send_message(
        message.chat.id,
        f"<b>{faculty_row['name']} / {group_row['name']}</b> uchun topilgan hujjatlar:",
        reply_markup=docs_keyboard(docs)
    )


@bot.message_handler(func=lambda m: m.text == "👤 Mening profilim")
def my_profile(message):
    user_data = get_user_data(message.from_user.id)
    if not user_data:
        bot.send_message(message.chat.id, "Profil topilmadi.")
        return

    faculty_name = "Tanlanmagan"
    group_name = "Tanlanmagan"

    if user_data["faculty_id"]:
        fac = get_faculty_by_id(user_data["faculty_id"])
        if fac:
            faculty_name = fac["name"]

    if user_data["group_id"]:
        grp = get_group_by_id(user_data["group_id"])
        if grp:
            group_name = grp["name"]

    text = (
        f"<b>Sizning profilingiz</b>\n\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"👤 Ism: {user_data['full_name'] or '-'}\n"
        f"📛 Username: @{user_data['username'] if user_data['username'] else '-'}\n"
        f"🏛 Fakultet: {faculty_name}\n"
        f"👥 Guruh: {group_name}"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(func=lambda m: m.text == "ℹ Yordam")
def help_button(message):
    text = (
        "Botdan foydalanish:\n\n"
        "1) Fakultet tanlang\n"
        "2) Guruh tanlang\n"
        "3) O‘z guruhingiz uchun yuklangan PDF fayllarni oching\n\n"
        "Agar hujjat chiqmasa, admin hali yuklamagan bo‘lishi mumkin."
    )
    bot.send_message(message.chat.id, text)


@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    data = call.data

    if data == "back_faculties":
        bot.edit_message_text(
            "Fakultetni tanlang:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=faculties_keyboard()
        )
        return

    if data.startswith("fac:"):
        faculty_id = int(data.split(":")[1])
        fac = get_faculty_by_id(faculty_id)
        if not fac:
            bot.answer_callback_query(call.id, "Fakultet topilmadi")
            return

        bot.edit_message_text(
            f"<b>{fac['name']}</b> fakulteti tanlandi.\nEndi guruhni tanlang:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=groups_keyboard(faculty_id)
        )
        return

    if data.startswith("group:"):
        _, faculty_id, group_id = data.split(":")
        faculty_id = int(faculty_id)
        group_id = int(group_id)

        save_user(call.from_user, faculty_id=faculty_id, group_id=group_id)

        fac = get_faculty_by_id(faculty_id)
        grp = get_group_by_id(group_id)
        docs = get_docs_for_group(group_id)

        if docs:
            bot.edit_message_text(
                f"Siz tanladingiz:\n<b>{fac['name']} / {grp['name']}</b>\n\nTopilgan hujjatlar:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=docs_keyboard(docs)
            )
        else:
            bot.edit_message_text(
                f"Siz tanladingiz:\n<b>{fac['name']} / {grp['name']}</b>\n\n"
                "Hozircha bu guruh uchun PDF yuklanmagan.",
                call.message.chat.id,
                call.message.message_id
            )


# =========================
# FLASK ROUTES
# =========================
@app.route("/")
def home():
    return """
    <h2>SAMATI PRO BOT ishlayapti ✅</h2>
    <p>/health - health check</p>
    <p>/admin?key=YOUR_ADMIN_KEY - admin panel</p>
    """, 200


@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "samati-pro-bot"}), 200


@app.route(f"/webhook/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    json_str = request.get_data().decode("utf-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200


@app.route("/set-webhook")
def set_webhook_route():
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    if not BASE_URL:
        return "BASE_URL env kiritilmagan", 400

    webhook_url = f"{BASE_URL}/webhook/{BOT_TOKEN}"
    result = bot.set_webhook(url=webhook_url)
    return jsonify({"success": result, "webhook_url": webhook_url})


@app.route("/delete-webhook")
def delete_webhook_route():
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    result = bot.delete_webhook()
    return jsonify({"success": result})


@app.route("/files/<path:filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=False)


ADMIN_HTML = """
<!doctype html>
<html lang="uz">
<head>
  <meta charset="UTF-8">
  <title>SAMATI Admin Panel</title>
  <style>
    body { font-family: Arial, sans-serif; background:#f5f7fb; max-width: 1100px; margin: 20px auto; padding: 20px; }
    h1, h2, h3 { margin-top: 0; }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap:20px; }
    .card { background:#fff; border-radius:16px; padding:18px; box-shadow:0 3px 12px rgba(0,0,0,0.08); margin-bottom:20px; }
    input, select, button, textarea { width:100%; padding:12px; margin:8px 0; border:1px solid #ddd; border-radius:10px; box-sizing:border-box; }
    button { cursor:pointer; background:#111827; color:#fff; }
    a { text-decoration:none; color:#2563eb; }
    table { width:100%; border-collapse: collapse; margin-top: 10px; }
    th, td { padding:10px; border-bottom:1px solid #eee; text-align:left; vertical-align:top; }
    .stats { display:grid; grid-template-columns: repeat(4, 1fr); gap:14px; }
    .stat { background:#fff; padding:16px; border-radius:14px; box-shadow:0 3px 12px rgba(0,0,0,0.08); }
    .small { color:#666; font-size:13px; }
    .danger { color:#b91c1c; }
    @media (max-width: 850px) {
      .grid { grid-template-columns: 1fr; }
      .stats { grid-template-columns: repeat(2, 1fr); }
    }
  </style>
</head>
<body>
  <h1>SAMATI PRO Admin Panel</h1>
  <p class="small">Barcha boshqaruv shu yerda.</p>

  <div class="stats">
    <div class="stat"><h3>{{ users_count }}</h3><div class="small">Foydalanuvchilar</div></div>
    <div class="stat"><h3>{{ faculties_count }}</h3><div class="small">Fakultetlar</div></div>
    <div class="stat"><h3>{{ groups_count }}</h3><div class="small">Guruhlar</div></div>
    <div class="stat"><h3>{{ docs_count }}</h3><div class="small">PDF hujjatlar</div></div>
  </div>

  <div class="grid">
    <div>
      <div class="card">
        <h3>Fakultet qo'shish</h3>
        <form method="POST" action="/admin/add-faculty?key={{ key }}">
          <input type="text" name="name" placeholder="Masalan: Axborot texnologiyalari" required>
          <button type="submit">Qo'shish</button>
        </form>
      </div>

      <div class="card">
        <h3>Guruh qo'shish</h3>
        <form method="POST" action="/admin/add-group?key={{ key }}">
          <label>Fakultet</label>
          <select name="faculty_id" required>
            {% for f in faculties %}
            <option value="{{ f['id'] }}">{{ f['name'] }}</option>
            {% endfor %}
          </select>
          <input type="text" name="group_name" placeholder="Masalan: 0130" required>
          <button type="submit">Qo'shish</button>
        </form>
      </div>

      <div class="card">
        <h3>PDF yuklash</h3>
        <form method="POST" action="/admin/upload?key={{ key }}" enctype="multipart/form-data">
          <label>Fakultet</label>
          <select name="faculty_id" required id="facultySelect">
            {% for f in faculties %}
            <option value="{{ f['id'] }}">{{ f['name'] }}</option>
            {% endfor %}
          </select>

          <label>Guruh</label>
          <select name="group_id" required>
            {% for g in all_groups %}
            <option value="{{ g['id'] }}">{{ g['faculty_name'] }} / {{ g['name'] }}</option>
            {% endfor %}
          </select>

          <input type="text" name="title" placeholder="Masalan: Dars jadvali - Mart" required>
          <input type="file" name="pdf" accept="application/pdf" required>
          <button type="submit">PDF yuklash</button>
        </form>
      </div>

      <div class="card">
        <h3>Broadcast xabar</h3>
        <form method="POST" action="/admin/broadcast?key={{ key }}">
          <textarea name="message" rows="6" placeholder="Barcha foydalanuvchilarga yuboriladigan xabar..." required></textarea>
          <button type="submit">Yuborish</button>
        </form>
      </div>

      <div class="card">
        <h3>Webhook</h3>
        <p><a href="/set-webhook?key={{ key }}">Webhook yoqish</a></p>
        <p><a href="/delete-webhook?key={{ key }}">Webhook o‘chirish</a></p>
      </div>
    </div>

    <div>
      <div class="card">
        <h3>Fakultetlar</h3>
        <table>
          <tr><th>ID</th><th>Nomi</th><th>Amal</th></tr>
          {% for f in faculties %}
          <tr>
            <td>{{ f['id'] }}</td>
            <td>{{ f['name'] }}</td>
            <td><a class="danger" href="/admin/delete-faculty/{{ f['id'] }}?key={{ key }}" onclick="return confirm('Fakultet o‘chirilsinmi?')">O‘chirish</a></td>
          </tr>
          {% endfor %}
        </table>
      </div>

      <div class="card">
        <h3>Guruhlar</h3>
        <table>
          <tr><th>ID</th><th>Fakultet</th><th>Guruh</th><th>Amal</th></tr>
          {% for g in all_groups %}
          <tr>
            <td>{{ g['id'] }}</td>
            <td>{{ g['faculty_name'] }}</td>
            <td>{{ g['name'] }}</td>
            <td><a class="danger" href="/admin/delete-group/{{ g['id'] }}?key={{ key }}" onclick="return confirm('Guruh o‘chirilsinmi?')">O‘chirish</a></td>
          </tr>
          {% endfor %}
        </table>
      </div>

      <div class="card">
        <h3>PDF hujjatlar</h3>
        <table>
          <tr><th>ID</th><th>Yo'nalish</th><th>Title</th><th>Fayl</th><th>Amal</th></tr>
          {% for d in docs %}
          <tr>
            <td>{{ d['id'] }}</td>
            <td>{{ d['faculty_name'] }} / {{ d['group_name'] }}</td>
            <td>{{ d['title'] }}</td>
            <td><a href="/files/{{ d['filename'] }}" target="_blank">Ochish</a></td>
            <td><a class="danger" href="/admin/delete-doc/{{ d['id'] }}?key={{ key }}" onclick="return confirm('PDF o‘chirilsinmi?')">O‘chirish</a></td>
          </tr>
          {% endfor %}
        </table>
      </div>

      <div class="card">
        <h3>So‘nggi foydalanuvchilar</h3>
        <table>
          <tr><th>ID</th><th>Ism</th><th>Username</th><th>Tanlov</th></tr>
          {% for u in users %}
          <tr>
            <td>{{ u['tg_id'] }}</td>
            <td>{{ u['full_name'] or '-' }}</td>
            <td>{% if u['username'] %}@{{ u['username'] }}{% else %}-{% endif %}</td>
            <td>{{ u['faculty_name'] or '-' }} / {{ u['group_name'] or '-' }}</td>
          </tr>
          {% endfor %}
        </table>
      </div>
    </div>
  </div>
</body>
</html>
"""


@app.route("/admin")
def admin_page():
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    faculties = query_all("SELECT * FROM faculties ORDER BY id DESC")
    all_groups = query_all("""
        SELECT g.*, f.name AS faculty_name
        FROM groups_table g
        JOIN faculties f ON g.faculty_id = f.id
        ORDER BY g.id DESC
    """)
    docs = query_all("""
        SELECT d.*, f.name AS faculty_name, g.name AS group_name
        FROM documents d
        JOIN faculties f ON d.faculty_id = f.id
        JOIN groups_table g ON d.group_id = g.id
        ORDER BY d.id DESC
    """)
    users = query_all("""
        SELECT u.*, f.name AS faculty_name, g.name AS group_name
        FROM users u
        LEFT JOIN faculties f ON u.faculty_id = f.id
        LEFT JOIN groups_table g ON u.group_id = g.id
        ORDER BY u.id DESC
        LIMIT 50
    """)

    users_count = query_one("SELECT COUNT(*) AS c FROM users")["c"]
    faculties_count = query_one("SELECT COUNT(*) AS c FROM faculties")["c"]
    groups_count = query_one("SELECT COUNT(*) AS c FROM groups_table")["c"]
    docs_count = query_one("SELECT COUNT(*) AS c FROM documents")["c"]

    return render_template_string(
        ADMIN_HTML,
        key=ADMIN_KEY,
        faculties=faculties,
        all_groups=all_groups,
        docs=docs,
        users=users,
        users_count=users_count,
        faculties_count=faculties_count,
        groups_count=groups_count,
        docs_count=docs_count
    )


@app.route("/admin/add-faculty", methods=["POST"])
def admin_add_faculty():
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    name = request.form.get("name", "").strip()
    if not name:
        return "Fakultet nomi kerak", 400

    try:
        execute("INSERT INTO faculties (name, created_at) VALUES (?, ?)",
                (name, datetime.now().isoformat()))
    except Exception:
        pass

    return redirect(url_for("admin_page", key=ADMIN_KEY))


@app.route("/admin/add-group", methods=["POST"])
def admin_add_group():
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    faculty_id = request.form.get("faculty_id", "").strip()
    group_name = request.form.get("group_name", "").strip()

    if not faculty_id or not group_name:
        return "Ma'lumot yetarli emas", 400

    try:
        execute("""
            INSERT INTO groups_table (faculty_id, name, created_at)
            VALUES (?, ?, ?)
        """, (faculty_id, group_name, datetime.now().isoformat()))
    except Exception:
        pass

    return redirect(url_for("admin_page", key=ADMIN_KEY))


@app.route("/admin/upload", methods=["POST"])
def admin_upload():
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    faculty_id = request.form.get("faculty_id", "").strip()
    group_id = request.form.get("group_id", "").strip()
    title = request.form.get("title", "").strip()
    file = request.files.get("pdf")

    if not faculty_id or not group_id or not title or not file:
        return "Ma'lumot yetarli emas", 400

    if not file.filename.lower().endswith(".pdf"):
        return "Faqat PDF yuklang", 400

    safe_name = secure_filename(file.filename)
    final_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{safe_name}"
    save_path = os.path.join(UPLOAD_FOLDER, final_name)
    file.save(save_path)

    execute("""
        INSERT INTO documents (faculty_id, group_id, title, filename, uploaded_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        faculty_id,
        group_id,
        title,
        final_name,
        datetime.now().isoformat()
    ))

    return redirect(url_for("admin_page", key=ADMIN_KEY))


@app.route("/admin/delete-doc/<int:doc_id>")
def admin_delete_doc(doc_id):
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    doc = query_one("SELECT * FROM documents WHERE id=?", (doc_id,))
    if doc:
        safe_delete_file(doc["filename"])
        execute("DELETE FROM documents WHERE id=?", (doc_id,))

    return redirect(url_for("admin_page", key=ADMIN_KEY))


@app.route("/admin/delete-group/<int:group_id>")
def admin_delete_group(group_id):
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    docs = query_all("SELECT * FROM documents WHERE group_id=?", (group_id,))
    for d in docs:
        safe_delete_file(d["filename"])
    execute("DELETE FROM documents WHERE group_id=?", (group_id,))
    execute("DELETE FROM users WHERE group_id=?", (group_id,))
    execute("DELETE FROM groups_table WHERE id=?", (group_id,))

    return redirect(url_for("admin_page", key=ADMIN_KEY))


@app.route("/admin/delete-faculty/<int:faculty_id>")
def admin_delete_faculty(faculty_id):
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    docs = query_all("SELECT * FROM documents WHERE faculty_id=?", (faculty_id,))
    for d in docs:
        safe_delete_file(d["filename"])

    groups = query_all("SELECT * FROM groups_table WHERE faculty_id=?", (faculty_id,))
    for g in groups:
        execute("DELETE FROM users WHERE group_id=?", (g["id"],))

    execute("DELETE FROM documents WHERE faculty_id=?", (faculty_id,))
    execute("DELETE FROM groups_table WHERE faculty_id=?", (faculty_id,))
    execute("DELETE FROM users WHERE faculty_id=?", (faculty_id,))
    execute("DELETE FROM faculties WHERE id=?", (faculty_id,))

    return redirect(url_for("admin_page", key=ADMIN_KEY))


@app.route("/admin/broadcast", methods=["POST"])
def admin_broadcast():
    key = request.args.get("key", "")
    if not admin_only(key):
        return "Ruxsat yo'q", 403

    message = request.form.get("message", "").strip()
    if not message:
        return "Xabar bo'sh", 400

    users = query_all("SELECT tg_id FROM users")
    success = 0
    failed = 0

    for u in users:
        try:
            bot.send_message(u["tg_id"], message)
            success += 1
        except Exception:
            failed += 1

    return f"Broadcast tugadi. Yuborildi: {success}, Xato: {failed}", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
