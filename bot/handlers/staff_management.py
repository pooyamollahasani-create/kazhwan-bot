"""Owner-only Telegram admin management. Additive: existing features stay unchanged."""
import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, ConversationHandler, MessageHandler, filters
from telegram.constants import ChatType
from bot.db import Base, User

log = logging.getLogger(__name__)
WAIT_LOOKUP = 7101

class StaffAdmin(Base):
    __tablename__ = "staff_admins"
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class StaffAudit(Base):
    __tablename__ = "staff_admin_audit"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def owner_id(settings):
    explicit = os.getenv("OWNER_ID", "").strip()
    if explicit:
        return int(explicit)
    # Backward compatible when the legacy ADMIN_IDS has exactly one member.
    original = {int(v) for v in os.getenv("ADMIN_IDS", "86054420").split(",") if v.strip()}
    return next(iter(original)) if len(original) == 1 else None


def is_owner(uid, context):
    oid = context.application.bot_data.get("staff_owner_id")
    return oid is not None and uid == oid


async def initialize_staff(application):
    settings = application.bot_data["settings"]
    db = application.bot_data["db"]
    oid = owner_id(settings)
    application.bot_data["staff_owner_id"] = oid
    if oid is None:
        log.error("OWNER_ID must be set when ADMIN_IDS contains multiple IDs. Staff management disabled.")
    # create_all in Database.init() creates the two new tables; do not change existing tables.
    async with db.sessions() as session:
        existing = (await session.execute(select(StaffAdmin))).scalars().all()
        if not existing:
            # Initial import, once. A deactivated legacy admin is not restored on restart.
            if oid is not None:
                session.add(StaffAdmin(telegram_id=oid, active=True, created_by=oid))
            for aid in settings.admin_ids:
                if aid != oid:
                    session.add(StaffAdmin(telegram_id=aid, active=True, created_by=oid or aid))
            await session.commit()
            existing = (await session.execute(select(StaffAdmin))).scalars().all()
    settings.admin_ids.clear()
    if oid is not None:
        settings.admin_ids.add(oid)
    settings.admin_ids.update(row.telegram_id for row in existing if row.active and row.telegram_id != oid)


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزودن مدیر", callback_data="staff:add")],
        [InlineKeyboardButton("➖ حذف مدیر", callback_data="staff:remove")],
        [InlineKeyboardButton("📋 فهرست مدیران", callback_data="staff:list")],
        [InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="admin:home")],
    ])


async def _authorized(update, context):
    q = update.callback_query
    if not update.effective_user or not is_owner(update.effective_user.id, context) or update.effective_chat.type != ChatType.PRIVATE:
        if q:
            await q.answer("این بخش فقط برای مدیر اصلی است.", show_alert=True)
        return False
    return True


async def home(update, context):
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("👑 مدیریت مدیران کژوان", reply_markup=menu())
    return ConversationHandler.END


async def add_start(update, context):
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    context.user_data["staff_mode"] = "add"
    await update.callback_query.message.reply_text("شماره تماس، @username یا شناسه عددی تلگرام عضو ثبت‌شده را ارسال کنید. برای انصراف /cancel را بزنید.")
    return WAIT_LOOKUP


