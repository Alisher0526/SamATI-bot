import os
import logging
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "")
    .split(",")
    if x.strip().isdigit()
}

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Railway ko'pincha postgres:// beradi, SQLAlchemy uchun postgresqL+psycopg kerak emas,
# lekin yangi psycopg drayver bilan URL odatda ishlaydi. Shu ko'rinishni ham qabul qilamiz.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


# =========================
# DB MODELS
# =========================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(BigInteger, unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    faculty_id = Column(Integer, ForeignKey("faculties.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Faculty(Base):
    __tablename__ = "faculties"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    groups = relationship("Group", back_populates="faculty", cascade="all, delete-orphan")


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculties.id"), nullable=False)
    name = Column(String(100), nullable=False)
    edu_page_url = Column(Text, nullable=True)
    schedule_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    faculty = relationship("Faculty", back_populates="groups")


class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


@contextmanager
def db_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# =========================
# SEED DATA
# =========================
def seed_data():
    with db_session() as session:
        has_faculty = session.execute(select(Faculty).limit(1)).scalar_one_or_none()
        if has_faculty:
            return

        economics = Faculty(name="Iqtisod fakulteti")
        agrotech = Faculty(name="Agrotexnologiya fakulteti")
        vet = Faculty(name="Veterinariya fakulteti")
        session.add_all([economics, agrotech, vet])
        session.flush()

        groups = [
            Group(
                faculty_id=economics.id,
                name="0124",
                edu_page_url="https://example.com/edu/0124",
                schedule_text="Dushanba: Mikroiqtisod\nSeshanba: Matematika",
            ),
            Group(
                faculty_id=economics.id,
                name="0125",
                edu_page_url="https://example.com/edu/0125",
                schedule_text="Dushanba: Makroiqtisod\nChorshanba: Ingliz tili",
            ),
            Group(
                faculty_id=agrotech.id,
                name="A-101",
                edu_page_url="https://example.com/edu/a101",
                schedule_text="Seshanba: Agronomiya\nPayshanba: Biologiya",
            ),
            Group(
                faculty_id=vet.id,
                name="V-201",
                edu_page_url="https://example.com/edu/v201",
                schedule_text="Dushanba: Anatomiya\nJuma: Farmakologiya",
            ),
        ]
        session.add_all(groups)


# =========================
# HELPERS
# =========================
def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🏛 Fakultetlar", callback_data="faculties")],
        [InlineKeyboardButton("📅 Jadval", callback_data="schedule_faculties")],
        [InlineKeyboardButton("🔎 Guruh qidirish", callback_data="search_help")],
        [InlineKeyboardButton("📰 Yangiliklar", callback_data="news")],
        [InlineKeyboardButton("👤 Profilim", callback_data="profile")],
        [InlineKeyboardButton("ℹ️ Yordam", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📢 Post yuborish", callback_data="admin_broadcast")],
        [InlineKeyboardButton("➕ Fakultet qo'shish", callback_data="admin_add_faculty")],
        [InlineKeyboardButton("➕ Guruh qo'shish", callback_data="admin_add_group")],
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
    ]
    return InlineKeyboardMarkup(keyboard)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_or_create_user(tg_user):
    with db_session() as session:
        user = session.execute(select(User).where(User.tg_id == tg_user.id)).scalar_one_or_none()
        if not user:
            user = User(
                tg_id=tg_user.id,
                full_name=tg_user.full_name,
                username=tg_user.username,
                is_admin=is_admin(tg_user.id),
            )
            session.add(user)
            session.flush()
            session.refresh(user)
        else:
            user.full_name = tg_user.full_name
            user.username = tg_user.username
            user.is_admin = is_admin(tg_user.id)
            session.add(user)
            session.flush()
            session.refresh(user)
        return {
            "id": user.id,
            "tg_id": user.tg_id,
            "full_name": user.full_name,
            "username": user.username,
            "faculty_id": user.faculty_id,
            "group_id": user.group_id,
            "is_admin": user.is_admin,
        }


def build_faculties_keyboard(prefix: str = "faculty") -> InlineKeyboardMarkup:
    with db_session() as session:
        faculties = session.execute(select(Faculty).order_by(Faculty.name.asc())).scalars().all()

    keyboard = [
        [InlineKeyboardButton(f"🏛 {f.name}", callback_data=f"{prefix}:{f.id}")]
        for f in faculties
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="home")])
    return InlineKeyboardMarkup(keyboard)


