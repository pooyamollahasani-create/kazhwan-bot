from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import Forbidden, RetryAfter, TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db import BtcMembership, Trip, TripParticipant, User

logger = logging.getLogger(__name__)

BROADCAST_CITY, BROADCAST_CONTENT = range(410, 412)

# Importing this module patches only the admin keyboard, without replacing admin.py.
# This keeps the tested v1.9 admin code untouched.
from bot.handlers import admin as admin_module

_original_admin_keyboard = admin_module._admin_keyboard


def _admin_keyboard_with_broadcast() -> InlineKeyboardMarkup:
    markup = _original_admin_keyboard()
    rows = [list(row) for row in markup.inline_keyboard]
    button = InlineKeyboardButton("📣 ارسال پیام همگانی", callback_data="broadcast:start")
    # Avoid duplication if the module is ever reloaded.
    if not any(b.callback_data == "broadcast:start" for row in rows for b in row):
        rows.append([button])
    return InlineKeyboardMarkup(rows)


admin_module._admin_keyboard = _admin_keyboard_with_broadcast


def _is_admin(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return user_id in context.application.bot_data["settings"].admin_ids


def _audience_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 همه کاربران دارای تلگرام", callback_data="broadcast:audience:all")],
        [InlineKeyboardButton("⛰ اعضای BTC", callback_data="broadcast:audience:btc")],
        [
            InlineKeyboardButton("🇮🇷 سفرهای داخلی", callback_data="broadcast:audience:domestic"),
            InlineKeyboardButton("🌍 سفرهای خارجی", callback_data="broadcast:audience:international"),
        ],
        [InlineKeyboardButton("🧳 مسافران یک سفر مشخص", callback_data="broadcast:audience:trip")],
        [InlineKeyboardButton("📍 بر اساس شهر", callback_data="broadcast:audience:city")],
        [InlineKeyboardButton("❌ لغو", callback_data="broadcast:cancel")],
    ])


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و ارسال", callback_data="broadcast:send")],
        [InlineKeyboardButton("🔄 تغییر پیام", callback_data="broadcast:change")],
        [InlineKeyboardButton("❌ لغو", callback_data="broadcast:cancel")],
    ])


async def _recipient_ids(db, audience: dict) -> list[int]:
    """Return unique Telegram IDs for the selected audience."""
    kind = audience.get("kind")
    async with db.sessions() as session:
        if kind == "all":
            result = await session.execute(
                select(User.telegram_id).where(User.status == "active")
            )
        elif kind == "btc":
            result = await session.execute(
                select(User.telegram_id)
                .join(BtcMembership, BtcMembership.telegram_id == User.telegram_id)
                .where(User.status == "active", BtcMembership.status == "active")
            )
        elif kind == "international":
            result = await session.execute(
                select(User.telegram_id)
                .join(TripParticipant, TripParticipant.telegram_id == User.telegram_id)
                .join(Trip, Trip.id == TripParticipant.trip_id)
                .where(
                    User.status == "active",
                    TripParticipant.status == "attended",
                    Trip.trip_type == "international",
                    Trip.archived.is_(False),
                )
                .distinct()
            )
        elif kind == "domestic":
            result = await session.execute(
                select(User.telegram_id)
                .join(TripParticipant, TripParticipant.telegram_id == User.telegram_id)
                .join(Trip, Trip.id == TripParticipant.trip_id)
                .where(
                    User.status == "active",
                    TripParticipant.status == "attended",
                    Trip.trip_type.in_(["domestic_day", "domestic_multi"]),
                    Trip.archived.is_(False),
                )
                .distinct()
            )
        elif kind == "trip":
            result = await session.execute(
                select(User.telegram_id)
                .join(TripParticipant, TripParticipant.telegram_id == User.telegram_id)
                .where(
                    User.status == "active",
                    TripParticipant.trip_id == int(audience["trip_id"]),
                    TripParticipant.status == "attended",
                )
                .distinct()
            )
        elif kind == "city":
            city = (audience.get("city") or "").strip()
            # City data is user-entered, so accept common prefixes/suffixes around the name.
            result = await session.execute(
                select(User.telegram_id).where(
                    User.status == "active",
                    User.city.ilike(f"%{city}%"),
                )
            )
        else:
            return []
        return list(dict.fromkeys(int(x) for x in result.scalars().all()))


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_admin(update.effective_user.id, context):
        return ConversationHandler.END
    if update.effective_chat.type != ChatType.PRIVATE:
        await update.effective_message.reply_text("📣 ارسال همگانی فقط در PV ربات انجام می‌شود.")
        return ConversationHandler.END
    context.user_data.pop("broadcast", None)
    await update.effective_message.reply_text(
        "📣 ارسال پیام همگانی\n\nمخاطبان این پیام را انتخاب کنید:",
        reply_markup=_audience_keyboard(),
    )
    return BROADCAST_CONTENT


