from datetime import datetime
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler,ConversationHandler
from bot.handlers import trips as tr
from bot.handlers import admin as ad
from bot.handlers.prebooking import IR,JMONTHS,cal_kb,jalali_to_gregorian

def _date_text(jy,jm,jd):return f"{jd} {JMONTHS[jm-1]} {jy}"

async def group_type(update,c):
    q=update.callback_query
    if not q:return tr.TRIP_TYPE
    await q.answer()
    if not ad.is_admin(q.from_user.id,c):return ConversationHandler.END
    c.user_data["trip_type"]=q.data.split(":",1)[1]
    now=datetime.now(IR);from bot.handlers.prebooking import gregorian_to_jalali
    jy,jm,_=gregorian_to_jalali(now.year,now.month,now.day)
    await q.message.reply_text("📅 تاریخ شروع سفر را انتخاب کن:",reply_markup=cal_kb(0,"gstart",jy,jm))
    return tr.TRIP_START

async def group_cal(update,c):
    q=update.callback_query;await q.answer();z=q.data.split(":");act=z[1]
    if act=="none":return tr.TRIP_START if "gstart" in q.data else tr.TRIP_END
    kind=z[3]
    if act=="nav":
        jy,jm,d=map(int,z[4:7]);jm+=d
        if jm<1:jy-=1;jm=12
        if jm>12:jy+=1;jm=1
        await q.edit_message_reply_markup(reply_markup=cal_kb(0,kind,jy,jm));return tr.TRIP_START if kind=="gstart" else tr.TRIP_END
    if act=="day":
        jy,jm,jd=map(int,z[4:7]);val=_date_text(jy,jm,jd)
        if kind=="gstart":
            c.user_data["trip_start"]=val;await q.edit_message_text(f"✅ شروع: {val}")
            await q.message.reply_text("📅 تاریخ پایان سفر را انتخاب کن:",reply_markup=cal_kb(0,"gend",jy,jm));return tr.TRIP_END
        c.user_data["trip_end"]=val;await q.edit_message_text(f"✅ پایان: {val}")
        db=c.application.bot_data["db"];current=await db.get_trip_by_chat_id(c.user_data["settrip_chat_id"])
        similar=await db.find_similar_trips(c.user_data["trip_title"],c.user_data["trip_start"],val,c.user_data.get("trip_type","domestic_multi"),exclude_trip_id=current.id if current else None,limit=5)
        linkable=[x for x in similar if x.telegram_chat_id in (None,c.user_data["settrip_chat_id"])]
        if linkable:
            rows=[[InlineKeyboardButton(f"🔗 اتصال گروه به {x.title} | {x.trip_code}"[:60],callback_data=f"tripdupe:link:{x.id}")] for x in linkable]
            rows.append([InlineKeyboardButton("➕ سفر جدید جدا بساز",callback_data="tripdupe:new")]);await q.message.reply_text("⚠️ سفر مشابه وجود دارد.",reply_markup=InlineKeyboardMarkup(rows));return tr.TRIP_DUPLICATE
        return await tr._finish_settrip(q,c)
    return ConversationHandler.END

async def manual_type(update,c):
    q=update.callback_query;await q.answer();c.user_data["manual_trip_type"]=q.data.split(":",1)[1]
    from bot.handlers.prebooking import gregorian_to_jalali
    now=datetime.now(IR);jy,jm,_=gregorian_to_jalali(now.year,now.month,now.day)
    await q.message.reply_text("📅 تاریخ شروع را انتخاب کن:",reply_markup=cal_kb(0,"mstart",jy,jm));return ad.MANUAL_TRIP_START

