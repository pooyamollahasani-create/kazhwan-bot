import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import (
    CallbackQueryHandler,
    ChatJoinRequestHandler,
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
    private_start_keyboard,
    referral_question_keyboard,
    referral_retry_keyboard,
    rules_keyboard,
    trip_confirm_keyboard,
)
from bot.profile_extra import save_neighborhood
from bot.texts import RULES_TEXT, WELCOME_TEXT

logger = logging.getLogger(__name__)

(
    FULL_NAME,
    PHONE,
    CITY,
    NEIGHBORHOOD,
    SOURCE,
    SOURCE_OTHER,
    REFERRAL_HAS,
    REFERRAL_SEARCH,
    REFERRAL_CONFIRM,
    CHANNEL,
    RULES,
) = range(11)


def _is_private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE)


def _mask_phone(value: str | None) -> str:
    if not value:
        return "ثبت نشده"
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) <= 7:
        return value
    return f"{digits[:4]}***{digits[-4:]}"


async def _show_referrer_confirmation(message, context, referrer) -> int:
    context.user_data["pending_referrer_telegram_id"] = referrer.telegram_id
    await message.reply_text(
        "آیا معرف شما این شخص است؟\n\n"
        f"👤 {referrer.full_name}\n"
        f"📍 {referrer.city or '-'}\n"
        f"📱 {_mask_phone(referrer.phone)}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ بله، همین شخص است", callback_data="referralconfirm:yes"),
                InlineKeyboardButton("🔎 خیر، دوباره جستجو", callback_data="referralconfirm:no"),
            ]
        ]),
    )
    return REFERRAL_CONFIRM


