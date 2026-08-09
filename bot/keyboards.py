from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 ارسال شماره تماس", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def channel_keyboard(channel_username: str) -> InlineKeyboardMarkup:
    username = channel_username.lstrip("@")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال کژوان", url=f"https://t.me/{username}")],
        [InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_channel")],
    ])


def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ قوانین را مطالعه کردم و می‌پذیرم", callback_data="accept_rules")]
    ])


def discovery_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📸 اینستاگرام", callback_data="source:اینستاگرام"),
         InlineKeyboardButton("✈️ تلگرام", callback_data="source:تلگرام")],
        [InlineKeyboardButton("👥 معرفی دوستان", callback_data="source:معرفی دوستان")],
        [InlineKeyboardButton("🥾 سفرهای قبلی کژوان", callback_data="source:سفرهای قبلی کژوان")],
        [InlineKeyboardButton("🌐 گوگل", callback_data="source:گوگل"),
         InlineKeyboardButton("🤝 شرکت یا سازمان", callback_data="source:شرکت یا سازمان")],
        [InlineKeyboardButton("🎪 رویدادها و نمایشگاه‌ها", callback_data="source:رویدادها و نمایشگاه‌ها")],
        [InlineKeyboardButton("✍️ سایر", callback_data="source:other")],
    ]
    return InlineKeyboardMarkup(rows)


def referral_question_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ بله، کد معرف دارم", callback_data="referral:yes"),
            InlineKeyboardButton("❌ خیر", callback_data="referral:no"),
        ]
    ])


def referral_retry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ کد معرف ندارم", callback_data="referral:no")]
    ])


def private_start_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌿 ادامه در گفت‌وگوی خصوصی", url=f"https://t.me/{bot_username}?start=join")]
    ])


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["🗓 برنامه‌های آینده", "📝 ثبت‌نام‌های من"],
            ["👤 پروفایل من", "📜 تاریخچه فعالیت‌های من"],
            ["🎖 کارت عضویت", "📞 پشتیبانی"],
        ],
        resize_keyboard=True,
    )
