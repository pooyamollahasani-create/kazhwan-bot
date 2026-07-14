from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from bot.keyboards import main_menu

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data["db"]
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("ابتدا /start را بزنید و عضویت را کامل کنید.")
        return
    await update.message.reply_text(
        "👤 پروفایل من\n\n"
        f"نام: {user.full_name}\n"
        f"شماره تماس: {user.phone}\n"
        f"شهر: {user.city}\n"
        f"شناسه عضویت: {user.member_code}\n"
        f"امتیاز: {user.points}\n"
        f"وضعیت: {user.status}",
        reply_markup=main_menu(),
    )

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data["db"]
    activities = await db.list_activities(update.effective_user.id)
    if not activities:
        await update.message.reply_text("هنوز فعالیتی برای شما ثبت نشده است.")
        return

    lines = ["📜 تاریخچه فعالیت‌های من", ""]
    for item in activities:
        date_text = item.created_at.strftime("%Y/%m/%d")
        lines.append(f"• {date_text} — {item.title}")
        if item.details:
            lines.append(f"  {item.details}")
    await update.message.reply_text("\n".join(lines))

async def card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.application.bot_data["db"]
    user = await db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("ابتدا /start را بزنید.")
        return
    await update.message.reply_text(
        "🎖 کارت عضویت کژوان\n\n"
        f"نام: {user.full_name}\n"
        f"شناسه: {user.member_code}\n"
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
