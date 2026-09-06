from __future__ import annotations

from datetime import datetime, timezone
import re

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column
from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db import Activity, Base, Trip, TripParticipant, User
from bot.handlers.admin import is_admin
from bot.utils.xlsx import build_xlsx

FEEDBACK_REWARD_POINTS = 2
GUIDES_INPUT = 410
BEST_PART_INPUT = 420
IMPROVEMENT_INPUT = 421
GUIDE_COMMENT_INPUT = 422


class TripFeedbackSurvey(Base):
    __tablename__ = "trip_feedback_surveys"

    trip_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reward_points: Mapped[int] = mapped_column(Integer, default=FEEDBACK_REWARD_POINTS)
    created_by_telegram_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TripFeedbackGuide(Base):
    __tablename__ = "trip_feedback_guides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(160))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Reserved for the future leader-profile feature.
    leader_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)


class TripFeedbackResponse(Base):
    __tablename__ = "trip_feedback_responses"

    trip_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    overall_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    organization_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    services_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommend: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    best_part: Mapped[str | None] = mapped_column(Text, nullable=True)
    improvement: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reward_awarded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TripFeedbackGuideRating(Base):
    __tablename__ = "trip_feedback_guide_ratings"

    guide_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    trip_id: Mapped[int] = mapped_column(Integer, index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def _score_keyboard(prefix: str = "fbscore") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"{i} ⭐", callback_data=f"{prefix}:{i}") for i in range(1, 6)
    ]])


def _recommend_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ بله", callback_data="fbrecommend:yes"),
        InlineKeyboardButton("❌ خیر", callback_data="fbrecommend:no"),
    ]])


def _admin_feedback_keyboard(trip_id: int, survey, has_responses: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🧭 ثبت / ویرایش راهنماها", callback_data=f"tripfeedback:guides:{trip_id}")],
        [InlineKeyboardButton(
            "📨 ارسال یادآوری" if survey and survey.sent_at else "📤 ارسال نظرسنجی",
            callback_data=f"tripfeedback:send:{trip_id}",
        )],
        [
            InlineKeyboardButton("📊 نتایج", callback_data=f"tripfeedback:results:{trip_id}"),
            InlineKeyboardButton("📥 Excel", callback_data=f"tripfeedback:export:{trip_id}"),
        ],
    ]
    if survey and survey.is_open:
        rows.append([InlineKeyboardButton("🔒 بستن نظرسنجی", callback_data=f"tripfeedback:close:{trip_id}")])
    elif survey and survey.sent_at:
        rows.append([InlineKeyboardButton("🔓 باز کردن نظرسنجی", callback_data=f"tripfeedback:open:{trip_id}")])
    rows.append([InlineKeyboardButton("⬅️ بازگشت به سفر", callback_data=f"tripadmin:view:{trip_id}")])
    return InlineKeyboardMarkup(rows)


async def _get_or_create_survey(db, trip_id: int, admin_id: int) -> TripFeedbackSurvey | None:
    async with db.sessions() as session:
        trip = await session.get(Trip, trip_id)
        if not trip:
            return None
        survey = await session.get(TripFeedbackSurvey, trip_id)
        if survey is None:
            survey = TripFeedbackSurvey(
                trip_id=trip_id,
                created_by_telegram_id=admin_id,
                reward_points=FEEDBACK_REWARD_POINTS,
                is_open=False,
            )
            session.add(survey)
            await session.commit()
            await session.refresh(survey)
        return survey


async def _get_guides(db, trip_id: int) -> list[TripFeedbackGuide]:
    async with db.sessions() as session:
        result = await session.execute(
            select(TripFeedbackGuide)
            .where(TripFeedbackGuide.trip_id == trip_id)
            .order_by(TripFeedbackGuide.sort_order.asc(), TripFeedbackGuide.id.asc())
        )
        return list(result.scalars().all())


async def _response_count(db, trip_id: int, completed_only: bool = False) -> int:
    async with db.sessions() as session:
        stmt = select(func.count()).select_from(TripFeedbackResponse).where(
            TripFeedbackResponse.trip_id == trip_id
        )
        if completed_only:
            stmt = stmt.where(TripFeedbackResponse.completed.is_(True))
        result = await session.execute(stmt)
        return int(result.scalar_one())