async def lookup(update, context):
    if not await _authorized(update, context):
        return ConversationHandler.END
    raw = (update.effective_message.text or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    db = context.application.bot_data["db"]
    if raw.startswith("@"):
        condition = User.telegram_username.ilike(raw[1:])
    elif re.fullmatch(r"[0-9]{5,16}", raw) and len(raw) <= 11:
        # An ambiguous numeric string can be an ID or a phone: search both, show matches.
        digits = re.sub(r"\D", "", raw)
        from sqlalchemy import or_
        condition = or_(User.telegram_id == int(raw), User.phone == raw, User.phone == "+" + raw)
    else:
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 8 or len(digits) > 15:
            await update.message.reply_text("شماره یا شناسه معتبر نیست. دوباره تلاش کنید.")
            return WAIT_LOOKUP
        from sqlalchemy import func
        condition = func.replace(func.replace(User.phone, "+", ""), " ", "").like("%" + digits[-10:])
    async with db.sessions() as session:
        rows = (await session.execute(select(User).where(condition).limit(10))).scalars().all()
    if not rows:
        await update.message.reply_text("❌ این شخص در پروفایل‌های ثبت‌شده ربات پیدا نشد. دوباره جستجو کنید یا /cancel بزنید.")
        return WAIT_LOOKUP
    mode = context.user_data.get("staff_mode")
    buttons = []
    for u in rows:
        buttons.append([InlineKeyboardButton(f"{u.full_name[:25]} | @{u.telegram_username or '-'} | {u.telegram_id}"[:64], callback_data=f"staff:pick:{mode}:{u.telegram_id}")])
    buttons.append([InlineKeyboardButton("❌ لغو", callback_data="staff:cancel")])
    await update.message.reply_text("شخص موردنظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return ConversationHandler.END


async def remove_list(update, context):
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    db = context.application.bot_data["db"]
    oid = context.application.bot_data["staff_owner_id"]
    async with db.sessions() as session:
        rows = (await session.execute(select(StaffAdmin).where(StaffAdmin.active.is_(True)))).scalars().all()
        ids = [row.telegram_id for row in rows if row.telegram_id != oid]
        users = (await session.execute(select(User).where(User.telegram_id.in_(ids)))).scalars().all() if ids else []
    names = {u.telegram_id: u.full_name for u in users}
    buttons = [[InlineKeyboardButton(f"{names.get(i, str(i))} | {i}"[:64], callback_data=f"staff:pick:remove:{i}")] for i in ids]
    buttons.append([InlineKeyboardButton("⬅️ بازگشت", callback_data="staff:home")])
    await update.callback_query.message.reply_text("➖ مدیر موردنظر برای حذف را انتخاب کنید:" if ids else "مدیر عادی فعالی وجود ندارد.", reply_markup=InlineKeyboardMarkup(buttons))
    return ConversationHandler.END


async def list_staff(update, context):
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    db = context.application.bot_data["db"]
    oid = context.application.bot_data["staff_owner_id"]
    async with db.sessions() as session:
        rows = (await session.execute(select(StaffAdmin).where(StaffAdmin.active.is_(True)))).scalars().all()
        ids = [r.telegram_id for r in rows if r.telegram_id != oid]
        users = (await session.execute(select(User).where(User.telegram_id.in_(ids)))).scalars().all() if ids else []
    names = {u.telegram_id: u.full_name for u in users}
    lines = [f"👑 مدیر اصلی: {oid}", "", "🛡 مدیران عادی:"] + ([f"• {names.get(i, 'بدون پروفایل')} ({i})" for i in ids] or ["موردی وجود ندارد."])
    await update.callback_query.message.reply_text("\n".join(lines), reply_markup=menu())
    return ConversationHandler.END


async def pick(update, context):
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    _, _, mode, raw_id = update.callback_query.data.split(":")
    tid = int(raw_id)
    oid = context.application.bot_data["staff_owner_id"]
    if tid == oid:
        await update.callback_query.message.reply_text("مدیر اصلی قابل تغییر نیست.")
        return ConversationHandler.END
    db = context.application.bot_data["db"]
    async with db.sessions() as session:
        user = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
        if not user:
            await update.callback_query.message.reply_text("این شخص در دیتابیس ثبت نشده است.")
            return ConversationHandler.END
        row = await session.get(StaffAdmin, tid)
    if mode == "add" and row and row.active:
        await update.callback_query.message.reply_text("این شخص هم‌اکنون مدیر است.")
        return ConversationHandler.END
    if mode == "remove" and (not row or not row.active):
        await update.callback_query.message.reply_text("این شخص دیگر مدیر نیست.")
        return ConversationHandler.END
    action = "افزودن" if mode == "add" else "حذف"
    await update.callback_query.message.reply_text(
        f"{action} مدیر؟\n👤 {user.full_name}\n🆔 {tid}\n📱 {user.phone}\n@{user.telegram_username or '-'}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ تأیید نهایی", callback_data=f"staff:confirm:{mode}:{tid}")], [InlineKeyboardButton("❌ انصراف", callback_data="staff:cancel")]]),
    )
    return ConversationHandler.END


