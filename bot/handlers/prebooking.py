import asyncio, logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from bot.db import Base, Activity, Trip, User

log=logging.getLogger(__name__)
IR=ZoneInfo("Asia/Tehran")
CAP,PRICE,DISC,DEADLINE,EXECUTE,CANCEL_HOURS,CANCEL_POINTS=range(700,707)

class PrebookingSettings(Base):
    __tablename__="prebooking_settings"
    trip_id:Mapped[int]=mapped_column(Integer,primary_key=True)
    enabled:Mapped[bool]=mapped_column(Boolean,default=False)
    capacity:Mapped[int]=mapped_column(Integer,default=0)
    regular_price:Mapped[int]=mapped_column(BigInteger,default=0)
    early_discount:Mapped[int]=mapped_column(BigInteger,default=0)
    deadline_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    execution_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    cancel_hours:Mapped[int]=mapped_column(Integer,default=0)
    cancel_from_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    payment_recipient:Mapped[str]=mapped_column(String(255),default="")
    payment_account:Mapped[str]=mapped_column(String(255),default="")
    cancel_points:Mapped[int]=mapped_column(Integer,default=0)
    waitlist:Mapped[bool]=mapped_column(Boolean,default=True)
    show_names:Mapped[bool]=mapped_column(Boolean,default=True)
    chat_id:Mapped[int|None]=mapped_column(BigInteger,nullable=True)
    message_id:Mapped[int|None]=mapped_column(BigInteger,nullable=True)

class PrebookingGroup(Base):
    __tablename__="prebooking_groups"
    chat_id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    title:Mapped[str]=mapped_column(String(255),default="")
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class PrebookingPublication(Base):
    __tablename__="prebooking_publications"
    trip_id:Mapped[int]=mapped_column(Integer,primary_key=True)
    chat_id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    message_id:Mapped[int|None]=mapped_column(BigInteger,nullable=True)
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class Prebooking(Base):
    __tablename__="prebookings"
    trip_id:Mapped[int]=mapped_column(Integer,primary_key=True)
    telegram_id:Mapped[int]=mapped_column(BigInteger,primary_key=True)
    status:Mapped[str]=mapped_column(String(20),default="prebooked")
    price_snapshot:Mapped[int]=mapped_column(BigInteger,default=0)
    discount_snapshot:Mapped[int]=mapped_column(BigInteger,default=0)
    penalty_points:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

def admin(uid,c): return uid in c.application.bot_data["settings"].admin_ids
def money(n): return f"{int(n or 0):,} تومان"
def aware(d): return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d
def fdt(d): return aware(d).astimezone(IR).strftime("%Y/%m/%d - %H:%M") if d else "تعیین نشده"
def remain(d):
    if not d:return "تعیین نشده"
    sec=int((aware(d)-datetime.now(timezone.utc)).total_seconds())
    if sec<=0:return "پایان یافته"
    days,sec=divmod(sec,86400); hours=sec//3600
    return f"{days} روز و {hours} ساعت"

async def cfg(db,tid,create=False):
    async with db.sessions() as s:
        x=(await s.execute(select(PrebookingSettings).where(PrebookingSettings.trip_id==tid))).scalar_one_or_none()
        if not x and create:
            x=PrebookingSettings(trip_id=tid);s.add(x);await s.commit();await s.refresh(x)
        return x

async def trip(db,tid):
    async with db.sessions() as s:return (await s.execute(select(Trip).where(Trip.id==tid))).scalar_one_or_none()

async def counts(db,tid):
    async with db.sessions() as s:
        a=await s.scalar(select(func.count()).select_from(Prebooking).where(Prebooking.trip_id==tid,Prebooking.status.in_(["prebooked","confirmed"])))
        w=await s.scalar(select(func.count()).select_from(Prebooking).where(Prebooking.trip_id==tid,Prebooking.status=="waitlist"))
        return int(a or 0),int(w or 0)

async def text(db,t,c):
    a,w=await counts(db,t.id); left=max(0,c.capacity-a)
    lines=[f"🧳 {t.title}",f"📅 تاریخ سفر: {t.start_date_text} تا {t.end_date_text}","",
           f"💰 قیمت اصلی: {money(c.regular_price)}"]
    if c.early_discount:
        lines += [f"🎁 تخفیف ثبت‌نام زودهنگام: {money(c.early_discount)}",
                  f"💳 قیمت پیش‌رزرو: {money(max(0,c.regular_price-c.early_discount))}"]
    lines += ["",f"⏳ مهلت پیش‌رزرو: {fdt(c.deadline_at)}",f"⏱ فرصت باقی‌مانده: {remain(c.deadline_at)}","",
              f"👥 ظرفیت کل: {c.capacity}",f"✅ ثبت‌شده: {a}",f"🪑 باقی‌مانده: {left}"]
    if w:lines.append(f"⏳ لیست انتظار: {w} نفر")
    if c.show_names:
        async with db.sessions() as s:
            names=(await s.execute(select(User.full_name).join(Prebooking,Prebooking.telegram_id==User.telegram_id)
                 .where(Prebooking.trip_id==t.id,Prebooking.status.in_(["prebooked","confirmed"])).order_by(Prebooking.created_at))).scalars().all()
        if names:lines+=["","👥 پیش‌رزروها:","، ".join(names)]
    return "\n".join(lines)