async def _eligible_attendees(db, trip_id: int) -> list[User]:
    async with db.sessions() as session:
        result = await session.execute(
            select(User)
            .join(TripParticipant, TripParticipant.telegram_id == User.telegram_id)
            .where(
                TripParticipant.trip_id == trip_id,
                TripParticipant.status == "attended",
            )
            .order_by(User.full_name.asc())
        )
        return list(result.scalars().all())


async def feedback_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_admin(query.from_user.id, context):
        return
    await query.answer()
    if query.message.chat.type != ChatType.PRIVATE:
        return

    parts = query.data.split(":")
    if len(parts) < 3:
        return
    action = parts[1]
    try:
        trip_id = int(parts[2])
    except ValueError:
        return

    db = context.application.bot_data["db"]
    trip = await db.get_trip(trip_id)
    if not trip:
        await query.message.reply_text("سفر پیدا نشد.")
        return
    survey = await _get_or_create_survey(db, trip_id, query.from_user.id)
    guides = await _get_guides(db, trip_id)

    if action == "view":
        eligible = await _eligible_attendees(db, trip_id)
        completed = await _response_count(db, trip_id, completed_only=True)
        guide_text = "، ".join(g.name for g in guides) if guides else "هنوز ثبت نشده"
        status = "🟢 باز" if survey and survey.is_open else "🔒 بسته"
        sent = "✅ ارسال شده" if survey and survey.sent_at else "⚪ هنوز ارسال نشده"
        await query.message.reply_text(
            f"💬 نظرسنجی سفر — {trip.title}\n\n"
            f"🧭 راهنماها: {guide_text}\n"
            f"📨 وضعیت ارسال: {sent}\n"
            f"🔐 وضعیت پاسخ‌گویی: {status}\n"
            f"👥 قابل ارسال در تلگرام: {len(eligible)} نفر\n"
            f"✅ پاسخ کامل: {completed} نفر\n"
            f"⭐ امتیاز تکمیل نظرسنجی: {FEEDBACK_REWARD_POINTS}",
            reply_markup=_admin_feedback_keyboard(trip_id, survey, completed > 0),
        )
        return

    if action in {"open", "close"}:
        async with db.sessions() as session:
            row = await session.get(TripFeedbackSurvey, trip_id)
            if row:
                row.is_open = action == "open"
                await session.commit()
        await query.message.reply_text(
            "✅ نظرسنجی باز شد." if action == "open" else "🔒 نظرسنجی بسته شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ نظرسنجی سفر", callback_data=f"tripfeedback:view:{trip_id}")
            ]]),
        )
        return

    if action == "send":
        if not guides:
            await query.message.reply_text(
                "اول نام راهنماهای این سفر را ثبت کنید.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🧭 ثبت راهنماها", callback_data=f"tripfeedback:guides:{trip_id}")
                ]]),
            )
            return
        attendees = await _eligible_attendees(db, trip_id)
        if not attendees:
            await query.message.reply_text("هیچ مسافر دارای تلگرام با وضعیت «شرکت کرده» برای این سفر وجود ندارد.")
            return

        async with db.sessions() as session:
            row = await session.get(TripFeedbackSurvey, trip_id)
            row.is_open = True
            row.sent_at = datetime.now(timezone.utc)
            completed_result = await session.execute(
                select(TripFeedbackResponse.telegram_id).where(
                    TripFeedbackResponse.trip_id == trip_id,
                    TripFeedbackResponse.completed.is_(True),
                )
            )
            completed_ids = set(completed_result.scalars().all())
            await session.commit()

        sent = 0
        failed = 0
        skipped = 0
        for user in attendees:
            if user.telegram_id in completed_ids:
                skipped += 1
                continue
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=(
                        f"🌿 بازخورد سفر «{trip.title}»\n\n"
                        "تجربه‌ات کمک می‌کنه سفرهای بعدی کژوان بهتر بشن. "
                        f"با تکمیل کامل این نظرسنجی {FEEDBACK_REWARD_POINTS} امتیاز می‌گیری."
                    ),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("💬 شروع نظرسنجی", callback_data=f"feedback:start:{trip_id}")
                    ]]),
                )
                sent += 1
            except Exception:
                failed += 1

        await query.message.reply_text(
            f"📤 نظرسنجی ارسال شد.\n\n"
            f"✅ ارسال موفق: {sent}\n"
            f"⏭ قبلاً تکمیل کرده: {skipped}\n"
            f"⚠️ ارسال ناموفق: {failed}\n\n"
            "ارسال مجدد فقط برای کسانی انجام می‌شود که هنوز نظرسنجی را کامل نکرده‌اند.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ نظرسنجی سفر", callback_data=f"tripfeedback:view:{trip_id}")
            ]]),
        )
        return

    if action == "results":
        text = await _results_text(db, trip_id, trip.title)
        if len(text) > 3900:
            text = text[:3800] + "\n\n… ادامه جزئیات در خروجی Excel موجود است."
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ نظرسنجی سفر", callback_data=f"tripfeedback:view:{trip_id}")
            ]]),
        )
        return

    if action == "export":
        headers, rows = await _export_rows(db, trip_id)
        if not rows:
            await query.message.reply_text("هنوز پاسخ کاملی برای خروجی وجود ندارد.")
            return
        await query.message.reply_document(
            build_xlsx(headers, rows, sheet_name="Feedback"),
            filename=f"{trip.trip_code}_feedback.xlsx",
            caption=f"📥 نظرسنجی سفر {trip.title}",
        )


