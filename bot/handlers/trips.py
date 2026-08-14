from __future__ import annotations

from telegram import Update
from telegram.constants import ChatType
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

TRIP_TITLE, TRIP_START, TRIP_END = range(3)

STATUS_LABELS = {
    "declared": "🟡 اعلام حضور",
    "attended": "🟢 شرکت کرده",
    "cancelled": "⚪ انصراف",
}


def _is_group(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type in {ChatType.GROUP, ChatType.SUPERGROUP})


async def settrip_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id, context) or not _is_group(update):
        return ConversationHandler.END
    context.user_data["settrip_chat_id"] = update.effective_chat.id
    await update.effective_message.reply_text("🧳 نام این سفر چیست؟\nمثال: تبریز")
    return TRIP_TITLE


async def settrip_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if len(value) < 2:
        await update.effective_message.reply_text("لطفاً نام سفر را کامل وارد کنید.")
        return TRIP_TITLE
    context.user_data["trip_title"] = value
    await update.effective_message.reply_text("📅 تاریخ شروع سفر را وارد کنید.\nمثال: ۲۰ مهر ۱۴۰۵")
    return TRIP_START


async def settrip_start_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if not value:
        await update.effective_message.reply_text("تاریخ شروع را وارد کنید.")
        return TRIP_START
    context.user_data["trip_start"] = value
    await update.effective_message.reply_text("📅 تاریخ پایان سفر را وارد کنید.\nمثال: ۲۲ مهر ۱۴۰۵")
    return TRIP_END


async def settrip_end_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.effective_message.text or "").strip()
    if not value:
        await update.effective_message.reply_text("تاریخ پایان را وارد کنید.")
        return TRIP_END

    db = context.application.bot_data["db"]
    trip = await db.create_or_update_trip(
        telegram_chat_id=context.user_data["settrip_chat_id"],
        title=context.user_data["trip_title"],
        start_date_text=context.user_data["trip_start"],
        end_date_text=value,
        created_by_telegram_id=update.effective_user.id,
    )
    context.user_data.clear()
    await update.effective_message.reply_text(
        "✅ این گروه به سفر زیر متصل شد:\n\n"
        f"🧳 {trip.title}\n"
        f"📅 {trip.start_date_text} تا {trip.end_date_text}\n"
        f"🆔 {trip.trip_code}\n\n"
        "برای انتشار دکمه ثبت سفر: /tripregister"
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


async def tripconfirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    parts = query.data.split(":")
    trip_id = int(parts[1])
    choice = parts[2]
    db = context.application.bot_data["db"]
    trip = await db.get_trip(trip_id)
    if not trip:
        await query.message.reply_text("این سفر پیدا نشد.")
        return
    if choice == "no":
        await query.edit_message_text("ثبت این سفر لغو شد.")
        return
    if trip.status != "open":
        await query.edit_message_text("ثبت این سفر در حال حاضر بسته است.")
        return
    user = await db.get_user(query.from_user.id)
    if not user:
        await query.message.reply_text("ابتدا /start را بزنید و پروفایل خود را کامل کنید.")
        return
    await db.register_trip_participant(trip.id, query.from_user.id)
    await query.edit_message_text(
        f"✅ سفر «{trip.title}» در پروفایل شما با وضعیت «اعلام حضور» ثبت شد."
    )


async def tripparticipants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context) or not _is_group(update):
        return
    db = context.application.bot_data["db"]
    trip = await db.get_trip_by_chat_id(update.effective_chat.id)
    if not trip:
        await update.effective_message.reply_text("این گروه به سفری متصل نیست.")
        return
    rows = await db.list_trip_participants(trip.id)
    if not rows:
        await update.effective_message.reply_text("هنوز کسی این سفر را در پروفایل خود ثبت نکرده است.")
        return
    lines = [f"👥 مسافران ثبت‌شده — {trip.title}", ""]
    for idx, (participant, user) in enumerate(rows, 1):
        name = user.full_name if user else str(participant.telegram_id)
        lines.append(f"{idx}. {name} — {STATUS_LABELS.get(participant.status, participant.status)}")
    await update.effective_message.reply_text("\n".join(lines[:100]))