def public_kb(tid,full=False):
    label="⏳ ورود به لیست انتظار" if full else "✅ پیش‌رزرو"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label,callback_data=f"pre:join:{tid}"),
                                  InlineKeyboardButton("❌ لغو",callback_data=f"pre:cancel:{tid}")],
                                 [InlineKeyboardButton("🔄 بروزرسانی",callback_data=f"pre:refresh:{tid}")]])

async def refresh(c,tid):
    db=c.application.bot_data["db"]; x=await cfg(db,tid); t=await trip(db,tid)
    if not x or not t:return
    a,_=await counts(db,tid)
    body=await text(db,t,x); kb=public_kb(tid,a>=x.capacity and x.waitlist)
    async with db.sessions() as ss:
        pubs=(await ss.execute(select(PrebookingPublication).where(
            PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(True),
            PrebookingPublication.message_id.is_not(None)))).scalars().all()
    # Backward compatibility: update old single publication if it exists and was not migrated yet.
    legacy=[]
    if x.chat_id and x.message_id and not any(p.chat_id==x.chat_id for p in pubs):
        legacy=[(x.chat_id,x.message_id)]
    for chat_id,message_id in [(p.chat_id,p.message_id) for p in pubs]+legacy:
        try:
            await c.bot.edit_message_text(chat_id=chat_id,message_id=message_id,text=body,reply_markup=kb)
        except Exception as e:
            if "not modified" not in str(e).lower():log.exception("prebooking refresh chat=%s",chat_id)

async def passenger(update:Update,c:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; action,tid=q.data.split(":")[1:];tid=int(tid)
    db=c.application.bot_data["db"]; x=await cfg(db,tid);t=await trip(db,tid)
    if not x or not x.enabled or not t:await q.answer("پیش‌رزرو فعال نیست.",show_alert=True);return
    if action=="refresh":await q.answer("بروزرسانی شد");await refresh(c,tid);return
    now=datetime.now(timezone.utc)
    async with db.sessions() as s:
        u=(await s.execute(select(User).where(User.telegram_id==q.from_user.id))).scalar_one_or_none()
        if not u:
            me=await c.bot.get_me();await q.answer()
            await q.message.reply_text("برای پیش‌رزرو، ابتدا پروفایل کژوان را کامل کن. بعد از ثبت‌نام مستقیم به همین سفر برمی‌گردی.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 ثبت‌نام و ادامه پیش‌رزرو",url=f"https://t.me/{me.username}?start=prebook_{tid}")]]));return
        r=(await s.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.telegram_id==u.telegram_id))).scalar_one_or_none()
        if action=="join":
            if x.deadline_at and now>aware(x.deadline_at):await q.answer("مهلت تمام شده.",show_alert=True);return
            if r and r.status in ("prebooked","confirmed","waitlist"):await q.answer("قبلاً ثبت شده‌اید.",show_alert=True);return
            a=await s.scalar(select(func.count()).select_from(Prebooking).where(Prebooking.trip_id==tid,Prebooking.status.in_(["prebooked","confirmed"])))
            st="prebooked" if int(a or 0)<x.capacity else "waitlist"
            if st=="waitlist" and not x.waitlist:await q.answer("ظرفیت تکمیل است.",show_alert=True);return
            p=max(0,x.regular_price-x.early_discount)
            if r:r.status=st;r.price_snapshot=p;r.discount_snapshot=x.early_discount;r.updated_at=now
            else:s.add(Prebooking(trip_id=tid,telegram_id=u.telegram_id,status=st,price_snapshot=p,discount_snapshot=x.early_discount))
            await s.commit();await q.answer("پیش‌رزرو ثبت شد." if st=="prebooked" else "وارد لیست انتظار شدید.",show_alert=True)
            if st=="prebooked":
                pay=max(0,int(x.regular_price or 0)-int(x.early_discount or 0));owner=f" به نام {x.payment_recipient}" if x.payment_recipient else ""
                await c.bot.send_message(q.from_user.id,f"✅ پیش‌رزرو شما برای «{t.title}» ثبت شد.\n\nبرای قطعی شدن رزرو و استفاده از تخفیف {money(x.early_discount)}، مبلغ {money(pay)} را به {x.payment_account or 'شماره پرداخت اعلام‌شده توسط کژوان'}{owner} پرداخت کنید و عکس رسید را همین‌جا بفرستید.")
        else:
            if not r or r.status not in ("prebooked","confirmed","waitlist"):await q.answer("رزرو فعالی ندارید.",show_alert=True);return
            active=r.status in ("prebooked","confirmed"); penalty=0
            penalty_start=aware(x.cancel_from_at) if x.cancel_from_at else (aware(x.execution_at)-timedelta(hours=x.cancel_hours) if x.execution_at and x.cancel_hours else None)
            if active and penalty_start and x.cancel_points and now>=penalty_start:
                penalty=min(int(u.points or 0),x.cancel_points);u.points=int(u.points or 0)-penalty;r.penalty_points=penalty
                if penalty:s.add(Activity(telegram_id=u.telegram_id,activity_type="prebooking_cancel_penalty",title=f"جریمه لغو دیرهنگام {t.title}",details=f"-{penalty} امتیاز"))
            r.status="cancelled";r.updated_at=now
            if active and x.waitlist:
                nxt=(await s.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.status=="waitlist").order_by(Prebooking.created_at).limit(1))).scalar_one_or_none()
                if nxt:nxt.status="prebooked";nxt.updated_at=now
            await s.commit();await q.answer("لغو شد"+(f"؛ {penalty} امتیاز جریمه شد." if penalty else "."),show_alert=True)
    await refresh(c,tid)


