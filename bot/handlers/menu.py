from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from bot.keyboards import main_menu

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data["db"]
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("ابتدا /start را بزنید و عضویت را کامل کنید.")
        return
    btc = await db.get_btc_membership(update.effective_user.id)
    await update.message.reply_text(
        "👤 پروفایل من\n\n"
        f"نام: {user.full_name}\n"
        f"شماره تماس: {user.phone}\n"
        f"شهر: {user.city}\n"
        f"کد عضویت کژوان: {user.member_code}\n"
        f"کد عضویت BTC: {btc.btc_code if btc else 'عضو BTC نیستید'}\n"
        f"کد معرف کژوان: {user.referral_code or '-'}\n"
        f"تعداد معرفی موفق: {user.referral_count}\n"
        f"امتیاز: {user.points}\n"
        f"وضعیت: {user.status}",
        reply_markup=main_menu(),
    )

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data["db"]
    activities = await db.list_activities(update.effective_user.id)
    trips = await db.list_user_trips(update.effective_user.id)
    if not activities and not trips:
        await update.message.reply_text("هنوز فعالیتی برای شما ثبت نشده است.")
        return

    lines = ["📜 تاریخچه فعالیت‌های من", ""]
    if trips:
        labels = {
            "declared": "🟡 اعلام حضور",
            "attended": "🟢 شرکت کرده",
            "cancelled": "⚪ انصراف",
        }
        domestic = [(p, t) for p, t in trips if getattr(t, "trip_type", "domestic_multi") in {"domestic_day", "domestic_multi", "domestic"}]
        international = [(p, t) for p, t in trips if getattr(t, "trip_type", "domestic_multi") == "international"]

        if domestic:
            lines.append("🇮🇷 سفرهای داخلی")
            for participant, trip in domestic:
                subtype = "یک‌روزه" if getattr(trip, "trip_type", "domestic_multi") == "domestic_day" else "چندروزه"
                points = participant.awarded_points if getattr(participant, "points_awarded", False) else 0
                lines.append(
                    f"• {trip.title} ({subtype}) — {trip.start_date_text} تا {trip.end_date_text} — "
                    f"{labels.get(participant.status, participant.status)} — {points} امتیاز"
                )
            lines.append("")

        if international:
            lines.append("🌍 سفرهای خارجی")
            for participant, trip in international:
                points = participant.awarded_points if getattr(participant, "points_awarded", False) else 0
                lines.append(
                    f"• {trip.title} — {trip.start_date_text} تا {trip.end_date_text} — "
                    f"{labels.get(participant.status, participant.status)} — {points} امتیاز"
                )
            lines.append("")

    if activities:
        lines.append("🌿 سایر فعالیت‌ها")
        for item in activities:
            date_text = item.created_at.strftime("%Y/%m/%d")
            lines.append(f"• {date_text} — {item.title}")
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
    await update.message.reply_text(
        f"📞 راه ارتباط با پشتیبانی:\n{settings.support_contact}"
    )

async def placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "این بخش در نسخه بعدی فعال می‌شود. زیرساخت آن از همین حالا در حال آماده‌سازی است."
    )

def menu_handlers():
    return [
        MessageHandler(filters.Regex("^👤 پروفایل من$"), profile),
        MessageHandler(filters.Regex("^📜 تاریخچه فعالیت‌های من$"), history),
        MessageHandler(filters.Regex("^🎖 کارت عضویت$"), card),
        MessageHandler(filters.Regex("^📞 پشتیبانی$"), support),
        MessageHandler(
            filters.Regex("^(🗓 برنامه‌های آینده|📝 ثبت‌نام‌های من)$"),
            placeholder,
        ),
    ]
