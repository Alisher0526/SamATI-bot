import sqlite3

DB_NAME = "samati.db"


def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE,
        full_name TEXT,
        username TEXT,
        selected_group TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS faculties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS groups_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_name TEXT,
        group_name TEXT UNIQUE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT UNIQUE,
        schedule_text TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT
    )
    """)

    conn.commit()
    conn.close()


def add_user(telegram_id, full_name, username):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR IGNORE INTO users (telegram_id, full_name, username)
    VALUES (?, ?, ?)
    """, (telegram_id, full_name, username))
    conn.commit()
    conn.close()


def set_user_group(telegram_id, group_name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    UPDATE users
    SET selected_group = ?
    WHERE telegram_id = ?
    """, (group_name, telegram_id))
    conn.commit()
    conn.close()


def get_user_group(telegram_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT selected_group FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()
    conn.close()
    return row["selected_group"] if row and row["selected_group"] else None


def add_faculty(name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO faculties (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()


def get_faculties():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM faculties ORDER BY name")
    rows = cur.fetchall()
    conn.close()
    return [row["name"] for row in rows]


def add_group(faculty_name, group_name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR IGNORE INTO groups_table (faculty_name, group_name)
    VALUES (?, ?)
    """, (faculty_name, group_name))
    conn.commit()
    conn.close()


def get_groups():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT group_name FROM groups_table ORDER BY group_name")
    rows = cur.fetchall()
    conn.close()
    return [row["group_name"] for row in rows]


def get_groups_by_faculty(faculty_name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT group_name FROM groups_table
    WHERE faculty_name = ?
    ORDER BY group_name
    """, (faculty_name,))
    rows = cur.fetchall()
    conn.close()
    return [row["group_name"] for row in rows]


def save_schedule(group_name, schedule_text):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO schedules (group_name, schedule_text)
    VALUES (?, ?)
    ON CONFLICT(group_name) DO UPDATE SET schedule_text=excluded.schedule_text
    """, (group_name, schedule_text))
    conn.commit()
    conn.close()


def get_schedule(group_name):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT schedule_text FROM schedules WHERE group_name = ?", (group_name,))
    row = cur.fetchone()
    conn.close()
    return row["schedule_text"] if row else None


def add_announcement(text):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO announcements (text) VALUES (?)", (text,))
    conn.commit()
    conn.close()


def get_announcements(limit=10):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT text FROM announcements ORDER BY id DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [row["text"] for row in rows]


def get_user_ids():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT telegram_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [row["telegram_id"] for row in rows]


def get_stats():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS count FROM users")
    users_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM faculties")
    faculties_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM groups_table")
    groups_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM schedules")
    schedules_count = cur.fetchone()["count"]

    cur.execute("SELECT COUNT(*) AS count FROM announcements")
    announcements_count = cur.fetchone()["count"]

    conn.close()

    return {
        "users": users_count,
        "faculties": faculties_count,
        "groups": groups_count,
        "schedules": schedules_count,
        "announcements": announcements_count,
  }