async def broadcast_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not _is_admin(query.from_user.id, context):
        return ConversationHandler.END
    await query.answer()
    context.user_data.pop("broadcast", None)
    await query.message.reply_text(
        "📣 ارسال پیام همگانی\n\nمخاطبان این پیام را انتخاب کنید:",
        reply_markup=_audience_keyboard(),
    )
    return BROADCAST_CONTENT


async def audience_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not _is_admin(query.from_user.id, context):
        return ConversationHandler.END
    await query.answer()
    action = query.data.split(":")[-1]
    db = context.application.bot_data["db"]

    if action == "city":
        context.user_data["broadcast"] = {"audience": {"kind": "city"}}
        await query.message.reply_text(
            "📍 نام شهر را بفرستید.\nمثلاً: تهران یا کرج"
        )
        return BROADCAST_CITY

    if action == "trip":
        trips = await db.list_trips(limit=40)
        rows = []
        for trip in trips:
            rows.append([InlineKeyboardButton(
                f"{trip.title} | {trip.trip_code}"[:60],
                callback_data=f"broadcast:trip:{trip.id}",
            )])
        rows.append([InlineKeyboardButton("❌ لغو", callback_data="broadcast:cancel")])
        await query.message.reply_text(
            "🧳 سفر موردنظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return BROADCAST_CONTENT

    labels = {
        "all": "همه کاربران دارای تلگرام",
        "btc": "اعضای BTC",
        "domestic": "مسافران سفرهای داخلی",
        "international": "مسافران سفرهای خارجی",
    }
    if action not in labels:
        return BROADCAST_CONTENT
    context.user_data["broadcast"] = {
        "audience": {"kind": action},
        "audience_label": labels[action],
    }
    return await _ask_for_content(query.message, context)


async def trip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not _is_admin(query.from_user.id, context):
        return ConversationHandler.END
    await query.answer()
    trip_id = int(query.data.split(":")[-1])
    db = context.application.bot_data["db"]
    trip = await db.get_trip(trip_id)
    if not trip:
        await query.message.reply_text("این سفر پیدا نشد.")
        return ConversationHandler.END
    context.user_data["broadcast"] = {
        "audience": {"kind": "trip", "trip_id": trip_id},
        "audience_label": f"مسافران سفر «{trip.title}»",
    }
    return await _ask_for_content(query.message, context)


async def city_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_admin(update.effective_user.id, context):
        return ConversationHandler.END
    city = (update.effective_message.text or "").strip()
    if len(city) < 2 or len(city) > 60:
        await update.effective_message.reply_text("نام شهر معتبر نیست. دوباره بفرستید.")
        return BROADCAST_CITY
    data = context.user_data.setdefault("broadcast", {})
    data["audience"] = {"kind": "city", "city": city}
    data["audience_label"] = f"کاربران شهر «{city}»"
    return await _ask_for_content(update.effective_message, context)


async def _ask_for_content(message, context) -> int:
    data = context.user_data.get("broadcast", {})
    recipients = await _recipient_ids(context.application.bot_data["db"], data["audience"])
    data["recipient_ids"] = recipients
    count = len(recipients)
    if count == 0:
        await message.reply_text(
            f"⚠️ برای «{data.get('audience_label', 'این فیلتر')}» هیچ مخاطب تلگرامی پیدا نشد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 انتخاب مخاطب دیگر", callback_data="broadcast:start")]
            ]),
        )
        return ConversationHandler.END
    await message.reply_text(
        f"🎯 مخاطب: {data['audience_label']}\n"
        f"👥 تعداد گیرنده: {count}\n\n"
        "حالا پیام تبلیغاتی را بفرستید.\n\n"
        "می‌توانید یکی از این‌ها را بفرستید:\n"
        "• متن\n• عکس + کپشن\n• ویدیو + کپشن\n\n"
        "ربات قبل از ارسال همگانی، پیش‌نمایش و تأیید نهایی نشان می‌دهد."
    )
    return BROADCAST_CONTENT


