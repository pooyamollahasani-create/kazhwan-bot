from __future__ import annotations

from datetime import datetime, timezone
import logging

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (
    CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler,
    MessageHandler, filters,
)

from bot.utils.xlsx import build_xlsx
from sqlalchemy import select
from bot.db import Trip

logger = logging.getLogger(__name__)

MANUAL_TRIP_TITLE, MANUAL_TRIP_TYPE, MANUAL_TRIP_START, MANUAL_TRIP_END, MANUAL_GUEST_NAME, MANUAL_GUEST_PHONE, MANUAL_GUEST_STATUS, MANUAL_TRIP_DUPLICATE = range(100, 108)


STATUS_LABELS = {
    "declared": "🟡 اعلام حضور",
    "attended": "🟢 شرکت کرده",
    "cancelled": "⚪ انصراف",
}
TRIP_TYPE_LABELS = {
    "domestic_day": "🇮🇷 داخلی یک‌روزه",
    "domestic_multi": "🇮🇷 داخلی چندروزه",
    "international": "🌍 خارجی",
}
TRIP_STATUS_LABELS = {
    "open": "🟢 باز",
    "closed": "🔒 بسته",
    "ended": "🏁 پایان‌یافته",
    "archived": "🗃 آرشیوشده",
}


def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = context.application.bot_data["settings"]
    return user_id in settings.admin_ids


async def _list_trips_compat(db, limit: int = 30):
    """v1.4.6 compatibility path.

    Some Railway deployments retained an older Database class without
    list_trips().  The admin panel can query through the existing session
    factory directly, so trip management remains usable even in that case.
    """
    method = getattr(db, "list_trips", None)
    if callable(method):
        return await method(limit=limit)
    async with db.sessions() as session:
        result = await session.execute(
            select(Trip).order_by(Trip.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


def _admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 آمار", callback_data="admin:stats"),
            InlineKeyboardButton("👥 اعضا", callback_data="admin:members"),
        ],
        [InlineKeyboardButton("🧳 مدیریت سفرها", callback_data="admin:trips")],
        [
            InlineKeyboardButton("⏳ غیرفعال ۳۰ روز", callback_data="admin:inactive30"),
            InlineKeyboardButton("⌛ غیرفعال ۶۰ روز", callback_data="admin:inactive60"),
        ],
        [
            InlineKeyboardButton("🏆 معرف‌های برتر", callback_data="admin:referrals"),
            InlineKeyboardButton("📥 خروجی کامل", callback_data="admin:exportall"),
        ],
        [
            InlineKeyboardButton("📝 مسافران موقت", callback_data="admin:guests"),
            InlineKeyboardButton("🔎 جستجوی عضو", callback_data="admin:memberhelp"),
        ],
    ])


def _back_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="admin:home")]])


def _trip_list_keyboard(trips) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ تعریف سفر جدید", callback_data="tripadmin:new")]]
    for trip in trips[:30]:
        label = f"{TRIP_STATUS_LABELS.get(trip.status, trip.status)} | {trip.title} | {trip.trip_code}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"tripadmin:view:{trip.id}")])
    rows.append([InlineKeyboardButton("🗃 سفرهای آرشیوشده", callback_data="tripadmin:archived")])
    rows.append([InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def _trip_actions_keyboard(trip) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("➕ افزودن مسافر دستی", callback_data=f"tripadmin:addguest:{trip.id}")],
        [
            InlineKeyboardButton("👥 مسافران", callback_data=f"tripadmin:participants:{trip.id}:0"),
            InlineKeyboardButton("📥 Excel", callback_data=f"tripadmin:export:{trip.id}"),
        ],
    ]
    if trip.status == "open":
        rows.append([InlineKeyboardButton("🔒 بستن ثبت", callback_data=f"tripadmin:status:{trip.id}:closed")])
    else:
        rows.append([InlineKeyboardButton("🔓 باز کردن ثبت", callback_data=f"tripadmin:status:{trip.id}:open")])
    if trip.status != "ended":
        rows.append([InlineKeyboardButton("🏁 پایان سفر", callback_data=f"tripadmin:status:{trip.id}:ended")])
    rows.append([InlineKeyboardButton("🔀 ادغام سفر تکراری", callback_data=f"tripadmin:merge:{trip.id}")])
    rows.append([InlineKeyboardButton("🗑 آرشیو / حذف سفر", callback_data=f"tripadmin:archive:{trip.id}")])
    rows.extend([
        [InlineKeyboardButton("⬅️ سفرها", callback_data="admin:trips")],
        [InlineKeyboardButton("🏠 پنل مدیریت", callback_data="admin:home")],
    ])
    return InlineKeyboardMarkup(rows)


def _participant_list_keyboard(trip_id: int, people, page: int, per_page: int = 8) -> InlineKeyboardMarkup:
    start = page * per_page
    page_rows = people[start:start + per_page]
    buttons = []
    for item in page_rows:
        status = STATUS_LABELS.get(item["status"], item["status"])
        prefix = "👤" if item["kind"] == "user" else "📝"
        callback = (
            f"tripadmin:person:{trip_id}:{item['telegram_id']}:{page}"
            if item["kind"] == "user"
            else f"tripadmin:guest:{trip_id}:{item['guest_id']}:{page}"
        )
        buttons.append([InlineKeyboardButton(f"{prefix} {status} | {item['name']}"[:60], callback_data=callback)])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"tripadmin:participants:{trip_id}:{page-1}"))
    if start + per_page < len(people):
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"tripadmin:participants:{trip_id}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("⬅️ اطلاعات سفر", callback_data=f"tripadmin:view:{trip_id}")])
    return InlineKeyboardMarkup(buttons)