async def exporttrip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context) or not _is_group(update):
        return
    db = context.application.bot_data["db"]
    trip = await db.get_trip_by_chat_id(update.effective_chat.id)
    if not trip:
        await update.effective_message.reply_text("این گروه به سفری متصل نیست.")
        return
    items = await db.list_trip_participants(trip.id)
    headers = [
        "نام", "شماره تماس", "شهر", "Username", "Telegram ID", "کد عضویت",
        "وضعیت", "تاریخ اعلام حضور", "نام سفر", "کد سفر",
    ]
    rows = []
    for participant, user in items:
        rows.append([
            user.full_name if user else "",
            user.phone if user else "",
            user.city if user else "",
            f"@{user.telegram_username}" if user and user.telegram_username else "",
            participant.telegram_id,
            user.member_code if user else "",
            STATUS_LABELS.get(participant.status, participant.status),
            participant.declared_at.isoformat() if participant.declared_at else "",
            trip.title,
            trip.trip_code,
        ])
    file_obj = build_xlsx(headers, rows, sheet_name="Trip")
    filename = f"{trip.trip_code or 'trip'}_participants.xlsx"
    await update.effective_message.reply_document(file_obj, filename=filename, caption=f"📥 خروجی {trip.title}")


async def _set_trip_status_for_chat(update, context, status: str, success_text: str) -> None:
    if not is_admin(update.effective_user.id, context) or not _is_group(update):
        return
    db = context.application.bot_data["db"]
    trip = await db.get_trip_by_chat_id(update.effective_chat.id)
    if not trip:
        await update.effective_message.reply_text("این گروه به سفری متصل نیست.")
        return
    await db.set_trip_status(trip.id, status)
    await update.effective_message.reply_text(success_text)


async def tripclose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_trip_status_for_chat(update, context, "closed", "🔒 ثبت سفر بسته شد.")


async def tripopen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_trip_status_for_chat(update, context, "open", "🔓 ثبت سفر دوباره باز شد.")


async def endtrip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_trip_status_for_chat(
        update, context, "ended", "🏁 سفر پایان‌یافته ثبت شد. حالا می‌توانید حضور واقعی مسافرها را نهایی کنید."
    )


async def _participant_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE, status: str) -> None:
    if not is_admin(update.effective_user.id, context) or not _is_group(update):
        return
    db = context.application.bot_data["db"]
    trip = await db.get_trip_by_chat_id(update.effective_chat.id)
    if not trip:
        await update.effective_message.reply_text("این گروه به سفری متصل نیست.")
        return
    query_text = " ".join(context.args).strip()
    if not query_text and update.effective_message.reply_to_message:
        target = update.effective_message.reply_to_message.from_user
        telegram_id = target.id
        user = await db.get_user(telegram_id)
    elif query_text:
        matches = await db.search_users(query_text, limit=2)
        if len(matches) != 1:
            await update.effective_message.reply_text(
                "یک عضو یکتا پیدا نشد. کد عضویت یا شماره دقیق را وارد کنید، یا دستور را روی پیام شخص Reply کنید."
            )
            return
        user = matches[0]
        telegram_id = user.telegram_id
    else:
        await update.effective_message.reply_text(
            "دستور را روی پیام مسافر Reply کنید یا بعد از دستور کد عضویت/شماره را بنویسید."
        )
        return
    participant = await db.set_trip_participant_status(trip.id, telegram_id, status)
    if not participant:
        await update.effective_message.reply_text("این فرد قبلاً حضور خود را برای این سفر ثبت نکرده است.")
        return
    name = user.full_name if user else str(telegram_id)
    await update.effective_message.reply_text(
        f"✅ وضعیت {name}: {STATUS_LABELS.get(status, status)}"
    )


async def tripattend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _participant_status_command(update, context, "attended")


async def tripcancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _participant_status_command(update, context, "cancelled")


def build_settrip_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("settrip", settrip_start)],
        states={
            TRIP_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settrip_title)],
            TRIP_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, settrip_start_date)],
            TRIP_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, settrip_end_date)],
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
    ]