def build_groups_keyboard(faculty_id: int, prefix: str = "group") -> InlineKeyboardMarkup:
    with db_session() as session:
        groups = session.execute(
            select(Group).where(Group.faculty_id == faculty_id).order_by(Group.name.asc())
        ).scalars().all()

    keyboard = [
        [InlineKeyboardButton(f"📘 {g.name}", callback_data=f"{prefix}:{g.id}")]
        for g in groups
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="faculties")])
    return InlineKeyboardMarkup(keyboard)


def chunked(items, size=20):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    profile = get_or_create_user(user)

    text = (
        f"Assalomu alaykum, <b>{user.full_name}</b>!\n\n"
        "SAMATI PRO botga xush kelibsiz.\n"
        "Quyidagilardan birini tanlang:"
    )

    if profile["is_admin"]:
        text += "\n\nSiz admin sifatida kirdingiz. /admin"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(),
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Siz admin emassiz.")
        return

    await update.message.reply_text(
        "Admin panelga xush kelibsiz.",
        reply_markup=admin_menu_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Buyruqlar:\n"
        "/start - asosiy menyu\n"
        "/admin - admin panel\n"
        "/search <guruh> - guruh qidirish\n"
        "/mygroup - tanlangan guruhni ko'rish\n"
        "/setgroup <guruh_nomi> - guruhni saqlash\n"
    )
    await update.message.reply_text(text)


