from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from bot.handlers import onboarding as ob

_original_start=ob.start
_original_finish=ob.finish_registration

async def start(update,context):
    if update.effective_chat and update.effective_chat.type=="private" and context.args and context.args[0].startswith("prebook_"):
        try: tid=int(context.args[0].split("_",1)[1])
        except Exception: tid=None
        if tid:
            db=context.application.bot_data["db"];user=await db.get_user(update.effective_user.id)
            if user:
                await update.message.reply_text("پروفایل کژوان شما از قبل تکمیل است. برای ادامه پیش‌رزرو روی دکمه زیر بزنید:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ادامه پیش‌رزرو",callback_data=f"pre:join:{tid}")]]))
                return ob.ConversationHandler.END
            context.user_data.clear();context.user_data["pending_prebook_trip_id"]=tid
            await update.message.reply_text(ob.WELCOME_TEXT);await update.message.reply_text("لطفاً نام و نام خانوادگی خود را وارد کنید:")
            return ob.FULL_NAME
    return await _original_start(update,context)

async def finish_registration(update,context):
    tid=context.user_data.get("pending_prebook_trip_id")
    if not tid:return await _original_finish(update,context)
    # Preserve the target across the original registration function, which clears user_data.
    result=await _original_finish(update,context)
    target=update.callback_query.message if update.callback_query else update.message
    await target.reply_text("✅ ثبت‌نام کژوان تکمیل شد. حالا پیش‌رزرو همین سفر را ادامه بده:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ ادامه و ثبت پیش‌رزرو",callback_data=f"pre:join:{tid}")]]))
    return result

def install():
    ob.start=start
    ob.finish_registration=finish_registration
