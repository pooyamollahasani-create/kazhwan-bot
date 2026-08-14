from __future__ import annotations

from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.utils.xlsx import build_xlsx


def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = context.application.bot_data["settings"]
    return user_id in settings.admin_ids


def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 آمار", callback_data="admin:stats"),
            InlineKeyboardButton("👥 اعضا", callback_data="admin:members"),
        ],
        [
            InlineKeyboardButton("⏳ غیرفعال ۳۰ روز", callback_data="admin:inactive30"),
            InlineKeyboardButton("⌛ غیرفعال ۶۰ روز", callback_data="admin:inactive60"),
        ],
        [
            InlineKeyboardButton("🏆 معرف‌های برتر", callback_data="admin:referrals"),
            InlineKeyboardButton("📥 خروجی کامل", callback_data="admin:exportall"),
        ],
        [InlineKeyboardButton("🔎 راهنمای جستجوی عضو", callback_data="admin:memberhelp")],
    ])


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    await update.effective_message.reply_text(
        "🛠 پنل مدیریت کژوان\n\nیک گزینه را انتخاب کنید:",
        reply_markup=_admin_keyboard(),
    )


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    await update.effective_message.reply_text(
        f"شناسه عددی این گفتگو:\n`{update.effective_chat.id}`",
        parse_mode="Markdown",
    )