def _participant_actions_keyboard(trip_id: int, telegram_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ شرکت کرده", callback_data=f"tripadmin:set:{trip_id}:{telegram_id}:attended:{page}")],
        [InlineKeyboardButton("❌ انصراف", callback_data=f"tripadmin:set:{trip_id}:{telegram_id}:cancelled:{page}")],
        [InlineKeyboardButton("🟡 بازگشت به اعلام حضور", callback_data=f"tripadmin:set:{trip_id}:{telegram_id}:declared:{page}")],
        [InlineKeyboardButton("⬅️ لیست مسافران", callback_data=f"tripadmin:participants:{trip_id}:{page}")],
    ])


def _guest_actions_keyboard(trip_id: int, guest_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ شرکت کرده", callback_data=f"tripadmin:setguest:{trip_id}:{guest_id}:attended:{page}")],
        [InlineKeyboardButton("❌ انصراف", callback_data=f"tripadmin:setguest:{trip_id}:{guest_id}:cancelled:{page}")],
        [InlineKeyboardButton("🟡 اعلام حضور", callback_data=f"tripadmin:setguest:{trip_id}:{guest_id}:declared:{page}")],
        [InlineKeyboardButton("⬅️ لیست مسافران", callback_data=f"tripadmin:participants:{trip_id}:{page}")],
    ])


def _trip_type_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇮🇷 داخلی یک‌روزه — ۵ امتیاز", callback_data=f"{prefix}:domestic_day")],
        [InlineKeyboardButton("🇮🇷 داخلی چندروزه — ۱۵ امتیاز", callback_data=f"{prefix}:domestic_multi")],
        [InlineKeyboardButton("🌍 خارجی — ۱۰۰ امتیاز", callback_data=f"{prefix}:international")],
    ])


def _manual_status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ شرکت کرده", callback_data="manualgueststatus:attended")],
        [InlineKeyboardButton("🟡 اعلام حضور", callback_data="manualgueststatus:declared")],
        [InlineKeyboardButton("❌ انصراف", callback_data="manualgueststatus:cancelled")],
    ])


async def _all_trip_people(db, trip_id: int):
    people = []
    for participant, user in await db.list_trip_participants(trip_id):
        people.append({
            "kind": "user", "participant": participant, "user": user,
            "telegram_id": participant.telegram_id, "guest_id": None,
            "name": user.full_name if user else str(participant.telegram_id),
            "phone": user.phone if user else "", "status": participant.status,
            "declared_at": participant.declared_at,
        })
    for participant, guest in await db.list_guest_trip_participants(trip_id):
        people.append({
            "kind": "guest", "participant": participant, "user": None, "guest": guest,
            "telegram_id": None, "guest_id": guest.id, "name": guest.full_name,
            "phone": guest.phone or "", "status": participant.status,
            "declared_at": participant.declared_at,
        })
    people.sort(key=lambda x: x["declared_at"] or datetime.min.replace(tzinfo=timezone.utc))
    return people


async def _notify_real_user_trip_status(context, trip, user, participant, old_status: str | None) -> None:
    if not user or old_status == participant.status:
        return
    try:
        if participant.status == "attended":
            text = (
                f"🧳 سفر شما ثبت و تأیید شد.\n\n"
                f"حضور شما در «{trip.title}» توسط مدیریت کژوان تأیید شد.\n"
                f"⭐ امتیاز این سفر: {participant.awarded_points or trip.points_value}\n"
                f"🏆 امتیاز کل شما: {user.points}"
            )
        else:
            text = (
                f"🧳 وضعیت سفر «{trip.title}» توسط مدیریت کژوان به "
                f"«{STATUS_LABELS.get(participant.status, participant.status)}» تغییر کرد.\n"
                f"🏆 امتیاز کل شما: {user.points}"
            )
        await context.bot.send_message(chat_id=user.telegram_id, text=text)
    except Exception:
        logger.exception("Could not notify traveler %s about trip status", user.telegram_id)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        me = await context.bot.get_me()
        await update.effective_message.reply_text(
            f"🔐 پنل مدیریت فقط در گفت‌وگوی خصوصی ربات باز می‌شود:\nhttps://t.me/{me.username}?start=admin"
        )
        return
    await update.effective_message.reply_text(
        "🛠 پنل مدیریت کژوان\n\nیک گزینه را انتخاب کنید:",
        reply_markup=_admin_keyboard(),
    )


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    await update.effective_message.reply_text(
        f"شناسه عددی این گفتگو:\n`{update.effective_chat.id}`", parse_mode="Markdown"
    )