async def feedback_guides_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not is_admin(query.from_user.id, context):
        return ConversationHandler.END
    await query.answer()
    trip_id = int(query.data.rsplit(":", 1)[1])
    db = context.application.bot_data["db"]
    if await _response_count(db, trip_id, completed_only=False) > 0:
        await query.message.reply_text(
            "⚠️ برای این نظرسنجی پاسخ ثبت شده و برای حفظ صحت نتایج، فهرست راهنماها دیگر قابل تغییر نیست."
        )
        return ConversationHandler.END
    trip = await db.get_trip(trip_id)
    if not trip:
        return ConversationHandler.END
    guides = await _get_guides(db, trip_id)
    current = "\n".join(f"• {g.name}" for g in guides) if guides else "—"
    context.user_data["feedback_guides_trip_id"] = trip_id
    await query.message.reply_text(
        f"🧭 راهنماهای سفر «{trip.title}»\n\n"
        f"فهرست فعلی:\n{current}\n\n"
        "نام تمام راهنماها را بفرستید؛ هر اسم در یک خط جدا.\n"
        "مثال:\nپویا ملاحسنی\nمحسن کاظمی\nعلی رضایی\n\n"
        "پیام جدید، فهرست قبلی را کامل جایگزین می‌کند.",
        reply_markup=ForceReply(selective=True),
    )
    return GUIDES_INPUT


async def feedback_guides_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or not is_admin(update.effective_user.id, context):
        return ConversationHandler.END
    trip_id = context.user_data.get("feedback_guides_trip_id")
    if not trip_id:
        return ConversationHandler.END
    raw = (update.effective_message.text or "").strip()
    names = []
    for part in re.split(r"[\n،,]+", raw):
        name = re.sub(r"\s+", " ", part).strip(" -•\t")
        if len(name) >= 2 and name not in names:
            names.append(name)
    if not names:
        await update.effective_message.reply_text("حداقل نام یک راهنما را وارد کنید.")
        return GUIDES_INPUT
    if len(names) > 15:
        await update.effective_message.reply_text("حداکثر ۱۵ راهنما در هر سفر قابل ثبت است.")
        return GUIDES_INPUT

    db = context.application.bot_data["db"]
    if await _response_count(db, int(trip_id), completed_only=False) > 0:
        await update.effective_message.reply_text("در همین فاصله پاسخ ثبت شده؛ فهرست راهنماها تغییر نکرد.")
        return ConversationHandler.END

    async with db.sessions() as session:
        old = await session.execute(
            select(TripFeedbackGuide).where(TripFeedbackGuide.trip_id == int(trip_id))
        )
        for item in old.scalars().all():
            await session.delete(item)
        for idx, name in enumerate(names):
            session.add(TripFeedbackGuide(trip_id=int(trip_id), name=name, sort_order=idx))
        await session.commit()
    context.user_data.pop("feedback_guides_trip_id", None)
    await update.effective_message.reply_text(
        "✅ راهنماهای این سفر ثبت شدند:\n\n" + "\n".join(f"🧭 {n}" for n in names),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("⬅️ نظرسنجی سفر", callback_data=f"tripfeedback:view:{trip_id}")
        ]]),
    )
    return ConversationHandler.END


