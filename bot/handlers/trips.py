from __future__ import annotations

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.handlers.admin import is_admin
from bot.keyboards import trip_confirm_keyboard, trip_register_link_keyboard
from bot.utils.xlsx import build_xlsx

TRIP_TITLE, TRIP_TYPE, TRIP_START, TRIP_END, TRIP_DUPLICATE = range(5)

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


def _trip_type_label(trip_type: str) -> str:
    return TRIP_TYPE_LABELS.get(trip_type, trip_type)


def _is_group(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type in {ChatType.GROUP, ChatType.SUPERGROUP})


async def settrip_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id, context) or not _is_group(update):
        return ConversationHandler.END
    context.user_data["settrip_chat_id"] = update.effective_chat.id
    await update.effective_message.reply_text(
        "🧳 نام این سفر چیست؟\nمثال: تبریز",
        reply_markup=ForceReply(selective=True),
    )
    return TRIP_TITLE


async def settrip_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if len(value) < 2:
        await update.effective_message.reply_text("لطفاً نام سفر را کامل وارد کنید.")
        return TRIP_TITLE
    context.user_data["trip_title"] = value
    await update.effective_message.reply_text(
        "نوع سفر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇮🇷 داخلی یک‌روزه — ۵ امتیاز", callback_data="triptype:domestic_day")],
            [InlineKeyboardButton("🇮🇷 داخلی چندروزه — ۱۵ امتیاز", callback_data="triptype:domestic_multi")],
            [InlineKeyboardButton("🌍 خارجی — ۱۰۰ امتیاز", callback_data="triptype:international")],
        ]),
    )
    return TRIP_TYPE


async def settrip_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return TRIP_TYPE
    await query.answer()
    if not is_admin(query.from_user.id, context):
        return ConversationHandler.END
    trip_type = query.data.split(":", 1)[1]
    context.user_data["trip_type"] = trip_type
    label = _trip_type_label(trip_type)
    await query.message.reply_text(
        f"نوع سفر: {label}\n\n📅 تاریخ شروع سفر را وارد کنید.\nمثال: ۲۰ مهر ۱۴۰۵",
        reply_markup=ForceReply(selective=True),
    )
    return TRIP_START


async def settrip_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if not value:
        await update.effective_message.reply_text("تاریخ شروع را وارد کنید.")
        return TRIP_START
    context.user_data["trip_start"] = value
    await update.effective_message.reply_text(
        "📅 تاریخ پایان سفر را وارد کنید.\nمثال: ۲۲ مهر ۱۴۰۵",
        reply_markup=ForceReply(selective=True),
    )
    return TRIP_END