async def _stats_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    db = context.application.bot_data["db"]
    users = await db.list_group_users()
    unregistered = await db.list_unregistered_seen_members(limit=5000)
    inactive30 = await db.list_inactive_members(30, limit=5000)
    inactive60 = await db.list_inactive_members(60, limit=5000)
    total_referrals = sum(user.referral_count for user in users)
    total_points = sum(user.points for user in users)
    trips = await db.list_trips(limit=5000)
    guests = await db.list_unlinked_guests(limit=5000)
    return (
        "📊 آمار مدیریتی کژوان\n\n"
        f"اعضای ثبت‌شده در ربات: {len(users)}\n"
        f"اعضای دیده‌شده ولی ثبت‌نام‌نشده: {len(unregistered)}\n"
        f"غیرفعال بیش از ۳۰ روز: {len(inactive30)}\n"
        f"غیرفعال بیش از ۶۰ روز: {len(inactive60)}\n"
        f"معرفی‌های موفق: {total_referrals}\n"
        f"مجموع امتیاز اعضا: {total_points}\n"
        f"تعداد سفرهای ثبت‌شده: {len(trips)}\n"
        f"مسافران موقت بدون پروفایل: {len(guests)}"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_admin(update.effective_user.id, context):
        await update.effective_message.reply_text(await _stats_text(context))


async def members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    users = await context.application.bot_data["db"].list_group_users()
    await update.effective_message.reply_text(
        f"👥 تعداد اعضای ثبت‌شده در ربات: {len(users)}\n\nبرای خروجی Excel از /exportmembers استفاده کنید."
    )


async def registered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await members(update, context)


async def unregistered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    items = await context.application.bot_data["db"].list_unregistered_seen_members(limit=100)
    if not items:
        await update.effective_message.reply_text("✅ فعلاً عضو دیده‌شده و ثبت‌نام‌نشده‌ای نداریم.")
        return
    lines = ["👤 اعضای دیده‌شده ولی ثبت‌نام‌نشده", ""]
    for item in items[:80]:
        username = f"@{item.telegram_username}" if item.telegram_username else "بدون آیدی"
        lines.append(f"• {item.display_name} — {username}")
    await update.effective_message.reply_text("\n".join(lines))


async def _inactive_text(context: ContextTypes.DEFAULT_TYPE, days: int) -> str:
    db = context.application.bot_data["db"]
    members_list = await db.list_inactive_members(days=days, limit=100)
    if not members_list:
        return f"✅ فعلاً عضوی با بیش از {days} روز بی‌فعالیتی نداریم."
    now = datetime.now(timezone.utc)
    lines = [f"⏳ اعضای با بیش از {days} روز بی‌فعالیتی", ""]
    for m in members_list:
        inactive_days = (now - m.last_activity_at).days
        username = f"@{m.telegram_username}" if m.telegram_username else "بدون آیدی"
        lines.append(f"• {m.display_name} — {inactive_days} روز — {username}")
    return "\n".join(lines)


async def inactive30(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_admin(update.effective_user.id, context):
        await update.effective_message.reply_text(await _inactive_text(context, 30))


async def inactive60(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_admin(update.effective_user.id, context):
        await update.effective_message.reply_text(await _inactive_text(context, 60))


async def member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.effective_message.reply_text("مثال: /member KZH-000012 یا /member BTC-000012 یا شماره تماس")
        return
    db = context.application.bot_data["db"]
    users = await db.search_users(query)
    if not users:
        await update.effective_message.reply_text("عضوی با این مشخصات پیدا نشد.")
        return
    lines = [f"🔎 نتیجه جستجو برای «{query}»", ""]
    for user in users[:10]:
        btc = await db.get_btc_membership(user.telegram_id)
        username = f"@{user.telegram_username}" if user.telegram_username else "-"
        lines.extend([
            f"👤 {user.full_name}",
            f"📱 {user.phone} | 📍 {user.city}",
            f"🆔 کژوان: {user.member_code} | BTC: {btc.btc_code if btc else '-'}",
            f"کد معرف: {user.referral_code}",
            f"Telegram: {username} | ID: {user.telegram_id}",
            f"⭐ {user.points} امتیاز | 👥 {user.referral_count} معرفی",
            "—",
        ])
    await update.effective_message.reply_text("\n".join(lines))


async def topreferrals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    users = await context.application.bot_data["db"].list_top_referrers(limit=20)
    if not users:
        await update.effective_message.reply_text("هنوز معرفی موفقی ثبت نشده است.")
        return
    text = "🏆 معرف‌های برتر\n\n" + "\n".join(
        f"{i}. {u.full_name} — {u.referral_count} معرفی — {u.points} امتیاز"
        for i, u in enumerate(users, 1)
    )
    await update.effective_message.reply_text(text)


async def _member_export_rows(db, users):
    headers = [
        "نام و نام خانوادگی", "شماره تماس", "شهر", "Username", "Telegram ID",
        "کد عضویت کژوان", "کد عضویت BTC", "کد معرف کژوان", "معرف Telegram ID",
        "تعداد معرفی موفق", "امتیاز کل", "نحوه آشنایی", "تاریخ ثبت",
        "آخرین فعالیت", "وضعیت", "تاریخچه سفرهای داخلی", "تاریخچه سفرهای خارجی",
    ]
    histories = {}
    for participant, trip in await db.list_all_trip_history():
        bucket = histories.setdefault(participant.telegram_id, {"domestic": [], "international": []})
        target = "international" if trip.trip_type == "international" else "domestic"
        type_label = TRIP_TYPE_LABELS.get(trip.trip_type, trip.trip_type)
        text = (
            f"{trip.title} [{type_label}] ({trip.start_date_text} تا {trip.end_date_text}) - "
            f"{STATUS_LABELS.get(participant.status, participant.status)} - {participant.awarded_points or 0} امتیاز"
        )
        bucket[target].append(text)
    rows = []
    for user in users:
        btc = await db.get_btc_membership(user.telegram_id)
        history = histories.get(user.telegram_id, {"domestic": [], "international": []})
        rows.append([
            user.full_name, user.phone, user.city,
            f"@{user.telegram_username}" if user.telegram_username else "", user.telegram_id,
            user.member_code or "", btc.btc_code if btc else "", user.referral_code or "",
            user.referred_by_telegram_id or "", user.referral_count, user.points, user.discovery_source,
            user.created_at.isoformat() if user.created_at else "",
            user.last_activity_at.isoformat() if user.last_activity_at else "", user.status,
            " | ".join(history["domestic"]), " | ".join(history["international"]),
        ])
    return headers, rows


async def _send_xlsx(update: Update, headers, rows, filename: str, sheet_name: str) -> None:
    file_obj = build_xlsx(headers, rows, sheet_name=sheet_name)
    await update.effective_message.reply_document(file_obj, filename=filename, caption=f"📥 {filename}")


async def exportmembers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    db = context.application.bot_data["db"]
    users = await db.list_group_users()
    headers, rows = await _member_export_rows(db, users)
    await _send_xlsx(update, headers, rows, "kazhwan_members.xlsx", "Members")


async def exportinactive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    db = context.application.bot_data["db"]
    items = await db.list_inactive_members(30, limit=5000)
    now = datetime.now(timezone.utc)
    headers = ["نام", "Username", "Telegram ID", "روزهای بی‌فعالیتی", "آخرین فعالیت"]
    rows = [[m.display_name, f"@{m.telegram_username}" if m.telegram_username else "", m.telegram_id,
             (now-m.last_activity_at).days, m.last_activity_at.isoformat()] for m in items]
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


def _trip_export_data(trip, people):
    headers = [
        "نوع رکورد", "نام", "شماره تماس", "شهر", "Username", "Telegram ID", "کد عضویت کژوان",
        "وضعیت", "تاریخ ثبت", "نام سفر", "نوع سفر", "امتیاز سفر", "امتیاز اعطاشده/معوق", "کد سفر",
    ]
    rows = []
    for item in people:
        participant = item["participant"]
        if item["kind"] == "user":
            user = item["user"]
            rows.append([
                "پروفایل کژوان", user.full_name if user else item["name"], user.phone if user else "",
                user.city if user else "", f"@{user.telegram_username}" if user and user.telegram_username else "",
                participant.telegram_id, user.member_code if user else "",
                STATUS_LABELS.get(participant.status, participant.status),
                participant.declared_at.isoformat() if participant.declared_at else "", trip.title,
                TRIP_TYPE_LABELS.get(trip.trip_type, trip.trip_type), trip.points_value,
                participant.awarded_points or 0, trip.trip_code,
            ])
        else:
            guest = item["guest"]
            rows.append([
                "مسافر موقت", guest.full_name, guest.phone or "", "", "", "", "",
                STATUS_LABELS.get(participant.status, participant.status),
                participant.declared_at.isoformat() if participant.declared_at else "", trip.title,
                TRIP_TYPE_LABELS.get(trip.trip_type, trip.trip_type), trip.points_value,
                participant.pending_points or 0, trip.trip_code,
            ])
    return headers, rows


async def manual_trip_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not is_admin(query.from_user.id, context) or query.message.chat.type != ChatType.PRIVATE:
        return ConversationHandler.END
    await query.answer()
    context.user_data.clear()
    context.user_data["admin_flow"] = "manual_trip"
    await query.message.reply_text("🧳 نام سفر را وارد کنید:", reply_markup=ForceReply(selective=True))
    return MANUAL_TRIP_TITLE


async def manual_trip_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if len(value) < 2:
        await update.effective_message.reply_text("نام سفر را کامل وارد کنید.")
        return MANUAL_TRIP_TITLE
    context.user_data["manual_trip_title"] = value
    await update.effective_message.reply_text("نوع سفر را انتخاب کنید:", reply_markup=_trip_type_keyboard("manualtriptype"))
    return MANUAL_TRIP_TYPE


async def manual_trip_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return MANUAL_TRIP_TYPE
    await query.answer()
    context.user_data["manual_trip_type"] = query.data.split(":", 1)[1]
    await query.message.reply_text("📅 تاریخ شروع را وارد کنید:", reply_markup=ForceReply(selective=True))
    return MANUAL_TRIP_START


async def manual_trip_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if not value:
        return MANUAL_TRIP_START
    context.user_data["manual_trip_start"] = value
    await update.effective_message.reply_text("📅 تاریخ پایان را وارد کنید:", reply_markup=ForceReply(selective=True))
    return MANUAL_TRIP_END


async def manual_trip_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if not value:
        return MANUAL_TRIP_END
    context.user_data["manual_trip_end"] = value
    db = context.application.bot_data["db"]
    similar = await db.find_similar_trips(
        context.user_data["manual_trip_title"],
        context.user_data["manual_trip_start"],
        value,
        context.user_data["manual_trip_type"],
        limit=5,
    )
    if similar:
        rows = [[InlineKeyboardButton(
            f"🔗 استفاده از {trip.title} | {trip.trip_code}"[:60],
            callback_data=f"manualtripdupe:use:{trip.id}"
        )] for trip in similar]
        rows.append([InlineKeyboardButton("➕ با وجود شباهت، سفر جدید بساز", callback_data="manualtripdupe:new")])
        await update.effective_message.reply_text(
            "⚠️ یک سفر مشابه از قبل ثبت شده است.\n"
            "برای جلوگیری از رکورد تکراری، سفر موجود را انتخاب کنید یا آگاهانه سفر جدید بسازید.",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return MANUAL_TRIP_DUPLICATE
    return await _create_manual_trip_from_context(update, context)


async def _create_manual_trip_from_context(update_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = context.application.bot_data["db"]
    user = update_or_query.effective_user if isinstance(update_or_query, Update) else update_or_query.from_user
    trip = await db.create_manual_trip(
        title=context.user_data["manual_trip_title"],
        start_date_text=context.user_data["manual_trip_start"],
        end_date_text=context.user_data["manual_trip_end"],
        trip_type=context.user_data["manual_trip_type"],
        created_by_telegram_id=user.id,
    )
    context.user_data.clear()
    message = update_or_query.effective_message if isinstance(update_or_query, Update) else update_or_query.message
    await message.reply_text(
        f"✅ سفر «{trip.title}» ثبت شد.\n🆔 {trip.trip_code}\n"
        f"نوع: {TRIP_TYPE_LABELS.get(trip.trip_type, trip.trip_type)}\n⭐ امتیاز: {trip.points_value}\n\n"
        "این سفر بدون گروه تلگرام هم قابل مدیریت است.",
        reply_markup=_trip_actions_keyboard(trip),
    )
    return ConversationHandler.END


async def manual_trip_duplicate_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return MANUAL_TRIP_DUPLICATE
    await query.answer()
    if query.data == "manualtripdupe:new":
        return await _create_manual_trip_from_context(query, context)
    trip_id = int(query.data.rsplit(":", 1)[1])
    trip = await context.application.bot_data["db"].get_trip(trip_id)
    context.user_data.clear()
    if not trip:
        await query.message.reply_text("سفر موجود پیدا نشد؛ دوباره تلاش کنید.")
        return ConversationHandler.END
    await query.message.reply_text(
        f"✅ از سفر موجود استفاده می‌کنیم: «{trip.title}» | {trip.trip_code}",
        reply_markup=_trip_actions_keyboard(trip),
    )
    return ConversationHandler.END


async def manual_guest_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not is_admin(query.from_user.id, context) or query.message.chat.type != ChatType.PRIVATE:
        return ConversationHandler.END
    await query.answer()
    trip_id = int(query.data.rsplit(":", 1)[1])
    trip = await context.application.bot_data["db"].get_trip(trip_id)
    if not trip:
        await query.message.reply_text("سفر پیدا نشد.")
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["admin_flow"] = "manual_guest"
    context.user_data["manual_guest_trip_id"] = trip_id
    await query.message.reply_text(
        f"➕ افزودن مسافر به «{trip.title}»\n\nنام و نام خانوادگی مسافر را وارد کنید:",
        reply_markup=ForceReply(selective=True),
    )
    return MANUAL_GUEST_NAME


async def manual_guest_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if len(value.split()) < 2:
        await update.effective_message.reply_text("نام و نام خانوادگی را کامل وارد کنید.")
        return MANUAL_GUEST_NAME
    context.user_data["manual_guest_name"] = value
    await update.effective_message.reply_text(
        "شماره موبایل را وارد کنید. اگر ندارید فقط - بفرستید:",
        reply_markup=ForceReply(selective=True),
    )
    return MANUAL_GUEST_PHONE


async def manual_guest_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.effective_message.text or "").strip()
    phone = None if raw in {"-", "ندارم", ""} else raw
    context.user_data["manual_guest_phone"] = phone
    db = context.application.bot_data["db"]
    matched = await db.find_exact_user(context.user_data["manual_guest_name"], phone)
    if matched:
        context.user_data["manual_guest_matched_telegram_id"] = matched.telegram_id
        await update.effective_message.reply_text(
            f"✅ پروفایل کژوان پیدا شد: {matched.full_name} | {matched.member_code}\nوضعیت این سفر را انتخاب کنید:",
            reply_markup=_manual_status_keyboard(),
        )
    else:
        await update.effective_message.reply_text(
            "این شخص پروفایل قطعی کژوان ندارد؛ به‌عنوان «مسافر موقت» ثبت می‌شود.\n"
            "بعداً هنگام ثبت‌نام واقعی، سابقه با تأیید مدیر به پروفایل او متصل می‌شود.\n\n"
            "وضعیت سفر را انتخاب کنید:",
            reply_markup=_manual_status_keyboard(),
        )
    return MANUAL_GUEST_STATUS


async def manual_guest_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return MANUAL_GUEST_STATUS
    await query.answer()
    status = query.data.split(":", 1)[1]
    db = context.application.bot_data["db"]
    trip_id = int(context.user_data["manual_guest_trip_id"])
    trip = await db.get_trip(trip_id)
    matched_id = context.user_data.get("manual_guest_matched_telegram_id")
    if matched_id:
        existing_rows = await db.list_trip_participants(trip_id)
        previous = next((p for p, _ in existing_rows if p.telegram_id == matched_id), None)
        old_status = previous.status if previous else None
        await db.register_trip_participant(trip_id, matched_id)
        participant = await db.set_trip_participant_status(trip_id, matched_id, status)
        user = await db.get_user(matched_id)
        await _notify_real_user_trip_status(context, trip, user, participant, old_status)
        text = f"✅ {user.full_name if user else matched_id} به سفر اضافه شد: {STATUS_LABELS.get(status, status)}"
        if participant and participant.points_awarded:
            text += f"\n⭐ {participant.awarded_points} امتیاز ثبت شد."
    else:
        guest = await db.create_or_get_guest(
            context.user_data["manual_guest_name"],
            context.user_data.get("manual_guest_phone"),
            query.from_user.id,
        )
        participant = await db.register_guest_trip_participant(trip_id, guest.id, status=status)
        text = (
            f"✅ {guest.full_name} به‌صورت مسافر موقت ثبت شد.\n"
            f"وضعیت: {STATUS_LABELS.get(status, status)}"
        )
        if participant.pending_points:
            text += f"\n⭐ {participant.pending_points} امتیاز به‌صورت معوق نگه داشته شد."
    context.user_data.clear()
    await query.message.reply_text(text, reply_markup=_trip_actions_keyboard(trip))
    return ConversationHandler.END


async def admin_flow_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("فرآیند مدیریتی لغو شد.")
    return ConversationHandler.END


def build_admin_flow_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(manual_trip_start, pattern=r"^tripadmin:new$"),
            CallbackQueryHandler(manual_guest_start, pattern=r"^tripadmin:addguest:\d+$"),
        ],
        states={
            MANUAL_TRIP_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_trip_title)],
            MANUAL_TRIP_TYPE: [CallbackQueryHandler(manual_trip_type, pattern=r"^manualtriptype:(domestic_day|domestic_multi|international)$")],
            MANUAL_TRIP_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_trip_start_date)],
            MANUAL_TRIP_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_trip_end_date)],
            MANUAL_TRIP_DUPLICATE: [CallbackQueryHandler(manual_trip_duplicate_choice, pattern=r"^manualtripdupe:(?:use:\d+|new)$")],
            MANUAL_GUEST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_guest_name)],
            MANUAL_GUEST_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, manual_guest_phone)],
            MANUAL_GUEST_STATUS: [CallbackQueryHandler(manual_guest_status, pattern=r"^manualgueststatus:(declared|attended|cancelled)$")],
        },
        fallbacks=[CommandHandler("cancel", admin_flow_cancel)],
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_admin(query.from_user.id, context):
        return
    await query.answer()
    action = query.data.split(":", 1)[1]
    if action == "home":
        await query.message.reply_text("🛠 پنل مدیریت کژوان", reply_markup=_admin_keyboard())
    elif action == "stats":
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
        db = context.application.bot_data["db"]
        users = await db.list_group_users()
        headers, rows = await _member_export_rows(db, users)
        await query.message.reply_document(build_xlsx(headers, rows, sheet_name="Members"), filename="kazhwan_all_members.xlsx")
    elif action == "memberhelp":
        await query.message.reply_text("🔎 جستجوی عضو:\n/member نام یا شماره یا کد عضویت")
    elif action == "guests":
        guests = await context.application.bot_data["db"].list_unlinked_guests(limit=50)
        if not guests:
            await query.message.reply_text("✅ مسافر موقتِ بدون پروفایل نداریم.")
        else:
            lines = ["📝 مسافران موقت بدون پروفایل", ""]
            for guest in guests:
                lines.append(f"• {guest.full_name} — {guest.phone or 'بدون شماره'}")
            lines.append("\nبعد از ثبت‌نام واقعی، ربات تطبیق احتمالی را برای تأیید به مدیر پیشنهاد می‌دهد.")
            await query.message.reply_text("\n".join(lines))
    elif action == "trips":
        trips = await _list_trips_compat(context.application.bot_data["db"], limit=30)
        await query.message.reply_text(
            "🧳 مدیریت سفرها\n\nسفر موردنظر را انتخاب کنید:" if trips else "🧳 هنوز سفری ثبت نشده است. سفر جدید تعریف کنید:",
            reply_markup=_trip_list_keyboard(trips),
        )


