from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from bot.keyboards import discovery_keyboard, main_menu
from bot.profile_extra import get_neighborhood, save_neighborhood, update_basic_profile, update_phone

DOMESTIC_TOURS_URL = "https://kazhwan.com/tours/"
INTERNATIONAL_TOURS_URL = "https://kazhwan.com/%d8%aa%d9%88%d8%b1-%d8%ae%d8%a7%d8%b1%d8%ac%db%8c/"

EDIT_VALUE, EDIT_PHONE, EDIT_SOURCE, EDIT_SOURCE_OTHER = range(4)


def _profile_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ویرایش پروفایل", callback_data="profileedit:open")]
    ])


def _edit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 نام و نام خانوادگی", callback_data="profileedit:full_name")],
        [InlineKeyboardButton("📱 شماره موبایل", callback_data="profileedit:phone")],
        [InlineKeyboardButton("🏙 شهر", callback_data="profileedit:city"),
         InlineKeyboardButton("📍 محله", callback_data="profileedit:neighborhood")],
        [InlineKeyboardButton("📣 نحوه آشنایی با کژوان", callback_data="profileedit:discovery_source")],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data="profileedit:back")],
    ])


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data["db"]
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("ابتدا /start را بزنید و عضویت را کامل کنید.")
        return
    btc = await db.get_btc_membership(update.effective_user.id)
    neighborhood = await get_neighborhood(db, update.effective_user.id)
    joined = user.created_at.strftime("%Y/%m/%d") if user.created_at else "-"
    await update.message.reply_text(
        "👤 پروفایل من\n\n"
        f"نام: {user.full_name}\n"
        f"شماره تماس: {user.phone}\n"
        f"شهر: {user.city}\n"
        f"محله: {neighborhood or 'ثبت نشده'}\n"
        f"📅 تاریخ عضویت: {joined}\n"
        f"کد عضویت کژوان: {user.member_code}\n"
        f"کد عضویت BTC: {btc.btc_code if btc else 'عضو BTC نیستید'}\n"
        f"کد معرف کژوان: {user.referral_code or '-'}\n"
        f"تعداد معرفی موفق: {user.referral_count}\n"
        f"امتیاز: {user.points}\n"
        f"وضعیت: {user.status}",
        reply_markup=_profile_actions_keyboard(),
    )


async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    field = query.data.split(":", 1)[1]

    if field == "open":
        await query.edit_message_reply_markup(reply_markup=_edit_keyboard())
        return ConversationHandler.END

    if field == "back":
        await query.edit_message_reply_markup(reply_markup=_profile_actions_keyboard())
        return ConversationHandler.END

    context.user_data["profile_edit_field"] = field
    if field == "phone":
        await query.message.reply_text(
            "شماره جدید خودتان را با دکمه زیر ارسال کنید:",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📱 ارسال شماره جدید", request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
        return EDIT_PHONE

    if field == "discovery_source":
        await query.message.reply_text(
            "نحوه آشنایی جدید را انتخاب کنید:",
            reply_markup=discovery_keyboard(),
        )
        return EDIT_SOURCE

    labels = {"full_name": "نام و نام خانوادگی", "city": "شهر", "neighborhood": "محله"}
    await query.message.reply_text(f"{labels[field]} جدید را وارد کنید:")
    return EDIT_VALUE


async def edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.message.text or "").strip()
    field = context.user_data.get("profile_edit_field")
    if len(value) < 2:
        await update.message.reply_text("مقدار واردشده خیلی کوتاه است. دوباره وارد کنید.")
        return EDIT_VALUE
    if field == "full_name" and len(value.split()) < 2:
        await update.message.reply_text("لطفاً نام و نام خانوادگی را کامل وارد کنید.")
        return EDIT_VALUE

    db = context.application.bot_data["db"]
    if field == "neighborhood":
        await save_neighborhood(db, update.effective_user.id, value)
    elif field in {"full_name", "city"}:
        await update_basic_profile(db, update.effective_user.id, field, value)
    else:
        await update.message.reply_text("ویرایش انجام نشد. دوباره از پروفایل شروع کنید.")
        return ConversationHandler.END

    context.user_data.pop("profile_edit_field", None)
    await update.message.reply_text("✅ اطلاعات با موفقیت به‌روزرسانی شد.", reply_markup=main_menu())
    return ConversationHandler.END