async def settrip_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if not value:
        await update.effective_message.reply_text("تاریخ پایان را وارد کنید.")
        return TRIP_END
    context.user_data["trip_end"] = value
    db = context.application.bot_data["db"]
    current = await db.get_trip_by_chat_id(context.user_data["settrip_chat_id"])
    similar = await db.find_similar_trips(
        context.user_data["trip_title"], context.user_data["trip_start"], value,
        context.user_data.get("trip_type", "domestic_multi"),
        exclude_trip_id=current.id if current else None, limit=5,
    )
    linkable = [trip for trip in similar if trip.telegram_chat_id in (None, context.user_data["settrip_chat_id"])]
    if linkable:
        rows = [[InlineKeyboardButton(
            f"🔗 اتصال گروه به {trip.title} | {trip.trip_code}"[:60],
            callback_data=f"tripdupe:link:{trip.id}",
        )] for trip in linkable]
        rows.append([InlineKeyboardButton("➕ سفر جدید جدا بساز", callback_data="tripdupe:new")])
        await update.effective_message.reply_text(
            "⚠️ سفر مشابهی از قبل در بانک اطلاعاتی وجود دارد.\nبهتر است این گروه را به همان سفر وصل کنید تا سابقه دو بار ثبت نشود.",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return TRIP_DUPLICATE
    return await _finish_settrip(update, context)


async def _finish_settrip(update_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = context.application.bot_data["db"]
    user = update_or_query.effective_user if isinstance(update_or_query, Update) else update_or_query.from_user
    trip = await db.create_or_update_trip(
        telegram_chat_id=context.user_data["settrip_chat_id"],
        title=context.user_data["trip_title"],
        start_date_text=context.user_data["trip_start"],
        end_date_text=context.user_data["trip_end"],
        trip_type=context.user_data.get("trip_type", "domestic_multi"),
        created_by_telegram_id=user.id,
    )
    context.user_data.clear()
    message = update_or_query.effective_message if isinstance(update_or_query, Update) else update_or_query.message
    await message.reply_text(
        "✅ این گروه به سفر زیر متصل شد:\n\n"
        f"🧳 {trip.title}\n📅 {trip.start_date_text} تا {trip.end_date_text}\n"
        f"نوع: {_trip_type_label(trip.trip_type)}\n⭐ امتیاز حضور: {trip.points_value}\n🆔 {trip.trip_code}\n\n"
        "برای انتشار دکمه ثبت سفر: /tripregister"
    )
    return ConversationHandler.END


async def settrip_duplicate_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return TRIP_DUPLICATE
    await query.answer()
    if not is_admin(query.from_user.id, context):
        return ConversationHandler.END
    if query.data == "tripdupe:new":
        return await _finish_settrip(query, context)
    trip_id = int(query.data.rsplit(":", 1)[1])
    db = context.application.bot_data["db"]
    trip = await db.link_trip_to_chat(trip_id, context.user_data["settrip_chat_id"])
    context.user_data.clear()
    if not trip:
        await query.message.reply_text("اتصال انجام نشد؛ سفر موجود را بررسی کنید.")
        return ConversationHandler.END
    await query.message.reply_text(
        f"✅ این گروه به سفر موجود «{trip.title}» ({trip.trip_code}) متصل شد.\n"
        "هیچ سفر تکراری ساخته نشد.\n\nبرای انتشار دکمه ثبت سفر: /tripregister"
    )
    return ConversationHandler.END


async def settrip_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.effective_message.reply_text("تعریف سفر لغو شد.")
    return ConversationHandler.END


async def tripinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context) or not _is_group(update):
        return
    db = context.application.bot_data["db"]
    trip = await db.get_trip_by_chat_id(update.effective_chat.id)
    if not trip:
        await update.effective_message.reply_text("این گروه هنوز به سفری متصل نشده است. /settrip")
        return
    count = await db.count_trip_participants(trip.id)
    await update.effective_message.reply_text(
        f"🧳 {trip.title}\n"
        f"🆔 {trip.trip_code}\n"
        f"📅 {trip.start_date_text} تا {trip.end_date_text}\n"
        f"نوع: {_trip_type_label(trip.trip_type)}\n"
        f"⭐ امتیاز حضور: {trip.points_value}\n"
        f"وضعیت: {trip.status}\n"
        f"👥 اعلام حضور ثبت‌شده: {count}"
    )


async def tripregister(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context) or not _is_group(update):
        return
    db = context.application.bot_data["db"]
    trip = await db.get_trip_by_chat_id(update.effective_chat.id)
    if not trip:
        await update.effective_message.reply_text("ابتدا این گروه را با /settrip به یک سفر متصل کنید.")
        return
    if trip.status != "open":
        await update.effective_message.reply_text("ثبت سفر برای این گروه در حال حاضر بسته است. /tripopen")
        return
    me = await context.bot.get_me()
    await update.effective_message.reply_text(
        f"🧳 {trip.title}\n"
        f"📅 {trip.start_date_text} تا {trip.end_date_text}\n\n"
        "اگر مسافر این برنامه هستید، روی دکمه زیر بزنید تا این سفر در پروفایل کژوان شما ثبت شود.",
        reply_markup=trip_register_link_keyboard(me.username, trip.id),
    )


async def _is_channel_member(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    settings = context.application.bot_data["settings"]
    try:
        member = await context.bot.get_chat_member(settings.channel_username, user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception:
        return False


def _trip_channel_keyboard(channel_username: str, trip_id: int) -> InlineKeyboardMarkup:
    username = channel_username.lstrip("@")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال کژوان", url=f"https://t.me/{username}")],
        [InlineKeyboardButton("✅ بررسی عضویت و ثبت سفر", callback_data=f"tripchannel:{trip_id}")],
    ])


async def _register_trip_after_channel(query, context: ContextTypes.DEFAULT_TYPE, trip_id: int) -> None:
    db = context.application.bot_data["db"]
    trip = await db.get_trip(trip_id)
    if not trip:
        await query.message.reply_text("این سفر پیدا نشد.")
        return
    if trip.status != "open":
        await query.edit_message_text("ثبت این سفر در حال حاضر بسته است.")
        return
    user = await db.get_user(query.from_user.id)
    if not user:
        await query.message.reply_text("ابتدا /start را بزنید و پروفایل کژوان خود را کامل کنید.")
        return
    if not await _is_channel_member(context, query.from_user.id):
        settings = context.application.bot_data["settings"]
        await query.edit_message_text(
            "برای ثبت سفر لازم است عضو کانال رسمی کژوان باشید.\n"
            "عضویت در Beyond The Clouds الزامی نیست.",
            reply_markup=_trip_channel_keyboard(settings.channel_username, trip_id),
        )
        return
    await db.register_trip_participant(trip.id, query.from_user.id)
    await query.edit_message_text(
        f"✅ سفر «{trip.title}» در پروفایل کژوان شما با وضعیت «اعلام حضور» ثبت شد.\n"
        f"⭐ پس از تأیید حضور واقعی توسط مدیر، {trip.points_value} امتیاز دریافت می‌کنید."
    )


async def tripconfirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = query.data.split(":")
    trip_id = int(parts[1])
    choice = parts[2]
    if choice == "no":
        await query.edit_message_text("ثبت این سفر لغو شد.")
        return
    await _register_trip_after_channel(query, context, trip_id)


async def tripchannel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    trip_id = int(query.data.split(":", 1)[1])
    await _register_trip_after_channel(query, context, trip_id)


async def _management_in_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    me = await context.bot.get_me()
    await update.effective_message.reply_text(
        "🔐 مدیریت مسافران، تأیید حضور، انصراف، خروجی Excel و پایان سفر "
        "از پنل خصوصی ربات انجام می‌شود.\n\n"
        f"وارد PV شوید و /admin را بزنید:\nhttps://t.me/{me.username}?start=admin"
    )


async def tripparticipants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _management_in_private(update, context)


async def exporttrip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _management_in_private(update, context)


async def tripclose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _management_in_private(update, context)


async def tripopen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _management_in_private(update, context)


async def endtrip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _management_in_private(update, context)


async def tripattend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _management_in_private(update, context)


async def tripcancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _management_in_private(update, context)



def build_settrip_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("settrip", settrip_start)],
        states={
            TRIP_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settrip_title)],
            TRIP_TYPE: [CallbackQueryHandler(settrip_type, pattern=r"^triptype:(domestic_day|domestic_multi|international)$")],
            TRIP_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, settrip_start_date)],
            TRIP_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, settrip_end_date)],
            TRIP_DUPLICATE: [CallbackQueryHandler(settrip_duplicate_choice, pattern=r"^tripdupe:(?:link:\d+|new)$")],
        },
        fallbacks=[CommandHandler("cancel", settrip_cancel)],
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )


def trip_handlers():
    return [
        build_settrip_handler(),
        CommandHandler("tripinfo", tripinfo),
        CommandHandler("tripregister", tripregister),
        CommandHandler("tripparticipants", tripparticipants),
        CommandHandler("exporttrip", exporttrip),
        CommandHandler("tripclose", tripclose),
        CommandHandler("tripopen", tripopen),
        CommandHandler("endtrip", endtrip),
        CommandHandler("tripattend", tripattend),
        CommandHandler("tripcancel", tripcancel),
        CallbackQueryHandler(tripconfirm_callback, pattern=r"^tripconfirm:\d+:(yes|no)$"),
        CallbackQueryHandler(tripchannel_callback, pattern=r"^tripchannel:\d+$"),
    ]
