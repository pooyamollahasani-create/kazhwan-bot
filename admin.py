from __future__ import annotations

from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from bot.utils.xlsx import build_xlsx


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
}


def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = context.application.bot_data["settings"]
    return user_id in settings.admin_ids


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
        [InlineKeyboardButton("🔎 راهنمای جستجوی عضو", callback_data="admin:memberhelp")],
    ])


def _back_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="admin:home")]])


def _trip_list_keyboard(trips) -> InlineKeyboardMarkup:
    rows = []
    for trip in trips[:30]:
        label = f"{TRIP_STATUS_LABELS.get(trip.status, trip.status)} | {trip.title} | {trip.trip_code}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"tripadmin:view:{trip.id}")])
    rows.append([InlineKeyboardButton("⬅️ پنل مدیریت", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def _trip_actions_keyboard(trip) -> InlineKeyboardMarkup:
    rows = [
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
    rows.extend([
        [InlineKeyboardButton("⬅️ سفرها", callback_data="admin:trips")],
        [InlineKeyboardButton("🏠 پنل مدیریت", callback_data="admin:home")],
    ])
    return InlineKeyboardMarkup(rows)


def _participant_list_keyboard(trip_id: int, rows, page: int, per_page: int = 8) -> InlineKeyboardMarkup:
    start = page * per_page
    page_rows = rows[start:start + per_page]
    buttons = []
    for participant, user in page_rows:
        name = user.full_name if user else str(participant.telegram_id)
        status = STATUS_LABELS.get(participant.status, participant.status)
        buttons.append([
            InlineKeyboardButton(
                f"{status} | {name}"[:60],
                callback_data=f"tripadmin:person:{trip_id}:{participant.telegram_id}:{page}",
            )
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"tripadmin:participants:{trip_id}:{page-1}"))
    if start + per_page < len(rows):
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
    return (
        "📊 آمار مدیریتی کژوان\n\n"
        f"اعضای ثبت‌شده در ربات: {len(users)}\n"
        f"اعضای دیده‌شده ولی ثبت‌نام‌نشده: {len(unregistered)}\n"
        f"غیرفعال بیش از ۳۰ روز: {len(inactive30)}\n"
        f"غیرفعال بیش از ۶۰ روز: {len(inactive60)}\n"
        f"معرفی‌های موفق: {total_referrals}\n"
        f"مجموع امتیاز اعضا: {total_points}\n"
        f"تعداد سفرهای ثبت‌شده: {len(trips)}"
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


def _trip_export_data(trip, items):
    headers = [
        "نام", "شماره تماس", "شهر", "Username", "Telegram ID", "کد عضویت کژوان",
        "وضعیت", "تاریخ اعلام حضور", "نام سفر", "نوع سفر", "امتیاز سفر", "امتیاز اعطاشده", "کد سفر",
    ]
    rows = []
    for participant, user in items:
        rows.append([
            user.full_name if user else "", user.phone if user else "", user.city if user else "",
            f"@{user.telegram_username}" if user and user.telegram_username else "", participant.telegram_id,
            user.member_code if user else "", STATUS_LABELS.get(participant.status, participant.status),
            participant.declared_at.isoformat() if participant.declared_at else "", trip.title,
            TRIP_TYPE_LABELS.get(trip.trip_type, trip.trip_type), trip.points_value,
            participant.awarded_points or 0, trip.trip_code,
        ])
    return headers, rows


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
    elif action == "trips":
        trips = await context.application.bot_data["db"].list_trips(limit=30)
        if not trips:
            await query.message.reply_text("هنوز سفری ثبت نشده است.", reply_markup=_back_admin_keyboard())
        else:
            await query.message.reply_text("🧳 مدیریت سفرها\n\nسفر موردنظر را انتخاب کنید:", reply_markup=_trip_list_keyboard(trips))


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

    if action == "view":
        trip = await db.get_trip(int(parts[2]))
        if not trip:
            await query.message.reply_text("سفر پیدا نشد.")
            return
        items = await db.list_trip_participants(trip.id)
        attended = sum(1 for p, _ in items if p.status == "attended")
        declared = sum(1 for p, _ in items if p.status == "declared")
        cancelled = sum(1 for p, _ in items if p.status == "cancelled")
        await query.message.reply_text(
            f"🧳 {trip.title}\n🆔 {trip.trip_code}\n📅 {trip.start_date_text} تا {trip.end_date_text}\n"
            f"نوع: {TRIP_TYPE_LABELS.get(trip.trip_type, trip.trip_type)}\n⭐ امتیاز: {trip.points_value}\n"
            f"وضعیت: {TRIP_STATUS_LABELS.get(trip.status, trip.status)}\n\n"
            f"🟡 اعلام حضور: {declared}\n🟢 شرکت کرده: {attended}\n⚪ انصراف: {cancelled}",
            reply_markup=_trip_actions_keyboard(trip),
        )
    elif action == "participants":
        trip_id, page = int(parts[2]), int(parts[3])
        trip = await db.get_trip(trip_id)
        rows = await db.list_trip_participants(trip_id)
        if not rows:
            await query.message.reply_text("هنوز مسافری برای این سفر ثبت نشده است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ اطلاعات سفر", callback_data=f"tripadmin:view:{trip_id}")]]))
            return
        await query.message.reply_text(
            f"👥 مسافران — {trip.title if trip else trip_id}\nروی نام هر مسافر بزنید:",
            reply_markup=_participant_list_keyboard(trip_id, rows, page),
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
        participant = await db.set_trip_participant_status(trip_id, telegram_id, status)
        if not participant:
            await query.message.reply_text("این مسافر در این سفر ثبت نشده است.")
            return
        user = await db.get_user(telegram_id)
        extra = f"\n⭐ امتیاز سفر: {participant.awarded_points}" if participant.points_awarded else ""
        await query.message.reply_text(
            f"✅ وضعیت {user.full_name if user else telegram_id} به «{STATUS_LABELS.get(status, status)}» تغییر کرد.{extra}",
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
        items = await db.list_trip_participants(trip_id)
        headers, rows = _trip_export_data(trip, items)
        await query.message.reply_document(
            build_xlsx(headers, rows, sheet_name="Trip"),
            filename=f"{trip.trip_code}_participants.xlsx",
            caption=f"📥 خروجی {trip.title}",
        )


def admin_handlers():
    return [
        CommandHandler("admin", admin_panel), CommandHandler("chatid", chatid), CommandHandler("stats", stats),
        CommandHandler("members", members), CommandHandler("registered", registered), CommandHandler("unregistered", unregistered),
        CommandHandler("inactive30", inactive30), CommandHandler("inactive60", inactive60), CommandHandler("member", member),
        CommandHandler("topreferrals", topreferrals), CommandHandler("referrals", topreferrals),
        CommandHandler("exportmembers", exportmembers), CommandHandler("exportinactive", exportinactive),
        CommandHandler("exportreferrals", exportreferrals), CommandHandler("exportall", exportall),
        CallbackQueryHandler(admin_callback, pattern=r"^admin:"),
        CallbackQueryHandler(trip_admin_callback, pattern=r"^tripadmin:"),
    ]
