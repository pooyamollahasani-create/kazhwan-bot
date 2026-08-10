import json
import logging
from datetime import datetime, time, timedelta, timezone

from telegram import ChatPermissions, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ChatMemberHandler, ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

IRAN_TZ = timezone(timedelta(hours=3, minutes=30), name="Iran")
QUIET_START = time(23, 0, tzinfo=IRAN_TZ)
QUIET_END = time(11, 0, tzinfo=IRAN_TZ)


def _is_quiet_now() -> bool:
    now = datetime.now(IRAN_TZ).time().replace(tzinfo=None)
    return now >= time(23, 0) or now < time(11, 0)


def _locked_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


async def lock_group(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db = context.application.bot_data["db"]
    chat_id = settings.group_chat_id
    if not chat_id:
        return

    try:
        saved = await db.get_saved_group_permissions(chat_id)
        if saved is None:
            chat = await context.bot.get_chat(chat_id)
            permissions = chat.permissions or ChatPermissions(can_send_messages=True)
            await db.save_group_permissions(chat_id, json.dumps(permissions.to_dict()))

        await context.bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=_locked_permissions(),
            use_independent_chat_permissions=True,
        )
        logger.info("Quiet hours enabled for group %s", chat_id)
    except Exception:
        logger.exception("Failed to enable quiet hours")


async def unlock_group(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    db = context.application.bot_data["db"]
    chat_id = settings.group_chat_id
    if not chat_id:
        return

    try:
        saved = await db.get_saved_group_permissions(chat_id)
        if saved:
            permissions = ChatPermissions(**json.loads(saved))
        else:
            # Safe fallback for a normal discussion group if no snapshot exists.
            permissions = ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
                can_manage_topics=False,
            )

        await context.bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=permissions,
            use_independent_chat_permissions=True,
        )
        await db.clear_group_permissions(chat_id)
        logger.info("Quiet hours disabled for group %s", chat_id)
    except Exception:
        logger.exception("Failed to disable quiet hours")


async def initialize_quiet_hours(application) -> None:
    """Schedule daily lock/unlock and repair state after a Railway restart."""
    settings = application.bot_data["settings"]
    if not settings.group_chat_id:
        logger.warning("Quiet hours not scheduled because GROUP_CHAT_ID is empty")
        return

    if application.job_queue is None:
        raise RuntimeError(
            "JobQueue is unavailable. Install python-telegram-bot with the job-queue extra."
        )

    application.job_queue.run_daily(
        lock_group,
        time=QUIET_START,
        name="kazhwan_quiet_start",
    )
    application.job_queue.run_daily(
        unlock_group,
        time=QUIET_END,
        name="kazhwan_quiet_end",
    )

    # If Railway restarts at night, the group should still remain closed;
    # if it restarts during daytime, ensure it is open.
    class StartupContext:
        def __init__(self, app):
            self.application = app
            self.bot = app.bot

    startup_context = StartupContext(application)
    if _is_quiet_now():
        await lock_group(startup_context)
    else:
        # Only restore if a previous night-lock snapshot exists.
        db = application.bot_data["db"]
        if await db.get_saved_group_permissions(settings.group_chat_id):
            await unlock_group(startup_context)


async def track_group_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    if not update.effective_chat or update.effective_chat.id != settings.group_chat_id:
        return
    if not update.effective_user or update.effective_user.is_bot:
        return

    db = context.application.bot_data["db"]
    await db.touch_member_activity(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username,
        display_name=update.effective_user.full_name,
    )


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    change = update.chat_member
    if change is None:
        return

    settings = context.application.bot_data["settings"]
    if change.chat.id != settings.group_chat_id:
        return

    old_status = change.old_chat_member.status
    new_status = change.new_chat_member.status
    member = change.new_chat_member.user

    was_member = old_status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    }
    is_member = new_status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    }

    if not was_member and is_member and not member.is_bot:
        db = context.application.bot_data["db"]
        await db.touch_member_activity(
            telegram_id=member.id,
            username=member.username,
            display_name=member.full_name,
        )
        await context.bot.send_message(
            chat_id=change.chat.id,
            text=f"🌿 {member.full_name} عزیز، به گروه خوش اومدی.",
        )


def moderation_handlers():
    return [
        ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER),
        MessageHandler(filters.ChatType.GROUPS, track_group_activity),
    ]