async def edit_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.message.contact
    if not contact or contact.user_id != update.effective_user.id:
        await update.message.reply_text("لطفاً شماره خودتان را فقط با دکمه ارسال شماره جدید بفرستید.")
        return EDIT_PHONE
    db = context.application.bot_data["db"]
    await update_phone(db, update.effective_user.id, contact.phone_number)
    context.user_data.pop("profile_edit_field", None)
    await update.message.reply_text(
        "✅ شماره موبایل به‌روزرسانی شد.",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def edit_source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected = query.data.split(":", 1)[1]
    if selected == "other":
        await query.message.reply_text("نحوه آشنایی خود را بنویسید:")
        return EDIT_SOURCE_OTHER
    db = context.application.bot_data["db"]
    await update_basic_profile(db, query.from_user.id, "discovery_source", selected)
    context.user_data.pop("profile_edit_field", None)
    await query.message.reply_text("✅ نحوه آشنایی به‌روزرسانی شد.", reply_markup=main_menu())
    return ConversationHandler.END


async def edit_source_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.message.text or "").strip()
    if len(value) < 2:
        await update.message.reply_text("لطفاً توضیح کوتاهی وارد کنید.")
        return EDIT_SOURCE_OTHER
    db = context.application.bot_data["db"]
    await update_basic_profile(db, update.effective_user.id, "discovery_source", value)
    context.user_data.pop("profile_edit_field", None)
    await update.message.reply_text("✅ نحوه آشنایی به‌روزرسانی شد.", reply_markup=main_menu())
    return ConversationHandler.END


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data["db"]
    activities = await db.list_activities(update.effective_user.id)
    trips = await db.list_user_trips(update.effective_user.id)
    if not activities and not trips:
        await update.message.reply_text("هنوز فعالیتی برای شما ثبت نشده است.")
        return
    lines = ["📜 تاریخچه فعالیت‌های من", ""]
    if trips:
        labels = {"declared":"🟡 اعلام حضور","attended":"🟢 شرکت کرده","cancelled":"⚪ انصراف"}
        domestic = [(p,t) for p,t in trips if getattr(t,"trip_type","domestic_multi") in {"domestic_day","domestic_multi","domestic"}]
        international = [(p,t) for p,t in trips if getattr(t,"trip_type","domestic_multi") == "international"]
        if domestic:
            lines.append("🇮🇷 سفرهای داخلی")
            for participant, trip in domestic:
                subtype = "یک‌روزه" if getattr(trip,"trip_type","domestic_multi") == "domestic_day" else "چندروزه"
                points = participant.awarded_points if getattr(participant,"points_awarded",False) else 0
                lines.append(f"• {trip.title} ({subtype}) — {trip.start_date_text} تا {trip.end_date_text} — {labels.get(participant.status, participant.status)} — {points} امتیاز")
            lines.append("")
        if international:
            lines.append("🌍 سفرهای خارجی")
            for participant, trip in international:
                points = participant.awarded_points if getattr(participant,"points_awarded",False) else 0
                lines.append(f"• {trip.title} — {trip.start_date_text} تا {trip.end_date_text} — {labels.get(participant.status, participant.status)} — {points} امتیاز")
            lines.append("")
    if activities:
        lines.append("🌿 سایر فعالیت‌ها")
        for item in activities:
            lines.append(f"• {item.created_at.strftime('%Y/%m/%d')} — {item.title}")
    await update.message.reply_text("\n".join(lines))


async def card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data["db"]
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("ابتدا /start را بزنید.")
        return
    btc = await db.get_btc_membership(update.effective_user.id)
    await update.message.reply_text(
        "🎖 کارت عضویت کژوان\n\n"
        f"نام: {user.full_name}\n"
        f"کد کژوان: {user.member_code}\n"
        f"کد BTC: {btc.btc_code if btc else '-'}\n"
        f"کد معرف: {user.referral_code or '-'}\n"
        f"شهر: {user.city}\n"
        f"سطح: تازه‌وارد\n"
        f"امتیاز: {user.points}"
    )


async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    await update.message.reply_text(f"📞 راه ارتباط با پشتیبانی:\n{settings.support_contact}")


async def future_programs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🗓 برنامه‌های آینده کژوان\n\nنوع سفر موردنظرتان را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🇮🇷 سفرهای داخلی", url=DOMESTIC_TOURS_URL)],
            [InlineKeyboardButton("🌍 سفرهای خارجی", url=INTERNATIONAL_TOURS_URL)],
        ]),
    )


async def placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("این بخش در نسخه بعدی فعال می‌شود. زیرساخت آن از همین حالا در حال آماده‌سازی است.")


def profile_edit_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start, pattern="^profileedit:")],
        states={
            EDIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
            EDIT_PHONE: [MessageHandler(filters.CONTACT, edit_phone)],
            EDIT_SOURCE: [CallbackQueryHandler(edit_source, pattern="^source:")],
            EDIT_SOURCE_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_source_other)],
        },
        fallbacks=[],
        allow_reentry=True,
    )


def menu_handlers():
    return [
        profile_edit_handler(),
        MessageHandler(filters.Regex("^👤 پروفایل من$"), profile),
        MessageHandler(filters.Regex("^📜 تاریخچه فعالیت‌های من$"), history),
        MessageHandler(filters.Regex("^🎖 کارت عضویت$"), card),
        MessageHandler(filters.Regex("^📞 پشتیبانی$"), support),
        MessageHandler(filters.Regex("^🗓 برنامه‌های آینده$"), future_programs),
        MessageHandler(filters.Regex("^📝 ثبت‌نام‌های من$"), placeholder),
    ]
