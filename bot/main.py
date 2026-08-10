import logging
from telegram import Update
from telegram.ext import Application, ContextTypes

from bot.config import load_settings
from bot.db import Database
from bot.handlers.admin import admin_handlers
from bot.handlers.menu import menu_handlers
from bot.handlers.moderation import initialize_quiet_hours, moderation_handlers
from bot.handlers.onboarding import build_onboarding_handler

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "یک خطای موقت پیش آمد. لطفاً دوباره تلاش کنید."
        )


async def post_init(application: Application) -> None:
    db: Database = application.bot_data["db"]
    await db.init()
    await initialize_quiet_hours(application)
    await application.bot.set_my_commands([
        ("start", "شروع و تکمیل عضویت"),
        ("stats", "آمار اولیه مدیر"),
        ("inactive30", "اعضای غیرفعال بیش از ۳۰ روز"),
        ("inactive60", "اعضای غیرفعال بیش از ۶۰ روز"),
        ("chatid", "نمایش شناسه عددی گروه"),
        ("cancel", "توقف فرآیند جاری"),
    ])


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
    for handler in moderation_handlers():
        application.add_handler(handler, group=10)
    application.add_error_handler(error_handler)

    logger.info("Kazhwan bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