async def search_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Masalan: /search 0124")
        return

    query = " ".join(context.args).strip()
    with db_session() as session:
        groups = session.execute(
            select(Group, Faculty)
            .join(Faculty, Group.faculty_id == Faculty.id)
            .where(Group.name.ilike(f"%{query}%"))
            .order_by(Group.name.asc())
        ).all()

    if not groups:
        await update.message.reply_text("Hech narsa topilmadi.")
        return

    lines = ["Topilgan guruhlar:\n"]
    keyboard = []
    for group, faculty in groups[:20]:
        lines.append(f"• {group.name} — {faculty.name}")
        keyboard.append([
            InlineKeyboardButton(
                f"✅ {group.name}", callback_data=f"savegroup:{group.id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("⬅️ Asosiy menyu", callback_data="home")])
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def my_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db_session() as session:
        user = session.execute(
            select(User).where(User.tg_id == update.effective_user.id)
        ).scalar_one_or_none()

        if not user or not user.group_id:
            await update.message.reply_text("Siz hali guruh tanlamagansiz. /search 0124")
            return

        group = session.execute(select(Group).where(Group.id == user.group_id)).scalar_one_or_none()
        faculty = session.execute(select(Faculty).where(Faculty.id == user.faculty_id)).scalar_one_or_none()

    text = (
        f"Sizning guruhingiz: <b>{group.name}</b>\n"
        f"Fakultet: {faculty.name if faculty else '-'}\n"
        f"Edu page: {group.edu_page_url or 'kiritilmagan'}\n\n"
        f"Jadval:\n{group.schedule_text or 'kiritilmagan'}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def set_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Masalan: /setgroup 0124")
        return

    group_name = " ".join(context.args).strip()
    with db_session() as session:
        group = session.execute(select(Group).where(Group.name.ilike(group_name))).scalar_one_or_none()
        if not group:
            await update.message.reply_text("Bunday guruh topilmadi. /search orqali qidiring.")
            return

        user = session.execute(
            select(User).where(User.tg_id == update.effective_user.id)
        ).scalar_one_or_none()
        if not user:
            await update.message.reply_text("Avval /start bosing.")
            return

        user.group_id = group.id
        user.faculty_id = group.faculty_id
        session.add(user)

    await update.message.reply_text(f"{group.name} guruhi saqlandi ✅")


# =========================
# CALLBACKS
# =========================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "home":
        await query.edit_message_text(
            "Asosiy menyu:",
            reply_markup=main_menu_keyboard(),
        )
        return

    if data == "faculties":
        await query.edit_message_text(
            "Fakultetni tanlang:",
            reply_markup=build_faculties_keyboard("faculty"),
        )
        return

    if data.startswith("faculty:"):
        faculty_id = int(data.split(":")[1])
        await query.edit_message_text(
            "Guruhni tanlang:",
            reply_markup=build_groups_keyboard(faculty_id, "group"),
        )
        return

    if data.startswith("group:"):
        group_id = int(data.split(":")[1])
        with db_session() as session:
            group = session.execute(select(Group).where(Group.id == group_id)).scalar_one_or_none()
            faculty = session.execute(select(Faculty).where(Faculty.id == group.faculty_id)).scalar_one_or_none()

        text = (
            f"<b>Guruh:</b> {group.name}\n"
            f"<b>Fakultet:</b> {faculty.name if faculty else '-'}\n"
            f"<b>Edu page:</b> {group.edu_page_url or 'kiritilmagan'}\n\n"
            f"<b>Jadval:</b>\n{group.schedule_text or 'kiritilmagan'}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Guruhni saqlash", callback_data=f"savegroup:{group.id}")],
            [InlineKeyboardButton("⬅️ Fakultetlar", callback_data="faculties")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data.startswith("savegroup:"):
        group_id = int(data.split(":")[1])
        with db_session() as session:
            group = session.execute(select(Group).where(Group.id == group_id)).scalar_one_or_none()
            user = session.execute(
                select(User).where(User.tg_id == update.effective_user.id)
            ).scalar_one_or_none()
            if user and group:
                user.group_id = group.id
                user.faculty_id = group.faculty_id
                session.add(user)
        await query.edit_message_text("Guruh muvaffaqiyatli saqlandi ✅")
        return

    if data == "schedule_faculties":
        await query.edit_message_text(
            "Jadval uchun fakultetni tanlang:",
            reply_markup=build_faculties_keyboard("schedule_faculty"),
        )
        return

    if data.startswith("schedule_faculty:"):
        faculty_id = int(data.split(":")[1])
        await query.edit_message_text(
            "Jadval uchun guruhni tanlang:",
            reply_markup=build_groups_keyboard(faculty_id, "schedule_group"),
        )
        return

    if data.startswith("schedule_group:"):
        group_id = int(data.split(":")[1])
        with db_session() as session:
            group = session.execute(select(Group).where(Group.id == group_id)).scalar_one_or_none()
        await query.edit_message_text(
            f"📅 {group.name} guruhi jadvali:\n\n{group.schedule_text or 'Jadval kiritilmagan'}",
        )
        return

    if data == "news":
        with db_session() as session:
            items = session.execute(select(News).order_by(News.id.desc()).limit(10)).scalars().all()
        if not items:
            await query.edit_message_text("Hozircha yangiliklar yo'q.")
            return
        text = "📰 So'nggi yangiliklar:\n\n"
        for item in items:
            text += f"<b>{item.title}</b>\n{item.body}\n\n"
        await query.edit_message_text(text[:4000], parse_mode=ParseMode.HTML)
        return

    if data == "profile":
        with db_session() as session:
            user = session.execute(select(User).where(User.tg_id == update.effective_user.id)).scalar_one_or_none()
            faculty_name = "-"
            group_name = "-"
            if user and user.faculty_id:
                faculty = session.execute(select(Faculty).where(Faculty.id == user.faculty_id)).scalar_one_or_none()
                faculty_name = faculty.name if faculty else "-"
            if user and user.group_id:
                group = session.execute(select(Group).where(Group.id == user.group_id)).scalar_one_or_none()
                group_name = group.name if group else "-"

        text = (
            f"👤 <b>Profil</b>\n\n"
            f"Ism: {update.effective_user.full_name}\n"
            f"Username: @{update.effective_user.username if update.effective_user.username else '-'}\n"
            f"Fakultet: {faculty_name}\n"
            f"Guruh: {group_name}"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)
        return

    if data == "help" or data == "search_help":
        await query.edit_message_text(
            "Guruh qidirish uchun: /search 0124\n"
            "Guruh saqlash uchun: /setgroup 0124\n"
            "Saqlangan guruhni ko'rish uchun: /mygroup"
        )
        return

    # ADMIN CALLBACKS
    if data == "admin_stats":
        if not is_admin(update.effective_user.id):
            await query.edit_message_text("Ruxsat yo'q")
            return
        with db_session() as session:
            total_users = session.execute(select(func.count(User.id))).scalar_one()
            total_faculties = session.execute(select(func.count(Faculty.id))).scalar_one()
            total_groups = session.execute(select(func.count(Group.id))).scalar_one()
            total_news = session.execute(select(func.count(News.id))).scalar_one()
        text = (
            "📊 Statistika\n\n"
            f"Foydalanuvchilar: {total_users}\n"
            f"Fakultetlar: {total_faculties}\n"
            f"Guruhlar: {total_groups}\n"
            f"Yangiliklar: {total_news}"
        )
        await query.edit_message_text(text)
        return

    if data == "admin_broadcast":
        if not is_admin(update.effective_user.id):
            await query.edit_message_text("Ruxsat yo'q")
            return
        context.user_data["broadcast_mode"] = True
        await query.edit_message_text(
            "Yuboriladigan post matnini bitta xabar qilib yuboring.\nBekor qilish: /cancel"
        )
        return

    if data == "admin_add_faculty":
        if not is_admin(update.effective_user.id):
            await query.edit_message_text("Ruxsat yo'q")
            return
        context.user_data["add_faculty_mode"] = True
        await query.edit_message_text("Yangi fakultet nomini yuboring.")
        return

    if data == "admin_add_group":
        if not is_admin(update.effective_user.id):
            await query.edit_message_text("Ruxsat yo'q")
            return
        context.user_data["add_group_mode"] = True
        await query.edit_message_text(
            "Format:\nFAKULTET_ID | GURUH_NOMI | EDU_LINK | JADVAL"
        )
        return


# =========================
# TEXT HANDLER
# =========================
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    if text == "/cancel":
        context.user_data.clear()
        await update.message.reply_text("Bekor qilindi.")
        return

    if is_admin(user_id) and context.user_data.get("broadcast_mode"):
        context.user_data["broadcast_mode"] = False
        sent = 0
        failed = 0
        with db_session() as session:
            users = session.execute(select(User)).scalars().all()
        for batch in chunked(users, 20):
            for user in batch:
                try:
                    await context.bot.send_message(chat_id=user.tg_id, text=text)
                    sent += 1
                except Exception as e:
                    logger.warning("Broadcast xato tg_id=%s error=%s", user.tg_id, e)
                    failed += 1
        await update.message.reply_text(f"Yuborildi: {sent}\nXato: {failed}")
        return

    if is_admin(user_id) and context.user_data.get("add_faculty_mode"):
        context.user_data["add_faculty_mode"] = False
        with db_session() as session:
            exists = session.execute(select(Faculty).where(Faculty.name == text)).scalar_one_or_none()
            if exists:
                await update.message.reply_text("Bu fakultet allaqachon mavjud.")
                return
            session.add(Faculty(name=text))
        await update.message.reply_text("Fakultet qo'shildi ✅")
        return

    if is_admin(user_id) and context.user_data.get("add_group_mode"):
        context.user_data["add_group_mode"] = False
        try:
            faculty_id_str, group_name, edu_link, schedule_text = [x.strip() for x in text.split("|", 3)]
            faculty_id = int(faculty_id_str)
        except Exception:
            await update.message.reply_text("Format xato.\nFAKULTET_ID | GURUH_NOMI | EDU_LINK | JADVAL")
            return

        with db_session() as session:
            faculty = session.execute(select(Faculty).where(Faculty.id == faculty_id)).scalar_one_or_none()
            if not faculty:
                await update.message.reply_text("Bunday faculty_id topilmadi.")
                return
            session.add(
                Group(
                    faculty_id=faculty_id,
                    name=group_name,
                    edu_page_url=edu_link,
                    schedule_text=schedule_text,
                )
            )
        await update.message.reply_text("Guruh qo'shildi ✅")
        return

    # oddiy user uchun fallback qidiruv
    with db_session() as session:
        groups = session.execute(
            select(Group).where(Group.name.ilike(f"%{text}%")).order_by(Group.name.asc()).limit(10)
        ).scalars().all()

    if groups:
        keyboard = [
            [InlineKeyboardButton(f"📘 {g.name}", callback_data=f"group:{g.id}")]
            for g in groups
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Asosiy menyu", callback_data="home")])
        await update.message.reply_text(
            "Qidiruv natijalari:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text(
            "Tushunmadim. Menyudan foydalaning yoki /search 0124 deb yozing.",
            reply_markup=main_menu_keyboard(),
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Exception while handling an update:", exc_info=context.error)


def main():
    seed_data()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("search", search_group))
    app.add_handler(CommandHandler("mygroup", my_group))
    app.add_handler(CommandHandler("setgroup", set_group))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(error_handler)

    logger.info("Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
