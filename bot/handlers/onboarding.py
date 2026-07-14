from telegram import ReplyKeyboardRemove, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.keyboards import (
    channel_keyboard,
    contact_keyboard,
    discovery_keyboard,
    main_menu,
    rules_keyboard,
)
from bot.texts import RULES_TEXT, WELCOME_TEXT

FULL_NAME, PHONE, CITY, CHANNEL, RULES, SOURCE, SOURCE_OTHER = range(7)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = context.application.bot_data["db"]
    user = await db.get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(
            f"سلام {user.full_name} 🌿",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(WELCOME_TEXT)
    await update.message.reply_text("لطفاً نام و نام خانوادگی خود را وارد کنید:")
    return FULL_NAME

async def full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.message.text or "").strip()
    if len(value.split()) < 2:
        await update.message.reply_text("لطفاً نام و نام خانوادگی را کامل وارد کنید.")
        return FULL_NAME
    context.user_data["full_name"] = value
    await update.message.reply_text(
        "شماره تماس خودتان را با دکمه زیر ارسال کنید:",
        reply_markup=contact_keyboard(),
    )
    return PHONE

async def phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.message.contact
    if not contact or contact.user_id != update.effective_user.id:
        await update.message.reply_text(
            "لطفاً شماره خودتان را فقط با دکمه «ارسال شماره تماس» بفرستید."
        )
        return PHONE
    context.user_data["phone"] = contact.phone_number
    await update.message.reply_text(
        "شهر محل سکونت خود را وارد کنید:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return CITY

async def city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.message.text or "").strip()
    if len(value) < 2:
        await update.message.reply_text("نام شهر را دوباره وارد کنید.")
        return CITY
    context.user_data["city"] = value
    settings = context.application.bot_data["settings"]
    await update.message.reply_text(
        "برای ادامه، ابتدا عضو کانال رسمی کژوان شوید و سپس «بررسی عضویت» را بزنید.",
        reply_markup=channel_keyboard(settings.channel_username),
    )
    return CHANNEL

async def check_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    settings = context.application.bot_data["settings"]
    try:
        member = await context.bot.get_chat_member(
            chat_id=settings.channel_username,
            user_id=query.from_user.id,
        )
        is_member = member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception:
        await query.message.reply_text(
            "بررسی عضویت انجام نشد. مطمئن شوید ربات در کانال ادمین شده است."
        )
        return CHANNEL

    if not is_member:
        await query.answer("هنوز عضویت شما در کانال تأیید نشده است.", show_alert=True)
        return CHANNEL

    await query.edit_message_text("✅ عضویت شما در کانال تأیید شد.")
    await query.message.reply_text(RULES_TEXT, reply_markup=rules_keyboard())
    return RULES

async def accept_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        "از کجا با کژوان آشنا شدید؟",
        reply_markup=discovery_keyboard(),
    )
    return SOURCE

async def source(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    selected = query.data.split(":", 1)[1]
    if selected == "other":
        await query.message.reply_text("لطفاً نحوه آشنایی خود را بنویسید:")
        return SOURCE_OTHER
    return await finish_registration(update, context, selected)

async def source_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected = (update.message.text or "").strip()
    if len(selected) < 2:
        await update.message.reply_text("لطفاً توضیح کوتاهی وارد کنید.")
        return SOURCE_OTHER
    return await finish_registration(update, context, selected)

async def finish_registration(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    discovery_source: str,
) -> int:
    db = context.application.bot_data["db"]
    tg_user = update.effective_user
    user = await db.create_user(
        telegram_id=tg_user.id,
        telegram_username=tg_user.username,
        full_name=context.user_data["full_name"],
        phone=context.user_data["phone"],
        city=context.user_data["city"],
        discovery_source=discovery_source,
    )

    message = (
        "🎉 عضویت شما با موفقیت ثبت شد.\n\n"
        f"شناسه عضویت: {user.member_code}\n"
        "از این پس می‌توانید برنامه‌ها، ثبت‌نام‌ها و تاریخچه فعالیت‌های خود را ببینید."
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(message, reply_markup=main_menu())
    else:
        await update.message.reply_text(message, reply_markup=main_menu())
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("فرآیند عضویت متوقف شد. برای شروع دوباره /start را بزنید.")
    return ConversationHandler.END

def build_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, full_name)],
            PHONE: [MessageHandler(filters.CONTACT, phone)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city)],
            CHANNEL: [CallbackQueryHandler(check_channel, pattern="^check_channel$")],
            RULES: [CallbackQueryHandler(accept_rules, pattern="^accept_rules$")],
            SOURCE: [CallbackQueryHandler(source, pattern="^source:")],
            SOURCE_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, source_other)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