def build_feedback_guides_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(feedback_guides_start, pattern=r"^tripfeedback:guides:\d+$")],
        states={GUIDES_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_guides_receive)]},
        fallbacks=[CommandHandler("cancel", feedback_cancel)],
        allow_reentry=True,
    )


async def _ensure_response(db, trip_id: int, telegram_id: int) -> TripFeedbackResponse:
    async with db.sessions() as session:
        row = await session.get(TripFeedbackResponse, (trip_id, telegram_id))
        if row is None:
            row = TripFeedbackResponse(trip_id=trip_id, telegram_id=telegram_id)
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row


async def _set_response_field(db, trip_id: int, telegram_id: int, field: str, value) -> None:
    async with db.sessions() as session:
        row = await session.get(TripFeedbackResponse, (trip_id, telegram_id))
        if row is None:
            row = TripFeedbackResponse(trip_id=trip_id, telegram_id=telegram_id)
            session.add(row)
        setattr(row, field, value)
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    trip_id = int(query.data.rsplit(":", 1)[1])
    db = context.application.bot_data["db"]
    trip = await db.get_trip(trip_id)
    if not trip:
        await query.edit_message_text("این سفر پیدا نشد.")
        return ConversationHandler.END

    async with db.sessions() as session:
        survey = await session.get(TripFeedbackSurvey, trip_id)
        participant = await session.get(TripParticipant, (trip_id, query.from_user.id))
        response = await session.get(TripFeedbackResponse, (trip_id, query.from_user.id))
    if not survey or not survey.is_open:
        await query.edit_message_text("نظرسنجی این سفر در حال حاضر بسته است.")
        return ConversationHandler.END
    if not participant or participant.status != "attended":
        await query.edit_message_text("این نظرسنجی فقط برای مسافرانی است که حضورشان در سفر تأیید شده است.")
        return ConversationHandler.END
    if response and response.completed:
        await query.edit_message_text(
            f"✅ شما قبلاً نظرسنجی سفر «{trip.title}» را تکمیل کرده‌اید.\n"
            "امتیاز نظرسنجی هم قبلاً برایتان ثبت شده است."
        )
        return ConversationHandler.END

    await _ensure_response(db, trip_id, query.from_user.id)
    context.user_data["feedback_trip_id"] = trip_id
    context.user_data["feedback_guide_index"] = 0
    context.user_data["feedback_score_stage"] = "overall"
    await query.edit_message_text(
        f"💬 نظرسنجی سفر «{trip.title}»\n\n"
        "۱ از ۶ — در مجموع چقدر از این سفر راضی بودید؟",
        reply_markup=_score_keyboard(),
    )
    return 430


async def feedback_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    trip_id = context.user_data.get("feedback_trip_id")
    if not trip_id:
        return ConversationHandler.END
    score = int(query.data.split(":", 1)[1])
    db = context.application.bot_data["db"]
    stage = context.user_data.get("feedback_score_stage", "overall")

    if stage == "overall":
        await _set_response_field(db, trip_id, query.from_user.id, "overall_rating", score)
        context.user_data["feedback_score_stage"] = "organization"
        await query.edit_message_text(
            "۲ از ۶ — به برنامه‌ریزی، هماهنگی و نظم سفر چه امتیازی می‌دهید؟",
            reply_markup=_score_keyboard(),
        )
        return 430
    if stage == "organization":
        await _set_response_field(db, trip_id, query.from_user.id, "organization_rating", score)
        context.user_data["feedback_score_stage"] = "services"
        await query.edit_message_text(
            "۳ از ۶ — به کیفیت خدمات و هماهنگی‌های اجرایی سفر چه امتیازی می‌دهید؟",
            reply_markup=_score_keyboard(),
        )
        return 430

    await _set_response_field(db, trip_id, query.from_user.id, "services_rating", score)
    context.user_data["feedback_score_stage"] = "overall"
    await query.edit_message_text(
        "۴ از ۶ — آیا این سفر کژوان را به دوستانتان پیشنهاد می‌کنید؟",
        reply_markup=_recommend_keyboard(),
    )
    return 431