async def trip_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_admin(query.from_user.id, context):
        return
    await query.answer()
    if query.message.chat.type != ChatType.PRIVATE:
        await query.message.reply_text("مدیریت سفرها فقط در PV ربات انجام می‌شود.")
        return
    parts = query.data.split(":")
    action = parts[1]
    db = context.application.bot_data["db"]

    if action == "archived":
        trips = await db.list_archived_trips(limit=30)
        rows = []
        for trip in trips:
            suffix = f" → {trip.merged_into_trip_id}" if trip.merged_into_trip_id else ""
            rows.append([InlineKeyboardButton(
                f"🗃 {trip.title} | {trip.trip_code}{suffix}"[:60],
                callback_data=f"tripadmin:archivedview:{trip.id}",
            )])
        rows.append([InlineKeyboardButton("⬅️ سفرهای فعال", callback_data="admin:trips")])
        await query.message.reply_text(
            "🗃 سفرهای آرشیوشده" if trips else "هیچ سفر آرشیوشده‌ای وجود ندارد.",
            reply_markup=InlineKeyboardMarkup(rows),
        )
    elif action == "archivedview":
        trip = await db.get_trip(int(parts[2]))
        if not trip:
            await query.message.reply_text("سفر پیدا نشد.")
            return
        rows = []
        if trip.merged_into_trip_id is None:
            rows.append([InlineKeyboardButton("♻️ بازیابی سفر", callback_data=f"tripadmin:restore:{trip.id}")])
        rows.append([InlineKeyboardButton("⬅️ آرشیو", callback_data="tripadmin:archived")])
        merged = f"\n🔀 ادغام‌شده در سفر ID {trip.merged_into_trip_id}" if trip.merged_into_trip_id else ""
        await query.message.reply_text(
            f"🗃 {trip.title}\n🆔 {trip.trip_code}\n📅 {trip.start_date_text} تا {trip.end_date_text}{merged}",
            reply_markup=InlineKeyboardMarkup(rows),
        )
    elif action == "archive":
        trip = await db.get_trip(int(parts[2]))
        if not trip:
            await query.message.reply_text("سفر پیدا نشد.")
            return
        people = await _all_trip_people(db, trip.id)
        await query.message.reply_text(
            f"⚠️ آرشیو «{trip.title}»؟\n\n{len(people)} مسافر به این سفر متصل هستند. "
            "سفر از تاریخچه فعال حذف می‌شود و امتیازهای همین سفر موقتاً برگردانده می‌شوند؛ بعداً امکان بازیابی وجود دارد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 بله، آرشیو کن", callback_data=f"tripadmin:archiveconfirm:{trip.id}")],
                [InlineKeyboardButton("لغو", callback_data=f"tripadmin:view:{trip.id}")],
            ]),
        )
    elif action == "archiveconfirm":
        trip = await db.archive_trip(int(parts[2]))
        await query.message.reply_text(
            f"✅ سفر «{trip.title}» آرشیو شد." if trip else "سفر پیدا نشد یا قبلاً آرشیو شده است.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ سفرها", callback_data="admin:trips")]]),
        )
    elif action == "restore":
        trip = await db.restore_trip(int(parts[2]))
        if not trip:
            await query.message.reply_text("این سفر قابل بازیابی نیست؛ ممکن است در سفر دیگری ادغام شده باشد.")
            return
        await query.message.reply_text(
            f"♻️ سفر «{trip.title}» بازیابی شد و امتیاز حضورهای تأییدشده دوباره اعمال شد.",
            reply_markup=_trip_actions_keyboard(trip),
        )
    elif action == "merge":
        source = await db.get_trip(int(parts[2]))
        if not source:
            await query.message.reply_text("سفر پیدا نشد.")
            return
        candidates = [t for t in await db.list_trips(limit=50) if t.id != source.id]
        similar = await db.find_similar_trips(source.title, source.start_date_text, source.end_date_text, source.trip_type, exclude_trip_id=source.id, limit=50)
        similar_ids = {t.id for t in similar}
        candidates.sort(key=lambda t: (0 if t.id in similar_ids else 1, -t.id))
        rows = []
        for target in candidates[:25]:
            marker = "⭐ " if target.id in similar_ids else ""
            rows.append([InlineKeyboardButton(
                f"{marker}{target.title} | {target.trip_code}"[:60],
                callback_data=f"tripadmin:mergetarget:{source.id}:{target.id}",
            )])
        rows.append([InlineKeyboardButton("لغو", callback_data=f"tripadmin:view:{source.id}")])
        await query.message.reply_text(
            f"🔀 سفر مقصد برای ادغام «{source.title}» را انتخاب کنید.\n⭐ موارد مشابه بالاتر نمایش داده شده‌اند.",
            reply_markup=InlineKeyboardMarkup(rows),
        )
    elif action == "mergetarget":
        source_id, target_id = int(parts[2]), int(parts[3])
        source, target = await db.get_trip(source_id), await db.get_trip(target_id)
        if not source or not target:
            await query.message.reply_text("یکی از سفرها پیدا نشد.")
            return
        await query.message.reply_text(
            f"⚠️ ادغام نهایی؟\n\nاز: {source.title} | {source.trip_code}\nبه: {target.title} | {target.trip_code}\n\n"
            "مسافران یکی می‌شوند، امتیاز تکراری حذف می‌شود و سفر اول آرشیو خواهد شد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأیید ادغام", callback_data=f"tripadmin:mergeconfirm:{source_id}:{target_id}")],
                [InlineKeyboardButton("لغو", callback_data=f"tripadmin:view:{source_id}")],
            ]),
        )
    elif action == "mergeconfirm":
        source_id, target_id = int(parts[2]), int(parts[3])
        result = await db.merge_trips(source_id, target_id)
        if not result:
            await query.message.reply_text("ادغام انجام نشد؛ وضعیت سفرها را بررسی کنید.")
            return
        warning = "\n⚠️ هر دو سفر گروه جدا داشتند؛ گروه سفر مبدأ از رکورد آرشیوی جدا شد." if result["source_group_detached"] else ""
        await query.message.reply_text(
            f"✅ «{result['source_title']}» در «{result['target_title']}» ادغام شد.\n"
            f"👤 مسافر واقعی منتقل‌شده: {result['moved_real']}\n📝 مسافر موقت: {result['moved_guests']}\n"
            f"⭐ اصلاح خالص امتیازها: {result['points_delta']}{warning}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("مشاهده سفر مقصد", callback_data=f"tripadmin:view:{target_id}")]]),
        )
    elif action == "view":
        trip = await db.get_trip(int(parts[2]))
        if not trip:
            await query.message.reply_text("سفر پیدا نشد.")
            return
        people = await _all_trip_people(db, trip.id)
        attended = sum(1 for item in people if item["status"] == "attended")
        declared = sum(1 for item in people if item["status"] == "declared")
        cancelled = sum(1 for item in people if item["status"] == "cancelled")
        guests = sum(1 for item in people if item["kind"] == "guest")
        group_text = "متصل به گروه تلگرام" if trip.telegram_chat_id else "ثبت دستی — بدون گروه"
        await query.message.reply_text(
            f"🧳 {trip.title}\n🆔 {trip.trip_code}\n📅 {trip.start_date_text} تا {trip.end_date_text}\n"
            f"نوع: {TRIP_TYPE_LABELS.get(trip.trip_type, trip.trip_type)}\n⭐ امتیاز: {trip.points_value}\n"
            f"وضعیت: {TRIP_STATUS_LABELS.get(trip.status, trip.status)}\n📌 {group_text}\n\n"
            f"🟡 اعلام حضور: {declared}\n🟢 شرکت کرده: {attended}\n⚪ انصراف: {cancelled}\n"
            f"📝 مسافر موقت: {guests}",
            reply_markup=_trip_actions_keyboard(trip),
        )
    elif action == "participants":
        trip_id, page = int(parts[2]), int(parts[3])
        trip = await db.get_trip(trip_id)
        people = await _all_trip_people(db, trip_id)
        if not people:
            await query.message.reply_text("هنوز مسافری برای این سفر ثبت نشده است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ اطلاعات سفر", callback_data=f"tripadmin:view:{trip_id}")]]))
            return
        await query.message.reply_text(
            f"👥 مسافران — {trip.title if trip else trip_id}\n👤 پروفایل کژوان | 📝 مسافر موقت\nروی نام هر مسافر بزنید:",
            reply_markup=_participant_list_keyboard(trip_id, people, page),
        )
    elif action == "person":
        trip_id, telegram_id, page = int(parts[2]), int(parts[3]), int(parts[4])
        rows = await db.list_trip_participants(trip_id)
        found = next(((p,u) for p,u in rows if p.telegram_id == telegram_id), None)
        if not found:
            await query.message.reply_text("مسافر پیدا نشد.")
            return
        participant, user = found
        name = user.full_name if user else str(telegram_id)
        await query.message.reply_text(
            f"👤 {name}\n📱 {user.phone if user else '-'}\n🆔 {user.member_code if user else '-'}\n"
            f"وضعیت فعلی: {STATUS_LABELS.get(participant.status, participant.status)}\n"
            f"امتیاز اعطاشده: {participant.awarded_points or 0}",
            reply_markup=_participant_actions_keyboard(trip_id, telegram_id, page),
        )
    elif action == "set":
        trip_id, telegram_id, status, page = int(parts[2]), int(parts[3]), parts[4], int(parts[5])
        current_rows = await db.list_trip_participants(trip_id)
        current = next((p for p, _ in current_rows if p.telegram_id == telegram_id), None)
        old_status = current.status if current else None
        if old_status == status:
            await query.message.reply_text("این مسافر از قبل همین وضعیت را دارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ لیست مسافران", callback_data=f"tripadmin:participants:{trip_id}:{page}")]]))
            return
        participant = await db.set_trip_participant_status(trip_id, telegram_id, status)
        if not participant:
            await query.message.reply_text("این مسافر در این سفر ثبت نشده است.")
            return
        user = await db.get_user(telegram_id)
        trip = await db.get_trip(trip_id)
        await _notify_real_user_trip_status(context, trip, user, participant, old_status)
        extra = f"\n⭐ امتیاز سفر: {participant.awarded_points}" if participant.points_awarded else ""
        await query.message.reply_text(
            f"✅ وضعیت {user.full_name if user else telegram_id} به «{STATUS_LABELS.get(status, status)}» تغییر کرد.{extra}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ لیست مسافران", callback_data=f"tripadmin:participants:{trip_id}:{page}")]]),
        )
    elif action == "guest":
        trip_id, guest_id, page = int(parts[2]), int(parts[3]), int(parts[4])
        guest = await db.get_guest(guest_id)
        rows = await db.list_guest_trip_participants(trip_id)
        found = next(((p, g) for p, g in rows if g.id == guest_id), None)
        if not guest or not found:
            await query.message.reply_text("مسافر موقت پیدا نشد.")
            return
        participant, _ = found
        await query.message.reply_text(
            f"📝 مسافر موقت\n👤 {guest.full_name}\n📱 {guest.phone or '-'}\n"
            f"وضعیت: {STATUS_LABELS.get(participant.status, participant.status)}\n"
            f"⭐ امتیاز معوق: {participant.pending_points or 0}",
            reply_markup=_guest_actions_keyboard(trip_id, guest_id, page),
        )
    elif action == "setguest":
        trip_id, guest_id, status, page = int(parts[2]), int(parts[3]), parts[4], int(parts[5])
        participant = await db.set_guest_trip_participant_status(trip_id, guest_id, status)
        guest = await db.get_guest(guest_id)
        if not participant or not guest:
            await query.message.reply_text("مسافر موقت پیدا نشد.")
            return
        extra = f"\n⭐ امتیاز معوق: {participant.pending_points}" if participant.pending_points else ""
        await query.message.reply_text(
            f"✅ وضعیت {guest.full_name} به «{STATUS_LABELS.get(status, status)}» تغییر کرد.{extra}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ لیست مسافران", callback_data=f"tripadmin:participants:{trip_id}:{page}")]]),
        )
    elif action == "status":
        trip_id, status = int(parts[2]), parts[3]
        trip = await db.set_trip_status(trip_id, status)
        if trip:
            await query.message.reply_text(
                f"✅ وضعیت سفر «{trip.title}» به {TRIP_STATUS_LABELS.get(status, status)} تغییر کرد.",
                reply_markup=_trip_actions_keyboard(trip),
            )
    elif action == "export":
        trip_id = int(parts[2])
        trip = await db.get_trip(trip_id)
        if not trip:
            await query.message.reply_text("سفر پیدا نشد.")
            return
        people = await _all_trip_people(db, trip_id)
        headers, rows = _trip_export_data(trip, people)
        await query.message.reply_document(
            build_xlsx(headers, rows, sheet_name="Trip"),
            filename=f"{trip.trip_code}_participants.xlsx",
            caption=f"📥 خروجی {trip.title}",
        )