async def begin_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    request = update.chat_join_request
    if request is None:
        return ConversationHandler.END

    settings = context.application.bot_data["settings"]
    if settings.group_chat_id is None:
        logger.warning("Join request ignored because GROUP_CHAT_ID is not configured")
        return ConversationHandler.END
    if request.chat.id != settings.group_chat_id:
        return ConversationHandler.END

    db = context.application.bot_data["db"]
    existing = await db.get_user(request.from_user.id)

    await db.save_pending_join(
        telegram_id=request.from_user.id,
        group_chat_id=request.chat.id,
        user_chat_id=request.user_chat_id,
    )
    context.user_data.clear()

    if existing and existing.channel_verified:
        btc = await db.get_btc_membership(request.from_user.id)
        if btc and btc.rules_accepted:
            try:
                await context.bot.approve_chat_join_request(request.chat.id, request.from_user.id)
                await db.mark_group_approved_and_reward_referrer(request.from_user.id)
                await db.delete_pending_join(request.from_user.id)
                await context.bot.send_message(
                    chat_id=request.user_chat_id,
                    text=(
                        f"سلام {existing.full_name} 🌿\n"
                        "پروفایل کژوان و عضویت BTC شما از قبل ثبت شده بود و درخواست ورود تأیید شد."
                    ),
                    reply_markup=main_menu(),
                )
            except Exception:
                logger.exception("Failed to approve an existing BTC user's join request")
            return ConversationHandler.END

        try:
            await context.bot.send_message(
                chat_id=request.user_chat_id,
                text=(
                    f"سلام {existing.full_name} 🌿\n\n"
                    "پروفایل کژوان شما از قبل تکمیل شده است. برای عضویت در Beyond The Clouds "
                    "فقط قوانین گروه را مطالعه و تأیید کنید."
                ),
            )
            await context.bot.send_message(
                chat_id=request.user_chat_id,
                text=RULES_TEXT,
                reply_markup=rules_keyboard(),
            )
            return RULES
        except Exception:
            logger.exception("Could not send BTC rules to existing Kazhwan user")
            return ConversationHandler.END

    try:
        await context.bot.send_message(
            chat_id=request.user_chat_id,
            text=(
                "سلام 🌿\n\n"
                "درخواست عضویت شما در گروه کژوان دریافت شد. "
                "برای تأیید عضویت، چند سؤال کوتاه را همین‌جا پاسخ دهید."
            ),
        )
        await context.bot.send_message(
            chat_id=request.user_chat_id,
            text="لطفاً نام و نام خانوادگی خود را وارد کنید:",
        )
    except Exception:
        logger.exception("Could not message join requester")
        return ConversationHandler.END

    return FULL_NAME


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_private(update):
        me = await context.bot.get_me()
        await update.effective_message.reply_text(
            "برای تکمیل عضویت و استفاده از ربات، وارد گفت‌وگوی خصوصی شوید.",
            reply_markup=private_start_keyboard(me.username),
        )
        return ConversationHandler.END

    db = context.application.bot_data["db"]
    pending_trip_id = None
    if context.args and context.args[0].startswith("trip_"):
        try:
            pending_trip_id = int(context.args[0].split("_", 1)[1])
        except (ValueError, IndexError):
            pending_trip_id = None

    if pending_trip_id is not None:
        trip = await db.get_trip(pending_trip_id)
        if not trip:
            await update.message.reply_text("این سفر پیدا نشد یا دیگر در دسترس نیست.")
            pending_trip_id = None
        elif trip.status != "open":
            await update.message.reply_text("ثبت این سفر در حال حاضر بسته است.")
            pending_trip_id = None

    user = await db.get_user(update.effective_user.id)
    if user:
        settings = context.application.bot_data["settings"]
        if settings.group_chat_id:
            try:
                member = await context.bot.get_chat_member(settings.group_chat_id, user.telegram_id)
                if member.status in {
                    ChatMemberStatus.MEMBER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.OWNER,
                }:
                    await db.mark_existing_group_member(user.telegram_id)
                    await db.ensure_member_activity(
                        user.telegram_id, user.telegram_username, user.full_name
                    )
            except Exception:
                logger.exception("Could not check existing member status on /start")
        if pending_trip_id is not None:
            trip = await db.get_trip(pending_trip_id)
            if trip:
                await update.message.reply_text(
                    f"🧳 سفر «{trip.title}» | {trip.start_date_text} تا {trip.end_date_text}\n\n"
                    "این سفر در پروفایل شما ثبت شود؟",
                    reply_markup=trip_confirm_keyboard(trip.id),
                )
                return ConversationHandler.END
        await update.message.reply_text(
            f"سلام {user.full_name} 🌿",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    context.user_data.clear()
    if pending_trip_id is not None:
        context.user_data["pending_trip_id"] = pending_trip_id

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
    await update.message.reply_text(
        "محله محل سکونت خود را وارد کنید:\n"
        "مثال: ستارخان، عظیمیه، مهرشهر\n\n"
        "اگر محله مشخصی ندارید بنویسید «ندارم»."
    )
    return NEIGHBORHOOD


async def neighborhood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.message.text or "").strip()
    if len(value) < 2:
        await update.message.reply_text("لطفاً نام محله را وارد کنید یا بنویسید «ندارم».")
        return NEIGHBORHOOD
    context.user_data["neighborhood"] = value
    await update.message.reply_text(
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

    context.user_data["discovery_source"] = selected
    await query.message.reply_text(
        "آیا معرف دارید؟",
        reply_markup=referral_question_keyboard(),
    )
    return REFERRAL_HAS


async def source_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    selected = (update.message.text or "").strip()
    if len(selected) < 2:
        await update.message.reply_text("لطفاً توضیح کوتاهی وارد کنید.")
        return SOURCE_OTHER
    context.user_data["discovery_source"] = selected
    await update.message.reply_text(
        "آیا معرف دارید؟",
        reply_markup=referral_question_keyboard(),
    )
    return REFERRAL_HAS


async def referral_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]

    if choice == "no":
        context.user_data["referred_by_telegram_id"] = None
        return await ask_channel_membership(query.message, context)

    await query.message.reply_text(
        "برای پیدا کردن معرف، یکی از این موارد را وارد کنید:\n\n"
        "• نام و نام خانوادگی\n"
        "• شماره موبایل\n"
        "• کد معرف یا کد عضویت KZH\n\n"
        "مثال: محمد رضایی یا 09121234567",
        reply_markup=referral_retry_keyboard(),
    )
    return REFERRAL_SEARCH