async def feedback_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    trip_id = context.user_data.get("feedback_trip_id")
    if not trip_id:
        return ConversationHandler.END
    value = query.data.endswith(":yes")
    await _set_response_field(context.application.bot_data["db"], trip_id, query.from_user.id, "recommend", value)
    await query.edit_message_text(
        "۵ از ۶ — بهترین بخش این سفر از نظر شما چه بود؟\n\nاگر نظری ندارید «-» بفرستید."
    )
    return BEST_PART_INPUT


async def feedback_best_part(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    trip_id = context.user_data.get("feedback_trip_id")
    if not trip_id:
        return ConversationHandler.END
    text = (update.effective_message.text or "").strip()
    value = None if text in {"-", "—", "ندارم"} else text[:2000]
    await _set_response_field(context.application.bot_data["db"], trip_id, update.effective_user.id, "best_part", value)
    await update.effective_message.reply_text(
        "۶ از ۶ — چه چیزی می‌توانست در این سفر بهتر باشد؟\n\nاگر نظری ندارید «-» بفرستید."
    )
    return IMPROVEMENT_INPUT


async def feedback_improvement(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    trip_id = context.user_data.get("feedback_trip_id")
    if not trip_id:
        return ConversationHandler.END
    text = (update.effective_message.text or "").strip()
    value = None if text in {"-", "—", "ندارم"} else text[:2000]
    db = context.application.bot_data["db"]
    await _set_response_field(db, trip_id, update.effective_user.id, "improvement", value)
    context.user_data["feedback_guide_index"] = 0
    return await _prompt_next_guide(update, context)


async def _prompt_next_guide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    trip_id = int(context.user_data["feedback_trip_id"])
    guides = await _get_guides(context.application.bot_data["db"], trip_id)
    idx = int(context.user_data.get("feedback_guide_index", 0))
    if idx >= len(guides):
        await _complete_feedback(update, context)
        return ConversationHandler.END
    guide = guides[idx]
    context.user_data["feedback_current_guide_id"] = guide.id
    message = update.effective_message
    await message.reply_text(
        f"🧭 ارزیابی راهنما {idx + 1} از {len(guides)}\n\n"
        f"به عملکرد «{guide.name}» چه امتیازی می‌دهید؟",
        reply_markup=_score_keyboard("fbguide"),
    )
    return 432


async def feedback_guide_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()
    trip_id = int(context.user_data.get("feedback_trip_id", 0))
    guide_id = int(context.user_data.get("feedback_current_guide_id", 0))
    if not trip_id or not guide_id:
        return ConversationHandler.END
    score = int(query.data.split(":", 1)[1])
    db = context.application.bot_data["db"]
    async with db.sessions() as session:
        row = await session.get(TripFeedbackGuideRating, (guide_id, query.from_user.id))
        if row is None:
            row = TripFeedbackGuideRating(
                guide_id=guide_id, telegram_id=query.from_user.id, trip_id=trip_id, rating=score
            )
            session.add(row)
        else:
            row.rating = score
            row.updated_at = datetime.now(timezone.utc)
        guide = await session.get(TripFeedbackGuide, guide_id)
        await session.commit()
    await query.edit_message_text(
        f"📝 اگر درباره عملکرد «{guide.name if guide else 'راهنما'}» توضیحی دارید بنویسید.\n"
        "اگر توضیحی ندارید «-» بفرستید."
    )
    return GUIDE_COMMENT_INPUT


async def feedback_guide_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    guide_id = int(context.user_data.get("feedback_current_guide_id", 0))
    if not guide_id:
        return ConversationHandler.END
    text = (update.effective_message.text or "").strip()
    comment = None if text in {"-", "—", "ندارم"} else text[:2000]
    db = context.application.bot_data["db"]
    async with db.sessions() as session:
        row = await session.get(TripFeedbackGuideRating, (guide_id, update.effective_user.id))
        if row:
            row.comment = comment
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
    context.user_data["feedback_guide_index"] = int(context.user_data.get("feedback_guide_index", 0)) + 1
    return await _prompt_next_guide(update, context)


async def _complete_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    trip_id = int(context.user_data["feedback_trip_id"])
    telegram_id = update.effective_user.id
    db = context.application.bot_data["db"]
    awarded = False
    total_points = None
    trip_title = "سفر"
    async with db.sessions() as session:
        response = await session.get(TripFeedbackResponse, (trip_id, telegram_id))
        survey = await session.get(TripFeedbackSurvey, trip_id)
        trip = await session.get(Trip, trip_id)
        user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = user_result.scalar_one_or_none()
        if trip:
            trip_title = trip.title
        if response and not response.completed:
            response.completed = True
            response.completed_at = datetime.now(timezone.utc)
            response.updated_at = datetime.now(timezone.utc)
        if response and user and not response.reward_awarded:
            reward = int(survey.reward_points if survey else FEEDBACK_REWARD_POINTS)
            user.points += reward
            response.reward_awarded = True
            awarded = True
            total_points = int(user.points or 0)
            session.add(Activity(
                telegram_id=telegram_id,
                activity_type="feedback_reward",
                title=f"تکمیل نظرسنجی سفر {trip_title}",
                details=f"{trip.trip_code if trip else trip_id} | +{reward} امتیاز",
            ))
        elif user:
            total_points = int(user.points or 0)
        await session.commit()

    context.user_data.pop("feedback_trip_id", None)
    context.user_data.pop("feedback_guide_index", None)
    context.user_data.pop("feedback_current_guide_id", None)
    context.user_data.pop("feedback_score_stage", None)
    reward_text = f"\n⭐ {FEEDBACK_REWARD_POINTS} امتیاز به حسابت اضافه شد." if awarded else ""
    total_text = f"\n🏆 امتیاز کل: {total_points}" if total_points is not None else ""
    await update.effective_message.reply_text(
        f"✅ ممنون! نظرسنجی سفر «{trip_title}» کامل شد.{reward_text}{total_text}\n\n"
        "بازخوردت برای بهتر شدن سفرهای بعدی کژوان استفاده می‌شود. 🌿"
    )


async def _results_text(db, trip_id: int, trip_title: str) -> str:
    attendees = await _eligible_attendees(db, trip_id)
    async with db.sessions() as session:
        result = await session.execute(
            select(TripFeedbackResponse).where(
                TripFeedbackResponse.trip_id == trip_id,
                TripFeedbackResponse.completed.is_(True),
            ).order_by(TripFeedbackResponse.completed_at.asc())
        )
        responses = list(result.scalars().all())
        guides_result = await session.execute(
            select(TripFeedbackGuide)
            .where(TripFeedbackGuide.trip_id == trip_id)
            .order_by(TripFeedbackGuide.sort_order.asc())
        )
        guides = list(guides_result.scalars().all())
        ratings_result = await session.execute(
            select(TripFeedbackGuideRating).where(TripFeedbackGuideRating.trip_id == trip_id)
        )
        ratings = list(ratings_result.scalars().all())

    if not responses:
        return f"📊 نتایج نظرسنجی — {trip_title}\n\nهنوز پاسخ کاملی ثبت نشده است."

    def avg(values):
        vals = [int(v) for v in values if v is not None]
        return f"{sum(vals) / len(vals):.2f}" if vals else "-"

    recommend_yes = sum(1 for r in responses if r.recommend is True)
    lines = [
        f"📊 نتایج نظرسنجی — {trip_title}", "",
        f"✅ پاسخ کامل: {len(responses)} از {len(attendees)} مسافر قابل ارسال",
        f"⭐ رضایت کلی: {avg(r.overall_rating for r in responses)} / 5",
        f"🗂 برنامه‌ریزی و نظم: {avg(r.organization_rating for r in responses)} / 5",
        f"🧰 خدمات اجرایی: {avg(r.services_rating for r in responses)} / 5",
        f"👍 پیشنهاد به دیگران: {recommend_yes} از {len(responses)}",
        "", "🧭 عملکرد راهنماها:",
    ]
    by_guide = {g.id: [] for g in guides}
    for rating in ratings:
        if rating.guide_id in by_guide:
            by_guide[rating.guide_id].append(rating)
    for guide in guides:
        items = by_guide.get(guide.id, [])
        lines.append(f"• {guide.name}: {avg(x.rating for x in items)} / 5 ({len(items)} پاسخ)")

    improvements = [r.improvement for r in responses if r.improvement]
    best_parts = [r.best_part for r in responses if r.best_part]
    if best_parts:
        lines += ["", "💚 چند نکته مثبت:"] + [f"• {t[:250]}" for t in best_parts[-5:]]
    if improvements:
        lines += ["", "🛠 پیشنهادهای بهبود:"] + [f"• {t[:250]}" for t in improvements[-5:]]

    guide_comments = []
    guide_map = {g.id: g.name for g in guides}
    for item in ratings:
        if item.comment:
            guide_comments.append(f"• {guide_map.get(item.guide_id, 'راهنما')}: {item.comment[:250]}")
    if guide_comments:
        lines += ["", "🧭 توضیحات درباره راهنماها:"] + guide_comments[-8:]
    return "\n".join(lines)


async def _export_rows(db, trip_id: int):
    async with db.sessions() as session:
        responses_result = await session.execute(
            select(TripFeedbackResponse, User)
            .join(User, User.telegram_id == TripFeedbackResponse.telegram_id)
            .where(
                TripFeedbackResponse.trip_id == trip_id,
                TripFeedbackResponse.completed.is_(True),
            )
            .order_by(TripFeedbackResponse.completed_at.asc())
        )
        responses = list(responses_result.all())
        guides_result = await session.execute(
            select(TripFeedbackGuide)
            .where(TripFeedbackGuide.trip_id == trip_id)
            .order_by(TripFeedbackGuide.sort_order.asc())
        )
        guides = list(guides_result.scalars().all())
        ratings_result = await session.execute(
            select(TripFeedbackGuideRating).where(TripFeedbackGuideRating.trip_id == trip_id)
        )
        ratings = list(ratings_result.scalars().all())

    headers = [
        "نام مسافر", "Telegram ID", "رضایت کلی", "برنامه‌ریزی و نظم", "خدمات اجرایی",
        "پیشنهاد به دیگران", "بهترین بخش سفر", "پیشنهاد بهبود", "تاریخ تکمیل",
    ]
    for guide in guides:
        headers.extend([f"امتیاز راهنما: {guide.name}", f"توضیح راهنما: {guide.name}"])

    rating_map = {(r.telegram_id, r.guide_id): r for r in ratings}
    rows = []
    for response, user in responses:
        row = [
            user.full_name, user.telegram_id, response.overall_rating or "",
            response.organization_rating or "", response.services_rating or "",
            "بله" if response.recommend else "خیر", response.best_part or "",
            response.improvement or "",
            response.completed_at.isoformat() if response.completed_at else "",
        ]
        for guide in guides:
            item = rating_map.get((user.telegram_id, guide.id))
            row.extend([item.rating if item else "", item.comment if item and item.comment else ""])
        rows.append(row)
    return headers, rows


async def feedback_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in list(context.user_data):
        if key.startswith("feedback_"):
            context.user_data.pop(key, None)
    await update.effective_message.reply_text("فرآیند نظرسنجی لغو شد.")
    return ConversationHandler.END


def build_feedback_response_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(feedback_start, pattern=r"^feedback:start:\d+$")],
        states={
            430: [CallbackQueryHandler(feedback_score, pattern=r"^fbscore:[1-5]$")],
            431: [CallbackQueryHandler(feedback_recommend, pattern=r"^fbrecommend:(yes|no)$")],
            BEST_PART_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_best_part)],
            IMPROVEMENT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_improvement)],
            432: [CallbackQueryHandler(feedback_guide_score, pattern=r"^fbguide:[1-5]$")],
            GUIDE_COMMENT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_guide_comment)],
        },
        fallbacks=[CommandHandler("cancel", feedback_cancel)],
        allow_reentry=True,
    )


def feedback_handlers():
    return [
        build_feedback_guides_handler(),
        build_feedback_response_handler(),
        CallbackQueryHandler(
            feedback_admin_callback,
            pattern=r"^tripfeedback:(view|send|results|export|open|close):\d+$",
        ),
    ]
