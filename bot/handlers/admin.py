from datetime import datetime, timezone

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


async def _inactive_report(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int) -> None:
    if not is_admin(update.effective_user.id, context):
        return
    db = context.application.bot_data["db"]
    members = await db.list_inactive_members(days=days, limit=100)
    if not members:
        await update.effective_message.reply_text(
            f"✅ فعلاً عضو ثبت‌شده‌ای با بیش از {days} روز بی‌فعالیتی نداریم."
        )
        return

    now = datetime.now(timezone.utc)
    lines = [f"⏳ اعضای با بیش از {days} روز بی‌فعالیتی", ""]
    for member in members:
        inactive_days = (now - member.last_activity_at).days
        username = f"@{member.telegram_username}" if member.telegram_username else "بدون آیدی"
        lines.append(f"• {member.display_name} — {inactive_days} روز — {username}")
    await update.effective_message.reply_text("\n".join(lines))


async def inactive30(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _inactive_report(update, context, 30)


async def inactive60(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _inactive_report(update, context, 60)


def admin_handlers():
    return [
        CommandHandler("chatid", chatid),
        CommandHandler("stats", stats),
        CommandHandler("inactive30", inactive30),
        CommandHandler("inactive60", inactive60),
    ]