async def referral_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = (update.message.text or "").strip()
    if len(value) < 2:
        await update.message.reply_text(
            "نام، شماره موبایل یا کد معرف را کمی کامل‌تر وارد کنید.",
            reply_markup=referral_retry_keyboard(),
        )
        return REFERRAL_SEARCH

    db = context.application.bot_data["db"]
    candidates = await db.search_users(value, limit=12)
    candidates = [
        user for user in candidates
        if user.telegram_id != update.effective_user.id and user.status == "active"
    ]

    if not candidates:
        await update.message.reply_text(
            "معرفی با این مشخصات پیدا نشد.\n"
            "دوباره نام، شماره موبایل یا کد را وارد کنید؛ "
            "یا اگر معرف ندارید دکمه «معرف ندارم» را بزنید.",
            reply_markup=referral_retry_keyboard(),
        )
        return REFERRAL_SEARCH

    if len(candidates) == 1:
        return await _show_referrer_confirmation(update.message, context, candidates[0])

    rows = []
    for user in candidates[:8]:
        label = f"👤 {user.full_name} | {user.city or '-'} | {_mask_phone(user.phone)}"
        rows.append([
            InlineKeyboardButton(
                label[:60],
                callback_data=f"referralpick:{user.telegram_id}",
            )
        ])
    rows.append([InlineKeyboardButton("❌ معرف ندارم", callback_data="referral:no")])
    await update.message.reply_text(
        "چند نفر پیدا شدند. معرف خودتان را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return REFERRAL_SEARCH


async def referral_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    try:
        telegram_id = int(query.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.message.reply_text("این انتخاب معتبر نیست. دوباره جستجو کنید.")
        return REFERRAL_SEARCH

    if telegram_id == query.from_user.id:
        await query.message.reply_text("نمی‌توانید خودتان را به عنوان معرف انتخاب کنید.")
        return REFERRAL_SEARCH

    db = context.application.bot_data["db"]
    referrer = await db.get_user(telegram_id)
    if not referrer:
        await query.message.reply_text("این شخص پیدا نشد. لطفاً دوباره جستجو کنید.")
        return REFERRAL_SEARCH

    return await _show_referrer_confirmation(query.message, context, referrer)


async def referral_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]

    if choice == "no":
        context.user_data.pop("pending_referrer_telegram_id", None)
        await query.message.reply_text(
            "دوباره نام، شماره موبایل یا کد معرف را وارد کنید:",
            reply_markup=referral_retry_keyboard(),
        )
        return REFERRAL_SEARCH

    telegram_id = context.user_data.pop("pending_referrer_telegram_id", None)
    if telegram_id is None:
        await query.message.reply_text("لطفاً معرف را دوباره جستجو کنید.")
        return REFERRAL_SEARCH

    db = context.application.bot_data["db"]
    referrer = await db.get_user(int(telegram_id))
    if not referrer or referrer.telegram_id == query.from_user.id:
        await query.message.reply_text("معرف معتبر نیست. لطفاً دوباره جستجو کنید.")
        return REFERRAL_SEARCH

    context.user_data["referred_by_telegram_id"] = referrer.telegram_id
    await query.message.reply_text(f"✅ معرف شما «{referrer.full_name}» ثبت شد.")
    return await ask_channel_membership(query.message, context)


async def ask_channel_membership(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings = context.application.bot_data["settings"]
    await message.reply_text(
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
    db = context.application.bot_data["db"]
    pending_join = await db.get_pending_join(query.from_user.id)
    if pending_join:
        await query.message.reply_text(RULES_TEXT, reply_markup=rules_keyboard())
        return RULES
    return await finish_registration(update, context)


async def accept_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    return await finish_registration(update, context)


async def _notify_admins_about_guest_matches(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    db = context.application.bot_data["db"]
    settings = context.application.bot_data["settings"]
    candidates = await db.find_guest_match_candidates(user.full_name, user.phone, limit=8)
    if not candidates:
        return
    for guest in candidates:
        phone_text = guest.phone or "بدون شماره"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ اتصال سابقه", callback_data=f"guestmatch:link:{guest.id}:{user.telegram_id}"),
            InlineKeyboardButton("❌ این شخص نیست", callback_data=f"guestmatch:skip:{guest.id}:{user.telegram_id}"),
        ]])
        text = (
            "🔗 احتمال تطبیق مسافر موقت با پروفایل جدید\n\n"
            f"پروفایل جدید: {user.full_name} | {user.phone}\n"
            f"سابقه موقت: {guest.full_name} | {phone_text}\n\n"
            "اگر یک نفر هستند، اتصال را تأیید کنید. امتیاز سفرهای تأییدشده بعد از اتصال منتقل می‌شود."
        )
        for admin_id in settings.admin_ids:
            try:
                await context.bot.send_message(chat_id=admin_id, text=text, reply_markup=keyboard)
            except Exception:
                logger.exception("Could not send guest-match suggestion to admin %s", admin_id)


async def finish_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = context.application.bot_data["db"]
    tg_user = update.effective_user

    existing = await db.get_user(tg_user.id)
    is_new_profile = existing is None
    if existing:
        user = existing
    else:
        user = await db.create_user(
            telegram_id=tg_user.id,
            telegram_username=tg_user.username,
            full_name=context.user_data["full_name"],
            phone=context.user_data["phone"],
            city=context.user_data["city"],
            discovery_source=context.user_data["discovery_source"],
            referred_by_telegram_id=context.user_data.get("referred_by_telegram_id"),
        )
        await save_neighborhood(
            db,
            tg_user.id,
            context.user_data.get("neighborhood", ""),
        )

    await db.reward_referrer_if_needed(tg_user.id)

    if is_new_profile:
        await _notify_admins_about_guest_matches(context, user)

    approved = False
    pending_join = await db.get_pending_join(tg_user.id)
    pending_group_chat_id = pending_join.group_chat_id if pending_join else None
    if pending_group_chat_id:
        try:
            await context.bot.approve_chat_join_request(
                chat_id=pending_group_chat_id,
                user_id=tg_user.id,
            )
            await db.mark_group_approved_and_reward_referrer(tg_user.id)
            await db.ensure_member_activity(tg_user.id, tg_user.username, user.full_name)
            await db.delete_pending_join(tg_user.id)
            approved = True
        except Exception:
            logger.exception("Failed to approve join request after onboarding")

    if approved:
        btc = await db.get_btc_membership(tg_user.id)
        message = (
            "🎉 عضویت شما در Beyond The Clouds با موفقیت تأیید شد.\n\n"
            f"کد عضویت کژوان: {user.member_code}\n"
            f"کد عضویت BTC: {btc.btc_code if btc else '-'}\n"
            f"کد معرف کژوان: {user.referral_code}\n\n"
            "کد معرف را می‌توانید به دوستانتان بدهید."
        )
    elif pending_group_chat_id:
        message = (
            "✅ اطلاعات شما با موفقیت ثبت شد، اما تأیید خودکار ورود به گروه انجام نشد.\n"
            "مدیران موضوع را بررسی می‌کنند.\n\n"
            f"کد عضویت کژوان: {user.member_code}\n"
            f"کد معرف کژوان: {user.referral_code}"
        )
    else:
        settings = context.application.bot_data["settings"]
        already_in_group = False
        if settings.group_chat_id:
            try:
                member = await context.bot.get_chat_member(settings.group_chat_id, tg_user.id)
                already_in_group = member.status in {
                    ChatMemberStatus.MEMBER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.OWNER,
                }
            except Exception:
                logger.exception("Could not check group membership after registration")

        if already_in_group:
            await db.mark_existing_group_member(tg_user.id)
            await db.ensure_member_activity(
                tg_user.id, tg_user.username, user.full_name
            )
            btc = await db.get_btc_membership(tg_user.id)
            message = (
                "✅ اطلاعات شما با موفقیت ثبت شد.\n\n"
                f"کد عضویت کژوان: {user.member_code}\n"
                f"کد عضویت BTC: {btc.btc_code if btc else '-'}\n"
                f"کد معرف کژوان: {user.referral_code}"
            )
        else:
            message = (
                "🎉 پروفایل شما با موفقیت ثبت شد.\n\n"
                f"کد عضویت کژوان: {user.member_code}\n"
                f"کد معرف کژوان: {user.referral_code}\n"
                "عضویت در BTC جداست و فقط در صورت درخواست عضویت گروه برای شما کد BTC صادر می‌شود."
            )

    pending_trip_id = context.user_data.get("pending_trip_id")
    target_message = update.callback_query.message if update.callback_query else update.message
    await target_message.reply_text(message, reply_markup=main_menu())

    if pending_trip_id is not None:
        trip = await db.get_trip(int(pending_trip_id))
        if trip and trip.status == "open":
            await target_message.reply_text(
                f"🧳 سفر «{trip.title}» | {trip.start_date_text} تا {trip.end_date_text}\n\n"
                "این سفر در پروفایل شما ثبت شود؟",
                reply_markup=trip_confirm_keyboard(trip.id),
            )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "فرآیند تکمیل اطلاعات متوقف شد. برای شروع دوباره /start را بزنید."
    )
    return ConversationHandler.END


def build_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            ChatJoinRequestHandler(begin_join_request),
            CommandHandler("start", start),
        ],
        states={
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, full_name)],
            PHONE: [MessageHandler(filters.CONTACT, phone)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, city)],
            NEIGHBORHOOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, neighborhood)],
            SOURCE: [CallbackQueryHandler(source, pattern="^source:")],
            SOURCE_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, source_other)],
            REFERRAL_HAS: [CallbackQueryHandler(referral_choice, pattern="^referral:(yes|no)$")],
            REFERRAL_SEARCH: [
                CallbackQueryHandler(referral_choice, pattern="^referral:no$"),
                CallbackQueryHandler(referral_pick, pattern=r"^referralpick:-?\d+$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, referral_search),
            ],
            REFERRAL_CONFIRM: [
                CallbackQueryHandler(referral_confirm, pattern="^referralconfirm:(yes|no)$"),
                CallbackQueryHandler(referral_choice, pattern="^referral:no$"),
            ],
            CHANNEL: [CallbackQueryHandler(check_channel, pattern="^check_channel$")],
            RULES: [CallbackQueryHandler(accept_rules, pattern="^accept_rules$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_chat=False,
        per_user=True,
    )