async def manual_cal(update,c):
    q=update.callback_query;await q.answer();z=q.data.split(":");act=z[1]
    if act=="none":return ad.MANUAL_TRIP_START
    kind=z[3]
    if act=="nav":
        jy,jm,d=map(int,z[4:7]);jm+=d
        if jm<1:jy-=1;jm=12
        if jm>12:jy+=1;jm=1
        await q.edit_message_reply_markup(reply_markup=cal_kb(0,kind,jy,jm));return ad.MANUAL_TRIP_START if kind=="mstart" else ad.MANUAL_TRIP_END
    if act=="day":
        jy,jm,jd=map(int,z[4:7]);val=_date_text(jy,jm,jd)
        if kind=="mstart":
            c.user_data["manual_trip_start"]=val;await q.edit_message_text(f"✅ شروع: {val}");await q.message.reply_text("📅 تاریخ پایان را انتخاب کن:",reply_markup=cal_kb(0,"mend",jy,jm));return ad.MANUAL_TRIP_END
        c.user_data["manual_trip_end"]=val;await q.edit_message_text(f"✅ پایان: {val}")
        db=c.application.bot_data["db"];similar=await db.find_similar_trips(c.user_data["manual_trip_title"],c.user_data["manual_trip_start"],val,c.user_data["manual_trip_type"],limit=5)
        if similar:
            rows=[[InlineKeyboardButton(f"🔗 استفاده از {x.title} | {x.trip_code}"[:60],callback_data=f"manualtripdupe:use:{x.id}")] for x in similar];rows.append([InlineKeyboardButton("➕ سفر جدید بساز",callback_data="manualtripdupe:new")]);await q.message.reply_text("⚠️ سفر مشابه وجود دارد.",reply_markup=InlineKeyboardMarkup(rows));return ad.MANUAL_TRIP_DUPLICATE
        return await ad._create_manual_trip_from_context(q,c)
    return ConversationHandler.END

def install():
    tr.settrip_type=group_type
    ad.manual_trip_type=manual_type
    old_tr=tr.build_settrip_handler
    def bt():
        return ConversationHandler(entry_points=[tr.CommandHandler("settrip",tr.settrip_start)],states={
          tr.TRIP_TITLE:[tr.MessageHandler(tr.filters.TEXT&~tr.filters.COMMAND,tr.settrip_title)],
          tr.TRIP_TYPE:[CallbackQueryHandler(group_type,pattern=r"^triptype:")],
          tr.TRIP_START:[CallbackQueryHandler(group_cal,pattern=r"^pc:(?:none|nav|day):0:gstart")],
          tr.TRIP_END:[CallbackQueryHandler(group_cal,pattern=r"^pc:(?:none|nav|day):0:gend")],
          tr.TRIP_DUPLICATE:[CallbackQueryHandler(tr.settrip_duplicate_choice,pattern=r"^tripdupe:")],
        },fallbacks=[tr.CommandHandler("cancel",tr.settrip_cancel)],per_chat=True,per_user=True,allow_reentry=True)
    tr.build_settrip_handler=bt
    def ba():
        return ConversationHandler(entry_points=[CallbackQueryHandler(ad.manual_trip_start,pattern=r"^tripadmin:new$"),CallbackQueryHandler(ad.manual_guest_start,pattern=r"^tripadmin:addguest:\d+$")],states={
          ad.MANUAL_TRIP_TITLE:[ad.MessageHandler(ad.filters.TEXT&~ad.filters.COMMAND,ad.manual_trip_title)],
          ad.MANUAL_TRIP_TYPE:[CallbackQueryHandler(manual_type,pattern=r"^manualtriptype:")],
          ad.MANUAL_TRIP_START:[CallbackQueryHandler(manual_cal,pattern=r"^pc:(?:none|nav|day):0:mstart")],
          ad.MANUAL_TRIP_END:[CallbackQueryHandler(manual_cal,pattern=r"^pc:(?:none|nav|day):0:mend")],
          ad.MANUAL_TRIP_DUPLICATE:[CallbackQueryHandler(ad.manual_trip_duplicate_choice,pattern=r"^manualtripdupe:")],
          ad.MANUAL_GUEST_NAME:[ad.MessageHandler(ad.filters.TEXT&~ad.filters.COMMAND,ad.manual_guest_name)],
          ad.MANUAL_GUEST_PHONE:[ad.MessageHandler(ad.filters.TEXT&~ad.filters.COMMAND,ad.manual_guest_phone)],
          ad.MANUAL_GUEST_STATUS:[CallbackQueryHandler(ad.manual_guest_status,pattern=r"^manualgueststatus:")],
        },fallbacks=[ad.CommandHandler("cancel",ad.admin_flow_cancel)],per_chat=True,per_user=True,allow_reentry=True)
    ad.build_admin_flow_handler=ba
