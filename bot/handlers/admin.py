from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

def is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = context.application.bot_data["settings"]
    return user_id in settings.admin_ids

async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    await update.effective_message.reply_text(
        f"شناسه عددی این گفتگو:\n`{update.effective_chat.id}`",
        parse_mode="Markdown",
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    db = context.application.bot_data["db"]
    count = await db.count_users()
    await update.effective_message.reply_text(
        f"📊 آمار اولیه ربات\n\nتعداد اعضای ثبت‌شده: {count}"
    )

def admin_handlers():
    return [
        CommandHandler("chatid", chatid),
        CommandHandler("stats", stats),
    ]