JMONTHS=["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند"]
JWD=["ش","ی","د","س","چ","پ","ج"]

def gregorian_to_jalali(gy,gm,gd):
    gdm=[0,31,59,90,120,151,181,212,243,273,304,334]
    gy2=gy+1 if gm>2 else gy
    days=355666+365*gy+(gy2+3)//4-(gy2+99)//100+(gy2+399)//400+gd+gdm[gm-1]
    jy=-1595+33*(days//12053);days%=12053
    jy+=4*(days//1461);days%=1461
    if days>365:
        jy+=(days-1)//365;days=(days-1)%365
    if days<186:
        jm=1+days//31;jd=1+days%31
    else:
        jm=7+(days-186)//30;jd=1+(days-186)%30
    return jy,jm,jd

def jalali_to_gregorian(jy,jm,jd):
    jy+=1595
    days=-355668+365*jy+(jy//33)*8+((jy%33)+3)//4+jd
    days+=(jm-1)*31 if jm<7 else (jm-7)*30+186
    gy=400*(days//146097);days%=146097
    if days>36524:
        gy+=100*((days-1)//36524);days=(days-1)%36524
        if days>=365:days+=1
    gy+=4*(days//1461);days%=1461
    if days>365:
        gy+=(days-1)//365;days=(days-1)%365
    gd=days+1
    leap=(gy%4==0 and gy%100!=0) or gy%400==0
    sal=[0,31,29 if leap else 28,31,30,31,30,31,31,30,31,30,31]
    gm=1
    while gm<=12 and gd>sal[gm]:
        gd-=sal[gm];gm+=1
    return gy,gm,gd

def jmonth_days(jy,jm):
    if jm<=6:return 31
    if jm<=11:return 30
    gy1,gm1,gd1=jalali_to_gregorian(jy,1,1)
    gy2,gm2,gd2=jalali_to_gregorian(jy+1,1,1)
    return 30 if (datetime(gy2,gm2,gd2)-datetime(gy1,gm1,gd1)).days==366 else 29

def cal_kb(tid,kind,jy,jm):
    rows=[[InlineKeyboardButton("◀️",callback_data=f"pc:nav:{tid}:{kind}:{jy}:{jm}:-1"),
           InlineKeyboardButton(f"{JMONTHS[jm-1]} {jy}",callback_data="pc:none"),
           InlineKeyboardButton("▶️",callback_data=f"pc:nav:{tid}:{kind}:{jy}:{jm}:1")]]
    rows.append([InlineKeyboardButton(x,callback_data="pc:none") for x in JWD])
    gy,gm,gd=jalali_to_gregorian(jy,jm,1)
    # Python weekday Mon=0; Persian calendar Saturday=0
    offset=(datetime(gy,gm,gd).weekday()+2)%7
    cells=[None]*offset+list(range(1,jmonth_days(jy,jm)+1))
    while len(cells)%7:cells.append(None)
    for i in range(0,len(cells),7):
        rows.append([InlineKeyboardButton(" " if d is None else str(d),
            callback_data="pc:none" if d is None else f"pc:day:{tid}:{kind}:{jy}:{jm}:{d}") for d in cells[i:i+7]])
    rows.append([InlineKeyboardButton("❌ انصراف",callback_data=f"pc:cancel:{tid}:{kind}")])
    return InlineKeyboardMarkup(rows)

def hour_kb(tid,kind,jy,jm,jd):
    rows=[]
    for start in range(0,24,4):
        rows.append([InlineKeyboardButton(f"{h:02d}:00",callback_data=f"pc:hour:{tid}:{kind}:{jy}:{jm}:{jd}:{h}") for h in range(start,start+4)])
    rows.append([InlineKeyboardButton("⬅️ بازگشت به تقویم",callback_data=f"pc:back:{tid}:{kind}:{jy}:{jm}")])
    return InlineKeyboardMarkup(rows)

def minute_kb(tid,kind,jy,jm,jd,h):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"{h:02d}:{m:02d}",callback_data=f"pc:min:{tid}:{kind}:{jy}:{jm}:{jd}:{h}:{m}") for m in (0,15,30,45)
    ],[InlineKeyboardButton("⬅️ انتخاب ساعت",callback_data=f"pc:day:{tid}:{kind}:{jy}:{jm}:{jd}")]])

async def calendar_start(q,tid,kind):
    now=datetime.now(IR);jy,jm,jd=gregorian_to_jalali(now.year,now.month,now.day)
    title={"deadline":"مهلت پیش‌رزرو","execute":"زمان اجرای سفر","penalty":"شروع بازه جریمه"}[kind]
    await q.message.reply_text(f"📅 {title}\nتاریخ شمسی را انتخاب کن:",reply_markup=cal_kb(tid,kind,jy,jm))

async def calendar_cb(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer()
    z=q.data.split(":");act=z[1]
    if act=="none":return
    tid=int(z[2]);kind=z[3]
    if act=="cancel":
        await q.edit_message_text("❌ انتخاب تاریخ لغو شد.");return
    if act=="nav":
        jy,jm,delta=map(int,z[4:7]);jm+=delta
        if jm<1:jy-=1;jm=12
        if jm>12:jy+=1;jm=1
        await q.edit_message_reply_markup(reply_markup=cal_kb(tid,kind,jy,jm));return
    if act=="back":
        jy,jm=map(int,z[4:6]);await q.edit_message_text("📅 تاریخ شمسی را انتخاب کن:",reply_markup=cal_kb(tid,kind,jy,jm));return
    if act=="day":
        jy,jm,jd=map(int,z[4:7]);await q.edit_message_text(f"📅 {jd} {JMONTHS[jm-1]} {jy}\n🕐 ساعت را انتخاب کن:",reply_markup=hour_kb(tid,kind,jy,jm,jd));return
    if act=="hour":
        jy,jm,jd,h=map(int,z[4:8]);await q.edit_message_text(f"📅 {jd} {JMONTHS[jm-1]} {jy}\n🕐 دقیقه را انتخاب کن:",reply_markup=minute_kb(tid,kind,jy,jm,jd,h));return
    if act=="min":
        jy,jm,jd,h,m=map(int,z[4:9]);gy,gm,gd=jalali_to_gregorian(jy,jm,jd)
        local=datetime(gy,gm,gd,h,m,tzinfo=IR);utc=local.astimezone(timezone.utc)
        db=c.application.bot_data["db"]
        async with db.sessions() as ss:
            x=(await ss.execute(select(PrebookingSettings).where(PrebookingSettings.trip_id==tid))).scalar_one()
            setattr(x,{"deadline":"deadline_at","execute":"execution_at","penalty":"cancel_from_at"}[kind],utc);await ss.commit()
        label={"deadline":"مهلت پیش‌رزرو","execute":"زمان اجرای سفر","penalty":"شروع بازه جریمه"}[kind]
        await q.edit_message_text(f"✅ {label} ذخیره شد:\n📅 {jd} {JMONTHS[jm-1]} {jy}\n🕐 {h:02d}:{m:02d}")
        await refresh(c,tid)

def akb(tid,x):
    return InlineKeyboardMarkup([
      [InlineKeyboardButton(("🟢" if x.enabled else "⚪")+" فعال/غیرفعال",callback_data=f"pa:toggle:{tid}")],
      [InlineKeyboardButton("👥 ظرفیت",callback_data=f"pa:cap:{tid}"),InlineKeyboardButton("💰 قیمت",callback_data=f"pa:price:{tid}")],
      [InlineKeyboardButton("🎁 تخفیف تومانی",callback_data=f"pa:disc:{tid}"),InlineKeyboardButton("⏳ مهلت پیش‌رزرو",callback_data=f"pa:deadline:{tid}")],
      [InlineKeyboardButton("🚌 زمان اجرای سفر",callback_data=f"pa:execute:{tid}")],
      [InlineKeyboardButton("📅 شروع بازه جریمه",callback_data=f"pa:penaltydate:{tid}"),InlineKeyboardButton("➖ امتیاز جریمه",callback_data=f"pa:cp:{tid}")],
      [InlineKeyboardButton("💳 شماره پرداخت",callback_data=f"pa:payaccount:{tid}"),InlineKeyboardButton("👤 صاحب حساب",callback_data=f"pa:payname:{tid}")],
      [InlineKeyboardButton(("🟢" if x.waitlist else "⚪")+" لیست انتظار",callback_data=f"pa:wait:{tid}"),
       InlineKeyboardButton(("🟢" if x.show_names else "⚪")+" نمایش اسامی",callback_data=f"pa:names:{tid}")],
      [InlineKeyboardButton("📣 گروه‌های انتشار پیش‌رزرو",callback_data=f"pa:publish:{tid}")],
      [InlineKeyboardButton("➕ افزودن دستی مسافر",callback_data=f"pa:add:{tid}")],
      [InlineKeyboardButton("👥 مشاهده پیش‌رزروها",callback_data=f"pa:list:{tid}")]])

async def panel(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();tid=int(q.data.split(":")[-1]);db=c.application.bot_data["db"];x=await cfg(db,tid,True);t=await trip(db,tid);a,w=await counts(db,tid)
    await q.message.reply_text(f"🎟 تنظیمات پیش‌رزرو — {t.title}\n\nوضعیت: {'فعال' if x.enabled else 'غیرفعال'}\nظرفیت: {x.capacity} | ثبت: {a} | انتظار: {w}\nقیمت: {money(x.regular_price)}\nتخفیف: {money(x.early_discount)}\nمهلت: {fdt(x.deadline_at)}\nاجرای سفر: {fdt(x.execution_at)}\nشروع بازه جریمه: {fdt(x.cancel_from_at)}\nجریمه: {x.cancel_points} امتیاز",reply_markup=akb(tid,x))

async def register_prebooking_group(update,c):
    if not admin(update.effective_user.id,c):return
    chat=update.effective_chat
    if not chat or chat.type not in ("group","supergroup"):
        await update.effective_message.reply_text("این دستور را داخل گروهی بزن که می‌خواهی پیش‌رزروها در آن قابل انتشار باشد.");return
    db=c.application.bot_data["db"]
    async with db.sessions() as ss:
        g=(await ss.execute(select(PrebookingGroup).where(PrebookingGroup.chat_id==chat.id))).scalar_one_or_none()
        if g:g.title=chat.title or str(chat.id);g.active=True;g.updated_at=datetime.now(timezone.utc)
        else:ss.add(PrebookingGroup(chat_id=chat.id,title=chat.title or str(chat.id),active=True))
        await ss.commit()
    await update.effective_message.reply_text("✅ این گروه به مقصدهای انتشار پیش‌رزرو اضافه شد.\nاز این به بعد در پنل هر سفر می‌توانی انتخابش کنی.")

async def publication_picker(q,c,tid):
    db=c.application.bot_data["db"]
    async with db.sessions() as ss:
        groups=(await ss.execute(select(PrebookingGroup).where(PrebookingGroup.active.is_(True)).order_by(PrebookingGroup.title))).scalars().all()
        selected=set((await ss.execute(select(PrebookingPublication.chat_id).where(
            PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(True)))).scalars().all())
    if not groups:
        await q.message.reply_text("هنوز هیچ گروهی برای انتشار پیش‌رزرو ثبت نشده.\n\nداخل هر گروه موردنظر یک‌بار دستور /prebookinggroup را بزن، بعد برگرد اینجا.");return
    rows=[]
    for g in groups:
        mark="✅" if g.chat_id in selected else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {g.title}"[:60],callback_data=f"ppub:toggle:{tid}:{g.chat_id}")])
    rows += [[InlineKeyboardButton("📣 انتشار / بروزرسانی در گروه‌های انتخاب‌شده",callback_data=f"ppub:send:{tid}")],
             [InlineKeyboardButton("🗑 حذف پیام از گروه‌های ازانتخاب‌خارج‌شده",callback_data=f"ppub:cleanup:{tid}")]]
    await q.message.reply_text("📣 گروه‌های انتشار پیش‌رزرو\n\nیک یا چند گروه را انتخاب کن. این بخش مستقل از «ثبت سفرهای من» است.",reply_markup=InlineKeyboardMarkup(rows))

async def publication_cb(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();z=q.data.split(":");act=z[1];tid=int(z[2]);db=c.application.bot_data["db"]
    if act=="toggle":
        chat_id=int(z[3])
        async with db.sessions() as ss:
            pub=(await ss.execute(select(PrebookingPublication).where(
                PrebookingPublication.trip_id==tid,PrebookingPublication.chat_id==chat_id))).scalar_one_or_none()
            if pub:pub.active=not pub.active
            else:ss.add(PrebookingPublication(trip_id=tid,chat_id=chat_id,active=True))
            await ss.commit()
        await q.edit_message_reply_markup(reply_markup=(await _publication_keyboard(db,tid)));return
    if act=="send":
        x=await cfg(db,tid);t=await trip(db,tid)
        if not x.enabled or x.capacity<=0:
            await q.answer("اول پیش‌رزرو را فعال و ظرفیت را تعیین کن.",show_alert=True);return
        aa,_=await counts(db,tid);body=await text(db,t,x);kb=public_kb(tid,aa>=x.capacity and x.waitlist)
        async with db.sessions() as ss:
            pubs=(await ss.execute(select(PrebookingPublication).where(
                PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(True)))).scalars().all()
            if not pubs:
                await q.answer("حداقل یک گروه انتخاب کن.",show_alert=True);return
            ok=0;failed=0
            for pub in pubs:
                try:
                    if pub.message_id:
                        try:
                            await c.bot.edit_message_text(chat_id=pub.chat_id,message_id=pub.message_id,text=body,reply_markup=kb)
                        except Exception as e:
                            if "not modified" not in str(e).lower(): raise
                    else:
                        m=await c.bot.send_message(pub.chat_id,body,reply_markup=kb);pub.message_id=m.message_id
                    ok+=1
                except Exception:
                    failed+=1;log.exception("publish prebooking chat=%s",pub.chat_id)
            await ss.commit()
        await q.answer(f"انجام شد: {ok} گروه" + (f" | خطا: {failed}" if failed else ""),show_alert=True);return
    if act=="cleanup":
        async with db.sessions() as ss:
            pubs=(await ss.execute(select(PrebookingPublication).where(
                PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(False),
                PrebookingPublication.message_id.is_not(None)))).scalars().all()
            removed=0
            for pub in pubs:
                try:await c.bot.delete_message(pub.chat_id,pub.message_id);removed+=1
                except Exception:log.exception("delete prebooking publication chat=%s",pub.chat_id)
                pub.message_id=None
            await ss.commit()
        await q.answer(f"{removed} پیام حذف شد.",show_alert=True)

async def _publication_keyboard(db,tid):
    async with db.sessions() as ss:
        groups=(await ss.execute(select(PrebookingGroup).where(PrebookingGroup.active.is_(True)).order_by(PrebookingGroup.title))).scalars().all()
        selected=set((await ss.execute(select(PrebookingPublication.chat_id).where(
            PrebookingPublication.trip_id==tid,PrebookingPublication.active.is_(True)))).scalars().all())
    rows=[[InlineKeyboardButton(f"{'✅' if g.chat_id in selected else '⬜'} {g.title}"[:60],callback_data=f"ppub:toggle:{tid}:{g.chat_id}")] for g in groups]
    rows += [[InlineKeyboardButton("📣 انتشار / بروزرسانی در گروه‌های انتخاب‌شده",callback_data=f"ppub:send:{tid}")],
             [InlineKeyboardButton("🗑 حذف پیام از گروه‌های ازانتخاب‌خارج‌شده",callback_data=f"ppub:cleanup:{tid}")]]
    return InlineKeyboardMarkup(rows)

async def action(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return ConversationHandler.END
    await q.answer();_,a,tid=q.data.split(":");tid=int(tid);db=c.application.bot_data["db"];x=await cfg(db,tid,True)
    if a in ("toggle","wait","names"):
        async with db.sessions() as s:
            z=(await s.execute(select(PrebookingSettings).where(PrebookingSettings.trip_id==tid))).scalar_one()
            attr={"toggle":"enabled","wait":"waitlist","names":"show_names"}[a];setattr(z,attr,not getattr(z,attr));await s.commit()
        await q.message.reply_text("✅ تغییر کرد.");await refresh(c,tid);return ConversationHandler.END
    if a in ("deadline","execute","penaltydate"):
        await calendar_start(q,tid,"penalty" if a=="penaltydate" else a)
        return ConversationHandler.END
    states={"cap":CAP,"price":PRICE,"disc":DISC,"cp":CANCEL_POINTS,"payaccount":PAY_ACCOUNT,"payname":PAY_NAME}
    if a in states:
        c.user_data["pre_tid"]=tid;c.user_data["pre_state"]=states[a]
        prompts={"cap":"ظرفیت کل؟ فقط عدد","price":"قیمت اصلی به تومان؟ فقط عدد","disc":"تخفیف پیش‌رزرو به تومان؟ فقط عدد","cp":"جریمه چند امتیاز باشد؟","payaccount":"شماره کارت/حساب/شبا برای پرداخت را بفرست:","payname":"نام صاحب حساب را بفرست:"}
        await q.message.reply_text(prompts[a]);return states[a]
    if a=="add":
        return await preadd_start(update,c)
    if a=="publish":
        await publication_picker(q,c,tid);return ConversationHandler.END
    if a=="list":
        async with db.sessions() as s:
            rows=(await s.execute(select(User.full_name,Prebooking.status,Prebooking.price_snapshot,Prebooking.discount_snapshot).join(Prebooking,Prebooking.telegram_id==User.telegram_id).where(Prebooking.trip_id==tid).order_by(Prebooking.created_at))).all()
        lab={"prebooked":"🟡 پیش‌رزرو","confirmed":"🟢 قطعی","waitlist":"⏳ انتظار","cancelled":"⚪ لغو"}
        if not rows:
            await q.message.reply_text("هنوز کسی ثبت نشده.");return ConversationHandler.END
        async with db.sessions() as ss:
            rr=(await ss.execute(select(User.telegram_id,User.full_name,Prebooking.status).join(Prebooking,Prebooking.telegram_id==User.telegram_id).where(Prebooking.trip_id==tid).order_by(Prebooking.created_at))).all()
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(f"{lab.get(st,st)} | {name}"[:60],callback_data=f"pview:person:{tid}:{uid}")] for uid,name,st in rr])
        await q.message.reply_text("👥 پیش‌رزروها — برای تغییر وضعیت روی نام بزن:",reply_markup=kb)
    return ConversationHandler.END

async def value(update,c):
    st=c.user_data["pre_state"];tid=c.user_data["pre_tid"];v=(update.message.text or "").strip();db=c.application.bot_data["db"]
    try:
        async with db.sessions() as s:
            x=(await s.execute(select(PrebookingSettings).where(PrebookingSettings.trip_id==tid))).scalar_one()
            if st in (DEADLINE,EXECUTE):
                d=datetime.strptime(v,"%Y-%m-%d %H:%M").replace(tzinfo=IR).astimezone(timezone.utc);setattr(x,"deadline_at" if st==DEADLINE else "execution_at",d)
            elif st in (PAY_ACCOUNT,PAY_NAME):
                if not v:raise ValueError()
                setattr(x,{PAY_ACCOUNT:"payment_account",PAY_NAME:"payment_recipient"}[st],v)
            else:
                n=int(v.replace(",","").replace("٬",""));assert n>=0
                setattr(x,{CAP:"capacity",PRICE:"regular_price",DISC:"early_discount",CANCEL_HOURS:"cancel_hours",CANCEL_POINTS:"cancel_points"}[st],n)
            await s.commit()
        await update.message.reply_text("✅ ذخیره شد.");await refresh(c,tid);return ConversationHandler.END
    except Exception:
        await update.message.reply_text("فرمت درست نیست؛ دوباره وارد کن.");return st

async def mine(update,c):
    db=c.application.bot_data["db"]
    async with db.sessions() as s:
        rows=(await s.execute(select(Prebooking,Trip).join(Trip,Trip.id==Prebooking.trip_id).where(Prebooking.telegram_id==update.effective_user.id,Prebooking.status.in_(["prebooked","confirmed","waitlist"])).order_by(Prebooking.created_at.desc()))).all()
    if not rows:await update.message.reply_text("در حال حاضر پیش‌رزرو فعالی ندارید.");return
    lab={"prebooked":"🟡 پیش‌رزرو","confirmed":"🟢 قطعی","waitlist":"⏳ انتظار"};lines=["📝 ثبت‌نام‌های من",""]
    for r,t in rows:lines += [f"{lab.get(r.status,r.status)} — {t.title}",f"💳 مبلغ: {money(r.price_snapshot)}",f"🎁 تخفیف: {money(r.discount_snapshot)}",""]
    await update.message.reply_text("\n".join(lines))

async def preadd_start(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();tid=int(q.data.split(":")[2])
    c.user_data["preadd_tid"]=tid;c.user_data["preadd_waiting"]=True
    await q.message.reply_text("🔎 نام، شماره موبایل، KZH، BTC یا Telegram ID مسافر را وارد کن:")

async def preadd_search(update,c):
    if not admin(update.effective_user.id,c) or not c.user_data.get("preadd_waiting"):return
    value=(update.message.text or "").strip();db=c.application.bot_data["db"];tid=int(c.user_data["preadd_tid"])
    users=await db.search_users(value,limit=10)
    if not users:
        await update.message.reply_text("مسافری پیدا نشد. دوباره جستجو کن.");return
    rows=[[InlineKeyboardButton(f"{u.full_name} | {u.phone}"[:60],callback_data=f"padd:pick:{tid}:{u.telegram_id}")] for u in users]
    rows.append([InlineKeyboardButton("❌ لغو",callback_data=f"padd:cancel:{tid}")])
    await update.message.reply_text("مسافر را انتخاب کن:",reply_markup=InlineKeyboardMarkup(rows))

async def preadd_cb(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();z=q.data.split(":");act=z[1];tid=int(z[2]);db=c.application.bot_data["db"]
    if act=="cancel":
        c.user_data.pop("preadd_waiting",None);c.user_data.pop("preadd_tid",None);await q.edit_message_text("لغو شد.");return
    uid=int(z[3])
    if act=="pick":
        u=await db.get_user(uid)
        await q.edit_message_text(f"👤 {u.full_name}\nوضعیت موردنظر را انتخاب کن:",reply_markup=InlineKeyboardMarkup([
          [InlineKeyboardButton("🟡 پیش‌رزرو",callback_data=f"padd:set:{tid}:{uid}:prebooked"),
           InlineKeyboardButton("🟢 رزرو قطعی",callback_data=f"padd:set:{tid}:{uid}:confirmed")],
          [InlineKeyboardButton("⏳ لیست انتظار",callback_data=f"padd:set:{tid}:{uid}:waitlist"),
           InlineKeyboardButton("⚪ لغو",callback_data=f"padd:set:{tid}:{uid}:cancelled")]]));return
    if act=="set":
        status=z[4];x=await cfg(db,tid,True)
        async with db.sessions() as ss:
            r=(await ss.execute(select(Prebooking).where(Prebooking.trip_id==tid,Prebooking.telegram_id==uid))).scalar_one_or_none()
            price=max(0,x.regular_price-x.early_discount)
            if r:r.status=status;r.updated_at=datetime.now(timezone.utc)
            else:ss.add(Prebooking(trip_id=tid,telegram_id=uid,status=status,price_snapshot=price,discount_snapshot=x.early_discount))
            await ss.commit()
        c.user_data.pop("preadd_waiting",None);c.user_data.pop("preadd_tid",None)
        u=await db.get_user(uid);labels={"prebooked":"پیش‌رزرو","confirmed":"رزرو قطعی","waitlist":"لیست انتظار","cancelled":"لغو"}
        await q.edit_message_text(f"✅ {u.full_name} با وضعیت «{labels[status]}» ثبت شد.")
        await refresh(c,tid)

async def preperson_cb(update,c):
    q=update.callback_query
    if not admin(q.from_user.id,c):return
    await q.answer();z=q.data.split(":");tid=int(z[2]);uid=int(z[3]);db=c.application.bot_data["db"];u=await db.get_user(uid)
    await q.message.reply_text(f"👤 {u.full_name}\nوضعیت جدید:",reply_markup=InlineKeyboardMarkup([
      [InlineKeyboardButton("🟡 پیش‌رزرو",callback_data=f"padd:set:{tid}:{uid}:prebooked"),InlineKeyboardButton("🟢 قطعی",callback_data=f"padd:set:{tid}:{uid}:confirmed")],
      [InlineKeyboardButton("⏳ انتظار",callback_data=f"padd:set:{tid}:{uid}:waitlist"),InlineKeyboardButton("⚪ لغو",callback_data=f"padd:set:{tid}:{uid}:cancelled")]]))

def flow():
    return ConversationHandler(entry_points=[CallbackQueryHandler(panel,pattern=r"^pa:view:\d+$"),CallbackQueryHandler(action,pattern=r"^pa:(toggle|wait|names|publish|list|cap|price|disc|deadline|execute|penaltydate|cp|payaccount|payname|add|pick|status):\d+(?::[^:]+)?$")],
      states={CAP:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],PRICE:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],DISC:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],CANCEL_HOURS:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],CANCEL_POINTS:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],PAY_ACCOUNT:[MessageHandler(filters.TEXT&~filters.COMMAND,value)],PAY_NAME:[MessageHandler(filters.TEXT&~filters.COMMAND,value)]},fallbacks=[],allow_reentry=True)