async def _stats_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    db = context.application.bot_data["db"]
    users = await db.list_group_users()
    unregistered = await db.list_unregistered_seen_members(limit=5000)
    inactive30 = await db.list_inactive_members(30, limit=5000)
    inactive60 = await db.list_inactive_members(60, limit=5000)
    total_referrals = sum(user.referral_count for user in users)
    total_points = sum(user.points for user in users)
    return (
        "📊 آمار مدیریتی کژوان\n\n"
        f"اعضای ثبت‌شده در ربات: {len(users)}\n"
        f"اعضای دیده‌شده ولی ثبت‌نام‌نشده: {len(unregistered)}\n"
        f"غیرفعال بیش از ۳۰ روز: {len(inactive30)}\n"
        f"غیرفعال بیش از ۶۰ روز: {len(inactive60)}\n"
        f"معرفی‌های موفق: {total_referrals}\n"
        f"مجموع امتیاز اعضا: {total_points}"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    await update.effective_message.reply_text(await _stats_text(context))


async def members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    db = context.application.bot_data["db"]
    users = await db.list_group_users()
    await update.effective_message.reply_text(
        f"👥 تعداد اعضای ثبت‌شده در ربات: {len(users)}\n\n"
        "برای خروجی Excel از /exportmembers استفاده کنید."
    )


async def registered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await members(update, context)


async def unregistered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    db = context.application.bot_data["db"]
    items = await db.list_unregistered_seen_members(limit=100)
    if not items:
        await update.effective_message.reply_text("✅ فعلاً عضو دیده‌شده و ثبت‌نام‌نشده‌ای نداریم.")
        return
    lines = ["👤 اعضای دیده‌شده ولی ثبت‌نام‌نشده", ""]
    for item in items[:80]:
        username = f"@{item.telegram_username}" if item.telegram_username else "بدون آیدی"
        lines.append(f"• {item.display_name} — {username}")
    if len(items) > 80:
        lines.append(f"… و {len(items) - 80} نفر دیگر")
    await update.effective_message.reply_text("\n".join(lines))


async def _inactive_text(context: ContextTypes.DEFAULT_TYPE, days: int) -> str:
    db = context.application.bot_data["db"]
    members_list = await db.list_inactive_members(days=days, limit=100)
    if not members_list:
        return f"✅ فعلاً عضوی با بیش از {days} روز بی‌فعالیتی نداریم."
    now = datetime.now(timezone.utc)
    lines = [f"⏳ اعضای با بیش از {days} روز بی‌فعالیتی", ""]
    for member in members_list:
        inactive_days = (now - member.last_activity_at).days
        username = f"@{member.telegram_username}" if member.telegram_username else "بدون آیدی"
        lines.append(f"• {member.display_name} — {inactive_days} روز — {username}")
    return "\n".join(lines)


async def inactive30(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    await update.effective_message.reply_text(await _inactive_text(context, 30))


async def inactive60(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    await update.effective_message.reply_text(await _inactive_text(context, 60))


async def member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.effective_message.reply_text(
            "برای جستجو بعد از دستور نام، شماره، کد عضویت یا Telegram ID را بنویسید.\n\n"
            "مثال:\n/member KZH-000012\n/member 09123456789\n/member علی رضایی"
        )
        return
    db = context.application.bot_data["db"]
    users = await db.search_users(query)
    if not users:
        await update.effective_message.reply_text("عضوی با این مشخصات پیدا نشد.")
        return
    lines = [f"🔎 نتیجه جستجو برای «{query}»", ""]
    for user in users[:10]:
        username = f"@{user.telegram_username}" if user.telegram_username else "-"
        lines.extend([
            f"👤 {user.full_name}",
            f"📱 {user.phone} | 📍 {user.city}",
            f"🆔 {user.member_code} | معرف: {user.referral_code}",
            f"Telegram: {username} | ID: {user.telegram_id}",
            f"⭐ {user.points} امتیاز | 👥 {user.referral_count} معرفی",
            "—",
        ])
    await update.effective_message.reply_text("\n".join(lines))


async def topreferrals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    db = context.application.bot_data["db"]
    users = await db.list_top_referrers(limit=20)
    if not users:
        await update.effective_message.reply_text("هنوز معرفی موفقی ثبت نشده است.")
        return
    lines = ["🏆 معرف‌های برتر", ""]
    for index, user in enumerate(users, start=1):
        lines.append(
            f"{index}. {user.full_name} — {user.referral_count} معرفی — {user.points} امتیاز"
        )
    await update.effective_message.reply_text("\n".join(lines))


def _member_export_rows(users) -> tuple[list[str], list[list[object]]]:
    headers = [
        "نام و نام خانوادگی", "شماره تماس", "شهر", "Username", "Telegram ID",
        "کد عضویت", "کد معرف", "معرف Telegram ID", "تعداد معرفی موفق", "امتیاز",
        "نحوه آشنایی", "تاریخ ثبت", "آخرین فعالیت", "وضعیت",
    ]
    rows = []
    for user in users:
        rows.append([
            user.full_name, user.phone, user.city,
            f"@{user.telegram_username}" if user.telegram_username else "",
            user.telegram_id, user.member_code or "", user.referral_code or "",
            user.referred_by_telegram_id or "", user.referral_count, user.points,
            user.discovery_source,
            user.created_at.isoformat() if user.created_at else "",
            user.last_activity_at.isoformat() if user.last_activity_at else "",
            user.status,
        ])
    return headers, rows


async def _send_xlsx(update: Update, headers, rows, filename: str, sheet_name: str) -> None:
    file_obj = build_xlsx(headers, rows, sheet_name=sheet_name)
    file_obj.name = filename
    await update.effective_message.reply_document(
        document=file_obj,
        filename=filename,
        caption=f"📥 {filename}",
    )


async def exportmembers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    users = await context.application.bot_data["db"].list_group_users()
    headers, rows = _member_export_rows(users)
    await _send_xlsx(update, headers, rows, "kazhwan_members.xlsx", "Members")


async def exportinactive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    db = context.application.bot_data["db"]
    items = await db.list_inactive_members(30, limit=5000)
    now = datetime.now(timezone.utc)
    headers = ["نام", "Username", "Telegram ID", "روزهای بی‌فعالیتی", "آخرین فعالیت"]
    rows = []
    for item in items:
        rows.append([
            item.display_name,
            f"@{item.telegram_username}" if item.telegram_username else "",
            item.telegram_id,
            (now - item.last_activity_at).days,
            item.last_activity_at.isoformat(),
        ])
    await _send_xlsx(update, headers, rows, "kazhwan_inactive.xlsx", "Inactive")


async def exportreferrals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    users = await context.application.bot_data["db"].list_top_referrers(limit=5000)
    headers = ["نام", "شماره", "کد معرف", "تعداد معرفی موفق", "امتیاز", "Telegram ID"]
    rows = [[u.full_name, u.phone, u.referral_code or "", u.referral_count, u.points, u.telegram_id] for u in users]
    await _send_xlsx(update, headers, rows, "kazhwan_referrals.xlsx", "Referrals")


async def exportall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await exportmembers(update, context)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_admin(query.from_user.id, context):
        return
    await query.answer()
    action = query.data.split(":", 1)[1]
    if action == "stats":
        await query.message.reply_text(await _stats_text(context))
    elif action == "members":
        count = await context.application.bot_data["db"].count_group_users()
        await query.message.reply_text(f"👥 اعضای ثبت‌شده: {count}\nبرای فایل کامل: /exportmembers")
    elif action == "inactive30":
        await query.message.reply_text(await _inactive_text(context, 30))
    elif action == "inactive60":
        await query.message.reply_text(await _inactive_text(context, 60))
    elif action == "referrals":
        users = await context.application.bot_data["db"].list_top_referrers(limit=10)
        text = "🏆 معرف‌های برتر\n\n" + "\n".join(
            f"{i}. {u.full_name} — {u.referral_count} معرفی — {u.points} امتیاز"
            for i, u in enumerate(users, 1)
        ) if users else "هنوز معرفی موفقی ثبت نشده است."
        await query.message.reply_text(text)
    elif action == "exportall":
        users = await context.application.bot_data["db"].list_group_users()
        headers, rows = _member_export_rows(users)
        file_obj = build_xlsx(headers, rows, sheet_name="Members")
        await query.message.reply_document(file_obj, filename="kazhwan_all_members.xlsx")
    elif action == "memberhelp":
        await query.message.reply_text(
            "🔎 جستجوی عضو:\n/member نام یا شماره یا کد عضویت\n\nمثال: /member KZH-000012"
        )


def admin_handlers():
    return [
        CommandHandler("admin", admin_panel),
        CommandHandler("chatid", chatid),
        CommandHandler("stats", stats),
        CommandHandler("members", members),
        CommandHandler("registered", registered),
        CommandHandler("unregistered", unregistered),
        CommandHandler("inactive30", inactive30),
        CommandHandler("inactive60", inactive60),
        CommandHandler("member", member),
        CommandHandler("topreferrals", topreferrals),
        CommandHandler("referrals", topreferrals),
        CommandHandler("exportmembers", exportmembers),
        CommandHandler("exportinactive", exportinactive),
        CommandHandler("exportreferrals", exportreferrals),
        CommandHandler("exportall", exportall),
        CallbackQueryHandler(admin_callback, pattern=r"^admin:"),
    ]
