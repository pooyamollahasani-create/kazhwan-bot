import logging
from telegram import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    Update,
)
from telegram.ext import Application, ContextTypes

from bot.config import load_settings
from bot.db import Database
from bot.handlers.admin import admin_handlers
from bot.handlers.menu import menu_handlers
from bot.handlers.moderation import initialize_quiet_hours, moderation_handlers
from bot.handlers.onboarding import build_onboarding_handler
from bot.handlers.trips import trip_handlers

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error", exc_info=context.error)
    # Never spam a group with internal error messages. In private chat, a short
    # user-facing error is still useful; full details always stay in Railway logs.
    if isinstance(update, Update) and update.effective_message and update.effective_chat:
        if update.effective_chat.type == "private":
            await update.effective_message.reply_text(
                "یک خطای موقت پیش آمد. لطفاً دوباره تلاش کنید."
            )


async def post_init(application: Application) -> None:
    db: Database = application.bot_data["db"]
    logger.info("Kazhwan bot v1.6 loaded; Database=%s", type(db).__module__ + "." + type(db).__name__)
    settings = application.bot_data["settings"]
    await db.init()
    await initialize_quiet_hours(application)

    # Command menus are intentionally scoped. Passengers in groups only see
    # public travel commands; group admins see group-management commands;
    # the full management menu is only shown in the admins' private chats.
    private_user_commands = [
        ("start", "شروع و تکمیل پروفایل کژوان"),
    ]
    group_user_commands = [
        ("tripinfo", "اطلاعات سفر این گروه"),
    ]
    group_admin_commands = [
        ("settrip", "تعریف یا ویرایش سفر این گروه"),
        ("tripinfo", "اطلاعات سفر این گروه"),
        ("tripregister", "انتشار دکمه ثبت سفر برای مسافران"),
        ("chatid", "نمایش شناسه عددی گروه"),
        ("quieton", "بستن دستی چت گروه"),
        ("quietoff", "باز کردن دستی چت گروه"),
        ("cancel", "توقف فرآیند جاری"),
    ]
    private_admin_commands = [
        ("start", "شروع و تکمیل پروفایل کژوان"),
        ("admin", "پنل مدیریت"),
        ("stats", "آمار مدیریتی"),
        ("members", "تعداد اعضای ثبت‌شده"),
        ("member", "جستجوی عضو"),
        ("inactive30", "غیرفعال بیش از ۳۰ روز"),
        ("inactive60", "غیرفعال بیش از ۶۰ روز"),
        ("topreferrals", "معرف‌های برتر"),
        ("exportmembers", "خروجی Excel اعضا"),
        ("exportinactive", "خروجی Excel غیرفعال‌ها"),
        ("exportreferrals", "خروجی Excel معرف‌ها"),
        ("exportall", "خروجی کامل مدیریتی"),
        ("cancel", "توقف فرآیند جاری"),
    ]

    # Remove old menus from all scopes used by previous releases before setting
    # the clean passenger/admin menus. This prevents stale management commands
    # from remaining visible to normal travelers.
    await application.bot.delete_my_commands()
    await application.bot.delete_my_commands(scope=BotCommandScopeAllPrivateChats())
    await application.bot.delete_my_commands(scope=BotCommandScopeAllGroupChats())
    await application.bot.delete_my_commands(scope=BotCommandScopeAllChatAdministrators())
    for admin_id in settings.admin_ids:
        try:
            await application.bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            logger.exception("Could not clear old private admin command menu for %s", admin_id)
    await application.bot.set_my_commands(
        private_user_commands, scope=BotCommandScopeAllPrivateChats()
    )
    await application.bot.set_my_commands(
        group_user_commands, scope=BotCommandScopeAllGroupChats()
    )
    await application.bot.set_my_commands(
        group_admin_commands, scope=BotCommandScopeAllChatAdministrators()
    )

    # A private chat scope is narrower than AllPrivateChats, so only configured
    # admins see management commands when they press '/' in the bot's PV.
    for admin_id in settings.admin_ids:
        try:
            await application.bot.set_my_commands(
                private_admin_commands, scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception:
            logger.exception("Could not set private admin command menu for %s", admin_id)


def main() -> None:
    settings = load_settings()
    db = Database(settings.database_url)

    application = (
        Application.builder()
        .token(settings.bot_token)
        .concurrent_updates(False)
        .post_init(post_init)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db

    application.add_handler(build_onboarding_handler(), group=0)
    application.add_handlers(menu_handlers(), group=1)
    application.add_handlers(admin_handlers(), group=2)
    application.add_handlers(trip_handlers(), group=3)
    for handler in moderation_handlers():
        application.add_handler(handler, group=10)
    application.add_error_handler(error_handler)

    logger.info("Kazhwan bot v1.6 is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