async def loop(app):
    while True:
        try:
            db=app.bot_data["db"]
            async with db.sessions() as s:ids=(await s.execute(select(PrebookingPublication.trip_id).join(PrebookingSettings,PrebookingSettings.trip_id==PrebookingPublication.trip_id).where(PrebookingSettings.enabled.is_(True),PrebookingPublication.active.is_(True),PrebookingPublication.message_id.is_not(None)).distinct())).scalars().all()
            ctx=type("C",(),{"application":app,"bot":app.bot})()
            for tid in ids:await refresh(ctx,tid)
        except Exception:log.exception("prebooking timer")
        await asyncio.sleep(3600)

async def initialize_prebooking(app):
    from sqlalchemy import text as sql_text
    async with app.bot_data["db"].engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(sql_text("ALTER TABLE prebooking_settings ADD COLUMN IF NOT EXISTS cancel_from_at TIMESTAMPTZ"))
        await conn.execute(sql_text("ALTER TABLE prebooking_settings ADD COLUMN IF NOT EXISTS payment_recipient VARCHAR(255) DEFAULT ''"))
        await conn.execute(sql_text("ALTER TABLE prebooking_settings ADD COLUMN IF NOT EXISTS payment_account VARCHAR(255) DEFAULT ''"))
        await conn.execute(sql_text("""
            INSERT INTO prebooking_publications (trip_id, chat_id, message_id, active, created_at)
            SELECT trip_id, chat_id, message_id, TRUE, NOW()
            FROM prebooking_settings
            WHERE chat_id IS NOT NULL AND message_id IS NOT NULL
            ON CONFLICT (trip_id, chat_id) DO NOTHING
        """))
    asyncio.create_task(loop(app))

def handlers():
    return [flow(),CommandHandler("prebookinggroup",register_prebooking_group),CallbackQueryHandler(publication_cb,pattern=r"^ppub:"),CallbackQueryHandler(calendar_cb,pattern=r"^pc:"),CallbackQueryHandler(preadd_cb,pattern=r"^padd:"),CallbackQueryHandler(preperson_cb,pattern=r"^pview:person:"),CallbackQueryHandler(passenger,pattern=r"^pre:(join|cancel|refresh):\d+$"),MessageHandler(filters.Regex(r"^📝 ثبت‌نام‌های من$"),mine),MessageHandler(filters.TEXT & ~filters.COMMAND,preadd_search)]