async def confirm(update, context):
    if not await _authorized(update, context):
        return ConversationHandler.END
    await update.callback_query.answer()
    _, _, mode, raw_id = update.callback_query.data.split(":")
    tid = int(raw_id)
    oid = context.application.bot_data["staff_owner_id"]
    if tid == oid or mode not in ("add", "remove"):
        await update.callback_query.message.reply_text("درخواست نامعتبر است.")
        return ConversationHandler.END
    db = context.application.bot_data["db"]
    async with db.sessions() as session:
        user = (await session.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
        if not user:
            await update.callback_query.message.reply_text("پروفایل عضو یافت نشد.")
            return ConversationHandler.END
        row = await session.get(StaffAdmin, tid)
        if mode == "remove" and (row is None or not row.active):
            await update.callback_query.message.reply_text("این شخص دیگر مدیر نیست.")
            return ConversationHandler.END
        if mode == "add" and row and row.active:
            await update.callback_query.message.reply_text("این شخص از قبل مدیر است.")
            return ConversationHandler.END
        if row is None:
            row = StaffAdmin(telegram_id=tid, created_by=oid, active=True)
            session.add(row)
        row.active = mode == "add"
        row.changed_at = datetime.now(timezone.utc)
        session.add(StaffAudit(actor_id=oid, target_id=tid, action=mode))
        await session.commit()
    settings = context.application.bot_data["settings"]
    if mode == "add":
        settings.admin_ids.add(tid)
    else:
        settings.admin_ids.discard(tid)
    await update.callback_query.message.reply_text("✅ دسترسی مدیریتی فعال شد." if mode == "add" else "✅ دسترسی مدیریتی لغو شد.", reply_markup=menu())
    try:
        await context.bot.send_message(tid, "🛡 دسترسی مدیریتی شما در ربات کژوان فعال شد." if mode == "add" else "دسترسی مدیریتی شما در ربات کژوان لغو شد.")
    except Exception:
        log.info("Could not notify admin %s", tid)
    return ConversationHandler.END


async def cancel(update, context):
    if update.callback_query:
        if not await _authorized(update, context):
            return ConversationHandler.END
        await update.callback_query.answer()
        await update.callback_query.message.reply_text("عملیات لغو شد.", reply_markup=menu())
    else:
        await update.message.reply_text("عملیات لغو شد.")
    context.user_data.pop("staff_mode", None)
    return ConversationHandler.END


def handlers():
    from telegram.ext import CommandHandler
    return [
        ConversationHandler(
            entry_points=[CallbackQueryHandler(add_start, pattern=r"^staff:add$")],
            states={WAIT_LOOKUP: [MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, lookup)]},
            fallbacks=[CommandHandler("cancel", cancel)],
            per_chat=True, per_user=True, allow_reentry=True,
        ),
        CallbackQueryHandler(home, pattern=r"^staff:home$"),
        CallbackQueryHandler(remove_list, pattern=r"^staff:remove$"),
        CallbackQueryHandler(list_staff, pattern=r"^staff:list$"),
        CallbackQueryHandler(pick, pattern=r"^staff:pick:(add|remove):\d+$"),
        CallbackQueryHandler(confirm, pattern=r"^staff:confirm:(add|remove):\d+$"),
        CallbackQueryHandler(cancel, pattern=r"^staff:cancel$"),
    ]