async def content_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_admin(update.effective_user.id, context):
        return ConversationHandler.END
    data = context.user_data.get("broadcast")
    if not data or "recipient_ids" not in data:
        return ConversationHandler.END

    msg = update.effective_message
    # v1.10 intentionally supports text, photo and video only.
    if not (msg.text or msg.photo or msg.video):
        await msg.reply_text("فعلاً فقط متن، عکس یا ویدیو قابل ارسال است. دوباره بفرستید.")
        return BROADCAST_CONTENT

    data["source_chat_id"] = msg.chat_id
    data["source_message_id"] = msg.message_id

    await msg.reply_text(
        f"👁 پیش‌نمایش پیام\n\n"
        f"🎯 مخاطب: {data['audience_label']}\n"
        f"👥 تعداد گیرنده: {len(data['recipient_ids'])}"
    )
    await context.bot.copy_message(
        chat_id=msg.chat_id,
        from_chat_id=msg.chat_id,
        message_id=msg.message_id,
    )
    await msg.reply_text(
        "اگر همین پیام درست است، ارسال را تأیید کنید:",
        reply_markup=_confirm_keyboard(),
    )
    return BROADCAST_CONTENT


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not _is_admin(query.from_user.id, context):
        return ConversationHandler.END
    await query.answer()
    action = query.data.split(":")[-1]
    if action == "cancel":
        context.user_data.pop("broadcast", None)
        await query.message.reply_text("❌ ارسال همگانی لغو شد.")
        return ConversationHandler.END
    if action == "change":
        data = context.user_data.get("broadcast", {})
        data.pop("source_chat_id", None)
        data.pop("source_message_id", None)
        await query.message.reply_text("🔄 پیام جدید را بفرستید.")
        return BROADCAST_CONTENT
    if action != "send":
        return BROADCAST_CONTENT

    data = context.user_data.get("broadcast")
    if not data or not data.get("source_message_id"):
        await query.message.reply_text("اطلاعات پیام پیدا نشد. دوباره از «ارسال پیام همگانی» شروع کنید.")
        return ConversationHandler.END

    recipients = list(dict.fromkeys(data["recipient_ids"]))
    await query.message.reply_text(
        f"📤 ارسال برای {len(recipients)} نفر شروع شد...\n"
        "تا پایان ارسال، دوباره دکمه ارسال را نزنید."
    )

    success = 0
    failed = 0
    blocked = 0
    for telegram_id in recipients:
        try:
            await context.bot.copy_message(
                chat_id=telegram_id,
                from_chat_id=data["source_chat_id"],
                message_id=data["source_message_id"],
            )
            success += 1
        except RetryAfter as exc:
            wait_for = float(getattr(exc, "retry_after", 1)) + 0.5
            await asyncio.sleep(wait_for)
            try:
                await context.bot.copy_message(
                    chat_id=telegram_id,
                    from_chat_id=data["source_chat_id"],
                    message_id=data["source_message_id"],
                )
                success += 1
            except TelegramError:
                failed += 1
        except Forbidden:
            blocked += 1
        except TelegramError:
            failed += 1

        # Gentle pacing reduces Telegram flood-limit risk for larger lists.
        await asyncio.sleep(0.04)

    label = data.get("audience_label", "-")
    context.user_data.pop("broadcast", None)
    await query.message.reply_text(
        "✅ ارسال همگانی پایان یافت.\n\n"
        f"🎯 مخاطب: {label}\n"
        f"📨 موفق: {success}\n"
        f"🚫 ربات مسدود/غیرقابل دسترس: {blocked}\n"
        f"⚠️ ناموفق: {failed}\n"
        f"👥 مجموع: {len(recipients)}"
    )
    return ConversationHandler.END


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.reply_text("❌ ارسال همگانی لغو شد.")
    context.user_data.pop("broadcast", None)
    return ConversationHandler.END


def broadcast_handlers():
    flow = ConversationHandler(
        entry_points=[
            CommandHandler("broadcast", broadcast_command),
            CallbackQueryHandler(broadcast_start_callback, pattern=r"^broadcast:start$"),
        ],
        states={
            BROADCAST_CITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, city_receive),
                CallbackQueryHandler(cancel_callback, pattern=r"^broadcast:cancel$"),
            ],
            BROADCAST_CONTENT: [
                CallbackQueryHandler(audience_callback, pattern=r"^broadcast:audience:(all|btc|domestic|international|trip|city)$"),
                CallbackQueryHandler(trip_callback, pattern=r"^broadcast:trip:\d+$"),
                CallbackQueryHandler(confirm_callback, pattern=r"^broadcast:(send|change|cancel)$"),
                CallbackQueryHandler(broadcast_start_callback, pattern=r"^broadcast:start$"),
                MessageHandler((filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND, content_receive),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_callback, pattern=r"^broadcast:cancel$"),
        ],
        allow_reentry=True,
        name="kazhwan_broadcast_v1_10",
        persistent=False,
    )
    return [flow]