async def guest_match_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_admin(query.from_user.id, context):
        return
    await query.answer()
    parts = query.data.split(":")
    action, guest_id, telegram_id = parts[1], int(parts[2]), int(parts[3])
    if action == "skip":
        await query.edit_message_text("این تطبیق فعلاً نادیده گرفته شد.")
        return
    db = context.application.bot_data["db"]
    result = await db.link_guest_to_user(guest_id, telegram_id)
    if not result:
        await query.edit_message_text("این سابقه قبلاً متصل شده یا دیگر قابل اتصال نیست.")
        return
    trips_text = "، ".join(result["trip_titles"]) if result["trip_titles"] else "بدون سفر"
    await query.edit_message_text(
        f"✅ سابقه «{result['guest_name']}» به پروفایل {result['user_name']} متصل شد.\n"
        f"سفرها: {trips_text}\n⭐ امتیاز منتقل‌شده: {result['points_added']}"
    )
    try:
        await context.bot.send_message(
            chat_id=telegram_id,
            text=(
                "🔗 سابقه سفرهای قبلی شما توسط مدیریت کژوان به پروفایل‌تان متصل شد.\n"
                f"🧳 {trips_text}\n⭐ امتیاز افزوده‌شده: {result['points_added']}\n"
                f"🏆 امتیاز کل: {result['total_points']}"
            ),
        )
    except Exception:
        logger.exception("Could not notify linked guest traveler %s", telegram_id)


def admin_handlers():
    return [
        build_admin_flow_handler(),
        CommandHandler("admin", admin_panel), CommandHandler("chatid", chatid), CommandHandler("stats", stats),
        CommandHandler("members", members), CommandHandler("registered", registered), CommandHandler("unregistered", unregistered),
        CommandHandler("inactive30", inactive30), CommandHandler("inactive60", inactive60), CommandHandler("member", member),
        CommandHandler("topreferrals", topreferrals), CommandHandler("referrals", topreferrals),
        CommandHandler("exportmembers", exportmembers), CommandHandler("exportinactive", exportinactive),
        CommandHandler("exportreferrals", exportreferrals), CommandHandler("exportall", exportall),
        CallbackQueryHandler(admin_callback, pattern=r"^admin:"),
        CallbackQueryHandler(guest_match_callback, pattern=r"^guestmatch:(link|skip):\d+:\d+$"),
        CallbackQueryHandler(trip_admin_callback, pattern=r"^tripadmin:"),
    ]
